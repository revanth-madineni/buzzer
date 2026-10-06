# backend/app/models/

## Purpose
SQLAlchemy 2.0 ORM models (typed `Mapped[...]` style) for every persistent table. All models
subclass `Base` from `app/database.py`. Schema changes go through Alembic in
`app/migrations/versions/` (currently 001–006), which is kept in step with these files.

## Contents
- `__init__.py` — Re-exports all models. Import order matters: FK targets are imported before
  the tables that reference them (User → Course → Image → Game → Session). The block is
  deliberately not alphabetical, so ruff's I001 on it is expected.
- `user.py` — `User`: UUID string PK, optional `netid` / `email` / `username` (all unique,
  nullable), `password_hash`, and a **global** `role` enum `ADMIN | USER | GUEST` (default `USER`).
- `course.py` — `Course` (name + semester, `allow_guests` bool default true, `games`
  relationship with no cascade), `CourseRoster` (imported student list keyed by
  `netid`, unique per course, `is_active` flag), and `UserCourseAccess` (composite PK
  `user_id, course_id` with a **per-course** `role` enum `HOST | PLAYER`).
- `game.py` — `Game` (title, description, `max_players` default 150, nullable `course_id` FK
  → `courses.id` with a `course` relationship, `restricted` bool default false), `Question` (ordered by
  `order_index`; `type` is a free-form string, `grading_type` is `ACCURACY | COMPLETENESS`,
  type-specific data lives in JSON `config` and `answer_data`), and `UserGameAccess` (composite
  PK `user_id, game_id`, no role column).
- `session.py` — `GameSession` (one hosted run of a game: UUID PK, unique 6-char `room_code`,
  `game_id`, `course_id`, nullable `host_user_id`, status `LOBBY | IN_PROGRESS | COMPLETED |
  ABANDONED`) and `SessionScore` (one row per scored answer: session, user, question,
  `points_awarded` float, `answer_time_ms`, `is_correct`, raw `answer_data` JSON).
- `image.py` (T7, migration 005; T8, migration 006) — `Image`: uploaded images for map-pin
  questions, question prompts and answer options.
  - `id` is a random `uuid4` string set in Python (IDs are unguessable because any logged-in
    user can read an image by ID).
  - `mime_type` (`image/png | image/jpeg | image/webp`, from the decoded format), `width`,
    `height`, `byte_size`, `sha256` (indexed, **not** unique; for future dedupe).
  - `data` is `MEDIUMBLOB` on MySQL (plain `BLOB` caps at 64 KB) and `deferred`, so metadata
    queries never load the bytes. Use `image_service.get_image_with_data` when you need them.
  - `uploaded_by_user_id` → `users.id` and `course_id` → `courses.id`, both nullable with
    `ON DELETE SET NULL`. No relationships are declared on `User` or `Course`, so there's no
    cascade. Since T8 `course_id` **is** an access rule: a non-admin may only add images of
    the game's course to a question, and the host Images endpoints check HOST on it.
  - `alt_text` (T8): `VARCHAR(250)`, default `''`, editable in place.

## How it fits in
The data layer under `services/` (business logic) and `routers/` (HTTP). `schemas/` holds the
Pydantic request/response shapes; they are separate from these ORM classes. The access tables
(`UserCourseAccess`, `UserGameAccess`) are read by `services/game_service.py`,
`routers/game.py`, and `routers/admin.py` — authorization logic lives there and in `common/`,
not here.

### How games relate to courses
Since migration 004 (T4, spec `docs/plans/t4-ui-restructure.md`), **a game belongs to at most
one course** through `Game.course_id`. `GameSession` still carries its own `course_id` as well:
- `Game.course_id` is the course the game is authored for. "Which games belong to course X" is
  `Game.course_id == X`. It is nullable: games the backfill could not place, and games created
  through the admin API without a course, stay unassigned until an admin assigns them or their
  first room attaches them.
- `GameSession.course_id` is the course the session was **played in**. It is never rewritten. A
  session created before 004, or before its game was moved, can have a different `course_id`
  from its game. Results and exports belong to the session's course.
- `Game.restricted` narrows access. When true, a host also needs a `UserGameAccess` grant on
  the game, on top of course `HOST`. Migration 004 set it true on every game that existed
  then. New games default to false.
- `Course.allow_guests` is a per-course switch for GUEST players (default true).
- Who may act in a course is still governed by `UserCourseAccess.role` (`HOST` / `PLAYER`).

The access rules that use these columns are not implemented here. They are specified in the
T4 spec, §4.3–§4.6. Until those land, `services/game_service.py` still authorizes hosts with
per-user `UserGameAccess` grants alone, and ignores `course_id`, `restricted` and
`allow_guests`.

### Two separate role systems
- `User.role` (global): `ADMIN | USER | GUEST`.
- `UserCourseAccess.role` (per course): `HOST | PLAYER`.
"Host" is **not** a global role — a `USER` is a host only relative to a course where they hold
`HOST` access. Don't conflate the two when checking permissions.

## Gotchas
- **Deletes can fail at the DB.** `GameSession.game_id`, `GameSession.course_id`,
  `SessionScore.user_id`, and `SessionScore.question_id` have no `ondelete` and the reverse
  relationships (`Game.sessions`, `Course.sessions`, `User.scores`, `Question.scores`) have no
  cascade. Deleting a game/course/user/question that has sessions or scores will raise an
  integrity error (or try to null a non-nullable FK) unless the caller cleans up first.
  Deleting a `GameSession` *does* cascade to its scores.
  `Game.course_id` also has no `ondelete` and `Course.games` no cascade, so a course with games
  cannot be deleted either (there is no course-delete endpoint).
- **Don't assume a game has a course.** `Game.course_id` is nullable, and don't treat
  `Game.course_id` and `GameSession.course_id` as interchangeable (see above).
- Migration 004's DDL is not transactional on MySQL. If it fails partway, see the recovery
  steps in the T4 spec §4.1.
- `SessionScore` has only a non-unique index on `(session_id, user_id)`; nothing at the DB
  level prevents two scores for the same user + question. Dedup must happen in code.
- `GameSession.host_user_id` is nullable — don't assume every session has a host user.
- `Question.type` is an unconstrained string (not an enum); valid values are defined by the
  question-type handling in `services/`, not here.
- **Image bytes are immutable.** map_pin questions copy the image's `width`/`height` into
  their `config` and store targets as fractions of the image, which is only safe because the
  bytes never change. "Replace" (T8) uploads a new row and re-points every question; only
  `alt_text` and `course_id` (re-tagged when a game moves) change in place.
- **No FK from questions to images.** Questions reference images inside JSON `config`
  (`imageId`, `promptImageId`, `optionImageIds`; T8), so the DB can't stop an image row from
  going missing. T8's delete scans `config` first (409 `IMAGE_IN_USE`), and export still
  returns 409 `EXPORT_IMAGE_MISSING` if a row is gone anyway.
- `CourseRoster` is keyed by `netid`, not by `users.id` — roster rows exist independently of
  `User` accounts and are not FKs to them.
- `game.py`'s `TYPE_CHECKING` block imports `UserGameAccess` from `.user`, but it is defined in
  `game.py` itself. Harmless at runtime (type-check only), but wrong if you follow it.
- `created_at` columns use `server_default=func.now()` — the value is only populated after a
  flush/refresh, not on the Python object at construction.
