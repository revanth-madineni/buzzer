# T8 — Image Support in Questions

Status: agreed design, goldfish-tested and revised (2026-10-06). Ready for implementation.
Written 2026-10-06.
Scope: T8 in `instructions.md` — images in question prompts, images as answer options, image
management (view, replace, delete) and alt text, across the backend and all three frontends.
Builds on the image storage that T7 delivered (`docs/plans/t7-map-pin.md`, §4.3 and §4.16).
The second T7 question type (the party type) is a separate spec; §4.17 says how it plugs in.

Architecture context lives in the CLAUDE.md hierarchy. Read `backend/app/CLAUDE.md`,
`backend/app/{models,schemas,services,routers,websocket,common}/CLAUDE.md`,
`frontend/CLAUDE.md` and each app's `src/CLAUDE.md` and `src/pages/CLAUDE.md` before
implementing.

---

## 1. Problem

T7 added image storage for map-pin questions only: an image can be uploaded and read by ID,
and nothing else. T8 requires that images:

- appear in a question **prompt** alongside text;
- serve as **answer options** (e.g. multiple choice where the choices are pictures);
- keep working on canvas questions (map pin, already done);
- can be **viewed, replaced and deleted** through the admin and host interfaces;
- hold up under realistic use: invalid input, repeated use, images shared between questions.

Image-only options also need **alt text**, or a screen-reader user can't tell them apart.

## 2. Technical plan (summary)

- **References stay in question `config` JSON**, as map pin's do. Two new optional keys:
  - `promptImageId` — one image shown with the prompt, allowed on **every** question type;
  - `optionImageIds` — for `multiple_choice` and `multi_select` only: a list the same length as
    `options`, each entry an image ID or `null`. Each option is **either** text **or** an
    image, never both, never neither. A question may mix text and image options, and the same
    image may appear in more than one option.
