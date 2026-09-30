# backend/app/schemas/

## Purpose
Pydantic v2 request/response models for the HTTP API. Input validation (lengths, regex
patterns, per-question-type structure) lives here; authorization does not. These are separate
from the ORM classes in `models/` — response schemas use `from_attributes=True` to read them.

## Contents
- `__init__.py` — Empty; import from the submodules directly.
- `admin.py` — Admin-panel shapes, used by `routers/admin.py`:
  - Courses: `CourseCreate`, `CourseUpdate`, `CourseResponse`.
  - Roster: `RosterEntryResponse`, `RosterUploadResult` (imported/updated/deactivated/errors),
    `RosterEntryPatch`, `RosterRowIn`, `RosterImportPayload`.
  - Games: `GameCreate`, `GameUpdate`, `GameResponse` (`max_players` 1–500, default 150).
    No `course_id` anywhere — consistent with games not belonging to courses (see
    `models/CLAUDE.md`).
  - Questions: `QuestionCreate` (with a `model_validator` enforcing per-type structure),
    `QuestionUpdate`, `QuestionResponse` (**includes `answer_data` and `grading_type`**),
    `QuestionReorder` (`order` = full list of question IDs in the new order).
  - Users: `UserCreate` (local account; username lowercased, `^[a-zA-Z0-9_-]+$`, password 8–72
    chars), `UserUpdate` (can set `role` to `USER | ADMIN`), `UserResponse`.
  - Access grants: `CourseAccessGrant` (`course_id` + role `HOST | PLAYER`), `GameAccessGrant`
    (`game_id` only), `UserWithAccessResponse` (user + `course_access: list[dict]` +
    `game_access: list[int]`).
  - `AdminSessionItem` — flattened session row for the admin sessions list (game title, course
    name/semester, host display name, player count).
- `auth.py` — `LoginRequest` (`username`+`password`, or `netid` as a dev-only fallback),
  `TokenResponse`, `TempTokenResponse` (`temp_token` + `needs_onboarding`), `RefreshResponse`,
  `GuestJoinRequest` (display name, email, 6-char room code).
- `game.py` — Host/player-facing shapes, used by `routers/game.py` and services:
  `QuestionPublic` (client-safe question — **omits `answer_data` and `grading_type`**),
  `RoomCreateRequest` (`game_id` + `course_id`, both > 0), `RoomCreateResponse`,
  `ActiveSessionItem`, `RoomInfoResponse`, `MyCourseItem` (role is always `HOST` for that
  endpoint), `MyGameItem`, and `ScoreResult` (internal return type of
  `services/game_service.calculate_score`, not an API response).

## How it fits in
Routers declare these as `body:` params and `response_model=`s. The split mirrors the router
split: `admin.py` ↔ `routers/admin.py`, `auth.py` ↔ `routers/auth.py`, `game.py` ↔
`routers/game.py` + `services/game_service.py`. Creating a room (`RoomCreateRequest`) is the
point where a game is paired with a course.

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
  checked, and `routers/admin.py` assigns fields straight onto the model. A PUT can change
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
- HTML sanitization of question prompts (`bleach`) happens in `routers/admin.py`, not here.
