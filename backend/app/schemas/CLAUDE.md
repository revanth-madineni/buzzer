# backend/app/schemas/

## Purpose
Pydantic v2 request/response models for the HTTP API. Input validation (lengths, regex
patterns, per-question-type structure) lives here; authorization does not. These are separate
from the ORM classes in `models/` — response schemas use `from_attributes=True` to read them.

## Contents
- `__init__.py` — Empty; import from the submodules directly.
- `admin.py` — Admin-panel shapes, used by `routers/admin.py`:
  - Courses: `CourseCreate`, `CourseUpdate`, `CourseResponse` (all carry `allow_guests`;
    create defaults it to true).
  - Roster: `RosterEntryResponse`, `RosterUploadResult` (imported/updated/deactivated/errors),
    `RosterEntryPatch`, `RosterRowIn`, `RosterImportPayload`.
  - Games: `GameFields` (title/description/max_players, unknown keys forbidden; also validates
    an import bundle's `game` block, so a bundle can't carry `course_id`), `GameCreate`
    (`GameFields` + optional `course_id`), `GameUpdate` (can set `restricted`, but **not**
    `course_id`), `GameResponse` (+ `course_id: int | None`, `restricted`); `max_players` 1–500,
    default 150. Moving a game between courses has its own shapes: `GameMoveRequest`
    (`course_id: int`, `confirm`) and `GameMoveResult` (`applied`, `game`, `dropped_grants`).
  - Questions: `QuestionCreate` (with a `model_validator` enforcing per-type structure),
    `QuestionUpdate`, `QuestionResponse` (**includes `answer_data` and `grading_type`**),
    `QuestionReorder` (`order` = full list of question IDs in the new order).
  - Users: `UserCreate` (local account; username lowercased, `^[a-zA-Z0-9_-]+$`, password 8–72
    chars), `UserUpdate` (can set `role` to `USER | ADMIN`), `UserResponse`.
  - Access grants: `CourseAccessGrant` (`course_id` + role `HOST | PLAYER`), `GameAccessGrant`
    (`game_id` only), `UserWithAccessResponse` (user + `course_access: list[dict]` +
    `game_access: list[int]`). Per-course and per-game access lists: `CourseAccessEntry` (role
    `HOST | PLAYER`) and `GameAccessEntry` (`has_course_host` flags grants that have no effect).
  - `AdminSessionItem` — flattened session row for the admin sessions list (game title, course
    name/semester, host display name, player count).
- `auth.py` — `LoginRequest` (`username`+`password`, or `netid` as a dev-only fallback),
  `TokenResponse`, `TempTokenResponse` (`temp_token` + `needs_onboarding`), `RefreshResponse`,
  `GuestJoinRequest` (display name, email, 6-char room code).
- `game.py` — Host/player-facing shapes, used by `routers/game.py` and services:
  `QuestionPublic` (client-safe question — **omits `answer_data` and `grading_type`**),
  `RoomCreateRequest` (`game_id` + `course_id`, both > 0), `RoomCreateResponse`,
  `ActiveSessionItem`, `RoomInfoResponse`, `MyCourseItem` (role is always `HOST` for that
  endpoint), `MyGameItem` (+ `course_id: int | None`, null only for admins; `restricted`),
  and `ScoreResult` (internal return type of
  `services/game_service.calculate_score`, not an API response).
- `host.py` — Shapes for the course-host router (`/api/host`, T4):
  - `HostGameCreate` (= `GameFields`) / `HostGameUpdate` — title, description, max_players only. Hosts can't set
    `course_id` (it comes from the URL) or `restricted`.
  - `HostGameListItem` — `GameResponse` + `question_count`.
  - `RosterUploadMode` — `Literal["add_update", "replace"]`.
  - `SessionListItem` — an alias of `AdminSessionItem`, not a copy.
  - Question shapes are reused from `admin.py`.

## How it fits in
Routers declare these as `body:` params and `response_model=`s. The split mirrors the router
split: `admin.py` ↔ `routers/admin.py`, `auth.py` ↔ `routers/auth.py`, `game.py` ↔
`routers/game.py` + `services/game_service.py`, `host.py` ↔ `routers/host.py`. A game has its
own `course_id` (see `models/CLAUDE.md`). `RoomCreateRequest` still takes a `course_id` too. The rule
that the two must match (T4 spec §4.4) is enforced in `services/`, not here.

### Question structure rules (`QuestionCreate.validate_structure`)
`type` ∈ `multiple_choice | true_false | fill_in_the_blank | multi_select`;
`grading_type` ∈ `ACCURACY | COMPLETENESS`.

| type | `config` | `answer_data` (ACCURACY only) |
|---|---|---|
| multiple_choice | `options`: list, ≥2 | `answer_points`: list, len = options, each ≥ 0 |
| true_false | not checked | `answer_points`: dict with exactly keys `"true"`, `"false"` |
| fill_in_the_blank | not checked | `acceptedAnswers`: non-empty list of non-blank strings; `answerPoints`: list, len = acceptedAnswers, each ≥ 0; optional `editDistance`: int ≥ 0 |
| multi_select | `options`: list, ≥2 | `answer_points`: list, len = options, numbers (**negatives allowed**) |

`COMPLETENESS` questions have no `answer_data` requirements.

## Gotchas
- **`QuestionUpdate` has no structural validation.** Only per-field patterns/ranges are
  checked, and `services/question_service.update_question` assigns non-null fields straight
  onto the model. A PUT can change
  `type`, `grading_type`, `config`, or `answer_data` independently and leave a question that
  `QuestionCreate` would reject. Bulk game import does run each question through
  `QuestionCreate`.
- **Answer leakage:** `QuestionResponse` (admin) exposes `answer_data`; anything sent to hosts'
  screens or players' phones must use `QuestionPublic` instead.
- **Key naming is inconsistent inside `answer_data`:** `answer_points` (snake_case) for
  MC/TF/multi-select vs `acceptedAnswers` / `answerPoints` / `editDistance` (camelCase) for
  fill-in-the-blank. Scoring in `services/game_service.py` reads these exact keys.
- `true_false` `answer_points` values are not type-checked (only the key set is).
- **Length mismatch with the DB:** `RosterRowIn.netid` and `RosterEntryPatch.netid` allow up to
  100 chars, but `course_rosters.netid` is `String(50)`.
- `RosterRowIn.email` is a plain `str`, while `RosterEntryPatch.email` is `EmailStr` — imports
  accept emails that a patch would reject.
- `UserUpdate.role` only allows `USER | ADMIN`; `GUEST` can't be assigned (or removed via
  this path). `UserCreate` has no role field — new local users get the model default `USER`.
- `LoginRequest`: if `netid` is present it wins over username/password. The "dev only" rule is
  **not** in the schema — `routers/auth.py` rejects it unless `settings.is_development`.
- `GuestJoinRequest` lacks `extra="forbid"` (unlike most input schemas) and doesn't normalize
  `room_code` case.
- `UserWithAccessResponse.course_access` is an untyped `list[dict]`; its shape is whatever
  `routers/admin.py` builds.
- HTML sanitization of question prompts (`bleach`) happens in
  `services/question_service.sanitize_prompt`, not here.
