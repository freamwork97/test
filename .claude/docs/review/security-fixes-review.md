# Security Fixes Review — JWT Auth System (FastAPI + Next.js)

> Reviewed by: Codex (gpt-5.4) via subagent
> Date: 2026-04-17
> Files reviewed: security.py, auth_service.py, auth.py (endpoints), config.py, middleware.ts, lib/auth.ts

---

## Fix-by-Fix Evaluation

### C-1/C-2: RS256 Asymmetric Key Migration

**Verdict: Correct (mostly)**

- Backend signs with private key, frontend verifies with public key — architecture is correct.
- `decode_access_token()` validates audience, issuer, and `type` claim.
- Frontend uses `importSPKI` + RS256 in both `middleware.ts` and `lib/auth.ts`.
- Fail-fast on missing/short `JWT_PUBLIC_KEY` is appropriate.
- No new vulnerabilities introduced.

**Minor note:** No key rotation mechanism exists. If private key is compromised, there is no path to invalidate issued tokens before they expire.

---

### H-1: Atomic Refresh Token Rotation via `redis.getdel()`

**Verdict: Mostly Correct**

- The `GETDEL` approach correctly closes the race window — first concurrent request wins, second gets `None` → 401.
- Reuse detection still works via DB `is_revoked` check even when Redis entry is already gone.
- `_revoke_family()` still correctly handles active sibling sessions.

**New issue introduced (availability, not security):**
- Requires Redis 6.2+. If running an older Redis, `GETDEL` will fail.
- If the server crashes after `GETDEL` (Redis consumed) but before DB commit + new session creation, the user is permanently logged out with no recovery path.
- This is a UX/availability tradeoff, not a security regression.

---

### H-2: Refresh Cookie Path Widened

**Verdict: Correct**

- Cookie `path="/api/v1/auth"` covers both `/api/v1/auth/refresh` and `/api/v1/auth/logout`.
- `set_cookie` and `delete_cookie` both use the same path — consistent.
- No regressions found.

---

### H-3: CSRF Origin Validation Fixed

**Verdict: Partially Correct**

- `startswith` bypass (e.g., `trusted.com.evil.com`) is closed — correct.
- Referer is URL-parsed before comparison — correct.
- `_check_origin_if_present()` for login/register allows API clients without Origin header — correct design.

**Remaining issues:**
1. `Origin` header is compared as a raw string (stripped but not URL-parsed/normalized). Trailing slash, uppercase scheme, or default port differences can cause false rejects in edge cases.
2. `_verify_origin()` for `/refresh` and `/logout` requires Origin or Referer — returns 403 if both are absent. This will break legitimate mobile/native app clients that use cookie-based auth but don't send Origin/Referer.
3. If the intent is browser-only endpoints, this is acceptable. If it's a public API, a separate non-cookie auth path is needed.

---

### H-5: Atomic `failed_login_count`

**Verdict: INCOMPLETE — Race Condition Remains**

- The `UPDATE failed_login_count = failed_login_count + 1` is atomic at the DB level — correctly prevents lost-update on the count.
- **However:** the `locked_until` decision uses `user.failed_login_count` — the **stale in-memory ORM value**, not the post-increment DB value.

**Concrete exploit scenario (MAX_LOGIN_ATTEMPTS=5, lock_at=4):**
```
DB count = 3
Request A reads user (count=3), Request B reads user (count=3)
Both execute: UPDATE SET count=count+1
DB becomes: count=5

A checks: 3 >= 4? No → locked_until not set
B checks: 3 >= 4? No → locked_until not set

Result: 5 failed attempts recorded, NO lockout applied.
```

**Required fix:** Move the lock decision inside the atomic UPDATE using a DB-level expression:
```python
# Option 1: SQLAlchemy case() inside UPDATE
from sqlalchemy import case
locked_until_expr = case(
    (User.failed_login_count + 1 >= settings.MAX_LOGIN_ATTEMPTS,
     now + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)),
    else_=User.locked_until
)

stmt = update(User).where(User.id == user.id).values(
    failed_login_count=User.failed_login_count + 1,
    locked_until=locked_until_expr,
)
```
Or use `SELECT ... FOR UPDATE` + `RETURNING` to get the post-increment value.

---

### H-6: `token_version` Bump on All-Session Logout

**Verdict: Partial — Access Token Invalidation Correct, Refresh Race Remains**

- `token_version` bump + `/me` endpoint check correctly invalidates existing access tokens within 15min TTL window.
- Frontend middleware does NOT check DB `token_version`, so UI route protection still trusts the access token until expiry. Acceptable given 15min TTL.

**Race condition remaining:**
```
1. all-session logout starts → queries active sessions list
2. Concurrent refresh request creates a NEW refresh session
3. logout revokes sessions from step 1 (new session not in list)
4. New refresh session survives → can issue access tokens with new token_version
5. "All sessions logged out" guarantee is broken
```

**Required fix:** Use `users.sessions_revoked_after` timestamp. Any refresh session created before this timestamp is rejected on use. This makes the invariant hold regardless of race timing.

---

### H-7: Frontend JWT Claim Validation

**Verdict: Correct but Limited**

- `issuer` + `audience` validation in `jwtVerify()` is correct and consistent between `middleware.ts` and `lib/auth.ts`.
- `type === "access"` check prevents refresh tokens from being accepted as access tokens.

**Limitations (by design, not bugs):**
- Frontend does not check `ver` against DB — immediate effect of `token_version` bump is only enforced at backend endpoints (e.g., `/me`). Frontend middleware will still let the user through until token expires.
- If `NEXT_PUBLIC_APP_NAME` env differs from backend `APP_NAME`, all tokens will fail validation (fail-closed, not a security bug, but an ops hazard).
- `lib/auth.ts` has no key caching (`getPublicKey()` calls `importSPKI` on every invocation) — performance concern in server components under load.

---

## Summary

### Fixes Confirmed Correct
- **C-1/C-2** — RS256 migration: correct architecture and validation
- **H-1** — `getdel()` atomic rotation: race condition closed (with Redis 6.2+ caveat)
- **H-2** — Cookie path widening: correctly covers both refresh and logout

### Fixes With Remaining Issues

| Fix | Severity | Issue |
|-----|----------|-------|
| **H-5** | HIGH — must fix | Lock decision uses stale ORM value; concurrent failures can bypass lockout entirely |
| **H-6** | MEDIUM | Refresh-session race during all-session logout allows new sessions to survive |
| **H-3** | LOW-MEDIUM | Origin compared as raw string (no normalization); mobile clients without Origin are blocked on /refresh and /logout |
| **H-7** | LOW | `ver` not checked on frontend; `lib/auth.ts` has no key caching |

### New Problems Introduced
- **H-1**: Redis 6.2+ hard dependency — deployment regression risk if Redis version is not controlled
- **H-1**: No recovery path if server crashes between `GETDEL` and DB commit (user locked out)
- **H-3**: `_verify_origin()` on `/refresh`/`/logout` breaks non-browser API clients using cookies

### Overall Verdict

**C-1/C-2, H-1, H-2, H-7** — Direction is correct, no security regressions.

**H-3** — Correct for browser-only use case. Breaking change for non-browser clients.

**H-5** — Must be reworked. The count increment is atomic but lock trigger is still racy. This is an actively exploitable race.

**H-6** — Access token invalidation works. All-session logout has a refresh-race gap. Requires `sessions_revoked_after` pattern or row-level locking to close fully.