- **One function, `question_image_ids(type, config)`,** returns every image ID a question
  references (map pin's `imageId`, `promptImageId`, `optionImageIds`). Export, import, preload,
  the in-use check, usage lists and the report all go through it, so a new image key is added
  in one place.
- **One existence/scope check, `resolve_question_images`,** replaces `resolve_map_pin_image`
  and runs on create **and** update. It also enforces **course scoping**: a non-admin may only
  add images that belong to the game's course. Only image IDs **new** to the question are
  scope-checked, so an edit to a question in a game an admin later moved still saves.
- **Where images show.** The projector shows the prompt and phones show the options (that's
  already how Buzzer works), so:
  - prompt images: **projector only**;
  - option images: **phones** (image buttons in a grid), and thumbnails on every results surface
    (host results, game-over pages, player results and recap, HTML report, editor list).
- **Alt text** is a new editable `alt_text` column on `images` (migration 006). Phones receive
  the real alt text with the question; the editor warns authors not to name the answer in it.
- **Management:**
  - list images (admin: all, filterable by course; host: one course), each with where it's used;
  - edit alt text;
  - **delete**, refused with 409 `IMAGE_IN_USE` while any question references it;
  - **replace everywhere**: upload a new image and re-point every question that used the old
    one, in one transaction. Refused while an affected game is live, and for map-pin uses when
    the aspect ratio changes.
  - The editor keeps per-question "replace" (upload/choose another image for this question).
- **Images move with their game.** Moving a game to another course (or attaching a courseless
  game on its first room) re-tags images only that game uses, and copies images it shares with
  other games, so the new course's hosts can manage them (§4.7a).
- **Image bytes stay immutable.** Replace creates a new row; delete removes an unused one; only
  `alt_text` and `course_id` are ever updated in place, and neither affects geometry.
- **Concurrency:** a save takes a shared lock on each referenced image row; delete, replace and
  move take an exclusive one, so a save and a delete can't both pass their checks. One lock
  order everywhere (game → image → question rows); a MySQL deadlock that still slips through
  becomes 409 `CONFLICT` ("try again"), never a 500.
- **Export format stays version 2.** Images are collected through `question_image_ids`, and
  each bundle image may carry `alt_text`. Version-1 files import unchanged.

## 3. Alternatives considered

| Alternative | Why it lost |
|---|---|
| Change `options` from strings to objects `{text, imageId}` | Breaks every reader of `options` (scoring, four answer-reveal copies, both game frontends, both editors, the report, export) and existing version-1 game files, which must keep importing. A parallel `optionImageIds` list leaves every existing question valid and untouched. |
| Option = image **plus** text | Decided against: image-only options are what picture questions need, and alt text covers accessibility. |
| Prompt images on phones too | Phones never show the prompt today; showing only its image would be odd, and it would cost every phone a large download. The projector is where the prompt lives. |
| Alt text stored per use (in question `config`) | Doubles the parallel lists and makes authors re-type it for every reuse. Per image, it's written once. |
| Phones get a neutral label ("Option A, image") instead of the alt text | Guarantees no answer leak, but screen-reader users can't distinguish options during the question. Chosen instead: real alt text plus an editor warning; authors are teachers who can follow it. |
| Replace only per question in the editor | Simpler, but an image used in five questions needs five replacements, and the management page couldn't "replace" as T8 requires. Kept as a complement, not the only way. |
| Replace = overwrite the image's bytes | Map-pin targets are stored as fractions of the image; changing the bytes silently moves them (T7 §3). Images stay immutable. |
| Strict course scoping on every image of the question | A prompt-only edit would fail after an admin moves the game to another course, because the merged question is re-validated (T7 §4.5). Only newly added IDs are checked. |
| No course scoping (as in T7) | With a per-course picker hosts wouldn't stumble on other courses' images, but a hand-made PUT could still use them. Agreed to enforce it. |
| A real FK / join table `question_images` | Cleaner in-use checks, but every question write, import and the reveal code would have to maintain it, and the IDs already live in `config`. Classroom scale makes a scan fine (§4.6). |
| Images stay in the old course when a game moves | The new course's hosts couldn't see, replace or delete the moved game's images. Moving them (§4.7a) fixes that. |
| Move = re-tag every image of the game | Breaks a shared image for the other games that use it: their course's hosts would lose it from their picker and Images page. Shared images are copied instead. |
| Move = always copy | One code path, but every move leaves unused duplicates in the old course. Re-tag when exclusive, copy only when shared. |
| Auto-delete images when no longer used | Images can be shared and re-used later via the picker; deleting is an explicit action on the Images page. |
| Deduplicate uploads by `sha256` | Uploads are re-encoded, so the same file uploaded twice differs anyway (`services/CLAUDE.md`). The picker gives reuse instead. |

## 4. Detailed implementation

### 4.0 Conventions

- Errors use `BuzzerError(code, message, status)`; tests assert on `error` codes.
- Every write handler calls `await db.commit()` before returning (`docs/commit-race.md`).
- Every endpoint that writes a game or its questions calls `game_service.lock_game` +
  `assert_not_live` first (`routers/CLAUDE.md`, "Live games are locked").
- MySQL runs at REPEATABLE READ: once a transaction holds a lock, every read that decides the
  outcome must be a locking read (`services/CLAUDE.md`, "Locking reads after the game-row
  lock"). This applies to the in-use scans below.
- Lock order, everywhere: **game rows (ascending id) → image rows (ascending id) → question
  rows**.
  - A question save locks its game, then `FOR SHARE` on its images, and only then writes (or
    inserts) the question row. `update_question`'s existing re-read of the question row
    becomes `FOR SHARE` (`with_for_update(read=True)`), not `FOR UPDATE`: the game lock
    already serialises writers to the question, and a shared lock doesn't block delete's
    locking scan, which would otherwise deadlock against it.
  - Delete takes no game lock: image `FOR UPDATE`, then the question scan.
  - Replace and move lock games first, then images, then scan questions.
  - The locking question scan (§4.6) locks **question rows only**
    (`with_for_update(read=True, of=Question)`, i.e. `FOR SHARE OF questions`). Without `OF`,
    MySQL also share-locks the joined game rows, taking a game lock after an image lock.
- **Deadlocks become 409.** The order above removes the deadlocks found in review, but the
  locking scan is a full-table scan (next-key locks on every question row), so two concurrent
  replaces/moves can still deadlock each other. `register_exception_handlers` maps a MySQL
  deadlock (`OperationalError` / `DBAPIError` with errno 1213) to 409 `CONFLICT`
  `"The server was busy; please try again"`, and logs `db_deadlock`. MySQL has already rolled
  the transaction back, so nothing was written.
- "Image ID" means the stored UUID string. Import bundles may use any string up to 64 chars
  (e.g. `"map1"`), as T7 allows.
- New error codes:

| Code | Status | When | Message |
|---|---|---|---|
| `IMAGE_NOT_FOUND` | 422 | (exists) a question references an image that doesn't exist | `"Image {id} not found"` |
| `IMAGE_NOT_IN_COURSE` | 422 | a non-admin adds an image whose `course_id` isn't the game's course | `"Image {id} belongs to a different course"` |
| `IMAGE_IN_USE` | 409 | delete of an image any question references | `"Image is used by {n} question(s)"` (body also carries `usage`, §4.5) |
| `IMAGE_ASPECT_MISMATCH` | 422 | replace of an image used by a map-pin question with a different aspect ratio | `"The new image's shape differs from the old one, which would move map-pin targets"` |
| `GAME_LIVE` | 409 | (exists) replace touches a game being played | existing text |
| `CONFLICT` | 409 | replace found new uses appear while it waited for locks (§4.7) | `"Image usage changed; try again"` |
| `CONFLICT` | 409 | (new handler) any MySQL deadlock (see above) | `"The server was busy; please try again"` |

- **Extra fields in an error body.** `BuzzerError` gains an optional `extra: dict | None = None`,
  merged into the JSON body by `register_exception_handlers` (after `error` and `message`, never
  overriding them). New subclass `ImageInUseError(usage, hidden_usage_count)` → 409
  `IMAGE_IN_USE` with `extra = {"usage": [...], "hidden_usage_count": n}`. Every existing error
  is unchanged.

### 4.1 Migration `006_image_alt_text.py`

- `ALTER TABLE images ADD alt_text VARCHAR(250) NOT NULL DEFAULT ''`.
- Downgrade drops the column.
- Model `models/image.py`: `alt_text: Mapped[str] = mapped_column(String(250), nullable=False,
  server_default="")`. Not deferred.
- Update the model docstring: image **bytes and dimensions** are immutable. Only `alt_text`
  (descriptive) and `course_id` (ownership, re-tagged on game move, §4.7a) are updated in
  place; neither affects geometry.

### 4.2 Schemas — `backend/app/schemas/admin.py`

- `ALT_TEXT_MAX = 250`. Alt text is stripped of surrounding whitespace; empty is allowed.
- `ImageResponse` gains `alt_text: str`, `course_id: int | None`, `created_at: datetime`.
- New `ImageUsage`: `game_id: int`, `game_title: str`, `course_id: int | None`,
  `question_id: int`, `question_number: int` (1-based position in the game's questions ordered
  by `order_index, id`; **not** `order_index + 1`, which has gaps after deletes), `role:
  Literal["map", "prompt", "option"]` (one entry per question **and** role, so a question using
  an image as both prompt and option appears twice).
- New `ImageListItem(ImageResponse)`: `usage: list[ImageUsage]`, `hidden_usage_count: int`
  (uses in games the caller can't use; always 0 for admins; see §4.5).
- New `ImageAltUpdate`: `alt_text: str` (max 250), `extra="forbid"`.
- `QuestionResponse` gains `image_alt: dict[str, str]` — `{id: alt_text}` for every ID in
  `question_image_ids(type, config)` that exists (`{}` when none). The editors need it to show
  an option image's alt text and the empty-alt warning, including for images outside the
  picker's course. It isn't an ORM attribute, so `question_service` builds responses through
  a helper `question_responses(db, questions) -> list[QuestionResponse]` (one
  `get_images_meta` for all of them); the list, create and update handlers (admin and host)
  return its output.
- `GameMoveResult` gains `images_moved: int`, `images_copied: int` (§4.7a).
- **Question validation (`QuestionCreate.validate_structure`).** Shared helper
  `_validate_image_ref(value, key)`: a non-empty string of at most 64 chars (same rule as
  map pin's `imageId`).
  - **`promptImageId`** (all five types): optional; when present, `_validate_image_ref`.
    `null` is not allowed; to remove the image, omit the key.
  - **map_pin:** add `promptImageId` to the allowed `config` key set
    (`{"imageId", "imageWidth", "imageHeight", "promptImageId"}`). Nothing else about map pin
    changes.
  - **`optionImageIds`** (only `multiple_choice` and `multi_select`; present on any other type →
    error `"optionImageIds is only allowed on multiple_choice and multi_select"`):
    - must be a list with `len == len(options)`;
    - each entry `null` or `_validate_image_ref`;
    - the same ID may appear in several entries;
    - if **at least one** entry is an ID: every `options[i]` must be a string; where
      `optionImageIds[i]` is an ID, `options[i]` must be `""`; where it's `null`,
      `options[i].strip()` must be non-empty. Message: `"Option {i+1} must have either text or
      an image, not both"` / `"…not neither"`.
  - When `optionImageIds` is **absent or all `null`**, the existing option rules apply
    unchanged (no new checks on text-only questions; existing data with blank options stays
    editable). The editor omits an all-`null` list (§4.13), but the server treats one exactly
    like an absent key.

### 4.3 Image references — `backend/app/services/game_service.py`

Replace `game_image_ids` with:

- **`question_image_ids(type: str, config: dict) -> list[tuple[str, str]]`** — every
  `(image_id, role)` in the question, in a fixed order: map (`imageId`, map_pin only), prompt
  (`promptImageId`), options (`optionImageIds`, non-null entries, in option order). Ignores
  values that aren't non-empty strings (malformed rows never raise). **The one place** that
  knows which config keys hold images.
- **`game_image_ids(questions, audience: Literal["player", "host"]) -> list[str]`** — distinct
  IDs in question order. `"player"` excludes the `prompt` role (phones never show prompts);
  `"host"` includes everything.
- `get_game_image_ids(db, game_id, audience)` — same, loading the questions.

Callers updated:
- gateway `_player_image_ids` → `audience="player"`;
- gateway start branch (§4.8);
- export, import (§4.9), report (§4.12), usage scan (§4.6).

### 4.4 Question saving — `backend/app/services/question_service.py`

Replace `resolve_map_pin_image(db, body)` with
**`resolve_question_images(db, body, game, user, previous_ids)`**, called by `create_question`
(`previous_ids = set()`) and `update_question` (`previous_ids` = the IDs from the question's
current row, read after the existing re-read of the row, before the merge). That re-read
changes from `refresh(..., with_for_update=True)` to `with_for_update(read=True)` (§4.0, lock
order); it still uses `populate_existing` so it sees changes committed before the game lock.
In both paths, `resolve_question_images` runs **before** the question row is written or
inserted (flush), so image locks are taken before question-row write locks:

1. `ids = {id for id, _ in question_image_ids(body.type, body.config)}`; return if empty.
2. Load them with **`SELECT … WHERE id IN (…) ORDER BY id FOR SHARE`**
   (`with_for_update(read=True)`), metadata only. The shared lock blocks a concurrent delete or
   replace (which take `FOR UPDATE`) until this transaction commits.
3. Any ID missing → 422 `IMAGE_NOT_FOUND` (first missing ID in `question_image_ids` order).
4. If `user.role != "ADMIN"`: for each ID in `ids - previous_ids`, require
   `image.course_id == game.course_id` (both non-null), else 422 `IMAGE_NOT_IN_COURSE`.
5. map_pin: overwrite `config.imageWidth/imageHeight` from the stored image (as today).

Signatures change: `create_question(db, game, body, user)` and
`update_question(db, game, question, body, user)`. The four router call sites
(`routers/admin.py` create/update, `routers/host.py` create/update) pass the caller and the
game they already loaded.

### 4.5 Endpoints

All responses are `ImageResponse` / `ImageListItem` as in §4.2. Uploads keep their T7 behaviour
(re-encode, 2 MB per file, 30/min) and gain an optional `alt_text` form field (stripped, max
250, else 422 `VALIDATION_ERROR`).

| Endpoint | Guard | Behaviour |
|---|---|---|
| `GET /admin/images?course_id=&unassigned=` | `require_admin` | All images, newest first. `course_id` filters to one course; `unassigned=true` to `course_id IS NULL`; both → 422. Each with `usage` (all uses), `hidden_usage_count = 0`. |
| `PATCH /admin/images/{id}` | `require_admin` | Body `ImageAltUpdate`; sets `alt_text`. 404 if missing. |
| `DELETE /admin/images/{id}` | `require_admin` | §4.6. 204. |
| `POST /admin/images/{id}/replace` | `require_admin` | Multipart `file` + optional `alt_text`; §4.7. 201 with the **new** image. 30/min. |
| `GET /host/courses/{cid}/images` | `require_course_host` | Images with `course_id == cid`, newest first. `usage` lists only uses in games the caller `can_use_game`; the rest are counted in `hidden_usage_count`. |
| `PATCH /host/images/{id}` | `require_image_host` | As admin. |
| `DELETE /host/images/{id}` | `require_image_host` | §4.6. 204. A 409 lists only uses in games the caller `can_use_game` and counts the rest in `hidden_usage_count`, the same rule as the host list. |
| `POST /host/images/{id}/replace` | `require_image_host` | §4.7; additionally 403 `FORBIDDEN` if any use is in a game the caller can't use. |

- **`require_image_host(image_id)`** — new in `common/dependencies.py`, same shape as the T4
  dependencies: after `require_user`, load the image (404 `NOT_FOUND` for unknown/malformed),
  then non-admins need `has_course_host` on `image.course_id`; a `null` `course_id` → 403
  `FORBIDDEN`. Order: 401 → GUEST 403 → 404 → 403.
- **Body limits** (`main.py`): add `("POST", r"^/api/admin/images/[^/]+/replace$", 2.5 MB)` and
  `("POST", r"^/api/host/images/[^/]+/replace$", 2.5 MB)`. Without these the replace upload is
  only checked after Starlette has spooled the body (`common/CLAUDE.md`).
- `GET /api/images/{id}` is unchanged (bytes only). Alt text reaches clients via the payloads in
  §4.8 and the list endpoints.

### 4.6 Usage scan and delete — `backend/app/services/image_service.py`

- **`image_usage(db, image_ids: set[str], *, lock: bool) -> dict[str, list[ImageUsage]]`:**
  1. `SELECT questions.id, game_id, order_index, type, config, games.title, games.course_id
     FROM questions JOIN games … WHERE LOWER(CAST(config AS CHAR)) LIKE '%imageid%'`. All three
     keys contain `imageid` case-insensitively, so this pre-filter can't miss a reference. With
     `lock=True` the query is a locking read on **question rows only**
     (`with_for_update(read=True, of=Question)`; §4.0).
  2. For each row, `question_image_ids(type, config)`; keep pairs whose ID is in `image_ids`.
  3. `question_number`: one more (unlocked) query loads `id, game_id, order_index` for every
     question of the games found, and ranks them per game by `order_index, id`.
  The scan is O(questions with images); fine at classroom scale. If it ever isn't, a generated
  column or join table can replace the pre-filter without changing callers.
- **Delete (`delete_image(db, image)`)**, one transaction:
  1. Re-read the image `FOR UPDATE` (404 if it vanished).
  2. `image_usage(db, {id}, lock=True)`; non-empty → `ImageInUseError` (409 `IMAGE_IN_USE`,
     §4.0) with body `{"error", "message", "usage": [...], "hidden_usage_count": n}`. For an
     admin, `usage` is every use and `n = 0`; for a host, uses in games they can't
     `can_use_game` are left out of `usage` and counted in `n`. The message counts all uses.
  3. Delete the row, flush. The router commits.
  No live-game guard needed: an image in use can't be deleted, and an unused one isn't in any
  live game.
- Deleting a game or question never deletes images; they show up unused on the Images page.

### 4.7 Replace — `image_service.replace_image(db, old, raw, alt_text, user)`

1. `prepare_image(raw)` (validate + re-encode) **before** taking any lock. Failures are the
   usual upload errors.
2. Unlocked `image_usage(db, {old.id}, lock=False)` → the set of affected game IDs.
3. For each affected game, ascending id: `lock_game` + `assert_not_live` (409 `GAME_LIVE`).
4. Re-read `old` `FOR UPDATE`; re-run `image_usage(…, lock=True)`. If it now names a game not
   locked in step 3 → 409 `CONFLICT` ("try again"). Fewer uses is fine.
5. Host only: every use must be in a game the caller `can_use_game`, else 403 `FORBIDDEN`.
6. For each **map** use: compare aspect ratios; if
   `abs(new.w/new.h − old.w/old.h) / (old.w/old.h) > 0.01` → 422 `IMAGE_ASPECT_MISMATCH`.
7. Store the new image (`store_prepared`) with `course_id = old.course_id`, `uploaded_by =
   user`, `alt_text` = the form value if given, else `old.alt_text`.
8. For every use, rewrite the question's `config`: replace `old.id` with the new ID in that
   role's key — for `optionImageIds`, **every** matching entry (the same image may fill
   several options, but usage has one `option` entry per question); for map uses also set
   `imageWidth/imageHeight` from the new image. Assign a new dict (and a new list for
   `optionImageIds`) to `question.config` (don't mutate in place, or SQLAlchemy won't see the
   change). Flush.
9. Return the new image. The router commits. The old image is left in place, now unused.

Replace changes past reports too: reports read the current question (`services/CLAUDE.md`), so
an old session's report will show the new image. This is accepted; the Images page says so in
its confirm text (§4.13).

### 4.7a Images follow a game to its course — `image_service.rehome_game_images`

**`rehome_game_images(db, game, new_course_id, user, *, apply: bool) -> ImageRehome`**
(`moved: int`, `copied: int`). For each distinct image of the game
(`game_image_ids(questions, "host")`):
- already `course_id == new_course_id` → untouched, not counted;
- used **only** by this game's questions → **moved**: `course_id = new_course_id`;
- also used by any other game (`image_usage`) → **copied**: a new `Image` row with the same
  bytes, `mime_type`, `width`, `height`, `byte_size`, `sha256` and `alt_text`, a new UUID,
  `course_id = new_course_id`, `uploaded_by_user_id = user.id`. This game's questions are
  re-pointed to the copy (every role, every matching `optionImageIds` entry, new dicts as in
  §4.7 step 8). Map-pin dimensions are identical, so targets don't move and nothing else in
  `config` changes. The other games keep the original.

`apply=False` (preview) does unlocked reads and only counts. `apply=True`, with the game row
already locked by the caller:
1. Load the game's questions with a locking read (`FOR SHARE`, `populate_existing`; §4.0
   "Locking reads after the game-row lock").
2. Lock their images `FOR UPDATE`, ascending id (missing image → skip it; the question is
   already broken and this isn't the place to fix it).
3. `image_usage(ids, lock=True)` → uses outside this game.
4. Re-tag / copy (`get_image_with_data` for copies; flush only) as above.

Callers:
- **`POST /admin/games/{id}/move`.** `confirm=false`: preview counts in `GameMoveResult`
  (`images_moved`, `images_copied`), next to the existing `dropped_grants`. `confirm=true`:
  after the existing `lock_game` + `assert_not_live`, in the same transaction as the move. The
  counts in the result are the applied ones (they can differ from the preview if usage changed
  in between).
- **`game_service.create_room`, admin attaching a courseless game** (step 3 of "Room
  creation"): after the attach, `apply=True` with the room's course. The game row is already
  locked there. A later failure rolls the re-tag/copies back with the attach.
- Nothing else changes a game's course, so nothing else calls it.

`MoveGamePanel` (admin) shows the counts in its preview: "N image(s) will move to this course,
M shared image(s) will be copied." (omitted when both are 0).

Images that no question of the game references (unused uploads) stay where they are. The
`previous_ids` rule in §4.4 stays: it still covers images that were shared before a move,
data from before T8, and courseless images.

### 4.8 Socket payloads — `backend/app/websocket/gateway.py`

- **`_question_payload`** adds `imageAlt: {id: alt_text}` for every ID in
  `question_image_ids(q.type, q.config)`; omitted when the question has no images. It needs the
  images' metadata: load them once per question with `get_images_meta`. Make
  `_question_payload` async (it has three callers in the gateway; all are already inside a DB
  context). **Every** place that sends a question to a client must build it through
  `_question_payload`, including the host's `sync_state` restore of the current question;
  check each caller while making it async. Alt text is public by design (§3); the editor warns
  authors (§4.13).
- **Start branch:** emit `game_images` twice: `{imageIds: game_image_ids(questions, "player")}`
  to the room (as today), then `{imageIds: game_image_ids(questions, "host")}` to
  `{code}:host`. The host preloads both; `lib/images.ts` dedupes by ID.
- `_player_image_ids` uses `audience="player"`.
- **Game-over summaries** (`get_player_question_summary`, `get_host_question_summary`) already
  include `config`; add `imageAlt` the same way (one `get_images_meta` for all the session's
  image IDs).
- Answer handling, scoring and the four answer-reveal copies are **unchanged**: they work on
  indices, and option images don't change what an answer is.

### 4.9 Export / import — `backend/app/routers/admin.py`

- **Export:** collect images with `game_image_ids(questions, "host")` (every role). Each bundle
  entry gains `"alt_text"`. Missing image → 409 `EXPORT_IMAGE_MISSING` (unchanged). Version
  stays 2.
- **Import:**
  - `_bundle_images` reads optional `alt_text` per entry: a string of at most 250 chars, else
    422 `"Image {id} alt_text must be a string of at most 250 characters"`. Older v2 files
    without it import with `""`.
  - Every question's references (`question_image_ids`, all roles) must be in the bundle; else
    422 `"Question {n} references image {id} not in bundle"` (generalises the map-pin rule).
  - Only referenced images are prepared and stored (unchanged), tagged with the import's
    `course_id`, so they pass course scoping later.
  - Re-pointing rewrites every role's key from the old bundle ID to the new UUID; map uses also
    get dimensions (unchanged).
  - Version 1 may still not contain `images`; a v1 question with `promptImageId` or
    `optionImageIds` therefore fails with the "not in bundle" message.
- `QuestionCreate` runs on each imported question first, so the §4.2 rules apply to imports.

### 4.10 Shared frontend pieces (all three apps, byte-identical)

- **`src/components/AuthImage.tsx`** (new): `<AuthImage imageId alt className? />`. Uses
  `loadImage(imageId)` from `lib/images.ts` and renders an `<img src={img.src} alt={alt}>`
  (the cached blob URL). While loading: a `surface-alt` box with "Loading image…" (sr-only text
  plus a neutral placeholder). On failure: a `surface-alt` box with "Image unavailable" in
  `fg-muted`. Tokens only. `object-contain` so images are never cropped.
- **`src/components/ImagePicker.tsx`** (new, host and admin only, byte-identical): a panel used
  by the editors. Props: `listImages(): Promise<ImageListItem[]>`, `uploadImage(file, alt):
  Promise<ImageInfo>`, `onPick(image)`, `onCancel()`. Shows the course's images as a thumbnail
  grid (alt text below each, "No description" in `fg-muted` when empty), and an upload form
  (file + alt text, with the alt-text hint from §4.13). The editors pass the endpoint-specific
  functions, so the component itself stays identical.
- `scripts/check_theme.py`: add `(APPS, "src/components/AuthImage.tsx")` and
  `(("host", "admin"), "src/components/ImagePicker.tsx")` to `IDENTICAL_GROUPS`.
- `types/game.ts` (host and player): `QuestionPayload.config` gains `promptImageId?: string`
  and `optionImageIds?: (string | null)[]`; payloads gain `imageAlt?: Record<string, string>`
  (question payload and both game-over summary items).

### 4.11 Player app — `frontend/player/src/`

- **`pages/game/QuestionPage.tsx`**, multiple choice and multi-select: if any
  `optionImageIds[i]` is non-null, render options as a **2-column grid** of square buttons
  instead of the list. Each cell keeps its letter badge and existing colour / selected styling
  (T9 conventions in `pages/CLAUDE.md`). An image cell's **button** has an `aria-label` of
  `"Option {letter}: {alt}"` (or `"Option {letter}, image"` when alt is empty), with `alt =
  imageAlt[id] ?? ""`; the `<AuthImage>` inside it gets `alt=""`, so screen readers don't read
  the description twice. A text cell in the same grid shows its text. With no option images,
  the layout is unchanged.
- Prompt images are **not** shown on phones.
- `pages/game/ResultsPage.tsx`: "You answered" shows a thumbnail (`h-20`) for an image option.
  `pages/game/GameOverPage.tsx`: the recap shows a thumbnail next to ✓/✗ for image options.
- `GameLayout.tsx`: unchanged (it already preloads `imageIds`).

### 4.12 Host app and report

- **`pages/game/QuestionPage.tsx`:** under the prompt, when `promptImageId` is set, an
  `<AuthImage>` capped at `max-h-[45vh]`, centred. Hidden while locked, like the prompt.
- **`pages/game/ResultsPage.tsx`:** bar labels for image options show the letter plus a
  thumbnail (`h-16`) instead of text. Counts and "✓ Correct" stay beside the bar (T9 stage
  rules).
- **`pages/game/GameOverPage.tsx`:** the per-question breakdown shows thumbnails for image
  options (and a small prompt thumbnail when set).
- **`GameLayout.tsx`:** handles the second `game_images` (no code change; it already preloads
  whatever arrives).
- **HTML report (`services/report_service.py`):** generalise `_render_map_image_defs` to embed
  every image from `game_image_ids(questions, "host")` once. Prompt images render under the
  prompt (every type); image options render as thumbnails in the bar labels of
  **`multiple_choice`** questions; both via inline SVG `<use>` with a `<title>` carrying the
  alt text. Text options are unchanged.
  - **Multi-select in the report is out of scope.** `report_service` has no multi-select
    rendering at all (`services/CLAUDE.md`), and T8 doesn't add it. Its prompt image still
    renders. So that undrawn images aren't embedded, the report embeds the images it actually
    draws (map, prompt, and MC option images, in `question_image_ids` order, deduped) rather
    than all of `game_image_ids(questions, "host")`.

### 4.13 Editors and Images pages (admin and host)

**Both `QuestionEditorPage`s** (admin `pages/QuestionEditorPage.tsx`, host
`pages/manage/QuestionEditorPage.tsx`; make each change in both):
- `FormState` gains `promptImageId: string | null` and, per option, `imageId: string | null`.
  `questionToForm` / `formToPayload` map them to `config.promptImageId` (omitted when null) and
  `config.optionImageIds` (omitted when every entry is null; otherwise full length, with `""` as
  the option text where an image is set).
- Prompt: "Add image" / "Change" / "Remove" for every question type, opening `ImagePicker`.
- Options (MC, multi-select): each row has an "Image" button. With an image set, the text input
  is replaced by the thumbnail, its alt text and "Remove image". Reordering, adding or deleting
  options moves the image with its option. The same image may be picked for several options.
- **Alt text in the editor** comes from `QuestionResponse.image_alt` (§4.2) for saved
  questions, and from the picked `ImageInfo` when an image is chosen in the picker.
- **Multi-select's blank-option drop.** `formToPayload` currently drops multi-select options
  with blank text. An option **with an image counts as non-blank** and is kept, and whatever
  is dropped is removed from `options`, `optionImageIds` and `answer_points` together, so the
  three lists stay aligned. (The existing `points_value` derivation is unchanged.)
- Form errors (block save, before the request): **only when at least one option has an
  image**, every option must have text or an image. Questions without option images keep
  today's behaviour (MC keeps blank options, multi-select drops them).
- List line: `"N image options"` and `"prompt image"` badges.
- Pickers: admin lists `GET /admin/images?course_id={game.course_id}` (or `?unassigned=true` for
  a courseless game) and uploads to `POST /admin/images`; host lists `GET
  /host/courses/{cid}/images` and uploads to `POST /host/courses/{cid}/images`, where **`cid`
  is the game's own `course_id`** from `GET /host/games/{gameId}`, never the `:courseId` route
  param (that one is only for navigation and can differ from the game's course). The map-pin
  upload control gains the same picker, and its existing upload switches to the game's
  `course_id` the same way.
- **Alt-text hint** everywhere alt text is entered: *"Describe what's shown. Players' phones
  receive this text, so don't name the answer."* Empty alt text shows a non-blocking warning
  "No description — screen-reader users can't tell this image apart".

**Images pages** (new): admin `pages/ImagesPage.tsx` at `/images` (sidebar, "Host tools"
section, after Games); host `pages/manage/ImagesPage.tsx` at `/courses/:courseId/images`
(`HostLayout` link after Roster).
- Admin: course filter (All / each course / Unassigned). Host: the current course.
- Upload (file + alt text).
- Each image: thumbnail (click to view full size in an overlay), dimensions, size, upload date,
  alt text with inline edit (`PATCH`), and **Used by**: each use as "Game title — Q3 (option)",
  linking to that game's question editor, plus "+ N in games you can't access" when
  `hidden_usage_count > 0`.
- **Replace:** choose a file → confirm text "This will update N question(s) in M game(s) to use
  the new image. Past session reports will show the new image too." → `POST …/replace`. Shows
  the server's message on `GAME_LIVE` / `IMAGE_ASPECT_MISMATCH` / `CONFLICT`.
- **Delete:** disabled with "In use" while `usage` is non-empty or `hidden_usage_count > 0`;
  otherwise confirm → `DELETE`. A 409 `IMAGE_IN_USE` (raced) reloads the list and shows the
  message. Any 409 `CONFLICT` ("try again") is shown as-is.
- Theme tokens only; run `python scripts/check_theme.py`.

### 4.14 Integration tests (T5) — `tests/integration/test_images.py` (new)

Move `png()` / `upload()` from `test_map_pin.py` into `t4_helpers.py` and import them in both.
`T4World` records uploaded image IDs and deletes them in teardown, after games (T5's hint:
every creation path's cleanup).

- **Validation:** prompt image on each of the five types; `optionImageIds` length mismatch, an
  option with both text and image, with neither, on `true_false` → 422; unknown image → 422
  `IMAGE_NOT_FOUND`; same rules on PUT (merged validation). The same image in two options →
  201. An all-`null` list with a blank text option → 201 (treated as absent).
  `QuestionResponse.image_alt` carries the alt text on list/create/update.
- **Scoping:** host adds another course's image → 422 `IMAGE_NOT_IN_COURSE`; admin may; after an
  admin moves a game, a host's prompt-only edit of a question that keeps an old-course image
  succeeds.
- **List:** host sees only their course; `usage` roles correct (prompt + option on one question
  → two entries); `hidden_usage_count` for a use in a restricted game without a grant; admin
  `course_id` / `unassigned` filters; both filters → 422; GUEST 403; non-host 403.
- **Alt text:** upload with alt; PATCH; over 250 → 422; reaches `new_question.imageAlt` over the
  socket.
- **Delete:** unused → 204 and GET 404; in use (each role) → 409 `IMAGE_IN_USE` with `usage`
  and `hidden_usage_count`; a host's 409 for an image also used in a restricted game they have
  no grant on omits that use and counts it; host on another course's image → 403; null-course
  image → host 403, admin OK.
- **Usage numbering:** after deleting Q2 of three, the old Q3 is reported as
  `question_number` 2.
- **Replace:** re-points every use across two games and returns the new image; old image then
  deletable; live game → 409 `GAME_LIVE` and nothing changed; map use with different aspect →
  422 and nothing changed; same aspect → OK with new dimensions in config; host with a use in a
  game they can't use → 403; body over limit → 413; an image used in two options of one
  question → both entries re-pointed.
- **Move:** moving a game whose image no other game uses re-tags it (`course_id` = new course,
  same ID); an image shared with a game that stays behind is copied (new ID, new course, same
  `sha256` and dimensions), the moved game's questions point to the copy and the other game's
  don't change; preview counts (`confirm=false`) match and nothing is written; a host of the
  new course then sees both images in their list and can replace them. An admin's first room
  for a courseless game tags its null-course images with the room's course.
- **Concurrency:** HTTP can't hold one request's transaction open while another runs, so the
  locking can't be tested step by step. Instead, fire 20 concurrent pairs of "create a
  question using image X" and "delete image X" (fresh X per pair) and assert the end state:
  every pair ends with either the question created and the image kept, or the delete done and
  the create rejected with `IMAGE_NOT_FOUND`, or one side rejected with 409 `CONFLICT` and its
  change absent. Never a question pointing at a deleted image, and never a 500. Repeat with
  "edit a question that already uses X" instead of create (the case the `FOR SHARE` re-read
  in §4.4 exists for). Unit test: the exception handler maps a deadlock error to 409
  `CONFLICT`.
- **Socket:** players' `game_images` excludes prompt-only images; host's includes them;
  answers to image MC questions score as for text MC.
- **Export/import:** round trip of a game with prompt and option images and alt text; v2 file
  without `alt_text` imports; question referencing an image missing from the bundle → 422 and
  nothing created; v1 with `promptImageId` → 422.
- **Report:** the HTML report for a session with image options contains each image once.

Unit tests (`tests/unit/`): `question_image_ids` (all roles, malformed values ignored, order)
and the §4.2 validation rules.

### 4.15 Sample games (T6)

Not required by this spec, but at least one team member's game should use prompt and option
images. Bundle images go in the game JSON as base64 (version 2). Commit source images under
`sample_games/assets/`.

### 4.16 Context hierarchy updates

Update when the code lands: `backend/app/CLAUDE.md` (migration 006, image management),
`models/` (alt text and `course_id` now mutable; replace the "Images are immutable" gotcha),
`schemas/` (new keys and rules, `image_alt`, `GameMoveResult` counts), `services/`
(`question_image_ids`, `resolve_question_images`, usage/delete/replace/rehome, lock order,
`update_question`'s `FOR SHARE` re-read, `create_room` step 3), `routers/` (new endpoints,
access map, body limits, move counts), `common/` (`require_image_host`, new limits,
`BuzzerError.extra`, the deadlock → 409 handler), `websocket/` (`imageAlt`, two
`game_images`), `frontend/CLAUDE.md` (new byte-identical files), and each app's `pages/` and
`components/` files (admin `MoveGamePanel`).

### 4.17 How the party type plugs in

If the party question type uses images, it adds its config key(s) to `question_image_ids` and
gets export, import, preload, in-use checks, replace and the report for free. Its spec should
say which role (`map`, `prompt`, `option` or a new one) each key has.

### 4.18 Implementation order

1. Migration 006, model, schemas (`ImageResponse` fields, new shapes, question rules) + unit
   tests. `BuzzerError.extra` and the deadlock → 409 handler.
2. `question_image_ids` / `game_image_ids(audience)`; `resolve_question_images`, the
   `FOR SHARE` re-read in `update_question`, `question_responses` (`image_alt`) and the router
   call-site changes. Run the existing map-pin tests: nothing should change for map pin.
3. Usage scan, delete, replace, PATCH, list endpoints, `require_image_host`, body-limit rules;
   then `rehome_game_images` in move and `create_room`.
4. Gateway (`imageAlt`, two `game_images`), summaries, export/import, report.
5. Integration tests for 1–4.
6. Frontend: `AuthImage`, `ImagePicker`, `types/game.ts`, player pages, host game pages.
7. Editors, `MoveGamePanel`, then both Images pages. `check_theme.py`, `tsc --noEmit`,
   `npm run build`, manual
   check on a phone and a projector-sized window in both themes.
8. Context docs.

### 4.19 Files touched

Backend: `migrations/versions/006_image_alt_text.py` (new), `models/image.py`,
`schemas/admin.py`, `services/game_service.py`, `services/question_service.py`,
`services/image_service.py`, `services/report_service.py`, `routers/admin.py`,
`routers/host.py`, `common/dependencies.py`, `common/exceptions.py`, `main.py`,
`websocket/gateway.py`. (`services/game_service.py` also covers `create_room`.)

Frontend (each app unless stated): `src/components/AuthImage.tsx` (new, all three),
`src/components/ImagePicker.tsx` (new, host + admin), `src/types/game.ts` (host, player),
player `pages/game/{QuestionPage,ResultsPage,GameOverPage}.tsx`, host
`pages/game/{QuestionPage,ResultsPage,GameOverPage}.tsx`, both `QuestionEditorPage.tsx`, admin
`pages/ImagesPage.tsx` (new) + `App.tsx` + `components/MoveGamePanel.tsx`, host
`pages/manage/ImagesPage.tsx` (new) + `App.tsx`.

Other: `scripts/check_theme.py`, `tests/integration/{t4_helpers.py,test_map_pin.py,
test_images.py}`, `tests/unit/` (new tests), context `CLAUDE.md` files (§4.16).

## 5. Open questions

- **Image-option grid with many options.** Eight image options make a 2×4 grid of small cells
  on a phone. Acceptable, or cap image options per question (e.g. 6)? Currently no cap.
- **Report size.** The report embeds every image (up to 2 MB each). A game with many images
  could make a large file. Accept for now; revisit if it's a problem.
- **Picker and Images page download full images.** Thumbnails are the stored images (up to
  2 MB each) loaded through `loadImage`, so a course with 40 images costs a large download the
  first time the picker opens. Accept for now (staff desktops, cached afterwards); server-side
  thumbnails would be a separate change.

## Revision history

- 2026-10-06 — First version, from the design discussion.
- 2026-10-06 — Revised after the first goldfish test:
  - Lock order now covers question rows and the scan locks `OF questions`;
    `update_question`'s re-read is `FOR SHARE`; MySQL deadlocks map to 409 `CONFLICT`.
  - `BuzzerError.extra` / `ImageInUseError` so the 409 can carry `usage`; a host's 409 hides
    uses in games they can't use, like the list.
  - Multi-select's blank-option drop keeps image options and keeps the parallel lists
    aligned; the "text or image" form error applies only when some option has an image; an
    all-`null` `optionImageIds` is treated as absent.
  - `QuestionResponse.image_alt` for the editors; the host picker uses the game's
    `course_id`, not the route param.
  - New §4.7a: images move with their game (re-tag if exclusive, copy if shared), on admin
    move and on a courseless game's first room.
  - Decisions: the same image may fill several options (replace rewrites every entry);
    multi-select in the HTML report stays out of scope; `question_number` is the position,
    not `order_index + 1`; inner `<img alt="">` on phone option buttons; every question
    payload, including host `sync_state`, goes through `_question_payload`.
  - Image options apply to both `multiple_choice` and `multi_select` (both types exist).
    Status set to ready for implementation; no second goldfish test.
