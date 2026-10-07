# backend/app/services/

## Purpose
Business logic behind the routers and the WebSocket gateway: auth/token handling, room and
session lifecycle, access checks for hosting and joining, answer scoring, Redis live-game
state, roster import, and post-game exports/reports. Functions take an `AsyncSession` (and
`Redis` where needed) and generally `flush()` rather than commit — the caller owns the
transaction, with the exceptions noted below.

## Contents
- `__init__.py` — Empty.
- `access_service.py` — **The one definition of the course-host rules** (T4):
  - Predicates: `has_course_host`, `has_game_grant`, `can_use_game`,
    `can_view_session_results`.
  - Raising forms: `assert_can_use_game`, `assert_can_view_session_results`. They raise
    `NotFoundError`, `ForbiddenError` or `GameRestrictedError` (403 `GAME_RESTRICTED`).
  - `usable_games_stmt(user, course_id=None)` — the same rule as one `SELECT`, for lists.
    `without_ungranted_restricted(stmt, user)` is its restricted/grant part on its own; the
    host sessions list uses it.
  - `grant_holders(db, game_id, course_id)` — grant holders, each with whether they HOST
    `course_id` (admin game-access list and move).
  - Used by `common/dependencies.py`, `game_service.py` and `routers/game.py`.
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
  - **Access checks:** `assert_host_can_use_course`, `assert_host_can_use_game` (thin wrappers
    over `access_service`, with no callers left in the app), `authorise_player` (see below).
  - Lifecycle:
    - `create_room` (see "Room creation" below) enforces max 50 concurrent LOBBY/IN_PROGRESS
      rooms and writes `GameSession` + Redis room state.
    - `get_session_by_code`, `start_game` (LOBBY → IN_PROGRESS, returns ordered questions;
      takes the game-row lock first, see "Live-game guard"), `complete_game`, `abandon_game`.
  - **Live-game guard:**
    - `lock_game` (`SELECT … FOR UPDATE` on the game row) and `is_game_live` (an IN_PROGRESS
      session whose `room:{code}` still exists; a stale row without the key is not live).
    - `assert_not_live` raises 409 `GAME_LIVE`.
    - Every guarded write locks, checks, then writes, and `start_game` takes the same lock, so
      an edit and a game start serialize.
  - Scoring: `calculate_score` (pure) and `record_answer` (score → insert `SessionScore` →
    update Redis score, answered set, and answer distribution).
  - **Map pin (T7).** The one home of all map-pin geometry; the gateway, summaries and report
    call these rather than re-deriving anything:
    - `map_pin_click(answer)` → `(x, y)` only for exactly `{x, y}` with valid numbers in
      [0, 1] (rejects `bool`, NaN, ±inf);
    - `map_pin_distance(aspect, target, click)` in image-width units (dy divided by
      width/height), `map_pin_fraction(d, full, zero)` (linear falloff);
    - `map_pin_bucket(x, y)` → `"bx,by"` on the 50×50 grid (`MAP_PIN_GRID`; x = 1.0 → 49);
    - `map_pin_reveal(grading_type, config, answer_data)`, the same reveal for both grading
      types;
    - `map_pin_stats(config, answer_data, answers)` → `withinFullPct` / `averageCredit` from
      geometry, `None` when no answer has a valid `{x, y}`;
  - **Slider (T7, spec `docs/plans/t7-slider.md`).** Pieces that need the question row or
    `map_pin_fraction` (which slider reuses as-is):
    - `slider_answer_index(config, answer)` → snapped index only for exactly `{"value": n}`
      in range;
    - `slider_reveal(grading_type, config, answer_data)` — the same reveal for both grading
      types, every key always present, `target` canonical;
    - `slider_stats(...)` → `withinFullPct` / `averageCredit` like `map_pin_stats`;
    - `slider_dist_key(config, answer)` → histogram bin key; `_score_slider`.
  - **Image references (T8).** `question_image_ids(type, config)` → every `(image_id, role)`
    (`map` = map_pin `imageId`, `prompt` = `promptImageId`, `option` = non-null
    `optionImageIds`), in that order; malformed values ignored. **The one place** that knows
    which config keys hold images. `repoint_config` rewrites every reference to one ID (new
    dict/list). `game_image_ids(questions, audience)` / `get_game_image_ids(db, game_id,
    audience)`: distinct IDs in question order; `"player"` leaves out prompt images (phones
    never show prompts), `"host"` includes all.
  - Summaries: `get_leaderboard` (MySQL sum per user_id), `get_player_question_summary`,
    `get_host_question_summary` (both include an `answerReveal` per question, and `imageAlt`
    for questions with images (T8); the host one adds `withinFullPct` / `averageCredit` for
    map_pin and slider).
