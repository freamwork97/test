# JWT Authentication System — Security Review

**Date:** 2026-04-17  
**Reviewer:** Codex CLI (gpt-5.2-codex) via Claude Code subagent — 2nd pass with real file analysis  
**Scope:** FastAPI backend + Next.js frontend JWT auth implementation  
**Files reviewed:**
- `backend/app/core/security.py`
- `backend/app/api/v1/endpoints/auth.py`
- `backend/app/services/auth_service.py`
- `backend/app/models/user.py`
- `backend/app/models/refresh_session.py`
- `frontend/middleware.ts`
- `frontend/lib/auth.ts`

> **Note:** Review is based on the provided snippets. Actual router dependencies, CORS config, `settings` validation, Pydantic schemas, and DB transaction settings were not visible — some findings may already be mitigated elsewhere.

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 2     |
| HIGH     | 7     |
| MEDIUM   | 10    |
| LOW      | 5     |
| **Total**| **24**|

---

## CRITICAL

### Finding 1 — Empty JWT Secret Fallback

**Severity:** CRITICAL  
**Location:** `frontend/middleware.ts`, `frontend/lib/auth.ts` — module scope

**Issue:**  
`process.env.JWT_SECRET_KEY ?? ""` means if the secret is missing at runtime, JWT verification runs with an empty string key. If the same misconfiguration exists on the backend, an attacker can self-sign HS256 tokens with an empty key and bypass authentication entirely. Even if only the frontend is misconfigured, the middleware/server-side gating is bypassed.

**Fix:**  
Fail fast at app startup if `JWT_SECRET_KEY` is missing or too short. Require a minimum 32-byte random secret. Never use a default/fallback value.

```ts
const rawSecret = process.env.JWT_SECRET_KEY;
if (!rawSecret || rawSecret.length < 32) {
  throw new Error("JWT_SECRET_KEY is required and must be at least 32 characters");
}
const JWT_SECRET = new TextEncoder().encode(rawSecret);
```

---

### Finding 2 — Shared HS256 Secret Between Frontend and Backend

**Severity:** CRITICAL  
**Location:** `frontend/middleware.ts`, `frontend/lib/auth.ts`; `backend/app/core/security.py::create_access_token()`

**Issue:**  
Both the backend and frontend share the same HS256 symmetric secret. If the Next.js server/Edge environment or deployment platform leaks the frontend environment variable, an attacker can mint access tokens that the backend will accept. Giving the verifier the ability to sign tokens is a fundamental security flaw.

**Fix:**  
Switch to asymmetric JWT (RS256 or EdDSA). The backend signs with the private key; the frontend/middleware verifies with the public key only. Alternatively, remove client-side JWT verification entirely and rely on backend `/me` / session introspection for all auth decisions.

---

## HIGH

### Finding 3 — Non-Atomic Refresh Token Rotation (Race Condition)

**Severity:** HIGH  
**Location:** `backend/app/services/auth_service.py::refresh_tokens()`

**Issue:**  
Refresh token rotation is not atomic. Two concurrent requests with the same refresh token can both pass the `is_revoked == False` and `cached != None` checks before either revokes the session, then each issue a new refresh token. This breaks the one-time-use guarantee and forks the session family.

**Fix:**  
Use a DB row lock (`SELECT ... FOR UPDATE`) and perform revoke + new session creation in a single transaction. Atomicize the Redis check-and-delete using `GETDEL` or a Lua script to ensure the token is consumed exactly once.

---

### Finding 4 — Logout Cannot Revoke Refresh Session (Cookie Path Mismatch)

**Severity:** HIGH  
**Location:** `backend/app/api/v1/endpoints/auth.py::_set_auth_cookies()`, `/logout` endpoint

**Issue:**  
The refresh cookie is set with `path="/api/v1/auth/refresh"`. The `/logout` endpoint is at `/api/v1/auth/logout`, so browsers will NOT send the refresh cookie to logout. This means `logout_user()` receives no refresh token, cannot revoke the server-side session, and only clears the browser cookie. A stolen refresh token remains valid until expiry.

**Fix:**  
Widen the refresh cookie path to cover both endpoints, e.g., `path="/api/v1/auth"`. Or move the logout endpoint under the same path as refresh. Ensure the same path is used when deleting the cookie.

