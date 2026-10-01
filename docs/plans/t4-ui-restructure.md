# T4 — Host/Admin UI Restructure and Course-Specific Games

Status: agreed design, not yet goldfish-tested. Written 2026-09-30 on branch
`docs/design-t4-ui-restructure`. Task text: [instructions.md](../../instructions.md) §T4 (and §T5 for
tests). Architecture context: the `CLAUDE.md` hierarchy under `backend/` and `frontend/`; start at
[backend/app/CLAUDE.md](../../backend/app/CLAUDE.md) and [frontend/CLAUDE.md](../../frontend/CLAUDE.md).

## Priority tags

Every item in this document carries one tag:

- **[T4]** — required to meet the T4 task text (or required for a [T4] item to be safe/correct).
  Do these first.
- **[Extra]** — hardening or polish agreed in design. Valuable, but can be cut if time runs short;
  each one says what is lost if it is cut.
- **[T5]** — integration tests for the above.

A separate, unrelated bug fix is listed at the end under **Separate deliverable**; it ships on its
own `fix/` branch and MR and is **not** part of the T4 changes.

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

- **Data model [T4]:** add nullable `games.course_id` (FK → `courses.id`) and
  `games.restricted` (bool, default false); add `courses.allow_guests` (bool, default true) [Extra].
  Migration `004` backfills `course_id` from session history and sets `restricted = true` on
  **every existing game**, so nobody silently gains access; admins un-restrict deliberately.
- **Access rule [T4]:** a non-admin may use game G iff they hold course `HOST` on `G.course_id`,
  **and**, if `G.restricted`, they also hold a `UserGameAccess` grant on G. Course HOST is the
  primary rule; grants are an opt-in, admin-managed narrowing. Admins bypass all of it.
- **One place for access logic [T4]:** a new `services/access_service.py` holds the predicates;
  thin FastAPI dependencies in `common/dependencies.py` (`require_course_host`,
  `require_game_host`, `require_question_host`, `require_session_host`) **load the resource and
  check its own course** — never a course ID taken from the URL.
- **New host router [T4]:** `/api/host/...` with flat resource URLs. `/api/admin/*` is **not**
  loosened.
- **Shared services [T4]:** question CRUD (validation, `bleach` sanitization, ordering) moves into
  `services/question_service.py`; roster upload logic stays in `services/roster_service.py` with a
  new `mode`. Both the admin and host routers call these — no duplicated rules.
- **Courseless games [T4]:** the admin **API** may still create a game without a course (keeps the
  existing integration fixture unchanged); the admin **UI** always requires one. A courseless game
  is attached to the course of its first room, atomically, and the normal course-match rule
  applies from then on.
- **Frontend [T4]:** the host app gets a management area (Games, Questions, Roster, Sessions) per
  course; the admin sidebar is reordered to Users / Courses / Access first, then a "Host tools"
  section with the existing Games and Sessions pages.