- `slider_math.py` (T7) — **all slider geometry**, pure and import-free so `schemas/admin.py`
  can validate with it: `slider_geometry(config)` → `(min, max, step, N, D)` or None,
  `slider_index` (the one "in range" test: `k` within `[−EPS, N + EPS]`, snapped with
  `snap(k) = floor(k + 0.5)` — ties **up**, never Python's `round`), `slider_on_grid`,
  `slider_value` (canonical value, `int` when `D = 0`), `slider_bins` / `slider_bin`
  (`min(N + 1, 20)` bins, key `(k × B) // (N + 1)`), `slider_distance`, `slider_pct`, and
  `slider_target_line(reveal)` (the report's and host game-over's "Target: …" text).
  `frontend/*/src/lib/slider.ts` mirrors it formula for formula.
- `state_service.py` — Redis live state. Keys: `room:{code}` (JSON, 90-min TTL),
  `session:{id}:players` (set), `session:{id}:player:{uid}` (JSON incl. score, `is_connected`),
  `session:{id}:question` (current question + `started_at`), `session:{id}:answered:{qid}`
  (set), `session:{id}:dist:{qid}` (hash answer_key → count). Plus `restore_from_mysql`.
- `roster_service.py` — `process_roster_csv` (Canvas gradebook export: needs `Student` and
  `SIS Login ID` columns, skips the "Points Possible" row, netid = part before `@`, lowercased;
  stores only the **given name** as `full_name`) and `process_roster_rows` (pre-mapped rows from
  the admin column-mapping wizard). Both upsert by `(course_id, netid)` (reactivating listed
  inactive entries) and cap at 1000 rows. Both take `mode`:
  - `"replace"` (the default; all admin callers) also **deactivates every roster entry not in
    the upload**;
  - `"add_update"` (host default, T4) never deactivates.
  Deactivation lives in `_deactivate_missing`, which skips it when no row was valid.
- `image_service.py` (T7) — image validation, metadata stripping, storage. Pillow is imported
  as `PILImage`; bare `Image` is the ORM model.
  - `prepare_image(raw, *, force_reencode=True)` → `PreparedImage(data, mime, width, height,
    sha256)`. In order: 2 MB cap (413 `IMAGE_TOO_LARGE`); Pillow open (422 `INVALID_IMAGE`,
    which is where SVG/text land); format → mime, PNG/JPEG/WEBP only, MPO (multi-image phone
    JPEG) counts as JPEG (else 415 `UNSUPPORTED_IMAGE_TYPE`); animation rejected (415, not
    for MPO); dimensions checked **before decoding** (sides 1–8000, ≤ 40 MP, else 422); then
    re-encode if forced or if anything is outside the per-format metadata allowlist (JPEG APP
    segments + `info` keys, PNG `info` + text chunks, WebP **RIFF chunks**; trailing bytes after
    the image count as metadata; MPO always). Re-encoding applies EXIF orientation, keeps the
    ICC profile, PNG transparency and mode, and WebP lossless-ness (`VP8L`).
  - Invariant: its output is clean, so `prepare_image(out.data, force_reencode=False)` returns
    the same bytes. That's what makes export → import byte-identical; unit tests per format.
  - `store_image` (uploads: always re-encoded), `store_prepared` (import: prepared during
    validation, stored at insert; both take `alt_text`), `get_image` / `get_image_with_data`
    (malformed IDs → `None` without a query), `get_images_meta(ids)` (one `IN` query, no
    bytes). Flush only.
  - **Management (T8, spec `docs/plans/t8-images.md` §4.6–§4.7a):**
    - `image_usage(db, ids, *, lock)` → `ImageUsage` dicts per image. A `LIKE '%imageid%'`
      pre-filter on `CAST(config AS CHAR)` (can't miss: all three keys contain it), then
      `question_image_ids`; `question_number` is the position in the game. `lock=True` is
      `FOR SHARE OF questions` (question rows only, never the joined game rows).
      `visible_usage` splits uses into those in games the caller `can_use_game` and a hidden
      count. `list_images` builds the Images lists.
    - `lock_images(ids, read=)` — `FOR SHARE` / `FOR UPDATE`, ascending id.
    - `delete_image` — image `FOR UPDATE`, locking usage scan, 409 `IMAGE_IN_USE`
      (`ImageInUseError`) if used. No game lock.
    - `replace_image` — prepare first (no locks), unlocked scan → `lock_game` +
      `assert_not_live` for each affected game (ascending), image `FOR UPDATE`, locking scan
      (a new game → 409 `CONFLICT`), host: 403 if any use is in a game they can't use, map
      uses: 422 `IMAGE_ASPECT_MISMATCH` beyond 1 %, then a new row (same course; old alt
      text unless given) and every use re-pointed (map uses get new dimensions).
    - `rehome_game_images(game, course, user, apply=)` — images follow a game: exclusive →
      `course_id` re-tagged; shared with another game → copied (same bytes, new ID) and this
      game re-pointed. `apply=False` only counts (move preview). Called by the admin move
      and by `create_room`'s first-room attach.
- `question_service.py` — Question authoring shared by the admin router (and the host router,
  T4):
  - `sanitize_prompt` (`bleach`, tags `b i br u`, no attributes). **Every** prompt write goes
    through it, including game import.
  - `list_questions`, `create_question` (auto `order_index` = max + 1), `update_question`
    (T7: overlays the PUT on the existing question's content fields, re-reads the row
    `FOR UPDATE`, and validates the merged result with `QuestionCreate`, see
    `schemas/CLAUDE.md`).
  - `resolve_question_images(db, body, game, user, previous_ids)` (create and update, **not**
    import; T8): `FOR SHARE` on every referenced image (blocks a concurrent delete/replace),
    422 `IMAGE_NOT_FOUND`, then for non-admins 422 `IMAGE_NOT_IN_COURSE` unless each ID
    **new to the question** has `course_id == game.course_id`, then map_pin dimensions from
    the stored image, so scoring never needs a DB read. Runs before the question row is
    written. `question_responses(db, questions)` adds `image_alt` to `QuestionResponse`s.
  - `create_question(db, game, body, user)` / `update_question(db, game, question, body,
    user)` (T8 signatures). `update_question`'s re-read of the row is `FOR SHARE` (T8; the
    game lock already serialises writers, and a shared lock can't deadlock an image delete's
    scan).
  - `delete_question` (409 `QUESTION_HAS_ANSWERS` if any `SessionScore` references it), and
    `reorder_questions` (409 `CONFLICT` unless the IDs are exactly the game's question set).
  - Flush only. Every router write handler commits explicitly before it responds, because
    `get_db`'s own commit runs after the response is sent (`docs/commit-race.md`). Callers
    take the live-game guard first.
- `report_service.py` — `build_session_report` → standalone dark-theme HTML report with
  aggregate stats only (per-question distribution bar chart / word cloud, % correct, score
  histogram). No player names. Every image it **draws** (map, prompt, MC option; T7/T8) is
  embedded **once** as a data URI in a hidden SVG's `<defs>` (`id="img-{id}"`) and drawn by
  `<use>` with the alt text as `<title>`. slider: horizontal bars over the bins (value
  ranges, or just the end labels for a spectrum), the target's bin highlighted, then
  `slider_target_line`. map_pin: inline SVG + heatmap dots from
  `map_pin_bucket` + both circles + target, within-target % and average credit. Prompt
  images under the prompt; MC image options as bar-label thumbnails. Multi-select still
  isn't rendered (and its option images aren't embedded).
- `export_service.py` — `build_session_csv` (Player, Q1..Qn, Total) and `build_canvas_csv`
  (Canvas gradebook import format, SIS Login ID = netid [+ `@sis_domain`], optional
  per-question columns, `roster_only` flag).

## How it fits in
Called by `routers/` (admin, game, auth) and heavily by `websocket/gateway.py`, which drives
the in-game loop (start → question → answers → results → game over). MySQL (`models/`) is
the durable record; Redis (`state_service`) is the fast live-game view. Exceptions come from
`common/exceptions.py`.

### Access rules enforced here (the real authorization logic)
`common/`'s `require_user`/`require_admin` only check the global role. The course/game rules
live in `access_service.py` (hosting) and `game_service.authorise_player` (joining):

| check | ADMIN | USER | GUEST |
|---|---|---|---|
| `has_course_host` | always | `UserCourseAccess` role `HOST` on that course | effectively denied (no HOST row) |
| `can_use_game` (author/run) | always | game has a course, HOST on **`game.course_id`**, and, if `game.restricted`, a `UserGameAccess` grant | denied by `require_user` first |
| `can_view_session_results` | always | HOST on **`session.course_id`** and, if the game is restricted, a grant | denied by `require_user` first |
| `authorise_player` (join as player) | **any room** | active `CourseRoster` row matching `user.netid` **or** `UserCourseAccess` `PLAYER` **or** `HOST` for the session's course | **any room — no course check** |

- Course HOST is the main rule. A grant only matters on a restricted game, and a grant
  without HOST on the game's course does nothing.
- Results follow the course a session was **played in**, not the game's current course.

### Room creation (`create_room`, spec §4.4)
One transaction. `routers/game.py` commits it explicitly before responding, so the host's
socket `join_room` can't race the commit (see `docs/commit-race.md`):
1. The course must exist (404) **before** anything else, so a bad course never attaches a game.
2. The game row is loaded `SELECT … FOR UPDATE` (404 if missing). The lock serializes
   concurrent room creations for one game.
3. ADMIN: a courseless game is attached to this course (log `game_attached_on_first_room`).
   Non-admin: `assert_can_use_game` (courseless → 404, no HOST → 403 `FORBIDDEN`, restricted
   without a grant → 403 `GAME_RESTRICTED`).
4. A course different from `game.course_id` → 422 `COURSE_MISMATCH`, for admins too.
5. Then the existing room-limit check, room code, `GameSession` insert and Redis state. A later
   failure rolls back the attach along with everything else.

So every session created since T4 has `session.course_id == game.course_id`.
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
- `map_pin` (T7): `d` = aspect-corrected distance to `targets[0]`; points =
  `round(points_value × map_pin_fraction(d), 2)`; correct iff `d ≤ fullRadius`. A malformed
  question or answer scores 0 and logs `map_pin_bad_question` / `map_pin_bad_answer` instead
  of raising. Under COMPLETENESS the usual early return gives full points for any valid tap.
- `slider` (T7): `d = |k − kt| / N` in step indices; points =
  `round(points_value × map_pin_fraction(d), 2)`; correct iff `d ≤ fullRadius`. Bad data
  scores 0 and logs `slider_bad_question` / `slider_bad_answer`. `{value: 0}` is not empty.
Player answer keys: `selectedIndex`, `selectedValue`, `text`, `selectedIndices`, `x`/`y`,
`value`.
There is no speed bonus; scores are float sums.

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
- **`replace` uploads are full replacements.** Anyone absent is deactivated. When the 1000-row
  cap is hit, the loop `break`s but deactivation still runs, so students past row 1000 get
  deactivated.
- **Don't drop the `seen_netids` guard** in `_deactivate_missing`. An upload with zero valid rows
  (all rows errored, or only "Points Possible") returns 200 with `errors` and changes nothing
  *only* because of it. Without it, a `replace` upload would deactivate the whole roster. A T5
  test covers this (`tests/integration/test_host_management.py`).
- Roster matching compares `user.netid` (as received from the OAuth2 header, not lowercased)
  with lowercased roster netids. This relies on MySQL's case-insensitive default collation.
- **Image lock order (T8): game rows → image rows → question rows.** Saves: game, image
  `FOR SHARE`, then the question write. Delete: image `FOR UPDATE`, then the question scan.
  Replace/move: games, images, scan. The locking scan is a full-table `FOR SHARE OF
  questions`, so two concurrent replaces/moves can still deadlock; `common/exceptions.py`
  turns MySQL deadlocks (1213) into 409 `CONFLICT` "try again".
- **Locking reads after the game-row lock.** MySQL runs at `REPEATABLE READ`, where a plain
  `SELECT` sees the snapshot from the transaction's *first* read. Both a guarded edit and
  `start_game` have read before they take the lock. So once a transaction holds the lock, every
  read that decides the outcome must be a locking read (`with_for_update(read=True)` or
  `with_for_update()`, plus `populate_existing` for ORM objects already loaded). Otherwise it
  misses changes committed while it waited. This was checked against MySQL: after another
  transaction commits, the plain read still returns `LOBBY` while `FOR SHARE` returns
  `IN_PROGRESS`.
- `start_game` and `complete_game` **commit**; `abandon_game` only flushes. Keep this in mind
  when composing them with other writes.
- `create_room` counts rooms with `redis.keys("room:*")` plus a GET per key: O(N), blocking
  `KEYS`, and not atomic (two concurrent creates can both pass the 50-room limit).
  `delete_room_state` also uses `KEYS`.
- **Answer-reveal logic is duplicated** in 4 places: `get_player_question_summary`,
  `get_host_question_summary`, `report_service._answer_reveal`, and `websocket/gateway.py`
  `_answer_reveal`. `report_service` lacks `multi_select` entirely (no badge, chart, or reveal).
  map_pin avoids the drift: all four call `map_pin_reveal`, and each checks map_pin
  **before** the `COMPLETENESS` early return (so COMPLETENESS map-pin still gets the map).
  Slider does the same with `slider_reveal`.
- Distribution normalization differs: live Redis dist (`record_answer`) collapses internal
  whitespace for fill-in answers, while the host summary and report only `strip()`. map_pin
  uses `map_pin_bucket` in all three, so its counts agree.
- **Uploads re-encode; import usually doesn't.** A JPEG uploaded twice is stored as two
  slightly different re-encodes (different `sha256`), while a Buzzer export re-imports
  byte-for-byte.
- Reports and exports read the game's **current** questions, not a snapshot. Questions added
  after a session show as unanswered columns.
- `report_service` and `export_service` raise `ValueError` (not `NotFoundError`) for an unknown
  session; `report_service` embeds `q.prompt` as raw HTML, relying on the `bleach` sanitization
  done on write in `question_service.sanitize_prompt`.
- Canvas export: `roster_only=True` skips players **without a netid**. It does not check that
  the player is on the roster. The `Student` column uses the roster's given-name-only
  `full_name`.
- Without JWT key env vars, keys are regenerated on every restart (and per worker process), so
  all tokens are invalidated and multi-worker deployments can't verify each other's tokens.
