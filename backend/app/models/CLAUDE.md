# backend/app/models/

## Purpose
SQLAlchemy 2.0 ORM models (typed `Mapped[...]` style) for every persistent table. All models
subclass `Base` from `app/database.py`. Schema changes go through Alembic in
`app/migrations/versions/` (currently 001–003), which is kept in step with these files.

## Contents
- `__init__.py` — Re-exports all models. Import order matters: FK targets are imported before
  the tables that reference them (User → Course → Game → Session).
- `user.py` — `User`: UUID string PK, optional `netid` / `email` / `username` (all unique,
  nullable), `password_hash`, and a **global** `role` enum `ADMIN | USER | GUEST` (default `USER`).
- `course.py` — `Course` (name + semester), `CourseRoster` (imported student list keyed by
  `netid`, unique per course, `is_active` flag), and `UserCourseAccess` (composite PK
  `user_id, course_id` with a **per-course** `role` enum `HOST | PLAYER`).
- `game.py` — `Game` (title, description, `max_players` default 150), `Question` (ordered by
  `order_index`; `type` is a free-form string, `grading_type` is `ACCURACY | COMPLETENESS`,
  type-specific data lives in JSON `config` and `answer_data`), and `UserGameAccess` (composite
  PK `user_id, game_id`, no role column).
- `session.py` — `GameSession` (one hosted run of a game: UUID PK, unique 6-char `room_code`,
  `game_id`, `course_id`, nullable `host_user_id`, status `LOBBY | IN_PROGRESS | COMPLETED |
  ABANDONED`) and `SessionScore` (one row per scored answer: session, user, question,
  `points_awarded` float, `answer_time_ms`, `is_correct`, raw `answer_data` JSON).

## How it fits in
The data layer under `services/` (business logic) and `routers/` (HTTP). `schemas/` holds the
Pydantic request/response shapes; they are separate from these ORM classes. The access tables
(`UserCourseAccess`, `UserGameAccess`) are read by `services/game_service.py`,
`routers/game.py`, and `routers/admin.py` — authorization logic lives there and in `common/`,
not here.

### How games relate to courses
**There is no direct Game ↔ Course link.** `games` has no `course_id` and there is no
game–course join table. The only place the two meet is `GameSession`, which carries both
`game_id` and `course_id`: a course is chosen when a game is *run*, not when it is authored. So:
- A game is a reusable question bank that can be played in any course.
- Who may see/use a game is governed by `UserGameAccess` (per-user grants), independent of
  course membership.
- Who may act in a course is governed by `UserCourseAccess.role` (`HOST` / `PLAYER`).
- "Which games belong to course X" can only be answered via past sessions, or not at all.

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
- `SessionScore` has only a non-unique index on `(session_id, user_id)`; nothing at the DB
  level prevents two scores for the same user + question. Dedup must happen in code.
- `GameSession.host_user_id` is nullable — don't assume every session has a host user.
- `Question.type` is an unconstrained string (not an enum); valid values are defined by the
  question-type handling in `services/`, not here.
- `CourseRoster` is keyed by `netid`, not by `users.id` — roster rows exist independently of
  `User` accounts and are not FKs to them.
- `game.py`'s `TYPE_CHECKING` block imports `UserGameAccess` from `.user`, but it is defined in
  `game.py` itself. Harmless at runtime (type-check only), but wrong if you follow it.
- `created_at` columns use `server_default=func.now()` — the value is only populated after a
  flush/refresh, not on the Python object at construction.
