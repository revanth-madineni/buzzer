# T4 — Host/Admin UI Restructure and Course-Specific Games

Status: agreed design, revised after one goldfish test (see Revision history). Branch for this
document: `docs/design-t4-ui-restructure`. Task text: [instructions.md](../../instructions.md) §T4
(and §T5 for tests). Architecture context: the `CLAUDE.md` hierarchy under `backend/` and
`frontend/`; start at [backend/app/CLAUDE.md](../../backend/app/CLAUDE.md) and
[frontend/CLAUDE.md](../../frontend/CLAUDE.md).

## Priority tags

Every item in this document carries one tag:

- **[T4]** — required to meet the T4 task text, or required for a [T4] item to be safe/correct.
  Do these first.
- **[Extra]** — hardening or polish agreed in design. Can be cut if time runs short; each one
  says what is lost if it is cut.
- **[T5]** — integration tests for the above.

## Deliverables and branches

Branch names follow the repo's existing `<type>/<kebab-name>` convention (`docs/…`, `chore/…`,
`fix/…`).

| Deliverable | Branch | Contents |
|---|---|---|
| This design doc (T3) | `docs/design-t4-ui-restructure` | This file only. Merged **before** any implementation branch is opened. |
| T4 (backend + frontend) and its T5 tests | `feat/t4-host-admin` | §4.1–§4.15: backend (§4.1–§4.10), migration report script, frontend (§4.11–§4.12), tests (§4.14), and all context-doc updates (§4.15). One branch, one MR. |
| Unrelated bug fix | `fix/admin-rejoin-becomes-host` | See "Separate deliverable" at the end. Not part of T4. |

---

## 1. Problem

Today every management capability (games, questions, rosters, reports) lives behind
`require_admin` in `backend/app/routers/admin.py`, and the host app can only create and run rooms.
Games have no course: `Game` has no `course_id`, and a game meets a course only on `GameSession`
when a room is created (`backend/app/models/CLAUDE.md`). Which host may run which game is decided by
per-user `UserGameAccess` grants, independent of course.

T4 requires:

1. Hosts can download an HTML summary and a per-player score CSV for a completed session.
2. Hosts can view and update the roster of any course where they hold `HOST` (add/deactivate via
   CSV upload).
3. Hosts can create games and add/edit/delete/reorder questions and their scoring.
4. Games are attached to a course at creation; a game is accessible only to hosts and players of
   that course.
5. The admin UI leads with admin tasks (users, courses, granting course/game access); host and
   player actions remain available to admins but are secondary.
6. Everything integrates with the existing role/permission system — no bypassed checks.

## 2. Technical plan (summary)

- **Data model [T4]:** add nullable `games.course_id` (FK → `courses.id`), `games.restricted`
  (bool, default false) and `courses.allow_guests` (bool, default true). Migration `004` backfills
  `course_id` from session history and sets `restricted = true` on **every existing game**, so
  nobody silently gains access; admins un-restrict deliberately.
- **Host access rule [T4]:** a non-admin may use game G iff they hold course `HOST` on
  `G.course_id`, **and**, if `G.restricted`, they also hold a `UserGameAccess` grant on G. Course
  HOST is the primary rule; grants are an opt-in, admin-managed narrowing. Admins bypass all of it.
- **Player access rule [T4]:** unchanged code, newly guaranteed meaning — see §4.4.
- **One place for access logic [T4]:** `services/access_service.py` holds the predicates; FastAPI
  dependencies in `common/dependencies.py` **load the resource and check its own course** — never a
  course ID taken from the URL.
- **New host router [T4]:** `/api/host/...` with flat resource URLs. `/api/admin/*` is **not**
  loosened.
- **Shared services [T4]:** question CRUD (validation, `bleach` sanitization, ordering) moves into
  `services/question_service.py`; roster upload gains a `mode`. Admin and host routers both call
  these.
- **Course assignment [T4]:** the admin **API** may create a game without a course (keeps the
  existing integration fixture unchanged); the admin **UI** always requires one. A courseless game
  is attached to the course of its first room, under a row lock. Admins can assign or move a game
  to a course at any time; moving drops grants that would no longer work, after showing them.
- **Frontend [T4]:** the host app gets a management area (Games, Questions, Roster, Sessions) per
  course; the admin sidebar becomes Users / Courses / Access, then a "Host tools" section.

## 3. Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Retire `UserGameAccess` entirely** (course HOST is the only rule) | Before T4, every game a non-admin host could run needed a grant. Retiring grants would silently give every HOST in a course every game assigned to that course — including answer keys (`QuestionResponse.answer_data`) and edit/delete rights — and remove the admin's "granting game access" task named in T4. No existing test depends on grants either way (all tests run as admin), so this was decided on behavior, not tests. |
| **Keep grants as a mandatory second check** (HOST **and** grant always) | Breaks T4's core workflow: a host-created game would be invisible to co-hosts of the same course until an admin granted it. (Kept as the fallback in §5 if the TA requires it.) |
| **Grants as a way to share a game across courses** | Contradicts T4 ("only accessible to hosts and players of that course"). Cross-course reuse is done by copying a game (export/import). |
| **Nested URLs** `/host/courses/{cid}/games/{gid}/questions/{qid}` checked by `require_course_host(cid)` | Proves the caller hosts *cid*, not that game *gid* belongs to *cid*. Every nested handler must remember an extra ownership check; one miss is an IDOR. Flat URLs + resolve-then-check make it impossible to name the wrong course. |
| **Loosen `/admin/*` to accept course hosts** | Weakens every admin endpoint at once; mixes two permission models in one router. |
| **Guests as an undocumented global exception** | Guest tokens are not bound to a room (2 h access / 7 d refresh), so "guests allowed" would mean every course's live game is open to anyone with the code. A per-course switch makes it an admin decision. A per-session flag was finer-grained but more UI and schema for little gain. |
| **Backfill from each game's most recent session** | One mistaken or abandoned session would decide the game's course. Replaced by "most completed sessions". |
| **Restrict only games that already have grants** | A game admins ran but never granted would be backfilled unrestricted, and every HOST of that course would silently gain it. Replaced by restricting every existing game. |
| **Permanent admin exception for courseless games** | Leaves games unattached forever, visibly failing "attached at creation". Replaced by attach-on-first-room plus admin assign/move. |
| **Make `course_id` required on the admin API** | Would require editing the integration fixture (`tests/integration/conftest.py` `game_setup`). Avoidable. |
| **Recheck course HOST on every host socket action** | A DB query per click, and a mid-question revocation would strand players with no host. Rechecking at (re)join is enough. |
| **"Host tools" in the admin app as a link to the host app** | Works behind nginx (shared origin + token) but not in Vite dev. Kept the existing admin pages instead. |
| **Client-side roster parsing for hosts** | Duplicates the admin's column-mapping wizard and lets preview and commit disagree. |
| **Block question edits while any LOBBY/IN_PROGRESS session exists** | LOBBY rows are never cleaned up in MySQL, so this would lock some games permanently. LOBBY edits are harmless (questions are read at start and as each is shown). |
| **Session exports governed by the game's current course** | A game moved or backfilled to another course would take its old sessions' results with it. Sessions stay with the course they were played in (`session.course_id`). |