---

### Finding 5 — CSRF Origin Check Bypassable via Prefix Match

**Severity:** HIGH  
**Location:** `backend/app/api/v1/endpoints/auth.py::_verify_origin()`

**Issue:**  
`origin.startswith(allowed)` can be bypassed. If `ALLOWED_ORIGINS` contains `https://app.example.com`, then `https://app.example.com.evil.com` also passes. The same issue applies to `Referer` header prefix matching.

**Fix:**  
Parse the origin with `urllib.parse.urlparse` and perform exact match on scheme + hostname + port. Normalize allowed origins to a frozenset of canonical origins.

```python
from urllib.parse import urlparse

def _verify_origin(request: Request) -> None:
    raw = request.headers.get("Origin") or request.headers.get("Referer", "")
    parsed = urlparse(raw)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in settings.ALLOWED_ORIGINS_SET:
        raise HTTPException(status_code=403, detail="CSRF check failed")
```

---

### Finding 6 — CSRF Protection Incomplete (Login/Register Not Protected)

**Severity:** HIGH  
**Location:** `backend/app/api/v1/endpoints/auth.py` — all state-changing endpoints

**Issue:**  
CSRF checks only appear on `/refresh` and `/logout`. With cookie-based auth, all state-mutation APIs are CSRF targets. `/login` and `/register` are vulnerable to login CSRF and session swapping attacks. Other authenticated mutation endpoints (not shown) likely also lack protection.

**Fix:**  
Apply CSRF defense globally to all unsafe HTTP methods (POST/PUT/PATCH/DELETE) via a FastAPI dependency or middleware. At minimum, validate `Origin`/`Sec-Fetch-Site` headers consistently. Consider adding double-submit CSRF tokens for cross-origin scenarios.

---

### Finding 7 — Non-Atomic Failed Login Counter (Lockout Bypass + DoS)

**Severity:** HIGH  
**Location:** `backend/app/services/auth_service.py::_record_failed_attempt()`

**Issue:**  
`user.failed_login_count += 1` is a read-modify-write that is not atomic under concurrent requests. Simultaneous failed login attempts can lose increments, allowing an attacker to bypass account lockout. Conversely, account-level lockout alone allows an attacker to DoS any account by repeatedly triggering failures.

**Fix:**  
Use a DB atomic update (e.g., `UPDATE users SET failed_login_count = failed_login_count + 1 WHERE id = ?`) or row-level lock. Complement account lockout with IP+email rate limiting, exponential backoff, and CAPTCHA for repeated failures.

---

### Finding 8 — All-Session Logout Doesn't Invalidate Existing Access Tokens

**Severity:** HIGH  
**Location:** `backend/app/services/auth_service.py::logout_user()`, `_revoke_all_user_sessions()`; `/me` token_version check

**Issue:**  
`all_sessions=True` only revokes refresh sessions in the DB. Already-issued access tokens remain valid until expiry. Since `/me` validates `token_version`, the `token_version` must also be incremented on all-session logout, password change, or account compromise response — otherwise existing access tokens bypass revocation.

**Fix:**  
Atomically increment `user.token_version` in the same transaction as session revocation for all-session logout and password changes. For single-session logout, consider a `jti` denylist in Redis if immediate access token invalidation is required.

---

### Finding 9 — Frontend JWT Verification Missing Critical Claim Checks

**Severity:** HIGH  
**Location:** `frontend/lib/auth.ts::verifySession()`, `frontend/middleware.ts::middleware()`

**Issue:**  
Frontend JWT verification does not validate `issuer`, `audience`, `type` claim, `sub` format, or `ver` semantics. If any other token signed with the same secret exists (e.g., email verification, password reset), it could pass the frontend gating.

**Fix:**  
Pass `issuer` and `audience` to `jwtVerify`. Validate payload structure: enforce `type === "access"`, `sub` as a valid UUID string, `ver` as a number. Critical authorization decisions must be re-verified on the backend regardless.

```ts
await jwtVerify(token, JWT_SECRET, {
  algorithms: [JWT_ALGORITHM],
  issuer: process.env.NEXT_PUBLIC_APP_NAME,
  audience: process.env.NEXT_PUBLIC_APP_NAME,
});
```