## 3. Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Retire `UserGameAccess` entirely** (course HOST is the only rule) | Before T4, every game a non-admin host could run needed a grant. Retiring grants would silently give every HOST in a course every game assigned to that course — including answer keys (`QuestionResponse.answer_data`) and edit/delete rights. It would also remove the admin's "granting game access" task named in T4. No existing test depends on grants either way (all tests run as admin), so this was decided on behavior, not tests. |
| **Keep grants as a mandatory second check** (HOST **and** grant always) | Breaks T4's core workflow: a host-created game would be invisible to co-hosts of the same course until an admin granted it. |
| **Grants as a way to share a game across courses** | Contradicts T4 ("only accessible to hosts and players of that course"). Cross-course reuse should be done by copying a game (export/import), not by grants. |
| **Nested URLs** `/host/courses/{cid}/games/{gid}/questions/{qid}` checked by `require_course_host(cid)` | Insecure by default: proves the caller hosts *cid*, not that game *gid* belongs to *cid*. Every nested handler must remember an extra ownership check; one miss is an IDOR. Flat URLs + resolve-then-check make it impossible to name the wrong course. |
| **Loosen `/admin/*` to accept course hosts** | Weakens every admin endpoint at once; mixes two permission models in one router. |
| **Guests as an undocumented global exception** | Guest tokens are not bound to a room (2 h access / 7 d refresh), so "guests allowed" would mean every course's live game is open to anyone with the code. A per-course switch makes it an admin decision. **Per-session flag** was the finer-grained option; rejected for now as more UI and schema for little gain. |
| **Backfill from each game's most recent session** | One mistaken or abandoned session (wrong course picked, closed immediately) would decide the game's course. Replaced by "most completed sessions". |
| **Permanent admin exception for courseless games** | Leaves games unattached forever, which visibly fails T4's "attached at creation". Replaced by attach-on-first-room. |
| **Make `course_id` required on the admin API** | Would require editing the integration fixture (`tests/integration/conftest.py` `game_setup`). Arguably not "weakening", but avoidable. |
| **Recheck course HOST on every host socket action** | A DB query per click, and a mid-question revocation would strand players with no host. Rechecking at (re)join is enough. |
| **"Host tools" in the admin app as a link to the host app** | Works behind nginx (shared origin + token) but not in Vite dev (separate origins). Kept existing admin pages instead; can revisit later. |
| **Client-side roster parsing for hosts** (copy the admin's column-mapping wizard) | Duplicates a large page and lets preview and commit disagree. Server-side parsing guarantees the preview is what gets committed. |
| **Blocking question edits while any LOBBY/IN_PROGRESS session exists** | LOBBY rows are never cleaned up in MySQL (an abandoned lobby only expires in Redis), so this would lock some games permanently. LOBBY edits are harmless because questions are read when the game starts and as each question is shown. |

---

## 4. Detailed implementation

### 4.1 Migration `004_course_specific_games.py` — [T4] (except where tagged)

New file `backend/app/migrations/versions/004_course_specific_games.py`, `down_revision = "003"`
(match the revision ID format used in `003_float_points.py`).

`upgrade()`:

1. `games.course_id` — `Integer`, **nullable**, FK → `courses.id` (no `ondelete`; there is no
   course-delete endpoint), indexed. [T4]
2. `games.restricted` — `Boolean`, `NOT NULL`, `server_default false`. [T4]
3. `courses.allow_guests` — `Boolean`, `NOT NULL`, `server_default true`. [Extra — see 4.6]
4. Backfill `games.course_id` [T4]:

   ```
   for each game g with course_id IS NULL:
       completed = sessions of g with status = 'COMPLETED'
       if completed is not empty:
           per course c: n(c) = count, last(c) = max(created_at), maxid(c) = max(session id)
           pick c maximising (n, last, maxid)            # most completed, then most recent, then id
           g.course_id = c
       else:                                            # no completed sessions (none, or only
                                                        # LOBBY/ABANDONED/IN_PROGRESS ones)
           holders = users with a UserGameAccess row on g
           host_courses = union over holders of courses where they hold UserCourseAccess HOST
           if len(host_courses) == 1: g.course_id = that course
           else: leave NULL
   ```

5. `UPDATE games SET restricted = true` — **every existing game**, with or without grants. [T4]
   Restricting only games that have grants is not enough: a game that admins ran but never granted
   would be backfilled into a course unrestricted, and every HOST of that course would silently
   gain it, answer keys included. Restricting everything preserves today's behavior: a non-admin
   can use an existing game only if they hold a grant on it **and** HOST on its course. Cost:
   course hosts see no existing games they weren't granted until an admin un-restricts them (Access
   page, 4.12). Games created after the migration default to `restricted = false`.

`downgrade()`: drop the three columns (index/FK first). The backfill is not reversible; that is
acceptable and stated here.

Backfill must be written as SQL/`op.execute` or Core statements inside the migration — not by
importing ORM models (they will have moved on by the time the migration is replayed).

**Migration report — [Extra]** (cut → admins must find affected games/users by hand).
New read-only script `scripts/t4_migration_report.py`, rerunnable at any time, run inside the
backend container. Prints three sections (plain text or Markdown tables):

- **Restricted games:** id, title, course, list of grant holders. Right after the migration this is
  every game; flag those with **no** grant holders ("admin-only until un-restricted or granted").
- **Grant holders who lost access:** every `(user, game)` grant where the user does not hold HOST
  on `game.course_id` (includes games whose `course_id` is NULL).
- **Unassigned games:** games with `course_id IS NULL` and why (no sessions / no grants / grant
  holders host 0 or ≥2 courses).

### 4.2 Models and schemas — [T4]

