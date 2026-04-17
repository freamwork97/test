import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=255)
    hashed_password: str
    is_active: bool = Field(default=True)

    # Access token force-expiry: increment to invalidate all existing tokens
    token_version: int = Field(default=0)

    # Account lockout
    failed_login_count: int = Field(default=0)
    locked_until: datetime | None = Field(default=None)

    # Audit
    last_login_at: datetime | None = Field(default=None)
    password_changed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