---

## MEDIUM

### Finding 10 — Backend decode_access_token() Doesn't Validate `type` Claim

**Severity:** MEDIUM  
**Location:** `backend/app/core/security.py::decode_access_token()`

**Issue:**  
The backend does not enforce `payload["type"] == "access"` after decoding. If future tokens (email verification, password reset) use the same issuer/audience/secret, they could be accepted as access tokens.

**Fix:**  
After decoding, assert `payload.get("type") == "access"`. Validate `sub` and `ver` types. Consider separate secrets or audiences per token type.

---

### Finding 11 — JWT Algorithm Not Validated Against Allowlist at Startup

**Severity:** MEDIUM  
**Location:** `backend/app/core/security.py` — settings usage

**Issue:**  
`settings.JWT_ALGORITHM` is used as-is. A misconfiguration could allow a weak or unexpected algorithm. There is no code-level enforcement preventing `"none"` or arbitrary algorithm names.

**Fix:**  
At startup, validate that `settings.JWT_ALGORITHM` is in an explicit allowlist (e.g., `{"HS256", "RS256"}`). If HS256, also validate secret entropy (minimum 32 bytes). Never allow `"none"` in any code path.

---

### Finding 12 — DB Committed Before Redis Set in Session Creation (Consistency Gap)

**Severity:** MEDIUM  
**Location:** `backend/app/services/auth_service.py::_create_refresh_session()`

**Issue:**  
The DB commit happens before the Redis `SET`. If Redis fails, the DB has an active session row but the client received no usable token. During rotation, the old token is already revoked in DB, and if Redis fails, the new token is also unusable — forcing the user into an unrecoverable logged-out state.

**Fix:**  
Design refresh rotation as a single consistent workflow. Write to Redis before committing to DB (with an appropriate TTL), or implement compensation logic (rollback the DB row if Redis fails). Alternatively, treat DB as the authority and make Redis a cache-aside with refresh fallback to DB.

---

### Finding 13 — Redis/DB Inconsistency in Batch Revocation

**Severity:** MEDIUM  
**Location:** `backend/app/services/auth_service.py::_revoke_family()`, `_revoke_all_user_sessions()`

**Issue:**  
Redis deletes happen inside the loop before the final DB commit. A mid-loop failure leaves some sessions deleted in Redis but still `active` in DB, or vice versa. This breaks the consistency of revocation.

**Fix:**  
Batch DB updates in a transaction. Use Redis pipeline or Lua script for atomic multi-key deletion. Have a background cleanup job reconcile stale Redis keys, and treat DB `revoked_at` as the authoritative source of truth.

---

### Finding 14 — X-Forwarded-For Trusted Without Validation (IP Spoofing)

**Severity:** MEDIUM  
**Location:** `backend/app/api/v1/endpoints/auth.py::_client_ip()`

**Issue:**  
`X-Forwarded-For` is unconditionally trusted. An attacker can inject arbitrary values to bypass IP-based rate limiting, corrupt audit logs, or cause DB errors (the `created_ip` field has `max_length=45` but no length validation before storage).

**Fix:**  
Only trust forwarded headers from known trusted proxy IPs. Validate the extracted IP with `ipaddress.ip_address()`. Truncate or reject values exceeding 45 characters before storing.

---

### Finding 15 — Missing Email Normalization

**Severity:** MEDIUM  
**Location:** `backend/app/services/auth_service.py::register_user()`, login flow

**Issue:**  
Emails are not normalized before storage or lookup. Depending on DB collation, `User@Example.com` and `user@example.com` may be treated as distinct accounts, allowing duplicate registrations and bypassing lockout/rate-limit checks.

**Fix:**  
Normalize email (trim + lowercase) at the input boundary in the Pydantic schema or service layer. Ensure the unique index is on the normalized value.

---

### Finding 16 — Verbose Error Messages Leak Internal State

**Severity:** MEDIUM  
**Location:** `backend/app/services/auth_service.py` — various AuthError messages

**Issue:**  
Messages like `"Email already registered"`, `"Account temporarily locked"`, `"Refresh token expired"`, `"Session not found in store"`, and `"User not found or inactive"` reveal account existence, session state, and internal storage structure to unauthenticated callers.