`backend/app/models/game.py`: `Game.course_id: Mapped[int | None]`, `Game.restricted: Mapped[bool]`,
`Game.course` relationship. `backend/app/models/course.py`: `Course.allow_guests: Mapped[bool]`
[Extra], `Course.games` relationship (no cascade).

`backend/app/schemas/admin.py`:
- `GameCreate`: add `course_id: int | None = None` (optional on the **API**).
- `GameUpdate`: add `course_id: int | None` (move game; may not be set back to null) and
  `restricted: bool | None`.
- `GameResponse`: add `course_id`, `restricted`.
- `CourseCreate` / `CourseUpdate` / `CourseResponse`: add `allow_guests` [Extra].

`backend/app/schemas/game.py`: `MyGameItem` gains `course_id` and `restricted`.

New `backend/app/schemas/host.py`:
- `HostGameCreate` (title, description, max_players — **no** `course_id`; it comes from the URL).
- `HostGameUpdate` (title, description, max_players only — hosts cannot move or restrict games).
- `HostSessionItem` (session id, room code, game title, status, started/ended timestamps, player
  count).
- `RosterUploadMode = Literal["add_update", "replace"]`.
- `RosterPreviewResponse` [Extra]: `added`, `updated`, `reactivated`, `deactivated` (each a list of
  `{netid, full_name, email}`, `updated` also lists changed fields), `errors` (`{row, message}`),
  `version: str`.
- Question shapes are reused from `schemas/admin.py` (`QuestionCreate`, `QuestionUpdate`,
  `QuestionResponse`, `QuestionReorder`). Hosts need `answer_data` to edit scoring, so
  `QuestionResponse` is correct here.

### 4.3 Access layer — [T4]

New `backend/app/services/access_service.py` (pure async functions taking `db`, `user`):

```
has_course_host(db, user, course_id) -> bool
    ADMIN -> True
    else  -> exists UserCourseAccess(user_id, course_id, role='HOST')

can_use_game(db, user, game) -> bool
    ADMIN -> True
    game.course_id is NULL -> False
    not has_course_host(user, game.course_id) -> False
    game.restricted and not exists UserGameAccess(user, game) -> False
    True
```

`backend/app/common/dependencies.py` gains FastAPI dependencies built on these. Each **loads the
resource first** and checks the resource's own course:

```
require_course_host(course_id)      -> Course
    course = get(Course) or 404 NotFoundError
    if not has_course_host(user, course.id): 403 "You do not have HOST access to this course"

require_game_host(game_id)          -> Game
    game = get(Game) or 404
    if user is ADMIN: return game
    if game.course_id is NULL: 404 (do not reveal unassigned games)
    if not has_course_host(user, game.course_id): 403 "You do not have HOST access to this course"
    if game.restricted and no grant: 403 "This game is restricted"
    return game

require_question_host(game_id, question_id) -> Question
    game = require_game_host(game_id)
    q = get(Question) or 404; if q.game_id != game.id: 404

require_session_host(session_id)    -> GameSession
    s = get(GameSession) or 404
    if not has_course_host(user, s.course_id): 403      # the SESSION's course, not the game's
```

All four sit on top of `require_user` (GUEST → 403 before any lookup). Admin bypass still returns
404 for missing resources.

This adds an import edge `common/` → `services/access_service`. Record it in
`backend/app/common/CLAUDE.md`.

`backend/app/services/game_service.py`: `assert_host_can_use_course` / `assert_host_can_use_game`
become thin wrappers over `access_service` (or are replaced at their call sites) so there is one
definition of "is HOST".

### 4.4 Room creation and game visibility — [T4]

`game_service.create_room(db, redis, host, game_id, course_id)`:

```
game = get(Game) or 404
if not can_use_game(host, game) and not (host is ADMIN): 403/404 as in require_game_host

if game.course_id is NULL:                       # only reachable by ADMIN
    rows = UPDATE games SET course_id = :course_id
           WHERE id = :game_id AND course_id IS NULL
    if rows == 0: refresh(game)                  # concurrent create attached it first
    else: log "game_attached_on_first_room"(game_id, course_id, user_id)

if course_id != game.course_id: 422 "This game belongs to course <name>"
if not has_course_host(host, course_id): 403
... existing room-limit check, room code, GameSession insert, Redis room state ...
```