---

## 4. Detailed implementation

### 4.0 Error and response conventions — [T4]

All new REST errors use the existing `BuzzerError` envelope (`backend/app/common/exceptions.py`):
HTTP status + body `{"error": "<CODE>", "message": "<text>"}`. New codes are raised as
`BuzzerError("<CODE>", message, status)`; generic ones use the existing subclasses. Request-body
validation keeps FastAPI's `422 {"error": "VALIDATION_ERROR", "detail": [...]}`.

**Service-level validation rule:** when a service validates with Pydantic itself (question PUT
merge, §4.5), it must catch `pydantic.ValidationError` and re-raise
`fastapi.exceptions.RequestValidationError(exc.errors())`, so the client gets the standard 422
`VALIDATION_ERROR` body instead of the catch-all 500.

| Code | Status | Raised when | Message (exact text) |
|---|---|---|---|
| `NOT_FOUND` | 404 | Resource missing; question not in the URL's game; roster entry not in the URL's course; **non-admin** asking for a game whose `course_id` is NULL; course in `POST /game/rooms` or game create does not exist | `"<Thing> <id> not found"` (existing style) |
| `FORBIDDEN` | 403 | GUEST on a `require_user` endpoint (existing); caller lacks HOST on the relevant course | `"You do not have HOST access to this course"` |
| `GAME_RESTRICTED` | 403 | Non-admin HOST without a grant touches a restricted game, or a session whose game is restricted | `"This game is restricted"` |
| `COURSE_MISMATCH` | 422 | `POST /game/rooms` with a `course_id` different from the game's | `"This game belongs to course <name> (<semester>)"` |
| `GAME_LIVE` | 409 | Write blocked because the game is live (§4.5) | `"This game is being played right now"` |
| `GAME_HAS_RESULTS` | 409 | Host deletes a game that has any COMPLETED session, or any session (of any status) with at least one `SessionScore` row | `"Games with recorded results can only be deleted by an admin"` |
| `QUESTION_HAS_ANSWERS` | 409 | Delete a question referenced by any `SessionScore` [Extra] | `"Question has recorded answers and cannot be deleted"` |
| `INVALID_ORDER` | 422 | Reorder IDs are not exactly the game's question-ID set [Extra] | `"Order must list every question in this game exactly once"` |
| `SESSION_NOT_COMPLETED` | 409 | Host export/report for a session whose status is not COMPLETED | `"Results are available once the session is completed"` |
| `ROSTER_TOO_LARGE` | 422 | Roster upload with more than 1000 data rows [Extra] | `"Roster uploads are limited to 1000 rows"` |
| `ROSTER_EMPTY` | 422 | `mode=replace` upload with zero valid rows (would deactivate everyone) | `"No valid roster rows found — nothing was changed"` |
| `ROSTER_PREVIEW_REQUIRED` | 422 | Host commit with `mode=replace` and no `version` [Extra] | `"Preview the upload before replacing the roster"` |
| `ROSTER_CHANGED` | 409 | Host commit with a `version` (any mode) that no longer matches [Extra] | `"The roster changed since your preview — preview again"` |
| `INVALID_COURSE_ASSIGNMENT` | 422 | Move/assign with `course_id: null` | `"A game cannot be removed from its course"` |

Socket errors (event `error`, payload `{"message": str}`, emitted by `gateway._emit_error`):

| When | Message |
|---|---|
| Player not on roster / no PLAYER or HOST access (existing, unchanged) | `"You are not enrolled in the course roster for this game"` |
| GUEST joins a course with `allow_guests = false` [Extra] | `"This course does not allow guest players"` |
| Host (re)join by a non-owner, or by an owner who lost course HOST (existing text, new condition [Extra]) | `"Not authorised as host for this session"` |

422 vs 409 rule used throughout: **422** = the request itself is incomplete or invalid (fixing the
request fixes it, e.g. a missing preview `version`); **409** = the request is well-formed but
conflicts with current server state (e.g. a stale `version`, a live game). Invalid query values
(e.g. an unknown `?status=`) are typed as `Literal` query parameters, so FastAPI returns the
standard 422 `VALIDATION_ERROR`.

Error-precedence rule for the host dependencies: authentication (401) → GUEST (403 `FORBIDDEN`)
→ resource exists (404) → course HOST (403 `FORBIDDEN`) → restricted (403 `GAME_RESTRICTED`) →
state checks (409/422). Tests assert on `error` codes, not just status.

**Response shapes** (all new or changed fields; unchanged fields omitted):

- `GameResponse` (admin and host): existing fields + `course_id: int | null`, `restricted: bool`.
- `HostGameListItem`: `GameResponse` + `question_count: int` = number of `Question` rows with that
  `game_id`, computed with one grouped `COUNT` query for the whole list (no per-game query).
- `MyGameItem` (`GET /game/my-games`): existing fields + `course_id: int` (never null for
  non-admins; admins may see null), `restricted: bool`.
- `MyCourseItem` (`GET /game/my-courses`, unchanged): `id, name, semester, role`. ADMIN gets
  **every** course (`role` always `"HOST"`), ordered semester desc then name; USER gets courses
  where they hold HOST. The host app's course picker uses this list as-is.
- `CourseResponse`: existing fields + `allow_guests: bool`.
- `SessionListItem` (host sessions list): **same fields as the existing `AdminSessionItem`** —
  `session_id, room_code, status, game_id, game_title, course_id, course_name, course_semester,
  host_display_name, created_at, completed_at, player_count`. Reuse that schema (rename or alias
  it) rather than defining a second one. Sources, matching admin `list_sessions`
  (`routers/admin.py`): `created_at` / `completed_at` are the `GameSession` columns (there is no
  `started_at`); `player_count` = `COUNT(DISTINCT SessionScore.user_id)` for the session, so a
  player who joined but never answered is not counted; `host_display_name` = host's
  `display_name or username or netid`, null if no host. The host endpoint computes counts with one
  grouped query, not per session.
- `RosterUploadResult` (existing): `imported, updated, deactivated: int; errors: list[str]`.
  Host uploads also return this. In `add_update` mode `deactivated` is always 0.
- `RosterPreviewResponse` [Extra]: `added: list[RosterDiffRow]`, `updated: list[RosterDiffRow]`,
  `reactivated: list[RosterDiffRow]`, `deactivated: list[RosterDiffRow]` (empty unless
  `mode=replace`), `errors: list[str]` (same strings as `RosterUploadResult.errors`),
  `version: str`. `RosterDiffRow = {netid: str, full_name: str, email: str,
  changed_fields: list[str]}` (`changed_fields` empty except in `updated`).
- `CourseAccessEntry` (`GET /admin/courses/{id}/access`): `user_id, username, netid,
  display_name, role ("HOST" | "PLAYER")`.
