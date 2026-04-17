import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RefreshSession(SQLModel, table=True):
    __tablename__ = "refresh_sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)

    # sha256 hash of the opaque refresh token — raw token never stored
    token_hash: str = Field(unique=True, index=True)

    # Reuse detection: sessions sharing a family_id are all revoked if reuse detected
    family_id: uuid.UUID = Field(default_factory=uuid.uuid4, index=True)

    expires_at: datetime
    revoked_at: datetime | None = Field(default=None)

    # Audit metadata
    created_ip: str | None = Field(default=None, max_length=45)
    user_agent: str | None = Field(default=None, max_length=512)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at.replace(tzinfo=timezone.utc)

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired
