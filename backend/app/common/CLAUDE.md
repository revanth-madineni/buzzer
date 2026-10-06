# backend/app/common/

## Purpose
Cross-cutting backend plumbing: FastAPI auth dependencies (who is the caller, are they an
admin), the app's exception types and JSON error handlers, structlog setup, the slowapi
rate limiter, and the request body size limit.

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
  - Course-host dependencies (T4), built on `services/access_service.py`. Each runs after
    `require_user`, **loads the resource first**, and checks the course that resource belongs
    to, never a course ID from the URL:
    - `require_course_host(course_id)` → `Course`;
    - `require_game_host(game_id)` → `Game` (checks `game.course_id`);
    - `require_question_host(game_id, question_id)` → `Question` (404 if it isn't in that game);
    - `require_session_host(session_id)` → `GameSession` (checks `session.course_id`);
    - `require_image_host(image_id)` (T8) → `Image` (404 for unknown/malformed IDs; checks
      HOST on `image.course_id`; a courseless image is 403 for non-admins).
- `exceptions.py` — `BuzzerError(code, message, status_code, extra=None)` and subclasses
  `NotFoundError` (404), `ForbiddenError` (403), `UnauthorizedError` (401), `ConflictError`
  (409), `ImageInUseError` (409 `IMAGE_IN_USE` with `usage` + `hidden_usage_count`, T8).
  `register_exception_handlers(app)` maps them to `{"error": code, "message": ...}` plus any
  `extra` fields (never overriding those two), validation errors to 422 `{"error":
  "VALIDATION_ERROR", "detail": [...]}`, a MySQL deadlock (`DBAPIError` errno 1213, T8) to
  409 `CONFLICT` "The server was busy; please try again", and anything else to a generic
  500 `INTERNAL_ERROR`.
- `logging.py` — `configure_logging()`: structlog with console renderer + DEBUG in development,
  JSON + INFO otherwise; quiets `uvicorn.access` in production unless stress-test mode is on.
- `body_limit.py` (T7) — `BodySizeLimitMiddleware`, a pure ASGI middleware taking
  `(method, path regex, max_bytes)` rules (first match wins; other requests untouched).
  Registered in `main.py`, inside CORS so a 413 still gets CORS headers:
  - `POST ^/api/admin/images$`, `POST ^/api/host/courses/\d+/images$` and the T8 replace
    routes `POST ^/api/{admin,host}/images/[^/]+/replace$`: 2.5 MB;
  - `POST ^/api/admin/games/import$`: 26 MB.
  A `Content-Length` over the limit gets 413 `{"error":"REQUEST_TOO_LARGE"}` without the body
  being read. Otherwise it wraps `receive` and counts bytes, so a chunked or understated body
  is cut off too: it raises out of `receive`, drops whatever error the app then sends (FastAPI
  turns the aborted read into a 400), and sends the 413 instead.
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
`get_current_user`, `require_user` and `require_admin` check only the **global** `User.role`
(`ADMIN | USER | GUEST`, see `models/CLAUDE.md`):

| dependency | ADMIN | USER | GUEST |
|---|---|---|---|
| `get_current_user` | ✓ | ✓ | ✓ |
| `require_user` | ✓ | ✓ | ✗ 403 |
| `require_admin` | ✓ | ✗ 403 | ✗ 403 |

The course-host dependencies add the course/game rules. The predicates live in
`services/access_service.py` (see `services/CLAUDE.md`); these dependencies only pick the
resource and map failures to errors, in this order:
401 → GUEST 403 `FORBIDDEN` → 404 `NOT_FOUND` → 403 `FORBIDDEN` (no HOST on the course) →
403 `GAME_RESTRICTED` (restricted game, no grant). For a non-admin, a game with no course is a
404. ADMIN passes every check once the resource exists. A new host-facing endpoint should use
one of these dependencies rather than its own query. `websocket/gateway.py` tracks a
per-connection `HOST`/`PLAYER` role for a room; see `websocket/CLAUDE.md` for what it verifies.

Import edge: `dependencies.py` imports from `services/` (`auth_service`, and now
`access_service`). This is the only place `common/` depends on `services/`.

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
- **Body limits can't be a dependency.** Starlette spools the whole multipart body before
  dependencies run, so size checks in a handler (like `prepare_image`'s 2 MB) are per-file
  rules, not protection. New upload routes need a `BodySizeLimitMiddleware` rule, and the
  proxy in front must allow the size too (`backend/CLAUDE.md`).
