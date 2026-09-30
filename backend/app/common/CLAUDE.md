# backend/app/common/

## Purpose
Cross-cutting backend plumbing: FastAPI auth dependencies (who is the caller, are they an
admin), the app's exception types and JSON error handlers, structlog setup, and the slowapi
rate limiter.

## Contents
- `__init__.py` — Empty.
- `dependencies.py` — FastAPI `Depends` helpers:
  - `_token_from_request` — JWT from `Authorization: Bearer` header, falling back to the
    `access_token` cookie. (Also reused directly by `routers/auth.py` `/exchange-temp`.)
  - `get_current_user` — decodes the JWT, accepts `token_type` **`access` or `temp`**, loads the
    `User` by `sub` from the DB. 401 on missing/invalid/expired token or unknown user.
  - `require_admin` — 403 unless `user.role == "ADMIN"`.
  - `require_user` — 403 if `user.role == "GUEST"`; lets `ADMIN` and `USER` through.
  - `get_refresh_token` — reads the `refresh_token` cookie or 401s.
- `exceptions.py` — `BuzzerError(code, message, status_code)` and subclasses `NotFoundError`
  (404), `ForbiddenError` (403), `UnauthorizedError` (401), `ConflictError` (409).
  `register_exception_handlers(app)` maps them to `{"error": code, "message": ...}`, validation
  errors to 422 `{"error": "VALIDATION_ERROR", "detail": [...]}`, and anything else to a
  generic 500 `INTERNAL_ERROR`.
- `logging.py` — `configure_logging()`: structlog with console renderer + DEBUG in development,
  JSON + INFO otherwise; quiets `uvicorn.access` in production unless stress-test mode is on.
- `rate_limit.py` — the shared slowapi `limiter`. Keyed by client IP, except a random UUID per
  request (i.e. effectively **no limit**) in development, or when the request's `X-Stress-Key`
  header matches `settings.STRESS_TEST_KEY`.

## How it fits in
Routers put `Depends(require_admin)` / `Depends(require_user)` / `Depends(get_current_user)`
on endpoints, and raise the `BuzzerError` subclasses from anywhere (routers or services).
`main.py` calls `register_exception_handlers` and attaches `limiter` to `app.state`; endpoints
opt in with `@limiter.limit(...)`. WebSocket auth does **not** go through these dependencies —
`websocket/middleware.py` has its own copy of the token check.

### What is (and isn't) checked here
Only the **global** `User.role` (`ADMIN | USER | GUEST`, see `models/CLAUDE.md`):

| dependency | ADMIN | USER | GUEST |
|---|---|---|---|
| `get_current_user` | ✓ | ✓ | ✓ |
| `require_user` | ✓ | ✓ | ✗ 403 |
| `require_admin` | ✓ | ✗ 403 | ✗ 403 |

**There is no course-access or game-access dependency in `common/`.** Nothing here looks at
`UserCourseAccess` (HOST/PLAYER) or `UserGameAccess`. Those checks are done ad hoc with
queries in `routers/game.py` and `services/game_service.py` (filtering on
`UserCourseAccess.role == "HOST"`). `websocket/gateway.py` tracks a per-connection
`HOST`/`PLAYER` role for a room — see `websocket/CLAUDE.md` for what it verifies. A new
host-facing endpoint gets no course check unless it adds one itself.

## Gotchas
- **Temp tokens authenticate like access tokens.** `get_current_user` accepts `token_type ==
  "temp"` (15-min tokens from the OAuth2 callback and dev `netid` login, meant only for
  `/api/auth/exchange-temp`). So a temp token can call any endpoint, including admin ones if the
  user is an admin. `websocket/middleware.py` accepts them too. Refresh tokens are rejected.
- **Role comes from the DB, not the JWT.** `create_access_token` embeds `role`, but these
  dependencies ignore that claim and use the freshly loaded `user.role`, so promotions and
  demotions take effect immediately without re-login.
- The bearer header wins over the cookie; an invalid header token is not retried against the
  cookie.
- `require_user` is a deny-list (`!= GUEST`), not an allow-list — a new global role would be
  let through by default.
- Rate limiting keys on `get_remote_address` (the direct peer). Behind a reverse proxy without
  forwarded-IP handling, all clients share the proxy's IP and one limit bucket.
- The rate limiter is disabled in development, so rate-limit behavior can't be observed locally.
- Anyone who knows `STRESS_TEST_KEY` bypasses rate limits in production; leave it unset
  outside load tests.
- The catch-all 500 handler hides the exception from clients; check the `unhandled_error` log
  line for the real traceback.