**Fix:**  
Normalize all auth-related external error responses to generic messages (`"Invalid credentials"`, `"Invalid session"`). Log the specific reason server-side with a correlation ID.

---

### Finding 17 — Redis Cache Value Not Cross-Validated Against DB

**Severity:** MEDIUM  
**Location:** `backend/app/services/auth_service.py::refresh_tokens()`

**Issue:**  
The Redis cached value (`str(user_id)`) is retrieved but never compared against `session_row.user_id`. A Redis poisoning, key collision, or operational mistake would go undetected.

**Fix:**  
Assert `cached == str(session_row.user_id)`. On mismatch, reject the session and emit a security alert.

---

### Finding 18 — Revoked Session Rows May Be Cleaned Up Too Early (Reuse Detection Gap)

**Severity:** MEDIUM  
**Location:** `backend/app/services/auth_service.py::refresh_tokens()` — reuse detection logic

**Issue:**  
Reuse detection depends on the revoked session row existing in the DB. If a cleanup job deletes revoked/expired sessions too aggressively, a replayed revoked token would be treated as simply invalid (no row found), and the family revocation would not trigger.

**Fix:**  
Preserve revoked token rows (at minimum: `family_id`, `token_hash`, `revoked_at`, `expires_at`) for the full lifetime of the token family before deletion. Separate "expired" cleanup from "revoked" cleanup policies.

---

### Finding 19 — `COOKIE_SECURE` Tied to `DEBUG` Flag

**Severity:** MEDIUM  
**Location:** `backend/app/api/v1/endpoints/auth.py` — module scope

**Issue:**  
`COOKIE_SECURE = not settings.DEBUG` means a single misconfiguration (`DEBUG=True` in production) disables Secure cookies, making tokens transmissible over HTTP.

**Fix:**  
Enforce Secure cookies unconditionally in production. Add startup validation that prevents the application from starting with `DEBUG=True` in a production environment.

---

### Finding 20 — Frontend Middleware Protects Only `/dashboard`

**Severity:** MEDIUM  
**Location:** `frontend/middleware.ts` — `PROTECTED_PATHS` config

**Issue:**  
Only `/dashboard` is in the protected paths list. As new routes, server actions, route handlers, or API proxies are added, they will be unprotected by default unless the list is manually updated.

**Fix:**  
Manage protected paths as an explicit boundary, or invert the approach (protect everything and allowlist public paths). Backend APIs must always perform their own authentication checks regardless of frontend middleware.

---

## LOW

### Finding 21 — Refresh Token Hashed with Plain SHA-256 (No Server Pepper)

**Severity:** LOW  
**Location:** `backend/app/core/security.py::hash_refresh_token()`

**Issue:**  
Refresh tokens are stored as plain SHA-256 hashes. While `secrets.token_urlsafe(48)` makes brute force impractical, a DB dump alone is sufficient to attempt offline attacks — there is no server-side secret separating token storage from raw token derivation.

**Fix:**  
Use `HMAC-SHA256(server_pepper, raw_token)` where `pepper` is stored in an environment variable or secrets manager, separate from the DB.

---

### Finding 22 — Missing `nbf` Claim in Access Token

**Severity:** LOW  
**Location:** `backend/app/core/security.py::create_access_token()`

**Issue:**  
No `nbf` (not before) claim is set. This is not strictly required but makes clock-skew and immediate post-issuance validity semantics ambiguous.

**Fix:**  
Add `"nbf": now` to the payload and configure a small `leeway` in `decode_access_token()`.

---

### Finding 23 — No Cookie Prefix (`__Host-` or `__Secure-`)

**Severity:** LOW  
**Location:** `backend/app/api/v1/endpoints/auth.py` — cookie settings

**Issue:**  
Cookie prefixes are not used. The `__Host-` prefix enforces Secure, Path=/, and no Domain, reducing cookie injection risk. Without it, subdomain cookie injection is theoretically possible.

**Fix:**  
Use `__Secure-access_token` and `__Secure-refresh_token` as cookie names. Note: `__Host-` requires `Path=/` and no `Domain`, which conflicts with the restricted refresh cookie path.

---

### Finding 24 — User-Agent Not Truncated Before DB Storage

**Severity:** LOW  
**Location:** `backend/app/services/auth_service.py::_create_refresh_session()`

