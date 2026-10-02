# backend/app/routers/

## Purpose
FastAPI HTTP endpoints, all mounted under `/api` in `main.py`. Each router picks an auth
dependency from `common/dependencies.py`, does light validation/ownership checks, and calls
into `services/`. Live gameplay is **not** here — it runs over Socket.IO in `websocket/`.

## Contents
- `__init__.py` — Empty.
- `health.py` — `GET /api/health`: MySQL + Redis ping, active room/player counts. Public.
- `auth.py` — `/api/auth/*`: login, OAuth2 callback, temp-token exchange, guest join, refresh,
  logout. Sets the `refresh_token` cookie (httponly, `samesite=lax`, `path=/api/auth`, secure
  outside development).
- `admin.py` — `/api/admin/*`: 37 endpoints for courses, rosters, games, questions, game
  import/export, local users, access grants, guest merge, and session export/report.
  **Every one** depends on `require_admin`. T4 added:
  - `POST /admin/games/{id}/move` (assign/move with a `confirm` step that drops grants which
    would stop working);
  - `GET /admin/courses/{id}/access` and `GET /admin/games/{id}/access`;
  - `course_id` on game create and import (a form field; the bundle's `game` block may not
    carry one);
  - `restricted` on game update, and `allow_guests` on course create/update.
  Question endpoints are thin wrappers over `services/question_service.py`.
- `host.py` — `/api/host/*` (T4): course-host management. Every endpoint uses a
  `require_*_host` dependency (see the table below), and URLs are flat (`/host/games/{id}`,
  not nested under a course).
- `game.py` — `/api/game/*`: host resource discovery, room creation, room lookup, and
  per-session host tools (delete, guest list/merge, CSV export).

## How it fits in
`main.py` includes these routers, then wraps the FastAPI app in a Socket.IO ASGI app so
`/socket.io/*` goes to `websocket/gateway.py`. Request/response shapes come from `schemas/`
(`admin.py` ↔ `schemas/admin.py`, etc.). The DB session comes from `database.get_db`, which
**commits after the handler returns** (rolls back on exception). Handlers that don't call
`db.commit()` themselves rely on that.

### Endpoint access map
Global roles from `common/` (`ADMIN | USER | GUEST`); course/game rules come from
`services/access_service.py` (see `services/CLAUDE.md`).

**Admin-only** — everything under `/api/admin/` (`require_admin`). Hosts (USER with course
`HOST` access) cannot call any of these. Hosts use `/api/host/*` instead, which is narrower:
- no Canvas export;
- no column-mapping roster import;
- no grants or moves;
- no deleting games that have results.

**Course-host** — `/api/host/*` (`routers/host.py`). Errors in order: 401 → GUEST 403 → 404 →
403 `FORBIDDEN` → 403 `GAME_RESTRICTED` → state checks.

| endpoint | dependency | notes |
|---|---|---|
| `GET/POST /host/courses/{cid}/games` | `require_course_host` | list = games of the course the caller can use (`usable_games_stmt`) + `question_count`; create = in that course, unrestricted |
| `GET/PUT/DELETE /host/games/{gid}` | `require_game_host` | PUT: title/description/max_players only. DELETE: 409 `GAME_HAS_RESULTS` if any session is COMPLETED or has a score; else removes score-less sessions (Redis first) and the game |
| `GET/POST /host/games/{gid}/questions`, `POST …/reorder` | `require_game_host` | `question_service` |
| `PUT/DELETE /host/games/{gid}/questions/{qid}` | `require_question_host` | 404 if the question isn't in that game |
| `GET/POST /host/courses/{cid}/roster` | `require_course_host` | Canvas gradebook CSV only; `mode` `add_update` (default) or `replace` |
| `GET /host/courses/{cid}/sessions?status=` | `require_course_host` | sessions **played in** the course, any host; restricted games without a grant filtered in SQL |
| `GET /host/sessions/{sid}/export`, `…/report` | `require_session_host` | CSV / HTML; 409 `SESSION_NOT_COMPLETED` unless COMPLETED |

**Host-accessible** (`require_user` = ADMIN or USER; GUEST → 403):

| endpoint | additional check |
|---|---|
| `GET /game/my-courses` | ADMIN: all courses. USER: courses where they hold `HOST`. |
| `GET /game/my-games` | ADMIN: all games (including courseless ones). USER: games whose `course_id` is a course they HOST, minus restricted games they have no grant on (`access.usable_games_stmt`). |
| `GET /game/my-active-sessions` | Only sessions where `host_user_id == user.id`. |
| `POST /game/rooms` | `create_room`: the course must equal the game's course (422 `COURSE_MISMATCH`, admins included); non-admins need `can_use_game`; an admin's first room attaches a courseless game. |
| `DELETE /game/sessions/{id}` | ADMIN or the session's `host_user_id`. Any status. |
| `GET /game/sessions/{id}/guests` | ADMIN or session host. |
| `POST /game/sessions/{id}/merge-guest` | ADMIN or session host. |
| `GET /game/sessions/{id}/export` | ADMIN or session host. Raw CSV only (no Canvas format). |