- `GameAccessEntry` (`GET /admin/games/{id}/access`): `user_id, username, netid, display_name,
  has_course_host: bool`.
- `GameMoveResult` (`POST /admin/games/{id}/move`): `applied: bool`, `game: GameResponse`,
  `dropped_grants: list[GameAccessEntry]`.

### 4.1 Migration `004_course_specific_games.py` — [T4]

New file `backend/app/migrations/versions/004_course_specific_games.py` with `revision = "004"`,
`down_revision = "003"` (the IDs are plain strings; see `003_float_points.py`).

`upgrade()` — name every constraint explicitly (MySQL needs the names to drop them in
`downgrade()`), and use the string server defaults `"1"` / `"0"` for booleans, as
`001_initial_schema.py` does for `is_active` / `is_correct`:

1. `games.course_id` — `Integer`, **nullable**. FK `fk_games_course_id_courses` → `courses.id`
   (no `ondelete`; there is no course-delete endpoint). Index `ix_games_course_id`.
2. `games.restricted` — `Boolean`, `NOT NULL`, `server_default "0"`.
3. `courses.allow_guests` — `Boolean`, `NOT NULL`, `server_default "1"`. Always added, even if
   the guest check (§4.6) or its UI is cut, so the schema is stable.

Session status values are the uppercase strings of the `session_status` enum (`'LOBBY'`,
`'IN_PROGRESS'`, `'COMPLETED'`, `'ABANDONED'`); compare against them exactly in the backfill SQL.
4. Backfill `games.course_id`:

   ```
   for each game g:
       completed = sessions of g with status = 'COMPLETED'
       if completed is not empty:
           per course c: n(c) = count, last(c) = max(created_at), maxid(c) = max(session id)
           g.course_id = the c maximising (n, last, maxid)  # most completed, then most recent, then id
       else:                                                # no COMPLETED sessions: none at all, or only
                                                            # LOBBY / ABANDONED / IN_PROGRESS ones
           holders = users with a UserGameAccess row on g
           host_courses = union over holders of courses where they hold UserCourseAccess HOST
           g.course_id = the single course if len(host_courses) == 1 else NULL
   ```

5. `UPDATE games SET restricted = true` — **every existing game**, with or without grants. This
   preserves today's behavior: a non-admin can use an existing game only if they hold a grant on it
   **and** HOST on its course. Cost: course hosts see no existing game they weren't granted until an
   admin un-restricts it (Access page, §4.12). Games created after the migration default to
   `restricted = false`.

Write the backfill as `op.execute` / Core SQL inside the migration — never import ORM models.

`downgrade()`: drop `fk_games_course_id_courses`, then `ix_games_course_id`, then the three
columns. The backfill is not reversible; that is acceptable.

**Migration report — [Extra]** (cut → admins find affected games/users by hand).
New read-only script `scripts/t4_migration_report.py`, rerunnable, run inside the backend
container (`docker compose exec backend python scripts/t4_migration_report.py` — mount/copy as the
other `scripts/` are run). Prints Markdown tables:

- **Restricted games:** id, title, course, grant holders. Flag games with **no** grant holders
  ("admin-only until un-restricted or granted").
- **Grant holders who lost access:** every `(user, game)` grant where the user lacks HOST on
  `game.course_id` (including games whose `course_id` is NULL).
- **Unassigned games:** `course_id IS NULL`, with the reason (no sessions and no grants / grant
  holders host 0 courses / grant holders host ≥2 courses).

### 4.2 Models and schemas — [T4]

`backend/app/models/game.py`: `Game.course_id: Mapped[int | None]`, `Game.restricted:
Mapped[bool]`, `Game.course` relationship. `backend/app/models/course.py`:
`Course.allow_guests: Mapped[bool]`, `Course.games` relationship (no cascade).
`UserGameAccess.game_id` already has `ondelete="CASCADE"` and `Game.user_access` already has
`cascade="all, delete-orphan"` — deleting a game removes its grants; keep that.

`backend/app/schemas/admin.py`:
- `GameCreate`: add `course_id: int | None = None`.
- `GameUpdate`: add `restricted: bool | None`. **Not** `course_id` — moving goes through
  `POST /admin/games/{id}/move` (§4.7) so the grant-drop warning cannot be skipped.
- `GameResponse`, `CourseResponse`: fields per §4.0. `CourseCreate` / `CourseUpdate`: add
  `allow_guests: bool` (create default true; update optional).
- New: `GameMoveRequest {course_id: int, confirm: bool = false}`, `GameMoveResult`,
  `CourseAccessEntry`, `GameAccessEntry` (§4.0).

`backend/app/schemas/game.py`: `MyGameItem` per §4.0.

New `backend/app/schemas/host.py`:
- `HostGameCreate` (title, description, max_players — no `course_id`; it comes from the URL).
- `HostGameUpdate` (title, description, max_players only — hosts cannot move or restrict games).
- `HostGameListItem`, `RosterPreviewResponse`, `RosterDiffRow` (§4.0).
- `RosterUploadMode = Literal["add_update", "replace"]`.
- Question shapes are reused from `schemas/admin.py` (`QuestionCreate`, `QuestionUpdate`,
  `QuestionResponse`, `QuestionReorder`). Hosts need `answer_data` to edit scoring.

### 4.3 Access layer — [T4]

New `backend/app/services/access_service.py` (async functions taking `db`, `user`):

```
has_course_host(db, user, course_id) -> bool
    ADMIN -> True
    else  -> exists UserCourseAccess(user_id, course_id, role='HOST')

has_game_grant(db, user, game_id) -> bool
    exists UserGameAccess(user_id, game_id)

can_use_game(db, user, game) -> bool             # authoring + running a game
    ADMIN -> True
    game.course_id is NULL -> False
    not has_course_host(user, game.course_id) -> False
    game.restricted and not has_game_grant(user, game.id) -> False
    True

can_view_session_results(db, user, session, game) -> bool
    ADMIN -> True
    not has_course_host(user, session.course_id) -> False     # the SESSION's course
    game.restricted and not has_game_grant(user, game.id) -> False
    True
```

`can_view_session_results` deliberately checks HOST on **`session.course_id`**, not
`game.course_id`: a session stays with the course it was played in even if its game was later
moved. It applies the restricted/grant check because the HTML report contains the game's prompts
and correct answers, so a host who cannot open a restricted game must not read it through a
report.

`backend/app/common/dependencies.py` gains dependencies built on these. Each runs after
`require_user`, **loads the resource first**, and follows the precedence in §4.0:

```
require_course_host(course_id)      -> Course
    course = get(Course) or 404
    has_course_host(user, course.id) or 403 FORBIDDEN

require_game_host(game_id)          -> Game
    game = get(Game) or 404
    ADMIN -> return game
    game.course_id is NULL -> 404
    has_course_host(user, game.course_id) or 403 FORBIDDEN
    (not game.restricted or has_game_grant) or 403 GAME_RESTRICTED

require_question_host(game_id, question_id) -> Question
    game = require_game_host(game_id)
    q = get(Question) or 404; q.game_id == game.id or 404

require_session_host(session_id)    -> GameSession
    s = get(GameSession) or 404; game = get(Game, s.game_id)
    ADMIN -> return s
    has_course_host(user, s.course_id) or 403 FORBIDDEN
    (not game.restricted or has_game_grant) or 403 GAME_RESTRICTED
```