The attach UPDATE must run in the **same transaction** as the `GameSession` insert and must not be
followed by a commit before it (`get_db` commits only when the handler succeeds), so a failed room
creation (room limit, room-code collision) rolls the attach back. `RoomCreateRequest` keeps
`course_id` so existing clients and the integration fixture work unchanged.

`routers/game.py` `GET /game/my-games`: ADMIN → all games. USER → games whose `course_id` is in
the user's HOST courses, excluding restricted games without a grant. Response includes
`course_id` so the host `HomePage` can filter games by the selected course.

`GET /game/my-courses`: unchanged.

### 4.5 Shared services — [T4] (validation/guards tagged individually)

New `backend/app/services/question_service.py`, used by **both** `routers/admin.py` and the new
`routers/host.py`. Admin endpoints become thin wrappers; their responses and status codes must
not change for inputs that are valid today.

- `sanitize_prompt(html)` — **[T4]**. Move the `bleach.clean(...)` call (tags/attributes exactly as
  in `routers/admin.py` create, update and import paths) here. Every write path for prompts, admin
  and host, goes through it. Cutting this lets any course HOST store script in a prompt that
  `report_service` embeds as raw HTML.
- `create_question(db, game, QuestionCreate)` — [T4]; same `order_index` logic as today.
- `update_question(db, question, QuestionUpdate)` — [T4] for the move; **structure validation
  [Extra]** (cut → a PUT can save a question that create would reject; scoring may then raise):

  ```
  merged = current question fields overlaid with the non-null fields of the patch
  QuestionCreate.model_validate(merged)      # 422 VALIDATION_ERROR on failure
  merged.prompt = sanitize_prompt(merged.prompt)
  apply merged to question
  ```

- `delete_question(db, question)` — [T4]; **[Extra]:** if any `SessionScore` references the
  question → 409 "Question has recorded answers and cannot be deleted" instead of today's FK 500.
- `reorder_questions(db, game, ids)` — [T4]; **[Extra]:** `ids` must equal the game's question-ID
  set exactly (no duplicates, none missing) → otherwise 422.
- `is_game_live(db, redis, game_id) -> bool` — **[Extra]** (cut → a host can change questions under
  a running game; reorder/delete break `question_ids` stored in Redis):

  ```
  for s in GameSession where game_id = :g and status = 'IN_PROGRESS':
      if redis room:{s.room_code} exists: return True
  return False
  ```

  When live, host question create/update/delete/reorder, host game update/delete, and **admin**
  question create/update/delete/reorder return 409 `GAME_LIVE` "This game is being played right
  now". **Admin game deletion is exempt** (see 4.7).

`backend/app/services/roster_service.py`:
- Add `mode: RosterUploadMode = "replace"` to `process_roster_csv` and `process_roster_rows`.
  `replace` = today's behavior (upsert + deactivate everyone not in the upload). `add_update` =
  upsert only, never deactivate. Admin callers keep `replace` (behavior unchanged). [T4]
- **[Extra]** Fix the 1000-row cap: if the upload exceeds 1000 data rows, reject the whole upload
  with 422 instead of truncating and then deactivating everyone past row 1000.
- **[Extra]** `preview_roster_csv(db, course_id, file, mode) -> RosterPreviewResponse`: parse with the
  same parser, compute the diff without writing, and return `version` = SHA-256 of the course's
  current roster rows sorted by netid (`netid|full_name|email|is_active`).

### 4.6 Guests per course — [Extra]

