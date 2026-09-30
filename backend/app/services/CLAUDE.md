# backend/app/services/

## Purpose
Business logic behind the routers and the WebSocket gateway: auth/token handling, room and
session lifecycle, access checks for hosting and joining, answer scoring, Redis live-game
state, roster import, and post-game exports/reports. Functions take an `AsyncSession` (and
`Redis` where needed) and generally `flush()` rather than commit — the caller owns the
transaction, with the exceptions noted below.

## Contents
- `__init__.py` — Empty.
- `auth_service.py` — bcrypt password hashing; RS256 JWT creation/decoding. Token lifetimes:
  `access` 2 h (carries a `role` claim), `refresh` 7 d, `temp` 15 min. Keys come from
  base64-encoded `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY`, else ephemeral keys generated in memory.
  User helpers: `get_user_by_username` (lowercases), `get_user_by_id`,
  `get_or_create_user_by_netid` (OAuth2 + dev login; creates `USER`), `create_guest_user`
  (creates/reuses a `GUEST` by email; `ValueError` if the email belongs to a non-guest),
  `authenticate_local`.
- `bootstrap.py` — `bootstrap_admin()`, run from `main.py`'s lifespan: if `ADMIN_USERNAME` and
  `ADMIN_PASSWORD` are set and no `ADMIN` exists, creates one. Retries every 5 s until
  migrations have created the schema (blocks startup until then).
- `game_service.py` — Core game logic:
  - `generate_room_code` — 6 chars from `23456789ABCDEFGHJKMNPQRSTUVWXYZ`, 5 attempts.
  - **Access checks:** `assert_host_can_use_course`, `assert_host_can_use_game`,
    `authorise_player` (see below).
  - Lifecycle: `create_room` (checks access, enforces max 50 concurrent LOBBY/IN_PROGRESS rooms,
    writes `GameSession` + Redis room state), `get_session_by_code`, `start_game`
    (LOBBY → IN_PROGRESS, returns ordered questions), `complete_game`, `abandon_game`.
  - Scoring: `calculate_score` (pure) and `record_answer` (score → insert `SessionScore` →
    update Redis score, answered set, and answer distribution).
  - Summaries: `get_leaderboard` (MySQL sum per user_id), `get_player_question_summary`,
    `get_host_question_summary` (both include an `answerReveal` per question).
- `state_service.py` — Redis live state. Keys: `room:{code}` (JSON, 90-min TTL),
  `session:{id}:players` (set), `session:{id}:player:{uid}` (JSON incl. score, `is_connected`),
  `session:{id}:question` (current question + `started_at`), `session:{id}:answered:{qid}`
  (set), `session:{id}:dist:{qid}` (hash answer_key → count). Plus `restore_from_mysql`.
- `roster_service.py` — `process_roster_csv` (Canvas gradebook export: needs `Student` and
  `SIS Login ID` columns, skips the "Points Possible" row, netid = part before `@`, lowercased;
  stores only the **given name** as `full_name`) and `process_roster_rows` (pre-mapped rows from
  the admin column-mapping wizard). Both upsert by `(course_id, netid)`, cap at 1000 rows, and
  **deactivate every roster entry not in the upload**.
- `report_service.py` — `build_session_report` → standalone dark-theme HTML report with
  aggregate stats only (per-question distribution bar chart / word cloud, % correct, score
  histogram). No player names.
- `export_service.py` — `build_session_csv` (Player, Q1..Qn, Total) and `build_canvas_csv`
  (Canvas gradebook import format, SIS Login ID = netid [+ `@sis_domain`], optional
  per-question columns, `roster_only` flag).

## How it fits in
Called by `routers/` (admin, game, auth) and heavily by `websocket/gateway.py`, which drives
the in-game loop (start → question → answers → results → game over). MySQL (`models/`) is
the durable record; Redis (`state_service`) is the fast live-game view. Exceptions come from
`common/exceptions.py`.

### Access rules enforced here (the real authorization logic)
`common/` only checks the global role; the course/game checks live in `game_service.py`:

| check | ADMIN | USER | GUEST |
|---|---|---|---|
| `assert_host_can_use_course` | any existing course | needs `UserCourseAccess` role `HOST` for that course | effectively denied (no HOST row) |
| `assert_host_can_use_game` | any existing game | needs a `UserGameAccess` row | effectively denied |
| `authorise_player` (join as player) | **any room** | active `CourseRoster` row matching `user.netid` **or** `UserCourseAccess` `PLAYER` **or** `HOST` for the session's course | **any room — no course check** |

