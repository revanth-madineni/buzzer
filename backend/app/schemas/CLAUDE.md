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
    (`course_id: int`, `confirm`) and `GameMoveResult` (`applied`, `game`, `dropped_grants`,
    `images_moved`, `images_copied`; T8).
  - Questions: `QuestionCreate` (with a `model_validator` enforcing per-type structure),
    `QuestionUpdate`, `QuestionResponse` (**includes `answer_data` and `grading_type`**; T8
    adds `image_alt` `{id: alt_text}`, filled by `question_service.question_responses`),
    `QuestionReorder` (`order` = full list of question IDs in the new order).
    `QUESTION_TYPE_PATTERN` is shared by create and update, and `is_valid_number` (int or
    float, not `bool`, finite) is also used by `services/game_service`'s map-pin helpers.
  - Images (T7, T8): `ImageResponse` (`id`, `mime_type`, `width`, `height`, `byte_size`,
    `sha256`, `alt_text`, `course_id`, `created_at`; never the bytes), `ImageUsage` (one use:
    game, question, 1-based `question_number` = position, `role` `map | prompt | option`;
    one entry per question **and** role), `ImageListItem` (+ `usage`, `hidden_usage_count`),
    `ImageAltUpdate` (`alt_text` ≤ 250, stripped). `ALT_TEXT_MAX = 250`.
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
`type` ∈ `multiple_choice | true_false | fill_in_the_blank | multi_select | map_pin`;
`grading_type` ∈ `ACCURACY | COMPLETENESS`.

| type | `config` | `answer_data` (ACCURACY only, except map_pin) |
|---|---|---|
| multiple_choice | `options`: list, ≥2 | `answer_points`: list, len = options, each ≥ 0 |
| true_false | not checked | `answer_points`: dict with exactly keys `"true"`, `"false"` |
| fill_in_the_blank | not checked | `acceptedAnswers`: non-empty list of non-blank strings; `answerPoints`: list, len = acceptedAnswers, each ≥ 0; optional `editDistance`: int ≥ 0 |
| multi_select | `options`: list, ≥2 | `answer_points`: list, len = options, numbers (**negatives allowed**) |
| map_pin (T7) | exactly `imageId` (non-empty string ≤ 64; not required to be a UUID, so hand-made bundles can use `"map1"`) + optional `imageWidth`/`imageHeight` (positive ints, overwritten by the server) | **both grading types**: exactly `targets` (list of exactly 1 `{x, y}`, valid numbers in [0, 1]), `fullRadius` (≥ 0.02), `zeroRadius` (> fullRadius, ≤ 2). Radii are in image-width units. Unknown keys rejected everywhere. |

Other `COMPLETENESS` questions have no `answer_data` requirements. map_pin needs the target
under COMPLETENESS too, because both grading types show the same map reveal.

**Image keys (T8, `_validate_question_images`):**
- `promptImageId` — optional on **every** type (map_pin's allowed key set includes it); a
  non-empty string ≤ 64 (`null` not allowed; omit the key to remove the image).
- `optionImageIds` — `multiple_choice` and `multi_select` only: a list the same length as
  `options`, each entry `null` or an image ref; the same ID may repeat. If **any** entry is an
  ID, each option is either an image (`options[i] == ""`) or non-blank text, never both or
  neither. Absent or all-`null` → the old option rules, unchanged.

Whether images exist, and course scoping, are checked in
`services/question_service.resolve_question_images` (422 `IMAGE_NOT_FOUND` /
`IMAGE_NOT_IN_COURSE`), not here.

## Gotchas
- **`QuestionUpdate` is validated on the merged result (T7).** `QuestionUpdate` itself only
  checks per-field patterns, but `services/question_service.update_question` overlays the
  PUT's non-null fields on the existing question's seven content fields and runs
  `QuestionCreate` on the result (422 `VALIDATION_ERROR`). `config` and `answer_data` are
  replaced whole, not deep-merged. Consequence: a question that create would reject can't be
  PUT at all, even for a prompt-only change, until it's made valid. `order_index` stays out
  of the merge and is applied from the PUT as before.
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