(Cut → document in the README/spec that guests may join any course's room, as today.)

`game_service.authorise_player`: before the existing `GUEST` early-return, load the session's
course; if `user.role == "GUEST"` and not `course.allow_guests` → `ForbiddenError("This course does
not allow guest players")`. The check is at **socket join** (`join_room` and `rejoin_room` both
call `authorise_player`), not in `/auth/guest`, because guest tokens are not bound to a room.
`allow_guests` defaults to true, so existing behavior and the integration tests (guest players)
are unchanged. Only admins change it (CoursesPage, `POST/PUT /admin/courses`).

**[Extra, on top of 4.6]** Host toggle: `PATCH /host/courses/{course_id}/settings`
`{allow_guests: bool}` behind `require_course_host`, plus a switch on the host app's course pages.
Cut → hosts ask an admin to change it.

### 4.7 Admin router changes — `backend/app/routers/admin.py`

- [T4] Question endpoints delegate to `question_service` (4.5). Game import delegates prompt
  sanitization to `sanitize_prompt` and accepts optional `course_id` (form field).
- [T4] `POST /admin/games` accepts optional `course_id` (404 if the course does not exist).
- [T4] `PUT /admin/games/{id}` accepts `restricted`.
- [Extra] `PUT /admin/games/{id}` accepts `course_id` to **move** a game (non-null only; 409
  `GAME_LIVE` if live). Existing sessions keep their own `course_id`. Cut → wrong first-room
  attachments can only be fixed in the database.
- [T4] New `GET /admin/courses/{id}/access` → users with HOST/PLAYER on the course.
  New `GET /admin/games/{id}/access` → grant holders, each flagged `has_course_host`. (Used by the
  Access page, 4.11.) Granting/revoking keeps using the existing per-user endpoints.
- [T4] `POST/PUT /admin/courses` accept `allow_guests` (only if 4.6 is done).
- [Extra] `DELETE /admin/games/{id}`: **not** subject to the live-game block. Before deleting rows,
  for every session of the game call `state_service.delete_room_state(redis, room_code,
  session_id)` so no `room:{code}` or `session:{id}:*` keys survive. Cut → a test that fails
  mid-game leaves a Redis room counting toward the 50-room limit (T5's resource-limit warning).
- Roster import endpoints: behavior unchanged (`mode="replace"`); 1000-row fix applies via the
  shared service [Extra].

### 4.8 New host router — `backend/app/routers/host.py` — [T4]

Prefix `/host`, registered in `backend/app/main.py` alongside the others under `/api`. Every
endpoint depends on `require_user` plus the named access dependency.

| Method + path | Dependency | Behavior |
|---|---|---|
| `GET /host/courses/{course_id}/games` | `require_course_host` | Games with this `course_id` that the caller can use (restricted ones only with a grant; admin sees all). Includes question count. |
| `POST /host/courses/{course_id}/games` | `require_course_host` | Create game with `course_id` from the path, `restricted=false`. 201 `GameResponse`. |
| `GET /host/games/{game_id}` | `require_game_host` | `GameResponse`. |
| `PUT /host/games/{game_id}` | `require_game_host` | `HostGameUpdate`. 409 `GAME_LIVE` if live [Extra]. |
| `DELETE /host/games/{game_id}` | `require_game_host` | 409 if the game has **any** sessions ("Games that have been played can only be deleted by an admin") or is live. Otherwise delete (questions cascade). |
| `GET /host/games/{game_id}/questions` | `require_game_host` | Ordered `QuestionResponse` list. |
| `POST /host/games/{game_id}/questions` | `require_game_host` | `question_service.create_question`. |
| `PUT /host/games/{game_id}/questions/{question_id}` | `require_question_host` | `question_service.update_question`. |
| `DELETE /host/games/{game_id}/questions/{question_id}` | `require_question_host` | `question_service.delete_question`. |
| `POST /host/games/{game_id}/questions/reorder` | `require_game_host` | `question_service.reorder_questions`. |
| `GET /host/courses/{course_id}/roster` | `require_course_host` | Active and inactive entries (`RosterEntryResponse`). |
| `POST /host/courses/{course_id}/roster` | `require_course_host` | Multipart `file` (Canvas gradebook CSV, parsed by `process_roster_csv`) + `mode` (default `add_update`). Returns `RosterUploadResult`. **[Extra]** also requires `version` from a preview when `mode=replace`; mismatch → 409 `ROSTER_CHANGED` "The roster changed since your preview — preview again". |
| `POST /host/courses/{course_id}/roster/preview` | `require_course_host` | **[Extra]** Same inputs, no writes, returns `RosterPreviewResponse`. |
| `PATCH /host/courses/{course_id}/roster/{entry_id}` | `require_course_host` | **[Extra]** toggle `is_active` only; 404 if the entry is not in this course. |
| `GET /host/courses/{course_id}/sessions?status=` | `require_course_host` | `HostSessionItem` list for the course (any host's sessions), newest first. |
| `GET /host/sessions/{session_id}/export` | `require_session_host` | Raw per-player CSV (`export_service.build_session_csv`). 409 unless `status == COMPLETED`. |
| `GET /host/sessions/{session_id}/report` | `require_session_host` | HTML report (`report_service.build_session_report`). 409 unless `COMPLETED`. |

Sessions are governed by `session.course_id`, not the game's current course: old sessions whose
game was backfilled or moved to another course stay with the course they were played in.

### 4.9 Other existing endpoints

- [Extra] `GET /game/rooms/{code}` (`routers/game.py`): allow only ADMIN, the session's
  `host_user_id`, or a HOST on `session.course_id`; else 403. Verified 2026-09-30: the only
  callers are host `pages/game/GameLayout.tsx`, `scripts/smoke_test_websocket.py`,
  `scripts/simulate_players.py` and `tests/integration/test_game_flow.py` (all host or admin). The
  player app only calls the public `/ping`. **If a player caller is ever added**, extend the rule
  with `authorise_player` for that session rather than opening it up. Cut → any logged-in user,
  including a guest, can read any room's game/course metadata (as today).
- [Extra] `GET /game/sessions/{id}/export`: switch from ownership-only to `require_session_host`, so
  it matches the host router (a revoked host can no longer export; a co-host can). Admins still
  pass. Cut → two export buttons with two different rules.
- `/game/sessions/{id}` DELETE, `/guests`, `/merge-guest`, `my-active-sessions`: unchanged (out of
  scope).

### 4.10 Revoked HOST during a session — [Extra]

(Cut → a host whose HOST access is revoked keeps control of their existing sessions, as today.)

`backend/app/websocket/gateway.py`:
- `on_join_room`, HOST branch: currently `user.id == session.host_user_id or ADMIN`. Change to:
  ADMIN, **or** (`user.id == session.host_user_id` **and** `has_course_host(user,
  session.course_id)`). Otherwise emit the existing "Not authorised as host for this session"
  error.
- `on_rejoin_room`: apply the same course-HOST requirement to the non-admin host path. (Do not
  change the admin branch here; that is the separate fix below.)
- Already-connected host sockets are not rechecked: the running game can finish. If the revoked
  host disconnects mid-game they cannot rejoin, and the existing 5-minute abandon task ends the
  game (`game_abandoned` to players). That is accepted behavior.
- After the game, exports and reports require course HOST (4.8, 4.9).

### 4.11 Frontend — host app (`frontend/host/src/`) — [T4]

- `lib/api.ts`: add `put`, `patch`, `postForm` (multipart, no `Content-Type`) and `download` (Blob
  + `Content-Disposition` filename), copied from `frontend/admin/src/lib/api.ts`.
  **[Extra]** Fix error parsing to read `body.message ?? body.detail` (and stringify array
  `detail`s). Cut → 409 `GAME_LIVE` / `ROSTER_CHANGED` / 403 messages show as `HTTP 409` / `HTTP
  403`, and hosts cannot tell why an action failed.
- `App.tsx`: add a `HostLayout` (nav: course picker from `GET /game/my-courses` + links to Games,
  Roster, Sessions; "Play" back to `/home`; Sign out) wrapping new routes inside `RequireAuth`:
  - `/courses/:courseId/games` → `pages/manage/GamesPage.tsx`
  - `/courses/:courseId/games/:gameId/questions` → `pages/manage/QuestionEditorPage.tsx`
  - `/courses/:courseId/roster` → `pages/manage/RosterPage.tsx`
  - `/courses/:courseId/sessions` → `pages/manage/SessionsPage.tsx`
  The `:courseId` in the URL is for navigation only; every API call uses flat `/host/games/...` or
  `/host/sessions/...` paths and the server checks the resource's own course. `/game/:code/*`
  (projector screens) is unchanged and does not use `HostLayout`.
- `pages/HomePage.tsx`: course dropdown first; the game dropdown lists only games whose
  `course_id` matches the selected course. Add a "Manage" link per course. If `my-courses` is
  empty, show "You don't host any courses yet — ask an admin for HOST access" instead of empty
  dropdowns.
- `pages/manage/GamesPage.tsx`: list/create/edit/delete games for the course (`/host/courses/{id}/
  games`, `/host/games/{id}`). Show a restricted badge (read-only).
- `pages/manage/QuestionEditorPage.tsx`: adapted copy of `frontend/admin/src/pages/
  QuestionEditorPage.tsx` pointed at `/host/games/{id}/questions...`. The apps share no code, so
  this is a copy; record that in `frontend/host/src/pages/CLAUDE.md`. Show the `GAME_LIVE` message
  when edits are refused.
- `pages/manage/RosterPage.tsx`: roster table; upload CSV with a mode selector defaulting to "Add /
  update only". **[Extra]** Preview step: upload → show added / updated / reactivated / to be
  deactivated / errors → "Confirm" sends the file again with `mode` and `version`. Choosing
  "Replace roster" requires the preview and an extra confirm naming the deactivation count.
- `pages/manage/SessionsPage.tsx`: completed sessions for the course with "Download scores (CSV)"
  and "Download summary (HTML)" buttons (`api.download`).

### 4.12 Frontend — admin app (`frontend/admin/src/`) — [T4]

- `App.tsx` sidebar becomes two sections:
  - **Admin:** Users, Courses, Access.
  - **Host tools:** Games, Sessions, Guests.
  Default route changes from `/courses` to `/users`.
- New `pages/AccessPage.tsx` (`/access`): pick a course → its HOST/PLAYER users
  (`GET /admin/courses/{id}/access`) with grant/revoke (existing per-user endpoints), and its games
  with a **restricted** toggle (`PUT /admin/games/{id}`) and grant holders
  (`GET /admin/games/{id}/access`, grant/revoke). Warn on grant holders without HOST on the
  course ("this grant has no effect") and on restricted games with no grant holders ("only admins
  can run this game").
- `pages/GamesPage.tsx`: create and import forms **require** a course (the API keeps it optional);
  list shows course and restricted badge; "Unassigned" badge for null-course games ("will be
  attached to the course of its first room"). **[Extra]** "Move to course" action.
- `pages/CoursesPage.tsx`: `allow_guests` toggle [Extra, with 4.6].
- `pages/UserDetailPage.tsx`: game-access list shows each game's course; no behavior change.
- **[Extra]** `lib/api.ts`: same `message`/`detail` error fix as the host app.

### 4.13 Implementation order

1. Migration 004 + models + schemas (4.1, 4.2). Run against a copy of real data and check the
   backfill.
2. `access_service` + dependencies (4.3); rewire `create_room`, `my-games` (4.4).
3. Extract `question_service` / roster `mode`; switch admin router to them with no behavior change
   (4.5, 4.7). Run the existing integration suite — it must pass unchanged.
4. Host router (4.8) and `main.py` registration.
5. Host frontend (4.11), then admin frontend (4.12).
6. [Extra] items in any order: live-game block, PUT/reorder validation, delete-with-scores 409,
   roster preview/version/1000-cap, `allow_guests`, room-metadata check, export rule, revoked-HOST
   recheck, admin delete Redis cleanup, move game, error-message fix, migration report.
7. T5 tests (4.14) alongside each step.
8. Update the context hierarchy (4.15).

### 4.14 Integration tests — [T5]

New files under `tests/integration/` (e.g. `test_host_access.py`, `test_host_management.py`,
`test_host_exports.py`), using the existing `conftest.py` fixtures. Add helpers that, as admin,
create a local USER (`POST /admin/users`), grant course HOST/PLAYER and game access, and log in
(`POST /auth/login`). **Do not modify or weaken `test_game_flow.py` or existing fixtures.**

Required coverage (behavior, not just status codes — re-read state after each write):

- Access: HOST of course A can list/edit A's games; gets 403 on a game in course B via
  `/host/games/{id}`; gets 404 for a question ID that belongs to another game; GUEST → 403; USER
  with no HOST → 403; admin succeeds everywhere.
- Restricted: HOST without a grant → 403 on a restricted game and absent from `my-games` and the
  course game list; HOST with a grant → allowed; grant without HOST → denied.
- Course-specific: `POST /game/rooms` with a game from another course → 422; host-created game has
  the path's `course_id`.
- Attach-on-first-room: admin-created courseless game is attached by the first room; a second room
  in another course → 422; a non-admin cannot see or run a courseless game; a room creation that
  fails (e.g. nonexistent course) leaves the game courseless.
- Questions: host CRUD and reorder round-trip; prompt with `<script>` is stored sanitized. [Extra
  items, if built:] invalid PUT → 422 and question unchanged; reorder with a missing ID → 422;
  deleting a question with scores → 409; edits during an IN_PROGRESS game → 409 `GAME_LIVE`.
- Roster: `add_update` never deactivates; `replace` deactivates missing entries; non-HOST → 403.
  [Extra:] preview reports exactly what commit does; stale `version` → 409; >1000 rows → 422 with no
  changes.
- Exports: host of the session's course downloads CSV and HTML for a COMPLETED session (CSV rows
  match the players' scores from the game run); 409 for a non-completed session; host of another
  course → 403.
- [Extra, if built:] `allow_guests=false` → guest `join_room` gets an error, roster player still
  joins; `GET /game/rooms/{code}` → 403 for a guest; revoked host's `join_room` as HOST is refused;
  admin game delete leaves no `room:{code}` / `session:{id}:*` keys.
- Teardown: every test deletes the games it creates via admin delete (which also clears Redis, if
  the Extra is built).

### 4.15 Context hierarchy updates

Per `.claude/rules/context-sync.md`, edit (do not regenerate) these `CLAUDE.md` files when the
corresponding code lands: `backend/app/` (authorization section, data flow), `backend/app/models/`
("How games relate to courses" is rewritten), `backend/app/schemas/`, `backend/app/common/` (new
dependencies, new import edge), `backend/app/services/` (access rules table, new services),
`backend/app/routers/` (endpoint access map + host router), `backend/app/websocket/` (host join
rule), `frontend/` (role table), `frontend/host/src/` + `pages/` + `lib/`, `frontend/admin/src/` +
`pages/` + `lib/`.

### 4.16 Files touched

Backend: `migrations/versions/004_course_specific_games.py` (new), `models/game.py`,
`models/course.py`, `schemas/admin.py`, `schemas/game.py`, `schemas/host.py` (new),
`common/dependencies.py`, `services/access_service.py` (new), `services/question_service.py`
(new), `services/game_service.py`, `services/roster_service.py`, `routers/host.py` (new),
`routers/admin.py`, `routers/game.py`, `main.py`, `websocket/gateway.py` [Extra] — all under
`backend/app/`. `scripts/t4_migration_report.py` (new) [Extra].

Host frontend (`frontend/host/src/`): `lib/api.ts`, `App.tsx`, `pages/HomePage.tsx`,
`pages/manage/GamesPage.tsx`, `pages/manage/QuestionEditorPage.tsx`,
`pages/manage/RosterPage.tsx`, `pages/manage/SessionsPage.tsx` (all new under `manage/`).

Admin frontend (`frontend/admin/src/`): `App.tsx`, `pages/AccessPage.tsx` (new),
`pages/GamesPage.tsx`, `pages/CoursesPage.tsx`, `pages/UserDetailPage.tsx`, `lib/api.ts` [Extra].

Tests: new files under `tests/integration/` (4.14). Context docs: 4.15.

---

## 5. Open questions

1. **Does the TA accept opt-in game grants as "granting course/game access"?** Expected yes (grants
   remain a real admin task). Being confirmed with the TA; if the answer is no, revisit §3's first
   two rows before implementation.

Resolved during design (recorded here so they are not reopened):

- **Games whose only sessions are LOBBY/ABANDONED/IN_PROGRESS** count as having no completed
  sessions: they fall through to the grant-holder rule and otherwise stay `NULL` (4.1 step 4).
- **`allow_guests` is admin-only.** Host toggling is an [Extra] (4.6).
- **All existing games are restricted by the migration** (4.1 step 5).

---

## Separate deliverable (not T4): admin rejoin becomes host

Branch `fix/admin-rejoin-becomes-host`, its own MR, independent of the T4 branch.

Bug: `websocket/gateway.py` `on_rejoin_room` computes
`is_host = user.id == session.host_user_id or user.role == "ADMIN"`. An admin who joined a room as
a **player** and reconnects (`rejoin_room`) is re-registered as HOST: they join the host room, can
advance the game, and stop being a player.

Fix (prose): infer the role from how the user is actually registered in this session. If the
user is the session's `host_user_id`, they are host. Otherwise, if they are in Redis
`session:{id}:players`, they are a player (re-run `authorise_player` as today). Otherwise, an
ADMIN may take the host role only by an explicit `join_room` with `role: "HOST"`, never by
inference. Test: admin joins as PLAYER, disconnects, `rejoin_room` → still PLAYER and
`host_advance` is rejected.

Note: the player app never sends `rejoin_room` (`frontend/player/src/pages/CLAUDE.md`), so this
is reachable only by other clients or scripts. Fix it anyway.
