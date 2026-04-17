"""
conftest.py — RSA keys must be set in os.environ BEFORE any app import
because pydantic-settings reads env at Settings() instantiation time.
"""
import os
import uuid

# ── 1. Generate test RSA key pair ─────────────────────────────────────────────
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _rsa_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = _rsa_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

# ── 2. Inject into env BEFORE app import ──────────────────────────────────────
os.environ.setdefault("JWT_PRIVATE_KEY", _PRIVATE_PEM)
os.environ.setdefault("JWT_PUBLIC_KEY", _PUBLIC_PEM)
os.environ.setdefault("JWT_ALGORITHM", "RS256")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

# ── 3. Now import app (triggers Settings() with correct keys) ─────────────────
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401 — register SQLModel metadata before create_all
from app.db.redis import get_redis
from app.db.session import get_session
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def engine():
    _engine = create_async_engine(TEST_DB_URL, echo=False)
    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield _engine
    await _engine.dispose()


@pytest.fixture
async def db_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def mock_redis():
    store: dict = {}

    class MockRedis:
        async def get(self, key):
            return store.get(key)

        async def getdel(self, key):
            return store.pop(key, None)

        async def set(self, key, value, ex=None):
            store[key] = value

        async def delete(self, key):
            store.pop(key, None)

        def reset(self):
            store.clear()

    return MockRedis()


@pytest.fixture(autouse=True)
def reset_rate_limits():
    yield
    try:
        app.state.limiter._storage.reset()
    except Exception:
        pass


@pytest.fixture
def unique_user():
    uid = uuid.uuid4().hex[:8]
    return {"email": f"user-{uid}@example.com", "password": "Password1"}


@pytest.fixture
async def client(db_session, mock_redis):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: mock_redis

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()