- Hosting requires both checks independently: HOST in the course **and** a grant for the game.
  Since games have no course (see `models/CLAUDE.md`), any game you can use can be run in any
  course you host.
- `authorise_player` returns the display name used in-game: roster `full_name` (given name) for
  roster matches, else `display_name`/`username`.
- `report_service` and `export_service` do **no** access checks — the calling router must.

### Scoring rules (`calculate_score`)
Empty answer → 0. `COMPLETENESS` → full `points_value` for any answer. `ACCURACY`:
- `multiple_choice`: `answer_points[selectedIndex]`; correct iff points **==** `points_value`.
- `true_false`: `answer_points["true"/"false"]` by truthiness of `selectedValue`; correct iff ==.
- `fill_in_the_blank`: lowercase + collapse whitespace, Levenshtein ≤ `editDistance` against each
  accepted answer, best match's `answerPoints` (falls back to `points_value`); correct iff ≥.
- `multi_select`: sum of `answer_points` over `selectedIndices`, clamped at 0; correct iff ≥
  `points_value` and `points_value > 0`.
Player answer keys: `selectedIndex`, `selectedValue`, `text`, `selectedIndices`.

## Gotchas
- **Guests can join any room.** `authorise_player` returns immediately for `GUEST`, with no
  roster or course check. Admins likewise.
- **Room code uniqueness is checked only in Redis.** `generate_room_code` checks
  `room:{code}`, but `game_sessions.room_code` is UNIQUE in MySQL. Once an old session's Redis
  key expires, its code can be regenerated, and the insert in `create_room` fails with an
  integrity error.
- **Redis `session:*` keys have no TTL.** Only `room:{code}` expires (90 min, refreshed on
  activity). `complete_game` does not call `delete_room_state`, so players, answered sets, and
  distributions for completed games linger indefinitely. Only `abandon_game` (and one path in
  `routers/game.py`) cleans up.
- **`restore_from_mysql` is dead code.** No caller exists, so the "MySQL fallback" in the module
  docstring is not actually wired up.
- **`record_answer` does not dedupe.** It always inserts a `SessionScore`; callers must check
  `state.has_answered` first (the DB has no unique constraint either — see `models/CLAUDE.md`).
  If duplicates slip in, `get_leaderboard` sums both while the CSV exports keep only the last.
- `calculate_score` trusts answer types: a non-int `selectedIndex` raises `TypeError` in the
  range check, and a string `selectedValue` such as `"false"` is truthy and scores as `true`.
- MC/TF "correct" uses exact float equality with `points_value`; partial-credit options are
  never marked correct.
- **Roster uploads are full replacements.** Anyone absent is deactivated. When the 1000-row cap
  is hit, the loop `break`s but deactivation still runs, so students past row 1000 get
  deactivated.
- Roster matching compares `user.netid` (as received from the OAuth2 header, not lowercased)
  with lowercased roster netids. This relies on MySQL's case-insensitive default collation.
- `start_game` and `complete_game` **commit**; `abandon_game` only flushes. Keep this in mind
  when composing them with other writes.
- `create_room` counts rooms with `redis.keys("room:*")` plus a GET per key: O(N), blocking
  `KEYS`, and not atomic (two concurrent creates can both pass the 50-room limit).
  `delete_room_state` also uses `KEYS`.
- **Answer-reveal logic is duplicated** in 4 places: `get_player_question_summary`,
  `get_host_question_summary`, `report_service._answer_reveal`, and `websocket/gateway.py`
  `_answer_reveal`. `report_service` lacks `multi_select` entirely (no badge, chart, or reveal).
- Distribution normalization differs: live Redis dist (`record_answer`) collapses internal
  whitespace for fill-in answers, while the host summary and report only `strip()`.
- Reports and exports read the game's **current** questions, not a snapshot. Questions added
  after a session show as unanswered columns.
- `report_service` and `export_service` raise `ValueError` (not `NotFoundError`) for an unknown
  session; `report_service` embeds `q.prompt` as raw HTML, relying on the `bleach` sanitization
  done on write in `routers/admin.py`.
- Canvas export: `roster_only=True` skips players **without a netid**. It does not check that
  the player is on the roster. The `Student` column uses the roster's given-name-only
  `full_name`.
- Without JWT key env vars, keys are regenerated on every restart (and per worker process), so
  all tokens are invalidated and multi-worker deployments can't verify each other's tokens.