**Issue:**  
The `user_agent` field has `max_length=512` in the model but there is no explicit truncation or validation before the value is stored. An oversized User-Agent can cause a DB constraint error.

**Fix:**  
Truncate the User-Agent string to 512 characters before use, either in the service layer or via a Pydantic validator in the request schema.

---

### Finding 25 — `requireAuth()` Throws Generic Error (Potential 500 Exposure)

**Severity:** LOW  
**Location:** `frontend/lib/auth.ts::requireAuth()`

**Issue:**  
On auth failure, a generic `Error("Unauthorized")` is thrown. If callers do not handle this properly, it may surface as an unhandled 500 response rather than a clean 401/redirect.

**Fix:**  
In Next.js, use `redirect("/login")`, `notFound()`, or an explicit 401 response helper to standardize the failure mode. Do not rely on callers to handle a raw `Error` correctly.

---

## Recommended Remediation Priority

1. **[CRITICAL]** Add `JWT_SECRET_KEY` fail-fast validation — reject empty/short secrets at startup.
2. **[CRITICAL]** Switch to asymmetric JWT (RS256/EdDSA) or remove frontend JWT signing capability.
3. **[HIGH]** Atomize refresh token rotation with DB row lock + Redis `GETDEL`/Lua.
4. **[HIGH]** Fix refresh cookie path so logout can revoke the server-side session.
5. **[HIGH]** Replace `startswith()` CSRF check with exact origin match; apply to all unsafe endpoints.
6. **[HIGH]** Increment `token_version` on all-session logout and password change.
7. **[HIGH]** Atomize failed login counter; add IP-level rate limiting alongside account lockout.
8. **[MEDIUM]** Normalize error messages; add Redis↔DB consistency cross-validation; fix X-Forwarded-For handling.

---

## Additional Findings from Real-File Analysis (2nd Pass)

> The following were identified by Codex after reading the actual source files in the repository, supplementing the snippet-based analysis above.

### Additional Finding A — Next.js Version Confirmed Safe for CVE-2025-29927
- **Severity:** INFO
- **Location:** `frontend/package.json`
- **Note:** Next.js `16.2.4` is outside the known vulnerable range for CVE-2025-29927 (affected: `11/12/13/14/15` specific builds, patched at `12.3.5`, `13.5.9`, `14.2.25`, `15.2.3`). Structural defense (server-side re-verification, proxy-level header stripping) is still recommended.

### Additional Finding B — Timezone replace() Bug Confirmed (Lockout Bypass)
- **Severity:** MEDIUM
- **Location:** `backend/app/services/auth_service.py:154`, `backend/app/models/refresh_session.py:36`
- **Issue:** `replace(tzinfo=timezone.utc)` only attaches a timezone label without converting the underlying value. If DB returns naive local time, lockout expiry comparisons will be off by the server's UTC offset.
- **Fix:** Use `astimezone(timezone.utc)` for actual conversion. Enforce timezone-aware UTC columns throughout the DB schema.

### Additional Finding C — all_sessions Logout Session DoS Risk
- **Severity:** HIGH
- **Location:** `backend/app/api/v1/endpoints/auth.py:128`
- **Issue:** Possession of a single stolen refresh token is sufficient to call `all_sessions=true` and wipe all active sessions for that account. This turns token theft into a full account DoS.
- **Fix:** Require step-up authentication (password re-entry or active access token) before allowing all-session revocation. Add rate limiting and audit logging for this action.

### Additional Finding D — Register Race Condition 500 Exposure
- **Severity:** LOW
- **Location:** `backend/app/services/auth_service.py:33`
- **Issue:** Concurrent registrations with the same email will hit a DB unique constraint after both pass the SELECT check, surfacing an unhandled `IntegrityError` as a 500.
- **Fix:** Catch `IntegrityError` and return HTTP 409. Simplify to insert-first pattern.

### Additional Finding E — Email Enumeration via Registration Errors
- **Severity:** LOW
- **Location:** `backend/app/services/auth_service.py:35`
- **Issue:** "Email already registered" reveals account existence. Combined with the 3/hr rate limit, this is low-risk but still leaks PII status.
- **Fix:** For public-facing services, use a neutral message and email-based confirmation flow instead.
