"""
TDD: H-5 atomic lockout + H-6 all-session logout race fix
"""
import pytest
from httpx import AsyncClient

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"
ORIGIN = "http://localhost:3000"
HEADERS = {"Origin": ORIGIN}


# ── H-5: Atomic lockout boundary ─────────────────────────────────────────────

async def test_lockout_not_applied_before_max_attempts(client: AsyncClient, unique_user):
    """MAX-1 failures must NOT lock the account."""
    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    wrong = {**unique_user, "password": "WrongPass1"}

    for _ in range(4):  # MAX=5, so 4 failures should not lock
        await client.post(LOGIN_URL, json=wrong, headers=HEADERS)

    # Correct password must still work
    res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    assert res.status_code == 200, "Account must NOT be locked before MAX attempts"


async def test_lockout_applied_at_exactly_max_attempts(client: AsyncClient, unique_user):
    """Exactly MAX failures must lock the account."""
    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    wrong = {**unique_user, "password": "WrongPass1"}

    for _ in range(5):  # MAX=5
        await client.post(LOGIN_URL, json=wrong, headers=HEADERS)

    # Even correct password must be rejected (account locked)
    res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    assert res.status_code == 429, "Account must be locked after MAX attempts"


async def test_lockout_db_field_set_correctly(client: AsyncClient, unique_user, db_session):
    """After MAX failures, locked_until must be set in DB."""
    from app.services.auth_service import _get_active_user

    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    wrong = {**unique_user, "password": "WrongPass1"}

    for _ in range(5):
        await client.post(LOGIN_URL, json=wrong, headers=HEADERS)

    user = await _get_active_user(db_session, unique_user["email"])
    await db_session.refresh(user)
    assert user.locked_until is not None, "locked_until must be set in DB after MAX attempts"
    assert user.failed_login_count >= 5, "failed_login_count must be >= MAX in DB"


async def test_successful_login_resets_failed_count(client: AsyncClient, unique_user, db_session):
    """Successful login must reset failed_login_count and locked_until."""
    from app.services.auth_service import _get_active_user

    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    wrong = {**unique_user, "password": "WrongPass1"}

    # Fail twice, then succeed
    await client.post(LOGIN_URL, json=wrong, headers=HEADERS)
    await client.post(LOGIN_URL, json=wrong, headers=HEADERS)
    await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)

    user = await _get_active_user(db_session, unique_user["email"])
    await db_session.refresh(user)
    assert user.failed_login_count == 0
    assert user.locked_until is None


# ── H-6: All-session logout invalidates token_version ─────────────────────────

async def test_all_session_logout_bumps_token_version(client: AsyncClient, unique_user, db_session):
    """all_sessions=True logout must increment token_version."""
    from app.services.auth_service import _get_active_user

    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    login_res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    access_token = login_res.cookies.get("access_token", "")
    refresh_token = login_res.cookies.get("refresh_token", "")

    user_before = await _get_active_user(db_session, unique_user["email"])
    version_before = user_before.token_version

    client.cookies.set("refresh_token", refresh_token)
    await client.post(f"{LOGOUT_URL}?all_sessions=true", headers=HEADERS)
    client.cookies.clear()

    await db_session.refresh(user_before)
    assert user_before.token_version == version_before + 1, \
        "token_version must be incremented on all-session logout"


async def test_all_session_logout_invalidates_access_token(client: AsyncClient, unique_user):
    """Access token must be rejected after all-session logout (token_version bumped)."""
    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    login_res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    access_token = login_res.cookies.get("access_token", "")
    refresh_token = login_res.cookies.get("refresh_token", "")

    # Logout all sessions
    client.cookies.set("refresh_token", refresh_token)
    await client.post(f"{LOGOUT_URL}?all_sessions=true", headers=HEADERS)
    client.cookies.clear()

    # Old access token must now fail /me
    client.cookies.set("access_token", access_token)
    res = await client.get(ME_URL)
    client.cookies.clear()
    assert res.status_code == 401, "Access token must be invalid after all-session logout"


async def test_single_session_logout_does_not_bump_token_version(
    client: AsyncClient, unique_user, db_session
):
    """Single-session logout must NOT increment token_version."""
    from app.services.auth_service import _get_active_user

    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    login_res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    refresh_token = login_res.cookies.get("refresh_token", "")

    user_before = await _get_active_user(db_session, unique_user["email"])
    version_before = user_before.token_version

    client.cookies.set("refresh_token", refresh_token)
    await client.post(LOGOUT_URL, headers=HEADERS)
    client.cookies.clear()

    await db_session.refresh(user_before)
    assert user_before.token_version == version_before, \
        "token_version must NOT change on single-session logout"