**Any authenticated user, including GUEST** (`get_current_user`):
`GET /game/rooms/{code}`, which returns session/game/course metadata for any room code.

**Public (no auth):** `GET /health`, `GET /game/rooms/{code}/ping`, and all of `/auth/*`
(except that `/auth/exchange-temp` and `/auth/refresh` need a valid temp/refresh token).

Three kinds of host checks exist:
- **Creating** a room checks *HOST on the game's course (+ a grant if the game is
  restricted)*.
- **Managing** a session through `/game/sessions/{id}/…` (delete/export/guests/merge) checks
  only *`host_user_id` ownership*, not course role. So a host who has lost HOST access can
  still manage their old sessions there.
- `/host/sessions/{id}/export|report` check **course HOST** on the session's course instead,
  so any co-host can download results, but a host who lost HOST cannot.

### Auth flows (`auth.py`)
- `POST /auth/login` (5 per 15 min): `username`+`password` → access token + refresh cookie.
  `netid` (dev only) → **temp** token.
- `GET /auth/oauth2-callback`: reads netid/email from `X-Auth-Request-User` /
  `X-Auth-Request-Email` (set by Traefik's OAuth2 proxy), creates/fetches the USER, and returns
  an HTML page that redirects to `/host/login` or `/player/login` with a temp token in the URL
  fragment.
- `POST /auth/exchange-temp` (10/min): temp → access token + refresh cookie.
- `POST /auth/guest` (10 per 15 min): room must exist in Redis with status LOBBY/IN_PROGRESS →
  creates/reuses a GUEST by email → access token + refresh cookie.
- `POST /auth/refresh`: refresh cookie → new access + new refresh cookie.
- `POST /auth/logout`: clears the cookie only.

## Gotchas
- **OAuth2 callback trusts request headers.** Identity comes straight from
  `X-Auth-Request-User`. This is only safe if Traefik strips/sets that header and the backend
  is unreachable except through Traefik; otherwise anyone can log in as any netid. The
  failure branch also logs **all** request headers.
- **Guest identity is just an email.** `/auth/guest` has no password, so anyone who knows a
  guest's email can obtain that guest's tokens. Guest tokens aren't bound to the room used to
  join (2 h access, 7-day refresh).
- **Host `merge-guest` is over-broad.** It checks that the caller hosts *this* session, but
  not that the guest played in it. It then moves **all** of that guest's scores (across every
  session) to the target netid's user and deletes the guest. The target user doesn't have to
  be on the course roster. The body is an untyped `dict`, and missing fields return 409, not 422.
- Admin and host guest merge behave differently: admin normalizes (`strip().lower()`) and,
  when no user has that netid, **promotes the guest in place** to a USER; host only lowercases
  and 404s if no such user exists.
- **No server-side logout or token revocation.** Refresh tokens aren't rotated out or
  blacklisted; logout just deletes the cookie.
- `DELETE /admin/games/{id}` **deletes every session and score ever recorded for that game**
  (to satisfy the NOT NULL FK) and does not clear Redis for a live room.
- `DELETE /admin/users/{id}` deletes the user's scores. It refuses ADMIN targets, but
  `PUT /admin/users/{id}` can demote any admin, including the last one or yourself.
- There is no endpoint to delete a course, a roster entry (only deactivate via PATCH), or a
  question's scores. Deleting a question that has scores returns 409 `QUESTION_HAS_ANSWERS`
  (admin and host, via `question_service`).
- Patching a roster entry's `netid` to one that already exists in the course violates the
  unique constraint and surfaces as a 500.
- `DELETE /game/sessions/{id}` works on LOBBY/IN_PROGRESS sessions too. It wipes Redis and the
  DB row, but doesn't notify connected sockets.
- `GET /game/rooms/{code}` has no course check, so any logged-in user (including a guest) can
  read any room's game/course metadata.
- `health.py` counts players at `room:{code}:players`, but players live at
  `session:{id}:players` (see `services/state_service.py`), so `activePlayers` is always 0.
  It uses `KEYS room:*` and counts completed rooms still in Redis as active.
- Question `PUT` (admin and host) doesn't re-validate the whole question's structure (see
  `schemas/CLAUDE.md`).
- **Live games are locked.** These writes return 409 `GAME_LIVE` while the game has an
  IN_PROGRESS session with a Redis room (see `services/CLAUDE.md`):
  - question create/update/delete/reorder (admin and host);
  - host game update/delete;
  - admin move.
  Admin game delete is deliberately exempt. Any new endpoint that writes a game or its
  questions must call `game_service.lock_game` + `assert_not_live` first.
- `list_sessions` (admin) and `my_active_sessions` do N+1 queries per session.
- Validation failures in a few places raise `ConflictError` (409), e.g. reorder and merge, or
  `HTTPException(422)` with a string detail (game import). Neither uses the standard
  `VALIDATION_ERROR` shape.
