# T7 — Map Pin Question Type (classroom, canvas)

Status: agreed design, not yet goldfish-tested. Written 2026-10-04.
Scope: one of the two T7 types (the classroom one). The party type is a teammate's separate spec.
Also delivers the minimal image storage that T8 builds on.

Architecture context lives in the CLAUDE.md hierarchy. Read `backend/app/CLAUDE.md`,
`backend/app/{schemas,services,websocket,routers,models}/CLAUDE.md` and
`frontend/CLAUDE.md` before implementing.

---

## 1. Problem

Geography teachers quiz location by pointing, not naming: "where is Denver?" is answered by
putting a finger on the map. Buzzer's four question types can only ask that as multiple
choice, which tests recognition, not placement. We need a question where the player taps one
point on an image and is scored by how close they were, with partial credit that falls off
with distance, the way a teacher would grade "close, but not quite".

Buzzer also has no image storage today, so this type needs a minimal one.

## 2. Technical plan (summary)

- New question `type` **`map_pin`**. No change to the `questions` table: everything specific
  to the type lives in the existing `config` / `answer_data` JSON columns.
- `config` holds a reference to an image plus that image's pixel dimensions. `answer_data`
  holds the target as **fractions (0–1) of the image**, not lat/long, so any image works
  (maps, diagrams, photos).
- **Scoring:** distance is aspect-corrected into "image-width units". Full points within
  `fullRadius`, linear falloff to zero at `zeroRadius`. `is_correct` means "within
  `fullRadius`". A game's total is the existing per-question sum; nothing changes there.
- **Images:** new `images` table (migration 005). Images are **immutable**: never edited or
  replaced, and v1 has no delete. Upload is a multipart POST for admins and course HOSTs.
  On upload, images are rotated upright from their EXIF orientation and re-encoded with Pillow
  to **strip EXIF and other metadata**. The ICC colour profile is kept.
  Reading is a GET that any authenticated user (including GUEST players) can call by ID. IDs
  are random UUIDs and there is no list endpoint.
- **Import/export:** the bundle format moves to version 2 with a top-level `images` array
  (base64). Image IDs are remapped on import.
- **Player:** a canvas showing the image. Tap to place a pin, tap or drag to move it, then
  press **Confirm** to submit. Like every type, the phone doesn't show the prompt; the
  projector does.
- **Preloading:** the server sends the game's distinct map image IDs to players in the lobby
  (`sync_state.imageIds`) and again at game start (a new `game_images` event). Phones fetch
  them before the first question, so maps are usually cached by the time a question opens.
  The server timer stays authoritative, and answer time is measured the same way as for
  every other type.
- **Host:** during the question the projector shows the prompt (the city name) but **not** the
  map. On results it shows the map with a heatmap of taps grouped into a 50×50 grid, the
  target, and both radius circles.
- **Fixed alongside:** the question update path now re-validates the whole question, so a PUT
  can no longer produce a question that create would reject. This applies to all types.

## 3. Alternatives considered

