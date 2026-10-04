# backend/app/websocket/

## Purpose
The real-time game loop over Socket.IO (python-socketio, ASGI). Hosts and players connect with
a JWT, join a room by code, and from then on every phase transition (start → question →
results → … → game over), answer submission, lock/unlock, and disconnect/reconnect is handled
here. Business logic is delegated to `services/game_service.py` and Redis state to
`services/state_service.py`.

## Contents
- `__init__.py` — Empty.
- `events.py` — String constants for every event name (see the protocol below). Frontends
  hard-code the same strings.
- `middleware.py` — `authenticate_socket(auth, db)`: reads `auth["token"]`, decodes it, accepts
  `token_type` `access` **or `temp`**, and loads the `User`. It raises `ValueError`, which makes
  `connect` return `False`. This duplicates `common/dependencies.get_current_user` rather than
  reusing it.
- `gateway.py` — The `sio` `AsyncServer` and all handlers:
  - `connect` / `disconnect`, plus `join_room`, `rejoin_room`, `host_advance`, `submit_answer`,
    and `host_lock_question`.
  - Background tasks: `_question_timer_task` (time limit → `answer_phase_ended` to host, then
    auto-lock 0.5 s later) and `_host_abandon_task` (5-min grace after host disconnect →
    `abandon_game`).
  - Payload builders: `_question_payload` (no `answer_data`) and `_answer_reveal`.
  - `_emit_error(sid, message, code=None)` → `error` `{message, code?}`, and
    `_player_image_ids` (T7, the `imageIds` added to a player's `sync_state`).
  - `_client_ip` for per-IP connection rate limiting.

## How it fits in
`main.py` wraps the FastAPI app with `socketio.ASGIApp(sio, other_asgi_app=app)`, so
`/socket.io/*` lands here and everything else goes to `routers/`. A room is first created over
HTTP (`POST /api/game/rooms`), then driven entirely over sockets. In production `sio` uses
`AsyncRedisManager` for cross-instance broadcasts; in development it uses the in-memory
manager.

### Socket.IO rooms
- `{ROOM_CODE}`: everyone in the game.
- `{ROOM_CODE}:host`: host sockets only.
- `user:{user_id}`: one player's sockets, used for personalised payloads.

### Protocol
Client → server:
| event | who | payload |
|---|---|---|
| `join_room` | host or player | `{room_code, role: "HOST"\|"PLAYER"}` |
| `rejoin_room` | either | `{room_code}` (role is inferred) |
| `host_advance` | host | — (drives the phase state machine) |
| `host_lock_question` | host | — (toggles lock; pauses/resumes the timer) |
| `submit_answer` | player | `{question_id: int, answer_data: {...}, answer_time_ms}` |

Server → client: `sync_state` (to the joining sid; for a **player** in LOBBY/IN_PROGRESS it
includes `imageIds`, the game's distinct map-pin images in question order, for preloading;
stale in LOBBY if questions are edited), `game_images` `{imageIds}` (T7: room, emitted in
`host_advance`'s start branch right after `start_game` and **before** the first
`new_question`; final, since edits are locked once IN_PROGRESS), `new_question` (room),
`question_results`
(host: distribution; each player: own points/score/rank), `game_over` (host: anonymous scores +
per-question summary; each player: own summary), `player_joined` / `player_left` /
`answer_status` / `answer_phase_ended` (host room), `question_locked` / `question_unlocked` /
`host_disconnected` / `game_abandoned` (room), `answer_received` and `error` (sid).

`error` is `{message, code?}`. Only the three late-answer rejections in `submit_answer` carry a
`code`, and clients treat those as non-fatal (an honest answer just missed the window):
| message | `code` |
|---|---|
| "No active question" | `NO_ACTIVE_QUESTION` |
| "Question is locked" | `QUESTION_LOCKED` |
| "Question ID does not match the active question" | `QUESTION_MISMATCH` |
Every other error has no code and ends the player's game view.

### Phase state machine (`room:{code}` in Redis: `question_phase`)
`None` (lobby) → `host_advance` → `start_game` + first `new_question` → `QUESTION`
→ `host_advance` → `question_results` → `RESULTS` → `host_advance` → next `QUESTION`, or
`complete_game` + `game_over` → `COMPLETED`.
Only the host advances; the timer never advances the phase, it just locks the question.

### Who may do what
- **Connect:** any valid access/temp token (including GUEST). Rate-limited to 10 connections
  per IP per 10 s in production.
- **Join as HOST:** `user.id == session.host_user_id` **or** global `ADMIN`. There is **no
  course `HOST` role check here**. Course access was checked once, at room creation over HTTP.
- **Join as PLAYER:** session status LOBBY/IN_PROGRESS, then
  `game_service.authorise_player` (roster/course PLAYER/HOST; GUEST and ADMIN always allowed;
  see `services/CLAUDE.md`).
- **Host-only events** check `_sid_ctx[sid]["role"] == "HOST"`, set at join. **Player-only**
  `submit_answer` checks `role == "PLAYER"`.

### Answer privacy
`new_question` never includes `answer_data` (it does include `gradingType`, and `editDistance`
for fill-in-the-blank). **Invariant: nothing secret may ever go in a question's `config`**,
because `config` is sent to every phone (map_pin's `imageId` + dimensions live there; its
target lives in `answer_data`). Image IDs are therefore public too, which is fine. Correct answers only go out as `_answer_reveal` in
`question_results` / `game_over`. Players never receive other players' names or scores, only
their own points and rank. The host receives answer distributions and an anonymous score list.

## Gotchas
- **`rejoin_room` makes any ADMIN a host.** `is_host = user.id == host_user_id or role ==
  "ADMIN"`. An admin who joined as a **player** and reconnects is re-registered as HOST (joins
  the host room, can advance the game, and stops being a player).
- **Commit before you emit.** `_db()` only commits when its block exits, so a handler that
  emits inside the block announces writes that other handlers can't see yet.
  `on_submit_answer` therefore calls `await db.commit()` right after `record_answer`, before
  `answer_received` / `answer_status`. Without it, a host advancing on the last
  `answer_status` read MySQL too early (results reported 0–3 of 4 answers, and players'
  `yourPoints` / rank missed theirs). `tests/integration/test_answer_commit.py` guards it.
  Same class of bug as `docs/commit-race.md`.
- **Double-scoring race.** `submit_answer` checks `has_answered`, then `record_answer` writes
  the DB row and only afterwards adds to the Redis answered set. Two concurrent submits from the
  same user (double tap, two tabs) can both pass the check, and the DB has no unique constraint
  to stop it.
- **Answer payloads are only validated for `multi_select` and `map_pin`.** map_pin answers
  must be exactly `{x, y}` with finite numbers in [0, 1] (`game_service.map_pin_click`; the
  explicit finiteness check matters because Python's `json` accepts a literal `NaN`).
  For other types, a non-int `selectedIndex` makes
  `calculate_score` raise inside `on_submit_answer` (no try/except there), so the player gets no
  `answer_received`. A string `"false"` for `selectedValue` scores as `true`. `answer_time_ms`
  is client-supplied and unchecked.
- **Server-side timing is loose.** Submissions are accepted until the question is locked, which
  happens 0.5 s after the timer task fires. Late joiners get
  `timeLimitSeconds = max(5, remaining)`, so their client timer can outlast the server's.
- **Per-process state breaks with more than one instance.** `_sid_ctx`, `_timer_tasks`, and
  `_abandon_tasks` are in-memory dicts. The production Redis manager only fans out emits, so if
  a host reconnects to a different instance, the old instance's abandon task still fires and
  abandons the game. Lock/advance on another instance can't cancel the running timer. Treat
  this as single-instance (or sticky sessions) unless that's fixed.
- **Multiple host sockets:** disconnecting any one host socket (e.g. closing a second tab)
  auto-locks the question and starts the 5-min abandon countdown, even while another host
  socket is still connected.
- Host disconnect only triggers lock/abandon when status is `IN_PROGRESS`. An abandoned
  **lobby** just lingers until the 90-min Redis TTL.
- **`rejoin_room` for a player never re-sends the question.** Its `sync_state.currentQuestion`
  is the raw Redis record (`question_id`, `started_at`, `time_limit_seconds`, numbers), not a
  question payload with prompt/options. Only `join_room` pushes a late-join `new_question`.
  `rejoin_room` also doesn't check session status before re-adding a player.
- **`Game.max_players` is never enforced** anywhere; joins are unlimited.
- The rate-limit IP comes from `X-Forwarded-For`'s first value, which clients can spoof unless
  the proxy overwrites it.
- Players with no score rows get rank `len(players)` (tied last), because the leaderboard comes
  from MySQL `SessionScore` rows while the player list comes from Redis.
- `_answer_reveal` here is one of four copies (see `services/CLAUDE.md`). For `multi_select` it
  sends the full `answer_points` list to players.
- `socket_app` (line 61) is unused; `main.py` builds its own `ASGIApp` wrapper.
- `host_advance` and `host_lock_question` swallow all exceptions (logged as
  `*_unhandled_error`), so the host UI gets no `error` event on unexpected failures.
