import pytest
from httpx import AsyncClient

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"

ORIGIN = "http://localhost:3000"
HEADERS = {"Origin": ORIGIN}


async def _register_and_login(client: AsyncClient, user: dict) -> tuple[str, str]:
    """Register (if needed) and login, returning (access_token, refresh_token)."""
    await client.post(REGISTER_URL, json=user, headers=HEADERS)
    res = await client.post(LOGIN_URL, json=user, headers=HEADERS)
    assert res.status_code == 200
    return res.cookies.get("access_token", ""), res.cookies.get("refresh_token", "")


# ── Registration ─────────────────────────────────────────────────────────────

async def test_register_success(client: AsyncClient, unique_user):
    res = await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    assert res.status_code == 201
    assert res.json()["message"] == "registered"
    assert "access_token" in res.cookies
    assert "refresh_token" in res.cookies


async def test_register_duplicate_email(client: AsyncClient, unique_user):
    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    res = await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    assert res.status_code == 409


async def test_register_weak_password(client: AsyncClient):
    res = await client.post(
        REGISTER_URL,
        json={"email": "weak@example.com", "password": "short"},
        headers=HEADERS,
    )
    assert res.status_code == 422


async def test_register_invalid_email(client: AsyncClient):
    res = await client.post(
        REGISTER_URL,
        json={"email": "not-an-email", "password": "Password1"},
        headers=HEADERS,
    )
    assert res.status_code == 422


# ── Login ─────────────────────────────────────────────────────────────────────

async def test_login_success(client: AsyncClient, unique_user):
    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    assert res.status_code == 200
    assert "access_token" in res.cookies
    assert "refresh_token" in res.cookies


async def test_login_wrong_password(client: AsyncClient, unique_user):
    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    res = await client.post(
        LOGIN_URL,
        json={"email": unique_user["email"], "password": "WrongPass1"},
        headers=HEADERS,
    )
    assert res.status_code == 401


async def test_login_unknown_email(client: AsyncClient):
    res = await client.post(
        LOGIN_URL,
        json={"email": "nobody@example.com", "password": "Password1"},
        headers=HEADERS,
    )
    assert res.status_code == 401


async def test_account_lockout_after_max_attempts(client: AsyncClient, unique_user):
    await client.post(REGISTER_URL, json=unique_user, headers=HEADERS)
    wrong = {"email": unique_user["email"], "password": "WrongPass1"}
    for _ in range(5):
        await client.post(LOGIN_URL, json=wrong, headers=HEADERS)
    res = await client.post(LOGIN_URL, json=unique_user, headers=HEADERS)
    assert res.status_code == 429


# ── Token refresh ────────────────────────────────────────────────────────────

async def test_refresh_success(client: AsyncClient, unique_user):
    _, refresh_token = await _register_and_login(client, unique_user)

    client.cookies.set("refresh_token", refresh_token)
    res = await client.post(REFRESH_URL, headers=HEADERS)
    client.cookies.clear()

    assert res.status_code == 200
    assert "access_token" in res.cookies
    new_refresh = res.cookies.get("refresh_token", "")
    assert new_refresh != refresh_token  # rotation


async def test_refresh_missing_cookie(client: AsyncClient):
    res = await client.post(REFRESH_URL, headers=HEADERS)
    assert res.status_code == 401


async def test_refresh_invalid_token(client: AsyncClient):
    client.cookies.set("refresh_token", "totally-invalid-token")
    res = await client.post(REFRESH_URL, headers=HEADERS)
    client.cookies.clear()
    assert res.status_code == 401


async def test_refresh_reuse_detection_revokes_family(client: AsyncClient, unique_user):
    """Reusing a revoked (already-rotated) token must revoke the entire session family."""
    _, original_token = await _register_and_login(client, unique_user)

    # First rotation: original_token → new_token
    client.cookies.set("refresh_token", original_token)
    rotate_res = await client.post(REFRESH_URL, headers=HEADERS)
    client.cookies.clear()
    assert rotate_res.status_code == 200
    new_token = rotate_res.cookies.get("refresh_token", "")

    # Reuse the original (now revoked) token → reuse detected
    client.cookies.set("refresh_token", original_token)
    reuse_res = await client.post(REFRESH_URL, headers=HEADERS)
    client.cookies.clear()
    assert reuse_res.status_code == 401

    # The rotated token from the same family must also be invalidated
    client.cookies.set("refresh_token", new_token)
    family_res = await client.post(REFRESH_URL, headers=HEADERS)
    client.cookies.clear()
    assert family_res.status_code == 401


# ── CSRF ─────────────────────────────────────────────────────────────────────

async def test_refresh_csrf_blocked_without_origin(client: AsyncClient, unique_user):
    _, refresh_token = await _register_and_login(client, unique_user)

    client.cookies.set("refresh_token", refresh_token)
    res = await client.post(REFRESH_URL)  # no Origin header
    client.cookies.clear()
    assert res.status_code == 403


async def test_logout_csrf_blocked_without_origin(client: AsyncClient):
    res = await client.post(LOGOUT_URL)
    assert res.status_code == 403


# ── Logout ───────────────────────────────────────────────────────────────────

async def test_logout_clears_cookies(client: AsyncClient, unique_user):
    _, refresh_token = await _register_and_login(client, unique_user)

    client.cookies.set("refresh_token", refresh_token)
    res = await client.post(LOGOUT_URL, headers=HEADERS)
    client.cookies.clear()
    assert res.status_code == 200

    # Revoked token must no longer work
    client.cookies.set("refresh_token", refresh_token)
    refresh_res = await client.post(REFRESH_URL, headers=HEADERS)
    client.cookies.clear()
    assert refresh_res.status_code == 401


# ── /me ──────────────────────────────────────────────────────────────────────

async def test_me_returns_user(client: AsyncClient, unique_user):
    access_token, _ = await _register_and_login(client, unique_user)

    client.cookies.set("access_token", access_token)
    res = await client.get(ME_URL)
    client.cookies.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["email"] == unique_user["email"]
    assert "id" in data


async def test_me_unauthenticated(client: AsyncClient):
    res = await client.get(ME_URL)
    assert res.status_code == 401
