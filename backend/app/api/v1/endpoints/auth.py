import uuid
from urllib.parse import urlparse

import jwt
import redis.asyncio as aioredis
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import decode_access_token
from app.db.redis import get_redis
from app.db.session import get_session
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthError, authenticate_user, get_current_user, logout_user, refresh_tokens, register_user

router = APIRouter()

REFRESH_COOKIE = "refresh_token"
ACCESS_COOKIE = "access_token"
COOKIE_SECURE = not settings.DEBUG
COOKIE_SAMESITE = "lax"


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/api/v1/auth",  # H-2: covers /refresh AND /logout
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit(settings.RATE_LIMIT_REGISTER)
async def register(
    request: Request,
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
    redis: aioredis.Redis = Depends(get_redis),
) -> TokenResponse:
    _check_origin_if_present(request)  # H-4: login CSRF protection
    try:
        user = await register_user(db, body.email, body.password)
        access, refresh, _ = await authenticate_user(
            db, body.email, body.password, _client_ip(request),
            request.headers.get("User-Agent"), redis
        )
        _set_auth_cookies(response, access, refresh)
        return TokenResponse(message="registered")
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
    redis: aioredis.Redis = Depends(get_redis),
) -> TokenResponse:
    _check_origin_if_present(request)  # H-4: login CSRF protection
    try:
        access, refresh, _ = await authenticate_user(
            db, body.email, body.password,
            _client_ip(request), request.headers.get("User-Agent"), redis
        )
        _set_auth_cookies(response, access, refresh)
        return TokenResponse(message="logged in")
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_REFRESH)
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: AsyncSession = Depends(get_session),
    redis: aioredis.Redis = Depends(get_redis),
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    # CSRF: verify Origin/Referer matches allowed origins
    _verify_origin(request)

    try:
        access, new_refresh = await refresh_tokens(
            db, redis, refresh_token,
            _client_ip(request), request.headers.get("User-Agent")
        )
        _set_auth_cookies(response, access, new_refresh)
        return TokenResponse(message="refreshed")
    except AuthError as e:
        _clear_auth_cookies(response)
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/logout", response_model=TokenResponse)
async def logout(
    request: Request,
    response: Response,
    all_sessions: bool = False,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: AsyncSession = Depends(get_session),
    redis: aioredis.Redis = Depends(get_redis),
) -> TokenResponse:
    _verify_origin(request)
    if refresh_token:
        await logout_user(db, redis, refresh_token, all_sessions)
    _clear_auth_cookies(response)
    return TokenResponse(message="logged out")


@router.get("/me", response_model=UserResponse)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_session),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> UserResponse:
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_access_token(access_token)
        user_id = uuid.UUID(payload["sub"])
        token_version = payload.get("ver", 0)
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        user = await get_current_user(db, user_id, token_version=token_version)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return UserResponse(id=str(user.id), email=user.email, is_active=user.is_active)


def _verify_origin(request: Request) -> None:
    """H-3: exact URL-parsed origin comparison (prevents startswith bypass)."""
    origin_header = request.headers.get("Origin")
    referer_header = request.headers.get("Referer")

    if origin_header:
        origin = origin_header.strip()
    elif referer_header:
        try:
            p = urlparse(referer_header)
            origin = f"{p.scheme}://{p.netloc}"
        except Exception:
            raise HTTPException(status_code=403, detail="CSRF check failed")
    else:
        raise HTTPException(status_code=403, detail="CSRF check failed")

    if origin not in settings.ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="CSRF check failed")


def _check_origin_if_present(request: Request) -> None:
    """H-4: for login/register — enforce origin when browser sends it (blocks login CSRF)."""
    origin_header = request.headers.get("Origin")
    if not origin_header:
        return  # API/mobile clients without Origin are allowed
    if origin_header.strip() not in settings.ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="CSRF check failed")
