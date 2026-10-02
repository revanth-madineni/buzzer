# backend/app/

## Purpose
The Buzzer backend: a FastAPI REST API (`/api/*`) and a python-socketio real-time gateway
(`/socket.io/*`) served from one ASGI app. MySQL holds the durable record (courses, games,
sessions, scores); Redis holds live game state. Hosts create rooms over REST and drive them
over sockets; players join and answer over sockets.

## Contents
Top-level files:
- `main.py` — Builds the FastAPI `app`: CORS, slowapi, exception handlers, and the four routers
  under `/api`. The lifespan connects Redis and runs `bootstrap_admin`. Exports **`asgi_app`**
  (`socketio.ASGIApp(sio, other_asgi_app=app)`), which is what must be served, not `app`.
- `config.py` — `Settings` from env/`.env`: `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, JWT keys,
  `CORS_ORIGINS`, `MAX_ROOMS` (50), `FRONTEND_URL`, `ADMIN_USERNAME/PASSWORD`,
  `STRESS_TEST_KEY`. Helpers: `is_development`, `is_stress_test_mode`.
- `database.py` — Async engine, `AsyncSessionLocal`, `Base`, and `get_db` (commits after the
  handler returns, rolls back on exception).
- `redis_client.py` — Lazy process-wide `get_redis()` (`decode_responses=True`) and
  `close_redis()`.
- `migrations/` — Alembic (versions 001–004). Not covered by a context file.

Subdirectories (each has its own `CLAUDE.md`, so read it before working there):
| dir | role |
|---|---|
| `models/` | SQLAlchemy tables. A game belongs to at most one course (`Game.course_id`, nullable); each `GameSession` keeps the course it was played in, which can differ. |
| `schemas/` | Pydantic request/response shapes and per-question-type structure validation. |
| `common/` | Auth dependencies (global role only), exception types, logging, rate limiter. |
| `services/` | Business logic: access checks, room lifecycle, scoring, Redis state, roster, exports. |
| `routers/` | REST endpoints: `auth`, `admin` (all admin-only), `game` (host-facing), `health`. |
| `websocket/` | Socket.IO gateway: join/rejoin, phase state machine, answers, timers, disconnects. |

## How it fits together
Dependency direction: `routers/` and `websocket/` → `services/` → `models/` + Redis.
`schemas/` validate at the REST edge (the socket gateway validates payloads by hand), and
`common/` is shared plumbing. Nothing below `routers/`/`websocket/` imports them.

### Authorization is split across three layers
1. **`common/`**: global `User.role` only (`require_admin`, `require_user` = not GUEST).
2. **`services/access_service.py`** (hosting) and **`game_service.authorise_player`**
   (joining):
   - Hosting a game needs `HOST` on **the game's course**, plus a grant if the game is
     `restricted`.
   - Joining as a player needs a roster row or course `PLAYER`/`HOST` on the session's course.
     Guests and admins join any room.
   - `common/dependencies.py` wraps the hosting rule as `require_course_host`,
     `require_game_host`, `require_question_host` and `require_session_host`.
3. **`routers/game.py` / `websocket/gateway.py`**: session **ownership**
   (`host_user_id == user.id` or ADMIN) for managing a session or joining it as host.
New host-facing endpoints should use the `require_*_host` dependencies rather than writing their
own queries. Older endpoints still use layer 3 (ownership) only. Full tables are in `common/`,
`services/`, and `routers/` `CLAUDE.md`.

### Where state lives
| store | holds | lifetime |
|---|---|---|
| MySQL (`models/`) | users, courses, rosters, games, questions, `GameSession`, `SessionScore` (one row per answer) | durable; the source of truth for scores and leaderboards |
| Redis `room:{code}` | status, `question_phase`, `question_index`, `question_ids`, lock/timer fields, `host_sid` | 90-min TTL, refreshed on socket activity |
| Redis `session:{id}:*` | players (name, running score, connected), current question + `started_at`, answered sets, answer distributions | **no TTL** (see `services/CLAUDE.md`) |
| gateway process memory | `_sid_ctx` (sid → user/role/room), question timer tasks, host-abandon tasks | per process; lost on restart |

### Data flow for one game
1. **Create room (REST, host).** `POST /api/game/rooms` → `routers/game.py` →
   `game_service.create_room`. It checks access, requires the room's course to be the game's
   course (an admin's first room attaches a courseless game), enforces `MAX_ROOMS`, and generates
   a code. It inserts `GameSession(status=LOBBY)` in MySQL and `room:{code}` in Redis.
2. **Player auth (REST).** `GET /api/game/rooms/{code}/ping`, then a token from
   `/api/auth/guest`, `/api/auth/login`, or OAuth2 (`oauth2-callback` → temp token →
   `exchange-temp`).
3. **Connect + join (socket).** `connect` → `websocket/middleware.authenticate_socket`
   (access/temp JWT). Then `join_room`:
   - Host path: an ownership check, then the socket enters `{code}` and `{code}:host`.
   - Player path: `authorise_player`, then `state.add_player`, then the socket enters `{code}`
     and `user:{id}`.
   Each joiner gets `sync_state`, and the host gets `player_joined`.
4. **Start (socket, host).** `host_advance` with `question_phase` unset:
   - `game_service.start_game` **commits** `IN_PROGRESS` and returns ordered questions.
   - Their IDs go into `room:{code}.question_ids`.
   - `state.set_current_question` stores the question with `started_at`.
   - `new_question` (no `answer_data`) goes to the room, and a timer task starts. The phase is
     now `QUESTION`.
5. **Answer (socket, player).** `submit_answer`:
   - The gateway checks the phase, the lock, that the question ID matches the current one, and
     `has_answered`.
   - `game_service.record_answer` runs `calculate_score`, inserts a `SessionScore` (committed
     when the gateway's `_db()` context exits), and updates the Redis running score, answered
     set, and distribution.
   - `answer_received` goes to the player and `answer_status` to the host room. If every
     player has answered, the timer is cancelled and the host gets `answer_phase_ended`.
6. **Time up.** The timer task sends `answer_phase_ended` to the host. About 0.5 s later it sets
   `question_locked` and emits `question_locked` to the room. Answers are now rejected. The phase
   does **not** change; only the host advances.
7. **Reveal (socket, host).** `host_advance` in `QUESTION`:
   - The gateway builds `_answer_reveal` from `answer_data`, the Redis distribution, and a
     leaderboard summed from MySQL.
   - The host gets `question_results` with the distribution. Each `user:{id}` room gets its own
     points, score, and rank.
   - The phase is now `RESULTS`.
8. **Next / finish.** `host_advance` in `RESULTS` loops back to step 4's broadcast with the next
   question ID. After the last question:
   - `complete_game` **commits** `COMPLETED`.
   - The host gets `game_over` with anonymous scores and a per-question summary. Each player
     gets their own summary.
   - Redis `session:*` keys are *not* cleaned up.
9. **After the game (REST).** Host: `/api/game/sessions/{id}/export|guests|merge-guest`. Admin:
   `/api/admin/sessions/{id}/export` (Canvas) and `/report`. All of these read MySQL only.

Side paths:
- **Host disconnects while `IN_PROGRESS`:** the question is auto-locked with the remaining time
  saved, `host_disconnected` is emitted, and a 5-min abandon task starts. On host re-join the
  task is cancelled and the question is unlocked with the saved time.
- **Host lock/unlock:** `host_lock_question` pauses and resumes the timer.

## Gotchas
Most important cross-cutting issues. Details and more are in each subdirectory's file.
- **`APP_ENV` defaults to `"development"`.** If it isn't set in production:
  - dev `netid` login works (anyone can sign in as any netid);
  - HTTP and socket rate limits are off;
  - `/api/docs` is public;
  - the socket manager is in-memory;
  - cookies lose `secure`.
- **Serve `app.main:asgi_app`, not `app.main:app`.** Serving `app` silently drops all
  socket traffic.
- **Single-instance assumption.** Timers, abandon tasks, and sid context live in process
  memory (`websocket/CLAUDE.md`). Multiple workers/instances need sticky sessions at minimum and
  still misbehave on host reconnect.
- **Room codes can collide with finished sessions.** Uniqueness is checked only against Redis,
  but `game_sessions.room_code` is UNIQUE in MySQL (`services/CLAUDE.md`).
- **No DB-level answer dedupe.** A double submit can be scored twice
  (`websocket/` race + `models/` missing unique constraint).
- **Answer-reveal logic exists in four copies** (`services/` ×3, `websocket/` ×1), and they have
  already diverged (`report_service` lacks `multi_select`).
- **Temp tokens work everywhere.** They authenticate like access tokens on REST and sockets
  (`common/CLAUDE.md`).
- **OAuth2 identity is a request header.** `X-Auth-Request-User` is trusted, which is safe only
  behind Traefik's OAuth2 middleware (`routers/CLAUDE.md`).
- **Error shape varies.** Clients see `{"error","message"}` from `BuzzerError`,
  `{"error":"VALIDATION_ERROR","detail":[…]}` from validation, and `{"detail": "..."}` from
  `HTTPException`. The player frontend only reads `detail`.
