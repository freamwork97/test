import uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expires_at,
    verify_password,
)
from app.models.refresh_session import RefreshSession
from app.models.user import User

REFRESH_KEY_PREFIX = "refresh:"


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def register_user(
    db: AsyncSession, email: str, password: str
) -> User:
    existing = await db.exec(select(User).where(User.email == email))
    if existing.first():
        raise AuthError("Email already registered", 409)

    user = User(email=email, hashed_password=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
    redis: aioredis.Redis,
) -> tuple[str, str, uuid.UUID]:
    user = await _get_active_user(db, email)

    _check_lockout(user)

    if not verify_password(password, user.hashed_password):
        await _record_failed_attempt(db, user)
        raise AuthError("Invalid credentials")

    await _reset_failed_attempts(db, user)

    access_token = create_access_token(user.id, user.token_version)
    raw_refresh, session = await _create_refresh_session(
        db, redis, user.id, ip, user_agent
    )
    return access_token, raw_refresh, session.family_id


async def refresh_tokens(
    db: AsyncSession,
    redis: aioredis.Redis,
    raw_token: str,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, str]:
    token_hash = hash_refresh_token(raw_token)

    # Atomically consume the Redis entry (GETDEL = read + delete in one op).
    # If two concurrent requests arrive with the same token, only the first
    # wins the GETDEL; the second gets None and is rejected — race condition closed.
    try:
        cached = await redis.getdel(f"{REFRESH_KEY_PREFIX}{token_hash}")
    except Exception:
        raise AuthError("Service unavailable", 503)

    session = await db.exec(
        select(RefreshSession).where(RefreshSession.token_hash == token_hash)
    )
    session_row = session.first()

    if not session_row:
        raise AuthError("Invalid refresh token")

    if session_row.is_revoked:
        # Reuse detected — revoke entire session family
        await _revoke_family(db, redis, session_row.family_id)
        raise AuthError("Refresh token reuse detected — all sessions invalidated")

    if session_row.is_expired:
        raise AuthError("Refresh token expired")

    # cached is None means either Redis miss (after getdel consumed by concurrent request)
    # or Redis eviction — both should be treated as invalid
    if cached is None:
        raise AuthError("Session not found in store")

    user = await db.get(User, session_row.user_id)
    if not user or not user.is_active:
        raise AuthError("User not found or inactive")

    # Mark session revoked in DB (Redis entry already removed by getdel above)
    session_row.revoked_at = datetime.now(timezone.utc)
    await db.commit()

    new_access = create_access_token(user.id, user.token_version)
    raw_refresh, _ = await _create_refresh_session(
        db, redis, user.id, ip, user_agent, family_id=session_row.family_id
    )
    return new_access, raw_refresh


async def logout_user(
    db: AsyncSession,
    redis: aioredis.Redis,
    raw_token: str,
    all_sessions: bool = False,
) -> None:
    token_hash = hash_refresh_token(raw_token)
    session = await db.exec(
        select(RefreshSession).where(RefreshSession.token_hash == token_hash)
    )
    session_row = session.first()
    if not session_row:
        return

    if all_sessions:
        await _revoke_all_user_sessions(db, redis, session_row.user_id)
    else:
        await _revoke_session(db, redis, session_row)


async def get_current_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise AuthError("User not found")
    return user


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_active_user(db: AsyncSession, email: str) -> User:
    result = await db.exec(select(User).where(User.email == email))
    user = result.first()
    if not user or not user.is_active:
        raise AuthError("Invalid credentials")
    return user


def _check_lockout(user: User) -> None:
    if user.locked_until and datetime.now(timezone.utc) < user.locked_until.replace(
        tzinfo=timezone.utc
    ):
        raise AuthError("Account temporarily locked", 429)


async def _record_failed_attempt(db: AsyncSession, user: User) -> None:
    # H-5: atomic UPDATE ... SET count = count + 1 prevents lost-update race condition
    now = datetime.now(timezone.utc)
    lock_at = settings.MAX_LOGIN_ATTEMPTS - 1  # lock triggers when this increment hits max

    stmt = (
        update(User)
        .where(User.id == user.id)
        .values(
            failed_login_count=User.failed_login_count + 1,
            locked_until=(
                now + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
                if user.failed_login_count >= lock_at
                else user.locked_until
            ),
        )
    )
    await db.exec(stmt)  # type: ignore[arg-type]
    await db.commit()
    await db.refresh(user)


async def _reset_failed_attempts(db: AsyncSession, user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()


async def _create_refresh_session(
    db: AsyncSession,
    redis: aioredis.Redis,
    user_id: uuid.UUID,
    ip: str | None,
    user_agent: str | None,
    family_id: uuid.UUID | None = None,
) -> tuple[str, RefreshSession]:
    raw_token = generate_refresh_token()
    token_hash = hash_refresh_token(raw_token)
    expires_at = refresh_token_expires_at()

    session = RefreshSession(
        user_id=user_id,
        token_hash=token_hash,
        family_id=family_id or uuid.uuid4(),
        expires_at=expires_at,
        created_ip=ip,
        user_agent=user_agent,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    ttl = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    await redis.set(f"{REFRESH_KEY_PREFIX}{token_hash}", str(user_id), ex=ttl)

    return raw_token, session


async def _revoke_session(
    db: AsyncSession, redis: aioredis.Redis, session: RefreshSession
) -> None:
    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await redis.delete(f"{REFRESH_KEY_PREFIX}{session.token_hash}")


async def _revoke_family(
    db: AsyncSession, redis: aioredis.Redis, family_id: uuid.UUID
) -> None:
    result = await db.exec(
        select(RefreshSession).where(
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),  # type: ignore[attr-defined]
        )
    )
    sessions = result.all()
    now = datetime.now(timezone.utc)
    for s in sessions:
        s.revoked_at = now
        await redis.delete(f"{REFRESH_KEY_PREFIX}{s.token_hash}")
    await db.commit()


async def _revoke_all_user_sessions(
    db: AsyncSession, redis: aioredis.Redis, user_id: uuid.UUID
) -> None:
    result = await db.exec(
        select(RefreshSession).where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),  # type: ignore[attr-defined]
        )
    )
    sessions = result.all()
    now = datetime.now(timezone.utc)
    for s in sessions:
        s.revoked_at = now
        await redis.delete(f"{REFRESH_KEY_PREFIX}{s.token_hash}")

    # H-6: bump token_version so all existing access tokens are immediately invalid
    await db.exec(  # type: ignore[arg-type]
        update(User)
        .where(User.id == user_id)
        .values(token_version=User.token_version + 1)
    )
    await db.commit()