This adds an import edge `common/` → `services/access_service`; record it in
`backend/app/common/CLAUDE.md`. `game_service.assert_host_can_use_course` /
`assert_host_can_use_game` become thin wrappers over `access_service`, so there is one definition
of "is HOST".

### 4.4 Room creation, game visibility, and player access — [T4]

`game_service.create_room(db, redis, host, game_id, course_id)` — one transaction, nothing
commits until the handler returns (`database.get_db`):

```
course = get(Course, course_id) or 404 NOT_FOUND           # checked BEFORE any attach
game = SELECT * FROM games WHERE id = :game_id FOR UPDATE   # row lock until commit/rollback
       or 404 NOT_FOUND

if host is ADMIN:
    if game.course_id is NULL:
        game.course_id = course.id
        log "game_attached_on_first_room"(game_id, course_id, user_id)
else:
    if game.course_id is NULL: 404 NOT_FOUND
    if not has_course_host(host, game.course_id): 403 FORBIDDEN
    if game.restricted and not has_game_grant(host, game.id): 403 GAME_RESTRICTED

if course.id != game.course_id: 422 COURSE_MISMATCH
... existing room-limit check, room code, GameSession insert, Redis room state ...
```

There is no separate "HOST on `course_id`" check after the match: for a non-admin, HOST on
`game.course_id` was already required, and the match makes it the same course. For an admin, no
HOST check applies. Order of failures for a non-admin: 404 (course) → 404 (game / courseless) →
403 `FORBIDDEN` → 403 `GAME_RESTRICTED` → 422 `COURSE_MISMATCH` → existing room-limit 409.

- The `FOR UPDATE` lock (`select(Game).where(...).with_for_update()`) serializes concurrent room
  creations for the same game, so two admins cannot attach it to different courses. Holding it
  through the room-limit scan is acceptable (room creation is rare).
- Because the course is verified first, a nonexistent course returns 404 and the game stays
  courseless. Any later failure (room limit, room-code collision) rolls back the attach with the
  session insert.
- `RoomCreateRequest` keeps `course_id`, so existing clients and the integration fixture work
  unchanged.

`GET /game/my-games` (`routers/game.py`): ADMIN → all games. USER → games with `course_id` in the
user's HOST courses, excluding restricted games without a grant. `GET /game/my-courses`:
unchanged (ADMIN → every course; see `MyCourseItem` in §4.0).

**Player access (no code change; stated so it is not lost).** A player's socket `join_room` /
`rejoin_room` calls `game_service.authorise_player(db, user, session)`, which admits:

- ADMIN — any room;
- GUEST — any room, unless the course has `allow_guests = false` (§4.6);
- USER — only with an **active** `CourseRoster` row matching `user.netid` **for
  `session.course_id`**, or `UserCourseAccess` PLAYER/HOST on `session.course_id`. Otherwise the
  socket gets `error` `"You are not enrolled in the course roster for this game"`.

With the `COURSE_MISMATCH` rule, every session created after this change has `session.course_id ==
game.course_id`, so "players of that course" means players of the game's course. Sessions created
before the migration keep the course they were created in. Do not change `authorise_player`
except for §4.6.

### 4.5 Shared services — [T4] (guards tagged individually)

New `backend/app/services/question_service.py`, used by **both** `routers/admin.py` and
`routers/host.py`. Admin endpoints become thin wrappers; their responses and status codes must not
change for inputs that are valid today.

- `sanitize_prompt(html)` — **[T4]**. Move the `bleach.clean(...)` call (tags/attributes exactly as
  in `routers/admin.py`'s create, update and import paths) here. Every prompt write, admin and
  host, goes through it. Cutting it lets any course HOST store script that `report_service` embeds
  as raw HTML.
- `create_question(db, game, QuestionCreate)` — same `order_index` logic as today.
- `update_question(db, question, QuestionUpdate)` — structure validation **[Extra]** (cut → a PUT
  can save a question create would reject):

  ```
  patch = body.model_dump(exclude_unset=True)    # only fields the client actually sent
  merged = current question fields overlaid with patch
  QuestionCreate.model_validate(merged)          # on pydantic.ValidationError → RequestValidationError (§4.0)
  merged.prompt = sanitize_prompt(merged.prompt)
  apply merged to question
  ```

  `exclude_unset` (not "non-null fields") means an explicit `null` is applied: a client can clear
  `config` or `answer_data` (e.g. when switching to `COMPLETENESS`). An explicit `null` for a
  field `QuestionCreate` requires (`type`, `grading_type`, `prompt`, …) fails validation → 422.
  Without the [Extra] validation, keep today's behavior (non-null fields only).

- `delete_question(db, question)` — **[Extra]:** 409 `QUESTION_HAS_ANSWERS` if any `SessionScore`
  references it (today: FK error → 500).
- `reorder_questions(db, game, ids)` — **[Extra]:** 422 `INVALID_ORDER` unless `ids` is exactly the
  game's question-ID set. (Today invalid reorders return a generic 409 `CONFLICT`; this changes
  only invalid input.)
- `is_game_live(db, redis, game_id) -> bool` — **[Extra]** (cut → a host can change questions under
  a running game):

  ```
  for s in GameSession where game_id = :g and status = 'IN_PROGRESS':
      if redis EXISTS room:{s.room_code}: return True
  return False                      # an IN_PROGRESS row whose Redis key expired is stale, not live
  ```

  When live: host question create/update/delete/reorder, host game update/delete, admin question
  create/update/delete/reorder, and admin move (§4.7) return 409 `GAME_LIVE`. **Admin game
  deletion is exempt** (§4.7).

  **Start race.** Without coordination, an edit can pass `is_game_live` while the game is still in
  LOBBY, then `start_game` commits IN_PROGRESS and captures `question_ids`, then the edit commits;
  a reorder or delete landing in that window corrupts the running game. Fix: every guarded write
  first takes `SELECT … FROM games WHERE id = :g FOR UPDATE`, then calls `is_game_live`, then
  writes; and `game_service.start_game` takes the same game-row lock before reading questions and
  setting IN_PROGRESS. Whichever runs first wins: an edit that gets the lock first is included in
  the game; a start that gets it first makes the edit see a live game → 409. (`start_game` already
  commits immediately, so the lock is short.)

  Admin question endpoints need Redis for this check: add `redis = Depends(get_redis)` to them, as
  `routers/game.py` endpoints already do.

`backend/app/services/roster_service.py`:
- [T4] Add `mode: RosterUploadMode = "replace"` to `process_roster_csv` and `process_roster_rows`.
  `replace` = today's behavior (upsert + deactivate everyone not in the upload). `add_update` =
  upsert (including reactivating listed inactive entries), never deactivate. Admin callers keep
  `replace`.