| Alternative | Why it lost |
|---|---|
| Store target as lat/long and project | Ties the type to geographic maps with a known projection. Fractions work for any image (anatomy diagrams, circuit boards) and the author places the target on the same image the player sees, so projection is never needed. Cost: no "you were 340 km off" feedback. Accepted. |
| Raw fraction distance (no aspect correction) | A radius of 0.05 would be 5% of width horizontally but 5% of height vertically, so on a 1.6:1 map the "circle" becomes a tall ellipse and players get more slack north–south. |
| Polygon regions ("click Colorado") | Points only for v1. `answer_data.targets` is a list so another target kind can be added later without a migration. |
| Multiple accepted targets | Not in v1. The `targets` list must have exactly one entry. Kept as a list so v2 can allow several (best-of, like fill-in's `acceptedAnswers`). |
| Submit on first tap (like MC buttons) | A fingertip covers about 10% of a phone-width map, and answers can't be changed after submitting. Place → adjust → confirm costs one extra tap. |
| Auto-submit an unconfirmed pin at time-up | The server rejects answers once the question is locked, so a client-side auto-submit at zero races the lock and often ends in an `error` event. On the player app, an `error` ends the game view. Not doing it; the Confirm button is made obvious instead. |
| Pinch-zoom on the canvas | More client complexity. A minimum `fullRadius` and place+confirm handle touch precision for v1. |
| Image bytes inside `config` (base64) | `new_question` would send the image to every phone on every question, and question JSON would hold megabytes. |
| Images on disk / object store | T8 requires images to be stored in the database. |
| Replaceable images | Replacing a map with one that is cropped differently or has a new aspect ratio silently moves every stored target. Immutable images make that impossible. "Replace" in T8 = upload a new image and re-point questions. |
| Sequential integer image IDs | Players can read any image by ID, so integer IDs would let anyone enumerate every uploaded image. |
| Dedupe images by content hash | Saves space on repeated imports of the same sample game, but makes ownership and future delete rules harder to reason about. `sha256` is stored (indexed, not unique) so T8 can add dedupe later. |
| Exporting images as references to server IDs | Bundles would break on any other server and on a fresh DB, including T6 sample games. |
| Measure `answer_time_ms` from map load, or hold the phone's answer clock until the map has loaded | Treats map-pin timing differently from every other type, and it's still the client's number. Preloading attacks the actual problem (load time eating into the answer window) and keeps one timing rule. |
| Server computes `answer_time_ms` from `started_at` | Stronger, but it changes the field for every question type. Out of scope; a separate fix. |
| Fetch images only when the question arrives | The first download of a map (up to 2 MB on school Wi-Fi) would eat into the server's timer. Kept only as the fallback when the preload missed. |
| Store uploaded bytes unmodified | Any player can download an image, so a phone photo's GPS EXIF would leak to the class. Re-encoding costs some JPEG quality and is accepted. |
| Re-encode every image on import too | Every export → import cycle would degrade a JPEG again, and round-trips would stop being byte-identical. Import only re-encodes images that still carry metadata (§4.3). |
| Plain `<img src="/api/images/{id}">` | The apps send the access token as a `Bearer` header from `localStorage`. An `<img>` request carries no such header, and the refresh cookie is scoped to `/api/auth`, so it would 401. Clients fetch with the header and use a blob URL (§4.9). |

## 4. Detailed implementation

### 4.0 Conventions

- Errors use `BuzzerError(code, message, status)` from `common/exceptions.py`, so clients get
  `{"error": code, "message": ...}`. Pydantic failures keep the standard 422
  `VALIDATION_ERROR` shape.
- **Fractions:** `x` is left→right as a fraction of image width, `y` is top→bottom as a
  fraction of image height. Both are in `[0, 1]`.
- **Width units:** distance measured in fractions of image **width**. A radius of 0.05 means
  5% of the image's width, in every direction.
- A "valid number" anywhere in this spec means: JSON number, `int` or `float` but **not
  `bool`** (Python's `True` is an `int`), finite (not NaN or ±inf).

### 4.1 Migration `005_images.py`

New table `images`:

| column | type | notes |
|---|---|---|
| `id` | `String(36)` PK | `uuid4()` string, generated in Python |
| `mime_type` | `String(32)` NOT NULL | one of `image/png`, `image/jpeg`, `image/webp` |
| `width` | `Integer` NOT NULL | pixels, as decoded |
| `height` | `Integer` NOT NULL | pixels, as decoded |
| `byte_size` | `Integer` NOT NULL | length of `data` |
| `sha256` | `String(64)` NOT NULL, indexed (non-unique) | hex digest of `data` |
| `data` | `MEDIUMBLOB` NOT NULL | use `sqlalchemy.dialects.mysql.MEDIUMBLOB`. Plain `BLOB` caps at 64 KB. |
| `uploaded_by_user_id` | `String(36)` FK → `users.id`, NULL, `ondelete="SET NULL"` | audit only |
| `course_id` | `Integer` FK → `courses.id`, NULL, `ondelete="SET NULL"` | course it was uploaded for (host uploads always set it); not an access rule in v1 |
| `created_at` | `DateTime`, `server_default=func.now()` | |

No change to `questions`. Downgrade drops the table.

### 4.2 Model — `backend/app/models/image.py`

- `Image` with the columns above. Mark `data` as `deferred()` so metadata queries never load
  the bytes.
- Re-export from `models/__init__.py` after `User` and `Course`, because `images` has FKs to both.
- Add no relationships from `User` or `Course`, so there's no cascade to reason about.

### 4.3 Image service — `backend/app/services/image_service.py` (new)

**Dependency:** add `Pillow` to `backend/requirements.txt`.

`prepare_image(raw: bytes, *, force_reencode: bool = True) -> PreparedImage(data, mime, width, height, sha256)`:
1. `len(raw) > 2 * 1024 * 1024` → 413 `IMAGE_TOO_LARGE` (2 MB cap on the input bytes).
2. Open with Pillow, with `Image.MAX_IMAGE_PIXELS = 40_000_000` (decompression-bomb guard), and
   call `load()` so the whole image is decoded. Read `format`. Any exception → 422
   `INVALID_IMAGE`.
3. Map the format → mime: `PNG→image/png`, `JPEG→image/jpeg`, `WEBP→image/webp`. Anything else
   (including SVG and GIF) → 415 `UNSUPPORTED_IMAGE_TYPE`. **The mime comes from the decoded
   format, never from the client's declared Content-Type or file extension.** The output keeps
   the same format.
4. **Strip metadata:**
   - **Decide whether to re-encode.** `has_metadata` is true when the image carries EXIF,
     XMP, a JPEG comment, or PNG text chunks (`tEXt`/`zTXt`/`iTXt`) — that is, anything in
     Pillow's `info` / `getexif()` other than `icc_profile`, `dpi`, `transparency` and
     `gamma`. Re-encode when `force_reencode` is true or `has_metadata` is true. Otherwise
     keep `raw` as-is.
   - **Rotate first.** Apply `ImageOps.exif_transpose` **before** stripping, so phone photos
     stay upright. Rotation can swap width and height.
   - **Re-encode** without EXIF/XMP/comments/text chunks:
     - JPEG at `quality=90`;
     - PNG with `optimize=True`;
     - WebP lossless if the source was lossless, else `quality=90`.
   - **Keep the ICC profile** (`icc_profile=`) when present, along with PNG transparency and
     the image mode.
   - Animation is out of scope: animated WebP/PNG → 415 `UNSUPPORTED_IMAGE_TYPE`.
5. Width and height are read **after** rotation. `width` or `height` < 1 or > 8000 → 422
   `INVALID_IMAGE`.
6. The output bytes are capped again: > 2 MB after re-encoding → 413 `IMAGE_TOO_LARGE`.
7. Return the **output** bytes, mime, dimensions, and the sha256 hex of the output bytes.

Functions:
- `store_image(db, raw, user, course_id, *, force_reencode=True) -> Image`: `prepare_image`,
  insert the output bytes with a new `uuid4`, `flush()`. The caller owns the transaction.
  - Both upload endpoints use `force_reencode=True`, so every uploaded image is re-encoded.
  - Import uses `force_reencode=False` (§4.8), so images that are already clean (which every
    Buzzer export is) are stored byte-for-byte.
- `get_image(db, image_id) -> Image | None`:
  - Returns `None` for an ID that isn't a well-formed UUID string, without querying.
  - Loads `data` only when the caller asks for it, via an `undefer` option or a separate
    function `get_image_with_data`.
- `get_images_meta(db, ids: set[str]) -> dict[str, Image]`: one `SELECT ... WHERE id IN`, no
  `data`.

### 4.4 Endpoints

| method + path | router | auth | behaviour |
|---|---|---|---|
| `POST /api/admin/images` | `routers/admin.py` | `require_admin` | multipart `file` (required), `course_id` form field (optional; 404 if given and missing). → 201 `ImageResponse` |
| `POST /api/host/courses/{course_id}/images` | `routers/host.py` | `require_course_host` | multipart `file`. Stores `course_id` from the URL. → 201 `ImageResponse` |
| `GET /api/images/{image_id}` | `routers/images.py` (**new**, mounted under `/api` in `main.py`) | `get_current_user` (any role, **GUEST included**) | 404 `NOT_FOUND` for unknown or malformed IDs. 200 with the raw bytes. |

- **Both POSTs:**
  - Decorate with `@limiter.limit("30/minute")`.
  - Read at most 2 MB + 1 byte from the upload, so a huge upload is rejected without being
    buffered whole.
  - Call `image_service.store_image`. The request's `get_db` commits.
  - Image upload does **not** take the live-game guard, because it doesn't write a game or its
    questions.
- **GET response headers:**
  - `Content-Type: <stored mime>`
  - `Cache-Control: private, max-age=31536000, immutable` (safe because images never change)
  - `X-Content-Type-Options: nosniff`
  - `Content-Disposition: inline`
- **No list, update, or delete endpoints in v1.** T8 adds them (see §4.16).

Schema `ImageResponse` (in `schemas/admin.py`, reused by host): `id`, `mime_type`, `width`,
`height`, `byte_size`. Never the data.

**Access decision:** the GET has no course check. Anyone who knows an ID can read the image.
Security comes from IDs being unguessable UUIDs and from having no listing. This is acceptable
because the image is shown to every player of the question anyway. Question authoring checks
only that the image **exists**, not which course uploaded it (§4.5).

### 4.5 Question schema and validation — `backend/app/schemas/admin.py`

Add `map_pin` to the `type` pattern in **`QuestionCreate` and `QuestionUpdate`**.

Add a `map_pin` branch in `QuestionCreate.validate_structure`. Unknown keys are rejected in
both objects.

**`config`** (checked for **both** grading types):
- `imageId`: str, required. It must be a UUID-shaped string; checking that the image exists
  happens in the service.
- `imageWidth`, `imageHeight`: optional on input. The server always overwrites them (below).
- Nothing else.

**`answer_data`:**
- **ACCURACY:** required.
  - `targets`: a list of **exactly 1** object `{x, y}`. `x` and `y` are valid numbers in
    `[0, 1]`, with no other keys.
  - `fullRadius`: a valid number, `0.02 ≤ fullRadius`.
  - `zeroRadius`: a valid number, `fullRadius < zeroRadius ≤ 2`.
- **COMPLETENESS:** either `{}` or exactly the ACCURACY shape. If the target is present, it is
  revealed on the results screen; scoring ignores it.

The 0.02 floor is a hard guard against targets that can't be hit on a phone. The editor
defaults (0.04 / 0.15) are higher (§4.11).

**Service side** (`services/question_service.py`), in a new helper `resolve_map_pin_image(db, data)`:
- It is called from `create_question`, `update_question` and the import path.
- For `type == "map_pin"`, it loads the image metadata, raises 422 `IMAGE_NOT_FOUND` if the
  image doesn't exist, and **overwrites** `config.imageWidth` / `imageHeight` with the stored
  dimensions.
- Images are immutable, so these copied dimensions can never go stale. Scoring therefore never
  needs a DB read.

**Update-path fix (all types).** Today `update_question` copies non-null fields onto the model
with no structural check (`schemas/CLAUDE.md` gotcha). New behaviour:
1. Build `merged` = the existing question's `type`, `grading_type`, `prompt`, `config`,
   `answer_data`, `time_limit_seconds` and `points_value`, overlaid with the PUT's non-null
   fields. `config` and `answer_data` are **replaced** whole, not deep-merged.
2. Run `QuestionCreate.model_validate(merged)`. A failure raises the standard 422
   `VALIDATION_ERROR`.
3. Run `resolve_map_pin_image`, then sanitize the prompt, then apply the changes.

Known consequence: an existing question that create would already reject can no longer be
PUT, even for a prompt-only change, until it is made valid. That is intended. The 422 message
says what's wrong.

Both the admin and host question routers go through `question_service`, so both get this
behaviour with no router changes.

### 4.6 Scoring — `backend/app/services/game_service.py`

Add a pure helper and use it everywhere map-pin geometry is needed:

```
map_pin_distance(config, target, click):
    aspect = config.imageWidth / config.imageHeight
    dx = click.x - target.x
    dy = (click.y - target.y) / aspect        # height fractions → width units
    return sqrt(dx² + dy²)

map_pin_fraction(d, fullRadius, zeroRadius):
    if d <= fullRadius: return 1
    if d >= zeroRadius: return 0
    return 1 - (d - fullRadius) / (zeroRadius - fullRadius)
```

Branch in `calculate_score`. The existing empty-answer and `COMPLETENESS` early returns stay
first and unchanged:

```
map_pin (ACCURACY):
    click = answer_data {x, y}       # already validated by the gateway (§4.7)
    target = question.answer_data.targets[0]
    d = map_pin_distance(question.config, target, click)
    frac = map_pin_fraction(d, fullRadius, zeroRadius)
    points = round(question.points_value * frac, 2)
    is_correct = (d <= fullRadius)
```

`calculate_score` also stays defensive on its own: a missing or invalid `x`/`y` returns
`ScoreResult(0, False)` rather than raising, because it is also reachable from tests and
future callers.

**Distribution bucket** (a single helper, `map_pin_bucket(x, y) -> str`):
`bx = min(49, floor(x * 50))`, `by = min(49, floor(y * 50))`, key `"bx,by"`. Use it in:
- `record_answer`, which adds one `increment_answer_dist` per answer;
- `get_host_question_summary`, which rebuilds the distribution from `SessionScore.answer_data`;
- `report_service`.
It must be the same helper in all three, or the counts will drift (the existing fill-in
whitespace normalization already shows this happening).

**Reveal.** Add one helper `map_pin_reveal(q) -> dict`:
```
{ "type": "map_pin", "imageId", "imageWidth", "imageHeight",
  "target": {x, y} | null, "fullRadius" | null, "zeroRadius" | null }
```
For COMPLETENESS, `_answer_reveal` still returns `{"type": "completeness"}` first. The host and
player results views therefore have no image for a COMPLETENESS map-pin question, which is
acceptable for v1.

All four reveal copies call this helper for `map_pin`:
- `get_player_question_summary`
- `get_host_question_summary`
- `report_service._answer_reveal`
- `websocket/gateway._answer_reveal`

Don't fold the other types into the helper in this work.

The host summary for map_pin also returns:
- `withinFullPct`: share of answers with `is_correct`;
- `averageCredit`: mean of `points_awarded / points_value`, or null when `points_value == 0`.

### 4.7 Socket gateway — `backend/app/websocket/gateway.py`

- **Preloading image IDs.** New helper `game_service.game_image_ids(questions) -> list[str]`:
  the distinct `config.imageId` values of the `map_pin` questions, in question order.
  - **`sync_state`** to a joining **player** (`join_room` and `rejoin_room`) gains `imageIds`
    when the session is LOBBY or IN_PROGRESS. Load the game's questions for this. In LOBBY the
    list can go stale, because questions can still be edited until the game starts.
  - **New event `game_images`** (constant in `events.py`, payload `{imageIds: [...]}`) is
    emitted to the whole `{ROOM_CODE}` room in the start branch of `host_advance`. It goes
    out right after `start_game` returns the ordered questions and **before** the first
    `new_question`. Edits are locked once the game is IN_PROGRESS, so this list is final.
  - Image IDs are already public through `config`, so this leaks nothing about answers.
  - The host gets `game_images` too (it's in the room) and may preload for its results
    screen.
- **`_question_payload`:** no change needed. `config` (`imageId` + dimensions) is public by
  design, and the target lives in `answer_data`, which is never sent. **Invariant: nothing
  secret may ever be put in `config`.** Add a comment at the `config` line saying so.
- **`on_submit_answer`:** add a `map_pin` payload check next to the existing `multi_select`
  one. `answer_data` must have exactly the keys `x` and `y`, both valid numbers in `[0, 1]`.
  Otherwise emit `error` ("map_pin answer must include x and y between 0 and 1") and don't
  score. The client clamps and validates before sending (§4.10), so this error should only
  ever reach a tampered client.
- `answer_time_ms` stays client-supplied (existing gotcha, unchanged).

### 4.8 Import / export — `backend/app/routers/admin.py`

Bump `_SUPPORTED_IMPORT_VERSION` handling:
- **Export** always writes `"version": 2`. It adds `"images": [{"id", "mime_type", "data"}]`,
  where `data` is standard base64. The list holds each distinct `config.imageId` used by the
  game's `map_pin` questions, each exactly once. Questions keep their source `imageId`.
  - If an image row is missing, return 409 `EXPORT_IMAGE_MISSING`. This shouldn't be possible
    while v1 has no delete.
  - `imageWidth`/`imageHeight` are exported but ignored on import (they are recomputed).
- **Import** accepts version `1` or `2`. Anything else keeps the existing 422.
  - **Before reading:** reject files over 25 MB (422).
  - **Before any insert:**
    1. **Images.** v1 bundles may not contain `images`. In v2 it is optional and holds at most
       50 entries. Each entry needs a unique `id` (string) and base64 `data`. Decode it and run
       `image_service.prepare_image` (§4.3). Failures map to 422 with the existing
       string-detail format: `"Image {id} invalid: ..."`.
    2. **Questions.** Run `QuestionCreate` on each question, as today.
    3. **References.** Every `map_pin` question's `config.imageId` must be one of the bundle's
       image `id`s. Otherwise 422 `"Question {n} references image {id} not in bundle"`.
       References to images already on the server are **not** allowed. That keeps bundles
       self-contained.
    Step 1 runs `image_service.prepare_image(..., force_reencode=False)`. Hand-made bundles
    that carry EXIF are still cleaned, while bundles exported from Buzzer (already clean)
    round-trip with identical bytes and no extra JPEG generation loss. Keep the prepared
    output for the insert; don't decode twice.
  - **Insert**, in the same transaction as the game:
    1. Store only the bundle images that are actually referenced, each with a **new** UUID.
       Build a map from old ID to new ID.
    2. Rewrite each question's `config.imageId` through that map.
    3. Set `imageWidth`/`imageHeight` from the decoded dimensions.
    4. Insert the questions.
    The existing single `commit()` at the end covers everything, so a failure leaves neither
    images nor questions behind.
  - `uploaded_by_user_id` on imported images is the importing admin, and `course_id` is the
    form's `course_id`.

Hosts still have no import/export (unchanged).

### 4.9 Frontend shared rules (all three apps)

The apps share no code (`frontend/CLAUDE.md`), so each app that needs it gets its own copy of
two small pieces. They have to behave the same everywhere.

- **`lib/mapPin.ts`** (player, host, admin): fraction ↔ canvas mapping and the distance
  formula from §4.6. Unit-test the mapping in at least one app if a test runner is available.
  If not, record it in the context docs as untested.
  - **Contain-fit:** compute the drawn image rectangle inside the canvas
    (`offsetX, offsetY, drawW, drawH`, preserving aspect ratio).
  - **Pointer → fraction:**
    - `fx = (clientX - rect.left - offsetX) / drawW`, and the same for `fy`, where `rect` is
      `canvas.getBoundingClientRect()`.
    - Taps outside `[0, 1]` (the letterbox area) are **ignored**, not clamped.
    - Values sent to the server are clamped to `[0, 1]` anyway, as a guard against rounding.
  - **Backing store:** the canvas is CSS-sized to its container. Its backing store is
    `cssSize × devicePixelRatio`, and drawing is scaled accordingly.
  - **Resize:** on `resize` / `orientationchange`, recompute and redraw. Pins are stored as
    fractions, so they survive.
- **`lib/images.ts`** (player, host, admin): `loadImage(imageId) → Promise<HTMLImageElement>`.
  1. `fetch('/api/images/{id}')` with the Bearer header, using the app's existing `api` auth
     handling.
  2. → `blob` → `URL.createObjectURL` → an `Image` that resolves on load.
  3. Keep a module-level cache keyed by `imageId`. It caches the **promise**, so a preload
     and a question render asking for the same ID share one request. Images are immutable,
     so the same map reused across questions is downloaded once per page load.
  4. A failed load is evicted from the cache, so a later call retries.
  5. Never revoke cached URLs during a game.
  6. `preloadImages(ids: string[])` calls `loadImage` for each ID and swallows errors. It is
     fire-and-forget.
  The player `api.ts` is the older wrapper (`player/src/CLAUDE.md`). Add the blob fetch beside
  it rather than changing its JSON behaviour.

### 4.10 Player app — `frontend/player/src/`

- **`types/game.ts`:**
  - add `'map_pin'` to the question type union;
  - add `MapPinConfig { imageId; imageWidth; imageHeight }`;
  - add `MapPinReveal` (§4.6 shape);
  - answer payload `{ x: number; y: number }`.
- **`components/MapPinCanvas.tsx`** (new). Props: `imageId`, `disabled`, `pin`,
  `onPinChange`, and optional `reveal` and `myPin` for results.
  - **Interactive mode:**
    - Pointer events, with `touch-action: none` on the canvas only.
    - A tap places the pin, and a later tap or drag moves it.
    - The pin is drawn as a marker whose **tip** sits at the point.
  - **Reveal mode:** draws the player's pin, the target dot, and the `fullRadius` and
    `zeroRadius` circles. A radius in width units `r` becomes `r × drawW` pixels.
  - **Loading:** while the image is loading (a preload miss), show "Loading map…". The
    `TimerBar` keeps running; the server's timer is authoritative.
- **`pages/game/GameLayout.tsx`:** call `preloadImages` with `imageIds` from `sync_state`, and
  again on the new `game_images` event. Add `imageIds?: string[]` to `SyncStatePayload` and
  a `GameImagesPayload` type.
- **`pages/game/QuestionPage.tsx`:** a `map_pin` branch with `TimerBar` (same `key` / `paused`
  props as the other branches), `MapPinCanvas`, and a **Confirm** button.
  - Confirm is enabled when a pin exists, the image has loaded, the question isn't locked, and
    nothing has been submitted yet. It calls `emitAnswer(questionId, {x, y}, msSinceMount)`.
  - `answer_time_ms` is measured from mount, the same as every other type.
  - No auto-submit at time-up (§3).
- **`pages/game/ResultsPage.tsx`:** for `map_pin`, `MapPinCanvas` in reveal mode with the
  player's own submitted pin, which is already in local state from submit, plus points.
  - Show "Within target" / "Partial credit" / "Too far" from points vs. `pointsValue`: equal,
    between, or 0.
  - For a COMPLETENESS reveal, show only "Answer recorded".
- **`pages/game/GameOverPage.tsx`:** the recap line for `map_pin` shows the credit percentage.
  No image.

### 4.11 Host app — `frontend/host/src/`

- **`types/game.ts`:** same additions as the player app (no `imageIds` on the host's
  `sync_state`; the host only gets `game_images`).
- **`pages/game/GameLayout.tsx`:** on `game_images`, call `preloadImages` so the results
  heatmap draws without a wait.
- **`pages/game/QuestionPage.tsx`:** add `typeLabel` "Map Pin". Show the prompt as usual.
  **Do not render the map.** The projector shows the city name, and the phones show the map.
- **`components/MapPinHeatmap.tsx`** (new): draws the image (via `lib/images.ts`) and, for each
  distribution key `"bx,by"`, a translucent dot at the cell centre
  (`(bx + 0.5) / 50, (by + 0.5) / 50`). Dot area grows with the count. It also draws the target
  and both radius circles from the reveal.
- **`pages/game/ResultsPage.tsx`:** for `map_pin`, `MapPinHeatmap` instead of the bar chart.
  Add `typeLabel`.
- **`pages/game/GameOverPage.tsx`:** for `map_pin`, show the "Within target" % (`withinFullPct`)
  and average credit (`averageCredit`) from the host summary. No image. Add `typeLabel`.
  `typeLabel` is duplicated across these three pages; update all three.
- **`pages/manage/QuestionEditorPage.tsx`:** see §4.12. Uploads go to
  `POST /api/host/courses/{courseId}/images`, using `:courseId` from the route.

### 4.12 Question editors — admin and host

Make these changes in **both** `frontend/admin/src/pages/QuestionEditorPage.tsx` and
`frontend/host/src/pages/manage/QuestionEditorPage.tsx`.
- **Type select:** add "Map pin (tap on image)".
- **`FormState` / `defaultForm`:** `imageId: string | null`, `imageWidth`, `imageHeight`,
  `targetX`, `targetY` (null until set), `fullRadius` (default **0.04**), `zeroRadius`
  (default **0.15**).
- **UI:**
  - An "Upload image" file input, accepting `image/png,image/jpeg,image/webp`.
    - Admin uploads go to `POST /api/admin/images` with the game's `course_id` if it has one.
    - Host uploads go to the course endpoint.
    - Show the server's error message on failure.
  - A canvas (the app's own copy of the §4.9 mapping). Click it to set the target.
  - Two range inputs for the radii, from 0.02 to 0.5 in steps of 0.005, with live circles and
    numeric readouts. Enforce `zeroRadius > fullRadius` in the form.
  - Show a warning (not an error) when `fullRadius < 0.04`: "may be hard to hit on a phone".
- **`formToPayload`:**
  - `config = { imageId }`
  - `answer_data`:
    - ACCURACY: `{ targets: [{x: targetX, y: targetY}], fullRadius, zeroRadius }`
    - COMPLETENESS: the same if a target was set, else `{}`.
  - Block saving ACCURACY with no image or no target.
- **`questionToForm`:** the reverse, reading `targets[0]`.
- **List rendering:** "Map pin — target (0.42, 0.37), r 0.04 → 0.15".
- **Replacing an image:** an editor "replace image" is just uploading a new one and saving the
  question with the new `imageId`. The old image row is left in place (§4.16).

### 4.13 Report and CSV export

- **`services/report_service.py`** (standalone HTML; it cannot call the authenticated GET):
  - For each distinct map-pin image in the session, embed it **once** as a `data:` URI.
  - Each map-pin question renders an inline SVG that references that image, with the
    heatmap dots (using `map_pin_bucket`), the target, and the circles.
  - Text stats: within-target % and average credit.
  - Images are capped at 2 MB, so the report size is bounded by the distinct images in one
    game.
- **`services/export_service.py`:** CSVs are per-question points, so no change. Verify with a
  test that map-pin points appear.

### 4.14 Integration tests (T5) — `tests/integration/test_map_pin.py`

Against the live stack, following `conftest.py`. Each item is one test:
1. **Upload auth:** admin upload → 201. Course-HOST upload to their own course → 201. HOST on a
   different course → 403. GUEST → 403. No token → 401.
2. **Upload validation:** > 2 MB → 413. An SVG and a text file renamed `.png` → 415 / 422. The
   stored `mime_type` comes from the content, not the declared type.
3. **Metadata stripping:**
   - Upload a JPEG carrying GPS EXIF and orientation 6 (rotate 90°), e.g. 400×200 stored.
     The GET bytes have no EXIF (re-open with Pillow: `getexif()` is empty, and there's no
     `exif` in `info`).
   - The stored `width`/`height` are 200×400 (rotated upright).
   - `byte_size` and `sha256` match the returned bytes.
   - A PNG with a `tEXt` chunk comes back without it.
   - A JPEG with an ICC profile keeps it.
4. **GET:** a GUEST player token can fetch by ID (200, correct Content-Type, `immutable` cache
   header). An unknown UUID or a malformed ID → 404. There is no list route (`GET /api/images`
   → 404/405).
5. **Create validation:**
   - Missing image → 422 `IMAGE_NOT_FOUND`.
   - `targets` with 0 or 2 entries → 422.
   - `fullRadius ≥ zeroRadius` → 422.
   - `fullRadius < 0.02` → 422.
   - `x = true` → 422.
   - `x = 1.5` → 422.
   - Client-sent `imageWidth` is overwritten by the stored value.
6. **Update symmetry:**
   - A PUT that only changes `answer_data` to an invalid shape → 422, and the row is unchanged.
   - A PUT that changes `type` from `multiple_choice` to `map_pin` without `config` → 422.
   - A valid PUT → 200.
   Cover both the admin and host routes.
7. **Scoring** (drive a real game with a non-square image, e.g. 800×400, aspect 2):
   - A tap exactly on the target → full points, `is_correct`.
   - A tap at distance `(full + zero) / 2` purely horizontally → 50% (± 0.01).
   - The same **width-unit** distance purely vertically → also 50%. This is the
     aspect-correction test. In height fractions that offset is `dy = d_mid × aspect`, where
     `d_mid = (full + zero) / 2`. For example, full 0.04 and zero 0.15 give `d_mid` = 0.095,
     so `dy` = 0.19 on a 2:1 image.
   - Beyond `zeroRadius` → 0, not correct.
   - COMPLETENESS → full points for any valid tap.
8. **Socket validation:** `{x: "0.5", y: 0.5}`, `{x: NaN}` (sent as a string or null),
   `{x: 0.5}` (missing y), and extra keys → `error`, with no `SessionScore` row.
9. **Answer privacy:** the `new_question` payload has no `targets` / radii anywhere.
   `question_results` includes the reveal.
10. **Distribution:** two taps in the same 2% cell and one elsewhere → the host
    `question_results` distribution has `{"bx,by": 2, ...}`.
11. **Import/export round trip:**
    - Export a game with two map-pin questions sharing one image → `version: 2`, one `images`
      entry.
    - Import it → new game, new image ID (≠ source), questions point to the new ID, and the
      bytes are identical.
    - A bundle whose question references a missing image → 422, with **no** game or image rows
      created.
    - A v1 bundle with no map-pin questions still imports.
    - A hand-made v2 bundle whose image carries GPS EXIF → the stored image has no EXIF.
12. **Preloading:**
    - A player joining a LOBBY room of a game with three map-pin questions over two distinct
      images gets `sync_state.imageIds` with exactly those two IDs, in question order.
    - A game with no map-pin questions → `imageIds` is `[]`.
    - On start, every room member gets `game_images` **before** the first `new_question`
      (check the event order on one socket).

### 4.15 Sample game (T6) and scripts

- **`sample_games/us_cities_map.json`:** a version 2 bundle with one embedded public-domain US
  map PNG (≤ 2 MB; convert from SVG first, because SVG is refused) and 8 or more city
  questions. Mix of `points_value`, at least one COMPLETENESS warm-up.
  - **Author it through the editor and export it.** Don't hand-type target coordinates; they
    have to be measured on the real image.
- **`scripts/simulate_players.py`:** if it builds answers per type, add `map_pin` → random
  `{x, y}` in `[0, 1]`.
- **`scripts/seed_demo.py`:** no change required.

### 4.16 What T8 builds on (not in this work)

- **List / view / delete images:**
  - Add `GET /api/admin/images` (admin only) and a per-course host list filtered by
    `images.course_id`.
  - Delete must first check that no question references the image, by searching `config` JSON
    for `$.imageId` across `map_pin` questions (and later prompt/option images), and return
    409 `IMAGE_IN_USE` if one does.
- **Replace** = upload a new image and re-point questions. Never change an image's bytes.
- **Prompt and option images:** reference image IDs from new `config` keys, always through the
  same GET and `lib/images.ts`. Extend export's image collection to every key that holds an
  image ID; keep that as one function so it doesn't get duplicated.

### 4.17 Implementation order

1. Migration 005 + `Image` model + `image_service` (with metadata stripping) + the three
   endpoints (+ tests 1–4).
2. Schema `map_pin` branch, `resolve_map_pin_image`, update-path fix (+ tests 5–6).
3. Scoring, bucket, reveal helper, gateway validation, `game_image_ids` + `sync_state.imageIds`
   + `game_images` (+ tests 7–10, 12).
4. Import/export v2 (+ test 11).
5. Frontend `lib/` pieces, then editors (admin, then host), player, host game pages.
6. Report, sample game, simulator.
7. Context hierarchy updates (§4.18).

### 4.18 Context hierarchy updates

Per `.claude/rules/context-sync.md`, update:

| file | what to add |
|---|---|
| `backend/app/models/CLAUDE.md` | `Image`, immutability, deferred `data`, no FK from questions |
| `backend/app/schemas/CLAUDE.md` | `map_pin` row in the structure table; `QuestionUpdate` is now validated on the merged result; `ImageResponse` |
| `backend/app/services/CLAUDE.md` | `image_service` (rotate + strip metadata on upload; import re-encodes only when metadata is present); map_pin scoring rules; the single bucket/reveal helpers; `game_image_ids` |
| `backend/app/websocket/CLAUDE.md` | map_pin payload validation; the "nothing secret in `config`" invariant; `sync_state.imageIds` for players and the new `game_images` event in the protocol table |
| `backend/app/routers/CLAUDE.md` | the three image endpoints in the access map; import/export v2 |
| `backend/app/CLAUDE.md` | migrations now 001–005; `routers/images.py` |
| `frontend/*/src/{pages,components,lib}/CLAUDE.md` | new components, `lib/mapPin.ts`, `lib/images.ts`, blob-URL loading |

### 4.19 Files touched

**Backend:**
- New: `migrations/versions/005_images.py`, `models/image.py`, `services/image_service.py`,
  `routers/images.py`.
- Changed: `models/__init__.py`, `main.py`, `schemas/admin.py`, `services/question_service.py`,
  `services/game_service.py`, `services/report_service.py`, `websocket/gateway.py`,
  `websocket/events.py`, `routers/admin.py`, `routers/host.py`, `backend/requirements.txt`.

**Frontend:**
- Player:
  - new: `lib/mapPin.ts`, `lib/images.ts`, `components/MapPinCanvas.tsx`;
  - changed: `types/game.ts`, `pages/game/GameLayout.tsx`,
    `pages/game/{Question,Results,GameOver}Page.tsx`.
- Host:
  - new: `lib/mapPin.ts`, `lib/images.ts`, `components/MapPinHeatmap.tsx`;
  - changed: `types/game.ts`, `pages/game/GameLayout.tsx`,
    `pages/game/{Question,Results,GameOver}Page.tsx`, `pages/manage/QuestionEditorPage.tsx`.
- Admin:
  - new: `lib/mapPin.ts`, `lib/images.ts`;
  - changed: `pages/QuestionEditorPage.tsx`.

**Other:** `tests/integration/test_map_pin.py`, `sample_games/us_cities_map.json`,
`scripts/simulate_players.py` (if needed), and the CLAUDE.md files in §4.18.

## 5. Open questions

- **O1 — EXIF metadata. Resolved:** uploads are rotated upright and re-encoded to strip
  metadata (§4.3). Import re-encodes only when metadata is present.
- **O2 — First-question load time. Resolved:** image IDs are preloaded through
  `sync_state.imageIds` and `game_images` (§4.7, §4.9). Two things are left over:
  - A phone that joins after `game_images` and before its first map question loads on demand.
    That's covered, because `sync_state` for IN_PROGRESS also carries `imageIds`.
  - A slow network can still miss the window. The fallback is "Loading map…" while the server
    timer runs.
- **O3 — Player rejoin mid-question.** This is an existing `rejoin_room` bug: the question isn't
  re-sent (`websocket/CLAUDE.md`), so a reconnecting player gets no map. It's out of scope, but
  more visible with this type.

## Revision history

- 2026-10-04 — Initial spec from design discussion (decisions: immutable images; aspect-corrected
  linear falloff; `is_correct` = within `fullRadius`; place + confirm; 50×50 heatmap; single
  point in a `targets` list; no km display; upload for admin and course HOST; base64 images in
  v2 bundles with ID remap).
- 2026-10-04 — Two changes:
  - Answer time is measured from mount for every type, with the server timer authoritative.
    O2 is resolved by preloading image IDs (`sync_state.imageIds` + `game_images`).
  - O1 is resolved: uploads are rotated from EXIF orientation and re-encoded to strip
    metadata, keeping the ICC profile. Import re-encodes only when metadata is present, so
    Buzzer exports round-trip byte-identical.
