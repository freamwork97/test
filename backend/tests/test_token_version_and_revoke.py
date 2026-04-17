"""
TDD: Fix 1 - token_version centralized in get_current_user()
     Fix 2 - DB commit before Redis delete in _revoke_all_user_sessions()
     Fix 3 - bulk UPDATE for session revoke
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlmodel import select

from app.models.refresh_session import RefreshSession

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"
ORIGIN = "http://localhost:3000"
HEADERS = {"Origin": ORIGIN}


# ── Fix 1: token_version check centralized in get_current_user() ─────────────

async def test_get_current_user_raises_when_token_version_mismatch(
    client: AsyncClient, unique_user, db_session
):
    """get_current_user() must raise AuthError when token_version mismatches."""
    from app.services.auth_service import get_current_user, AuthError

    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    login_res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    access_token = login_res.cookies.get("access_token", "")
    refresh_token = login_res.cookies.get("refresh_token", "")

    # Bump token_version via all-session logout
    client.cookies.set("refresh_token", refresh_token)
    await client.post(f"{LOGOUT_URL}?all_sessions=true", headers=HEADERS)
    client.cookies.clear()

    # Decode user_id from token and get stale token_version
    from app.core.security import decode_access_token
    payload = decode_access_token(access_token)
    user_id = uuid.UUID(payload["sub"])
    stale_version = payload.get("ver", 0)

    # get_current_user with mismatched version must raise
    with pytest.raises(AuthError) as exc_info:
        await get_current_user(db_session, user_id, token_version=stale_version)
    assert exc_info.value.status_code == 401


async def test_get_current_user_succeeds_with_correct_token_version(
    client: AsyncClient, unique_user, db_session
):
    """get_current_user() must succeed when token_version matches."""
    from app.services.auth_service import get_current_user
    from app.core.security import decode_access_token

    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    login_res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    access_token = login_res.cookies.get("access_token", "")

    payload = decode_access_token(access_token)
    user_id = uuid.UUID(payload["sub"])
    version = payload.get("ver", 0)

    user = await get_current_user(db_session, user_id, token_version=version)
    assert user.id == user_id


async def test_get_current_user_requires_token_version(
    client: AsyncClient, unique_user, db_session
):
    """get_current_user() must require token_version — omitting it must raise TypeError (fail-closed)."""
    import inspect
    from app.services.auth_service import get_current_user

    sig = inspect.signature(get_current_user)
    param = sig.parameters.get("token_version")

    # token_version must be a required parameter (no default)
    assert param is not None, "token_version parameter must exist"
    assert param.default is inspect.Parameter.empty, (
        "token_version must be required (no default) to prevent silent bypass"
    )


# ── Fix 2: DB commit before Redis delete ─────────────────────────────────────

async def test_sessions_revoked_in_db_even_if_redis_delete_is_called_last(
    client: AsyncClient, unique_user, db_session
):
    """After all-session logout, sessions must be revoked in DB regardless of Redis order."""
    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    login_res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    refresh_token = login_res.cookies.get("refresh_token", "")

    client.cookies.set("refresh_token", refresh_token)
    await client.post(f"{LOGOUT_URL}?all_sessions=true", headers=HEADERS)
    client.cookies.clear()

    # All sessions must be revoked in DB (DB commit came first)
    from app.services.auth_service import _get_active_user
    user = await _get_active_user(db_session, unique_user["email"])
    result = await db_session.exec(
        select(RefreshSession).where(
            RefreshSession.user_id == user.id,
            RefreshSession.revoked_at.is_(None),  # type: ignore[attr-defined]
        )
    )
    active_sessions = result.all()
    assert len(active_sessions) == 0, "All sessions must be revoked in DB after all-session logout"


# ── Fix 3: Bulk UPDATE for session revoke ────────────────────────────────────

async def test_multiple_sessions_all_revoked_on_all_session_logout(
    client: AsyncClient, unique_user, db_session
):
    """All active sessions across multiple logins must be revoked."""
    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)

    # Create 3 sessions by logging in 3 times (need separate clients to avoid cookie conflicts)
    tokens = []
    for _ in range(3):
        res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
        tokens.append(res.cookies.get("refresh_token", ""))

    # Use first token to logout all sessions
    client.cookies.set("refresh_token", tokens[0])
    await client.post(f"{LOGOUT_URL}?all_sessions=true", headers=HEADERS)
    client.cookies.clear()

    # All sessions must be revoked in DB
    from app.services.auth_service import _get_active_user
    user = await _get_active_user(db_session, unique_user["email"])
    result = await db_session.exec(
        select(RefreshSession).where(
            RefreshSession.user_id == user.id,
            RefreshSession.revoked_at.is_(None),  # type: ignore[attr-defined]
        )
    )
    remaining = result.all()
    assert len(remaining) == 0, "All 3 sessions must be revoked after all-session logout"
