import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings

password_hash = PasswordHash((Argon2Hasher(),))

ACCESS_TOKEN_TYPE = "access"


def hash_password(plain: str) -> str:
    return password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return password_hash.verify(plain, hashed)


def _private_key() -> str:
    return settings.JWT_PRIVATE_KEY.replace("\\n", "\n")


def _public_key() -> str:
    return settings.JWT_PUBLIC_KEY.replace("\\n", "\n")


def create_access_token(user_id: uuid.UUID, token_version: int) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "iss": settings.APP_NAME,
        "aud": settings.APP_NAME,
        "exp": expire,
        "iat": now,
        "jti": str(uuid.uuid4()),
        "type": ACCESS_TOKEN_TYPE,
        "ver": token_version,
    }
    return jwt.encode(payload, _private_key(), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        _public_key(),
        algorithms=[settings.JWT_ALGORITHM],
        audience=settings.APP_NAME,
        issuer=settings.APP_NAME,
    )
    # Enforce token type claim to prevent refresh tokens being used as access tokens
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Wrong token type")
    return payload


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def refresh_token_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