- [Extra] More than 1000 data rows → 422 `ROSTER_TOO_LARGE`, nothing written (today: truncates,
  then deactivates everyone past row 1000).
- [T4] `mode=replace` with zero valid rows (every row errored, or only the "Points Possible" row)
  → 422 `ROSTER_EMPTY`, nothing written. Today such an upload would deactivate the whole roster.
- [Extra] `preview_roster_csv(db, course_id, file, mode) -> RosterPreviewResponse`: same parser,
  computes the diff without writing.
- [Extra] `roster_version(db, course_id) -> str` — **the one function** both preview and commit
  call:

  ```
  rows = course's roster entries ordered by netid
  payload = json.dumps([[r.netid, r.full_name, r.email, r.is_active] for r in rows],
                       separators=(",", ":"), ensure_ascii=False)
  return sha256(payload.encode("utf-8")).hexdigest()
  ```

  JSON avoids separator collisions (names can contain `|` or `,`).

**What the host upload accepts.** `process_roster_csv` is the existing parser behind admin's
`POST /admin/courses/{id}/roster`, and it already handles the Canvas gradebook export on its own:
it requires `Student` and `SIS Login ID` columns (case-insensitive), skips the "Points Possible"
row, strips `@domain` from the login and lowercases it, and keeps only the given name. If either
column is missing it writes nothing and returns `errors: ["Missing required columns: …"]`. Hosts
get **only** this format; the admin's column-mapping wizard (any CSV layout →
`POST .../roster/import`) stays admin-only. State this on the host RosterPage ("Upload the
gradebook CSV exported from Canvas").

**Roster entries vs `UserCourseAccess` PLAYER.** They are independent ways to let someone join as
a player (§4.4): a `CourseRoster` row is keyed by **netid** and matches NetID-SSO users; a
`UserCourseAccess` PLAYER row is keyed by **user id** and is how local accounts (no netid) get in.
Roster uploads never create, change, or remove `UserCourseAccess` rows, and deactivating a roster
entry does not revoke a PLAYER grant. Hosts manage the roster only; PLAYER/HOST grants remain
admin-only (Access page).

### 4.6 Guests per course — [Extra]

(Cut → document that guests may join any course's room, as today. The column from §4.1 stays.)

`game_service.authorise_player`: before the existing `GUEST` early-return, load the session's
course; if `user.role == "GUEST"` and not `course.allow_guests` → `ForbiddenError("This course does
not allow guest players")` (surfaces as the socket `error` in §4.0). The check is at socket join
(`join_room` and `rejoin_room` both call `authorise_player`), not in `/auth/guest`, because guest
tokens are not bound to a room. Default true, so existing behavior and the integration tests are
unchanged. Admin-only setting: `POST/PUT /admin/courses` + CoursesPage toggle.

**[Extra, on top of the above]** Host toggle: `PATCH /host/courses/{course_id}/settings`
`{allow_guests: bool}` behind `require_course_host` → `CourseResponse`, plus a switch on the host
course pages. Cut → hosts ask an admin.

### 4.7 Admin router changes — `backend/app/routers/admin.py`

- [T4] Question endpoints delegate to `question_service` (§4.5). Game import sanitizes through
  `sanitize_prompt` and accepts an optional `course_id` form field; a `course_id` that does not
  exist → 404 `NOT_FOUND` before anything is created.
- [T4] `POST /admin/games` accepts optional `course_id` (404 if the course does not exist).
- [T4] `PUT /admin/games/{id}` accepts `restricted`.
- [T4] **Assign / move game:** `POST /admin/games/{id}/move` body `GameMoveRequest`.

  ```
  game = SELECT ... FOR UPDATE or 404; course = get(Course, body.course_id) or 404
  body.course_id is null -> 422 INVALID_COURSE_ASSIGNMENT
  is_game_live(game) -> 409 GAME_LIVE                                  [Extra guard]
  doomed = grants on game whose user lacks HOST on body.course_id
  if not body.confirm:
      return GameMoveResult(applied=false, game=unchanged, dropped_grants=doomed)  # 200, no writes
  delete doomed grants; game.course_id = body.course_id
  return GameMoveResult(applied=true, game=updated, dropped_grants=doomed)
  ```

  Works for courseless games (assign) and assigned ones (move). Existing sessions keep their own
  `course_id`. `restricted` is not changed by a move. The UI always calls with `confirm=false`
  first and shows `dropped_grants` before confirming.
- [T4] `GET /admin/courses/{id}/access` → `list[CourseAccessEntry]`;
  `GET /admin/games/{id}/access` → `list[GameAccessEntry]`. Grant/revoke keep using the existing
  per-user endpoints (`POST/DELETE /admin/users/{id}/course-access|game-access`).
- [T4] `POST/PUT /admin/courses` accept `allow_guests`.
- [Extra] `DELETE /admin/games/{id}`: **not** subject to the live-game block. Before deleting rows,
  for every session of the game call `state_service.delete_room_state(redis, room_code,
  session_id)`. Cut → a test that fails mid-game leaves a Redis room counting toward the 50-room
  limit (T5's resource-limit warning).
- Roster import endpoints: unchanged (`mode="replace"`); the 1000-row fix applies via the shared
  service [Extra].

### 4.8 New host router — `backend/app/routers/host.py` — [T4]

Prefix `/host`, registered in `backend/app/main.py` under `/api`. Every endpoint depends on
`require_user` plus the named access dependency.

| Method + path | Dependency | Behavior |
|---|---|---|
| `GET /host/courses/{course_id}/games` | `require_course_host` | `list[HostGameListItem]`: games with this `course_id` the caller can use (restricted only with a grant; admin sees all). |
| `POST /host/courses/{course_id}/games` | `require_course_host` | `HostGameCreate` → 201 `GameResponse` with `course_id` from the path, `restricted=false`. |
| `GET /host/games/{game_id}` | `require_game_host` | `GameResponse`. |
| `PUT /host/games/{game_id}` | `require_game_host` | `HostGameUpdate` → `GameResponse`. 409 `GAME_LIVE` [Extra]. |
| `DELETE /host/games/{game_id}` | `require_game_host` | See below. 204. |
| `GET /host/games/{game_id}/questions` | `require_game_host` | Ordered `list[QuestionResponse]`. |
| `POST /host/games/{game_id}/questions` | `require_game_host` | 201 `QuestionResponse`. |
| `PUT /host/games/{game_id}/questions/{question_id}` | `require_question_host` | `QuestionResponse`. |
| `DELETE /host/games/{game_id}/questions/{question_id}` | `require_question_host` | 204. |
| `POST /host/games/{game_id}/questions/reorder` | `require_game_host` | `QuestionReorder` → 204. |
| `GET /host/courses/{course_id}/roster` | `require_course_host` | `list[RosterEntryResponse]` (active and inactive). |
| `POST /host/courses/{course_id}/roster` | `require_course_host` | Multipart: `file` (Canvas gradebook CSV, parsed by `process_roster_csv`), `mode` (default `add_update`), `version` [Extra]. → `RosterUploadResult`. `mode=replace` with no valid rows → 422 `ROSTER_EMPTY`. [Extra] `version` is **required** for `mode=replace` (missing → 422 `ROSTER_PREVIEW_REQUIRED`) and **optional** for `add_update`; whenever it is sent, in either mode, it must match `roster_version` (else 409 `ROSTER_CHANGED`). |
| `POST /host/courses/{course_id}/roster/preview` | `require_course_host` | [Extra] Same `file` + `mode`, no writes → `RosterPreviewResponse`. |
| `PATCH /host/courses/{course_id}/roster/{entry_id}` | `require_course_host` | [Extra] `{is_active: bool}` only → `RosterEntryResponse`; 404 if the entry is not in this course. |
| `GET /host/courses/{course_id}/sessions?status=` | `require_course_host` | `list[SessionListItem]` for sessions with this `session.course_id` (any host's), ordered `created_at` desc, **excluding sessions of restricted games the caller has no grant on** (admin sees all). `status`: optional `Literal["LOBBY","IN_PROGRESS","COMPLETED","ABANDONED"]`; omitted = all statuses; other values → 422 `VALIDATION_ERROR`. All filtering (status, restricted) is done **server-side** in the query. |
| `GET /host/sessions/{session_id}/export` | `require_session_host` | Raw per-player CSV (`export_service.build_session_csv`), `Content-Disposition: attachment; filename="…"`. 409 `SESSION_NOT_COMPLETED` unless `COMPLETED`. |
| `GET /host/sessions/{session_id}/report` | `require_session_host` | HTML report (`report_service.build_session_report`), same headers. 409 `SESSION_NOT_COMPLETED` unless `COMPLETED`. |

**Host game delete** (`DELETE /host/games/{game_id}`):

```
game = require_game_host(game_id)                                   # + SELECT … FOR UPDATE (§4.5)
if any session of game has status COMPLETED: 409 GAME_HAS_RESULTS
if any SessionScore exists for any session of game: 409 GAME_HAS_RESULTS   # incl. ABANDONED / IN_PROGRESS
if is_game_live(game): 409 GAME_LIVE                               # IN_PROGRESS with a live Redis room
for s in sessions of game (all score-less: LOBBY, ABANDONED, stale IN_PROGRESS):
    state_service.delete_room_state(redis, s.room_code, s.id)     # Redis first
    delete s
delete game                                                         # questions + UserGameAccess cascade
```

Partial results are never deleted by a host: any session with even one answer blocks the delete,
and only an admin can remove it (admin delete, §4.7). Deleting a game removes its
`UserGameAccess` rows through the existing `ondelete="CASCADE"` / `delete-orphan` (§4.2); the T5
test asserts no grant rows remain. Players sitting in a deleted LOBBY are not notified (same as
today's session delete).

### 4.9 Other existing endpoints

- [Extra] `GET /game/rooms/{code}` (`routers/game.py`): allow only ADMIN, the session's
  `host_user_id`, or a HOST on `session.course_id`; else 403 `FORBIDDEN`. Verified 2026-09-30: the
  only callers are host `pages/game/GameLayout.tsx`, `scripts/smoke_test_websocket.py`,
  `scripts/simulate_players.py` and `tests/integration/test_game_flow.py` (all host or admin). The
  player app only calls the public `/ping`. **If a player caller is ever added**, extend the rule
  with `authorise_player` for that session rather than opening it up. Cut → any logged-in user can
  read any room's game/course metadata, as today.
- [Extra] `GET /game/sessions/{id}/export`: switch from ownership-only to `require_session_host` so
  it matches the host router. Admins still pass. Cut → two export buttons with two rules.
- `DELETE /game/sessions/{id}`, `/guests`, `/merge-guest`, `my-active-sessions`: unchanged.

### 4.10 Revoked HOST during a session — [Extra]

(Cut → a host whose HOST access is revoked keeps control of their existing sessions, as today.)

`backend/app/websocket/gateway.py`:
- `on_join_room`, HOST branch: allow ADMIN, or (`user.id == session.host_user_id` **and**
  `has_course_host(user, session.course_id)`). Otherwise the existing "Not authorised as host for
  this session" error.
- `on_rejoin_room`: apply the same course-HOST requirement to the **non-admin** host path only. Do
  not touch the admin branch (that is the separate fix).
- Connected host sockets are not rechecked; the running game can finish. If the revoked host
  disconnects mid-game they cannot rejoin, and the existing 5-minute abandon task ends the game.
  Accepted.
- After the game, exports and reports require `can_view_session_results` (§4.3, §4.8).

### 4.11 Frontend — host app (`frontend/host/src/`) — [T4]

- `lib/api.ts`: add `put`, `patch`, `postForm` (multipart, no `Content-Type`) and `download` (Blob
  + `Content-Disposition` filename), copied from `frontend/admin/src/lib/api.ts`. **[Extra]** read
  errors as `body.message ?? (string detail) ?? "Invalid input"`, falling back to `HTTP <status>`.
  Cut → `GAME_LIVE` / `ROSTER_CHANGED` / `GAME_RESTRICTED` show as `HTTP 409` / `HTTP 403`.
- `App.tsx`: a `HostLayout` (course picker from `GET /game/my-courses` — every course for an
  admin, HOST courses for a USER; changing it navigates to the same sub-page for the new course;
  links to Games, Roster, Sessions; "Play" → `/home`; Sign out) wrapping, inside `RequireAuth`:
  - `/courses/:courseId/games` → `pages/manage/GamesPage.tsx`
  - `/courses/:courseId/games/:gameId/questions` → `pages/manage/QuestionEditorPage.tsx`
  - `/courses/:courseId/roster` → `pages/manage/RosterPage.tsx`
  - `/courses/:courseId/sessions` → `pages/manage/SessionsPage.tsx`
  `:courseId` is for navigation only; game/question/session API calls use flat `/host/games/...`
  and `/host/sessions/...` paths. `/game/:code/*` (projector screens) is unchanged and does not use
  `HostLayout`.
- `pages/HomePage.tsx`: course dropdown first; the game dropdown lists only `my-games` items whose
  `course_id` equals the selected course. Next to the course dropdown, a "Manage this course"
  button that navigates to `/courses/{selectedCourseId}/games` (disabled until a course is
  selected). If `my-courses` is empty, show "You don't host any courses yet — ask an admin for
  HOST access" and no dropdowns.
- `pages/manage/GamesPage.tsx`: list/create/edit/delete games for the course; restricted badge
  (read-only). Show `GAME_HAS_RESULTS` / `GAME_LIVE` messages.
- `pages/manage/QuestionEditorPage.tsx`: adapted copy of `frontend/admin/src/pages/
  QuestionEditorPage.tsx`, pointed at `/host/games/{id}/questions...`. The apps share no code;
  record the copy in `frontend/host/src/pages/CLAUDE.md`.
- `pages/manage/RosterPage.tsx`: roster table; CSV upload with a mode selector defaulting to "Add /
  update only". **[Extra]** Preview: upload → added / updated / reactivated / to be deactivated /
  errors → "Confirm" re-sends the file with `mode` and `version`. "Replace roster" requires the
  preview and a second confirm naming the deactivation count.
- `pages/manage/SessionsPage.tsx`: COMPLETED sessions (`?status=COMPLETED`) with "Download scores
  (CSV)" and "Download summary (HTML)" (`api.download`).

### 4.12 Frontend — admin app (`frontend/admin/src/`) — [T4]

- `App.tsx` sidebar in two sections — **Admin:** Users, Courses, Access; **Host tools:** Games,
  Sessions, Guests. Default route `/users` (was `/courses`).
- New `pages/AccessPage.tsx` (`/access`): pick a course (`GET /admin/courses`) →
  - its HOST/PLAYER users (`GET /admin/courses/{id}/access`). Grant: pick a user from
    `GET /admin/users` and a role → `POST /admin/users/{user_id}/course-access` body
    `{course_id, role}` (this upserts, so it also switches HOST ↔ PLAYER). Revoke →
    `DELETE /admin/users/{user_id}/course-access/{course_id}`.
  - its games (`GET /admin/games`, filtered by `course_id` client-side) with a **restricted**
    toggle (`PUT /admin/games/{id}` `{restricted}`) and grant holders
    (`GET /admin/games/{id}/access`). Grant → `POST /admin/users/{user_id}/game-access` body
    `{game_id}`. Revoke → `DELETE /admin/users/{user_id}/game-access/{game_id}`.
  - an **Unassigned games** list (games with `course_id = null`) with "Assign to this course" →
    `POST /admin/games/{id}/move` (same confirm flow as GamesPage).
  Warnings: grant holders with `has_course_host = false` ("this grant has no effect"); restricted
  games with no grant holders ("only admins can run this game").
- `pages/GamesPage.tsx`: create and import forms **require** a course (the API keeps it optional);
  list shows course, restricted badge, and "Unassigned" for null-course games. "Move / assign to
  course" action: call `/move` with `confirm=false`, show `dropped_grants` ("These users will lose
  access: …"), then call with `confirm=true`.
- `pages/CoursesPage.tsx`: `allow_guests` toggle.
- `pages/UserDetailPage.tsx`: game-access list shows each game's course; no behavior change.
- **[Extra]** `lib/api.ts`: same error-message fix as the host app.

### 4.13 Implementation order

All steps on `feat/t4-host-admin`, backend first, then frontend:

Backend
1. Migration 004 + models + schemas (§4.1, §4.2). Run against a copy of real data; check the
   backfill.
2. `access_service` + dependencies (§4.3); `create_room`, `my-games` (§4.4).
3. Extract `question_service` / roster `mode`; switch the admin router to them with no behavior
   change (§4.5, §4.7). The existing integration suite must pass unchanged.
4. Admin additions (§4.7), host router (§4.8), `main.py` registration.
5. [Extra] backend items in any order. T5 tests alongside each step. Backend context docs.

Frontend (same branch, built against the new API from steps 1–5)
6. Host frontend (§4.11), admin frontend (§4.12), [Extra] frontend items, frontend context docs.

### 4.14 Integration tests — [T5]

New files under `tests/integration/` (e.g. `test_host_access.py`, `test_host_management.py`,
`test_host_exports.py`), using the existing `conftest.py` fixtures. New helpers create, as admin,
local USERs (`POST /admin/users`), grant course HOST/PLAYER and game access, and log in
(`POST /auth/login`). **Do not modify or weaken `test_game_flow.py` or existing fixtures.** Assert
on `error` codes from §4.0 and re-read state after each write.

- **Host access:** HOST of course A can list/edit A's games; 403 `FORBIDDEN` on a course-B game via
  `/host/games/{id}`; 404 for a question ID from another game; GUEST → 403; USER with no HOST →
  403; admin succeeds everywhere.
- **Restricted:** HOST without grant → 403 `GAME_RESTRICTED`, absent from `my-games` and the course
  game list; HOST with grant → allowed; grant without HOST → 403 `FORBIDDEN`.
- **Player access:** a USER with no roster row and no course access in the room's course gets socket
  `error` `"You are not enrolled in the course roster for this game"` on `join_room` as PLAYER and
  is not in the host's player list; a USER with PLAYER access in that course joins; a USER with
  PLAYER access only in a *different* course is denied.
- **Course-specific:** `POST /game/rooms` with a game from another course → 422 `COURSE_MISMATCH`;
  host-created game carries the path's `course_id`.
- **Attach-on-first-room:** courseless admin game is attached by its first room; a second room in
  another course → 422 `COURSE_MISMATCH`; nonexistent course → 404 and the game is still
  courseless; a non-admin cannot see or run a courseless game.
- **Assign/move:** `confirm=false` returns `dropped_grants` and changes nothing; `confirm=true` moves
  the game and deletes exactly those grants; old sessions keep their `course_id`.
- **Questions:** host CRUD and reorder round-trip; a `<script>` prompt is stored sanitized. [Extra,
  if built:] invalid PUT → 422 `VALIDATION_ERROR` and the question is unchanged; reorder with a
  missing ID → 422 `INVALID_ORDER`; delete a scored question → 409 `QUESTION_HAS_ANSWERS`; edits
  during an IN_PROGRESS game → 409 `GAME_LIVE`.
- **Host game delete:** blocked with 409 `GAME_HAS_RESULTS` after a COMPLETED session, and also
  for an ABANDONED (or IN_PROGRESS) session with at least one answer; the game, its sessions and
  scores are unchanged afterwards. A game with only a score-less LOBBY session deletes, leaving no
  session row, no `room:{code}` key and no `UserGameAccess` rows.
- **Live-edit race [Extra, if built]:** not reliably testable end-to-end; cover with the
  `GAME_LIVE` test above and rely on the row lock (§4.5).
- **Roster:** `add_update` never deactivates; `replace` deactivates missing entries; `replace`
  with no valid rows → 422 `ROSTER_EMPTY` and nothing deactivated; a CSV without `Student` /
  `SIS Login ID` → `errors` and no changes; non-HOST → 403. [Extra:] preview matches what commit
  does; `replace` without `version` → 422 `ROSTER_PREVIEW_REQUIRED`; stale `version` → 409
  `ROSTER_CHANGED`; >1000 rows → 422 `ROSTER_TOO_LARGE` with no changes.
- **Exports:** host of the session's course downloads CSV and HTML for a COMPLETED session (CSV
  scores match the game run); non-completed → 409 `SESSION_NOT_COMPLETED`; host of another course
  → 403; HOST without grant on a restricted game → 403 `GAME_RESTRICTED` and the session is absent
  from the course session list.
- **[Extra, if built]:** `allow_guests=false` → guest gets `"This course does not allow guest
  players"`, roster player still joins; `GET /game/rooms/{code}` → 403 for a guest; revoked host's
  `join_room` as HOST refused; admin game delete leaves no `room:{code}` / `session:{id}:*` keys.
- **Sessions list:** `?status=COMPLETED` returns only completed sessions; omitted returns all;
  `?status=bogus` → 422 `VALIDATION_ERROR`.

**Test data and teardown.**
- Every created name is unique per test using the same scheme as the existing fixture:
  `tag = uuid4().hex[:8]`; usernames `t4_host_{tag}` / `t4_player_{tag}` (allowed by
  `UserCreate`'s `^[a-zA-Z0-9_-]+$`), course names `T4 Course {tag}`, roster netids
  `t4n{tag}{i}`.
- Teardown, in this order, each call tolerant of 404: admin `DELETE /admin/games/{id}` for every
  game created (removes sessions, scores, grants, and — with the [Extra] — Redis keys); then admin
  `DELETE /admin/users/{id}` for every user created (their `UserCourseAccess` / `UserGameAccess`
  rows cascade with the user). Courses and roster rows are left as inert records, exactly as the
  existing fixture does for courses (there is no course-delete endpoint).
- Put these in a new fixture in a new `tests/integration/t4_helpers.py` (or a new conftest
  section) — do not change the existing `game_setup`.

### 4.15 Context hierarchy updates

Per `.claude/rules/context-sync.md`, edit (do not regenerate), all on `feat/t4-host-admin`
alongside the code they describe: backend — `backend/app/`, `models/`, `schemas/`, `common/`,
`services/`, `routers/`, `websocket/` `CLAUDE.md`; frontend — `frontend/`, `frontend/host/src/` +
`pages/` + `lib/`, `frontend/admin/src/` + `pages/` + `lib/` `CLAUDE.md`.

### 4.16 Files touched

Backend (under `backend/app/`): `migrations/versions/004_course_specific_games.py` (new),
`models/game.py`, `models/course.py`, `schemas/admin.py`, `schemas/game.py`, `schemas/host.py`
(new), `common/dependencies.py`, `services/access_service.py` (new), `services/question_service.py`
(new), `services/game_service.py`, `services/roster_service.py`, `routers/host.py` (new),
`routers/admin.py`, `routers/game.py`, `main.py`, `websocket/gateway.py` [Extra]. Also
`scripts/t4_migration_report.py` (new) [Extra].

Host frontend (`frontend/host/src/`): `lib/api.ts`, `App.tsx`, `pages/HomePage.tsx`, new
`pages/manage/{GamesPage,QuestionEditorPage,RosterPage,SessionsPage}.tsx`.

Admin frontend (`frontend/admin/src/`): `App.tsx`, `pages/AccessPage.tsx` (new),
`pages/GamesPage.tsx`, `pages/CoursesPage.tsx`, `pages/UserDetailPage.tsx`, `lib/api.ts` [Extra].

Tests: new test files and `tests/integration/t4_helpers.py` under `tests/integration/` (§4.14);
existing test files and fixtures unchanged. Context docs: §4.15.

---

## 5. Open questions

1. **Does the TA accept opt-in game grants as "granting course/game access"?** Being asked.
   **Proceed assuming yes.** Fallback if the TA requires a grant for every game: change the
   default of `games.restricted` to `true` for new games too, and auto-grant the creating host in
   `POST /host/courses/{id}/games`. No other part of this design changes.

Resolved (recorded so they are not reopened):

- Games whose only sessions are LOBBY/ABANDONED/IN_PROGRESS count as having no completed sessions
  (§4.1 step 4).
- `allow_guests` is admin-only; host toggling is [Extra] (§4.6). The column is always added.
- Every existing game is restricted by the migration (§4.1 step 5).
- Admin assign/move is [T4], via a confirm step that drops grants that would stop working (§4.7).

---

## Separate deliverable (not T4): admin rejoin becomes host

Branch `fix/admin-rejoin-becomes-host`, its own MR, independent of the T4 branches.

Bug: `backend/app/websocket/gateway.py` `on_rejoin_room` computes
`is_host = user.id == session.host_user_id or user.role == "ADMIN"`. An admin who joined a room as
a **player** and reconnects (`rejoin_room`) is re-registered as HOST: they join the host room, can
advance the game, and stop being a player.

Fix (prose): infer the role from how the user is registered in this session. The session's
`host_user_id` → host. Otherwise, present in Redis `session:{id}:players` → player (re-run
`authorise_player` as today). Otherwise an ADMIN becomes host only through an explicit `join_room`
with `role: "HOST"`, never by inference. Test: admin joins as PLAYER, disconnects, `rejoin_room` →
still PLAYER, and `host_advance` is rejected.

The player app never sends `rejoin_room` (`frontend/player/src/pages/CLAUDE.md`), so this is
reachable only by other clients or scripts. Fix it anyway.

---

## Revision history

- **2026-09-30, v1** — initial spec from the design discussion.
- **2026-09-30, v2** — after the first goldfish test: player access stated explicitly with a T5
  test; first-room attach uses `SELECT … FOR UPDATE` and validates the course first; session
  list/export/report apply the restricted/grant check (on the session's course); TA question
  proceeds with a concrete fallback; admin assign/move promoted to [T4] with a confirm step that
  drops stale grants; `allow_guests` column always added; host game delete blocks only on COMPLETED
  sessions and removes grants; error codes, response shapes and branches defined.
- **2026-09-30, v3** — goldfish Medium/Low items: `create_room` access check rewritten without the
  redundant/unreachable branches, with an explicit failure order; `question_count`,
  `player_count`, timestamps and `my-courses` (admin) defined; 422-vs-409 rule; roster `version`
  required for `replace`, optional but checked for `add_update`, computed by one JSON-based
  function; `ROSTER_EMPTY` guard for `replace` with no valid rows; host upload is Canvas-only and
  roster rows are independent of PLAYER grants; `?status=` filter typed and server-side; live-edit
  vs game-start race closed with a game-row lock in both edits and `start_game`; admin question
  endpoints get Redis; migration names its FK/index and uses `"1"`/`"0"` boolean defaults;
  `update_question` merges with `exclude_unset` so explicit nulls clear; game import 404s on an
  unknown course; T5 test-data naming and teardown; "Manage this course" and AccessPage endpoints
  named. Decision: host game delete is also blocked (`GAME_HAS_RESULTS`) when **any** session has
  scores, so partial results from ABANDONED games are never silently deleted.
- **2026-10-01, v4** — all of T4 (backend + frontend, §4.1–§4.15) moves to a single branch,
  `feat/t4-host-admin`, replacing `feat/t4-host-admin-backend` and `feat/t4-host-admin-frontend`.
  Why: there is one implementer, so separate MRs add coordination with no review benefit, and a
  single branch lets the UI be tested against the new API as it is built rather than waiting for a
  backend merge. Implementation order is unchanged (backend first, then frontend).
  `fix/admin-rejoin-becomes-host` stays separate.
