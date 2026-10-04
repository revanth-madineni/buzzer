# T7 — Map Pin Question Type (classroom, canvas)

Status: agreed design, goldfish-tested and revised. Written 2026-10-04.
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
  `fullRadius`". A game's total is the existing per-question sum of float points, with no
  speed bonus; nothing changes there. COMPLETENESS gives full points for any valid tap, but
  shows the **same** map reveal as ACCURACY.
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
- **Fixed alongside** (these affect all question types):
  - The question update path now re-validates the whole question, so a PUT can no longer
    produce a question that create would reject.
  - Late-answer socket errors carry a `code`, and the player app treats them as non-fatal
    instead of ending the game view.
  - Upload and import request bodies are size-limited before parsing (ASGI middleware +
    nginx `client_max_body_size`).

## 3. Alternatives considered

| Alternative | Why it lost |
|---|---|
| Store target as lat/long and project | Ties the type to geographic maps with a known projection. Fractions work for any image (anatomy diagrams, circuit boards) and the author places the target on the same image the player sees, so projection is never needed. Cost: no "you were 340 km off" feedback. Accepted. |
| Raw fraction distance (no aspect correction) | A radius of 0.05 would be 5% of width horizontally but 5% of height vertically, so on a 1.6:1 map the "circle" becomes a tall ellipse and players get more slack north–south. |
| Polygon regions ("click Colorado") | Points only for v1. `answer_data.targets` is a list so another target kind can be added later without a migration. |
| Multiple accepted targets | Not in v1. The `targets` list must have exactly one entry. Kept as a list so v2 can allow several (best-of, like fill-in's `acceptedAnswers`). |
| Submit on first tap (like MC buttons) | A fingertip covers about 10% of a phone-width map, and answers can't be changed after submitting. Place → adjust → confirm costs one extra tap. |
| Auto-submit an unconfirmed pin at time-up | The server rejects answers once the question is locked, so a client-side auto-submit at zero races the lock and would usually be rejected. Timing errors are now non-fatal (§4.7, §4.10), but an auto-submit that is usually rejected would mostly just show "not recorded". It would also submit pins the player never meant to confirm. Not doing it; the Confirm button is made obvious instead. |
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
| `data` | `MEDIUMBLOB` NOT NULL | Plain `BLOB` caps at 64 KB. Migration: `sqlalchemy.dialects.mysql.MEDIUMBLOB()`. Model: `LargeBinary().with_variant(MEDIUMBLOB(), "mysql")`. All tests run against the Docker MySQL stack (`tests/integration/conftest.py` targets `localhost:8000`), so there is no SQLite path, but the variant costs nothing. |
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

**Dependency:** add `Pillow` to `backend/requirements.txt`. Import it as
`from PIL import Image as PILImage, ImageOps`. The bare name `Image` always means the ORM
model in this module, so the two never clash.

`prepare_image(raw: bytes, *, force_reencode: bool = True) -> PreparedImage(data, mime, width, height, sha256)`.
The steps run in this order:
1. `len(raw) > 2 * 1024 * 1024` → 413 `IMAGE_TOO_LARGE` (2 MB cap on the input bytes).
2. `PILImage.open(BytesIO(raw))`. This reads only the header. Any exception → 422
   `INVALID_IMAGE`. **SVG, HTML and plain text land here**: Pillow can't open them at all.
3. Map `format` → mime: `PNG→image/png`, `JPEG→image/jpeg`, `MPO→image/jpeg`,
   `WEBP→image/webp`. Any other format Pillow can open (GIF, BMP, TIFF, …) → 415
   `UNSUPPORTED_IMAGE_TYPE`. **The mime comes from the decoded format, never from the client's
   declared Content-Type or file extension.** The output keeps the same format (MPO is saved as
   JPEG).
   - **MPO** is what Pillow reports for a JPEG whose MPF segment holds 2+ images (common in
     phone photos with a depth map or HDR gain map). It is treated as a JPEG: only the primary
     image is kept, and it is **always re-encoded** (step 7), which drops the MPF segment and
     the secondary images.
4. **Reject animation:** `getattr(img, "is_animated", False)` or `getattr(img, "n_frames", 1) > 1`
   → 415 `UNSUPPORTED_IMAGE_TYPE`. **Skipped for MPO**, whose extra frames are not animation.
5. **Check dimensions before decoding** (header size, before any rotation): `width` or `height`
   < 1 or > 8000, or `width × height` > 40,000,000 → 422 `INVALID_IMAGE`. This is the
   decompression-bomb guard, and it runs before `load()`, so oversized images are never
   decoded.
   - Don't touch `PILImage.MAX_IMAGE_PIXELS`. It's a process-wide global, and Pillow only
     raises above 2× its value. Our own check is stricter and comes first.
6. `img.load()`. Any exception → 422 `INVALID_IMAGE`.
7. **Decide whether to re-encode**, from an explicit allowlist per format of what is *not*
   metadata. `has_metadata` is true when anything is outside the allowlist:

   | format | allowed (not metadata) | everything else → `has_metadata` |
   |---|---|---|
   | JPEG | APP0 `JFIF`, APP2 `ICC_PROFILE`, APP14 `Adobe` segments (check `img.applist`). `info` keys `jfif`, `jfif_version`, `jfif_unit`, `jfif_density`, `dpi`, `progressive`, `progression`, `adobe`, `adobe_transform`, `icc_profile` | any other APPn (EXIF APP1, XMP APP1, Photoshop/IPTC APP13, MPF APP2, …), `comment`, any other `info` key |
   | PNG | `info` keys `icc_profile`, `dpi`, `gamma`, `transparency`, `srgb`, `chromaticity`, `aspect` | non-empty `img.text` (tEXt/zTXt/iTXt, which includes XMP), `exif`, any other `info` key |
   | WebP | RIFF chunks `VP8 `, `VP8L`, `VP8X`, `ALPH`, `ICCP` (scan the raw bytes, as for lossless detection in step 8; **not** Pillow's `info`) | any other chunk (`EXIF`, `XMP `, `ANIM`, `ANMF`, unknown) |
   | MPO | — | always (MPF is metadata) |

   An `info` key or chunk that isn't in the allowlist is treated as metadata, so an unknown one
   leads to a re-encode rather than a leak. WebP is checked from its chunks because Pillow puts
   container fields (`loop`, `background`, `timestamp`, `duration`) in `info` for **every**
   WebP, including its own clean output, so an `info` allowlist would never pass.
   **Trailing data is metadata** for every format: bytes after the JPEG `EOI` marker, after
   the PNG `IEND` chunk, or outside the WebP RIFF length (or a chunk walk that doesn't end
   exactly at the end of the file) set `has_metadata`, so a bundle can't smuggle data past
   the end of an image. Pillow's output ends cleanly, so the invariant below holds. Re-encode
   when `force_reencode` is true or `has_metadata` is true. Otherwise keep `raw` as-is.
8. **Re-encode** (only when step 7 says so):
   - **Rotate first.** Apply `ImageOps.exif_transpose` so phone photos stay upright. Rotation
     can swap width and height.
   - Save **without** passing `exif=`, `dpi=`, comments or text chunks, and pass
     `icc_profile=` when the source had one. Keep PNG transparency and the image mode.
     - JPEG: `quality=90`.
     - PNG: `optimize=True`.
     - WebP: `lossless=True` if the source was lossless, else `quality=90`. "Source was
       lossless" means the file's RIFF chunks include `VP8L`: scan the chunk headers after the
       12-byte `RIFF....WEBP` header, which covers both the simple and the extended (`VP8X`)
       layouts. A lossy source has a `VP8 ` chunk.
   - **Invariant: the output passes step 7 as clean.** Pillow writes only JFIF and ICC for
     JPEG, and nothing outside the allowlist for PNG or WebP. So running `prepare_image` on
     its own output with `force_reencode=False` returns the bytes unchanged. That is what
     makes import round trips byte-identical (test 11). Add a backend unit test for this
     invariant, one per format.
9. Width and height of the **output** (after rotation) are the stored dimensions.
10. The output bytes are capped again: > 2 MB → 413 `IMAGE_TOO_LARGE`.
11. Return the output bytes, mime, dimensions, and the sha256 hex of the output bytes.

Functions:
- `store_prepared(db, prepared: PreparedImage, user, course_id) -> Image`: insert with a new
  `uuid4`, `flush()`. The caller owns the transaction.
- `store_image(db, raw, user, course_id) -> Image`: `prepare_image(raw, force_reencode=True)`
  then `store_prepared`. Both upload endpoints use this, so every uploaded image is
  re-encoded.
- Import (§4.8) calls `prepare_image(raw, force_reencode=False)` during validation, keeps the
  `PreparedImage`, and calls `store_prepared` at insert time, so nothing is decoded twice.
  Images that are already clean (every Buzzer export) are stored byte-for-byte.
- `get_image(db, image_id) -> Image | None`:
  - Returns `None` for an ID that isn't a well-formed UUID string, without querying.
  - Loads `data` only when the caller asks for it, via an `undefer` option or a separate
    function `get_image_with_data`.
- `get_images_meta(db, ids: set[str]) -> dict[str, Image]`: one `SELECT ... WHERE id IN`, no
  `data`.

### 4.4 Endpoints

| method + path | router | auth | behaviour |
|---|---|---|---|
| `POST /api/admin/images` | `routers/admin.py` | `require_admin` | multipart `file` (required), `course_id` form field (optional; 404 `NOT_FOUND` via `NotFoundError` if given and missing, same as game import). → 201 `ImageResponse` |
| `POST /api/host/courses/{course_id}/images` | `routers/host.py` | `require_course_host` | multipart `file`. Stores `course_id` from the URL. → 201 `ImageResponse` |
| `GET /api/images/{image_id}` | `routers/images.py` (**new**, mounted under `/api` in `main.py`) | `get_current_user` (any role, **GUEST included**) | 404 `NOT_FOUND` for unknown or malformed IDs. 200 with the raw bytes. |

- **Both POSTs:**
  - Decorate with `@limiter.limit("30/minute")`. slowapi requires the handler to take a
    `request: Request` parameter (see `routers/auth.py` `login`).
  - Call `image_service.store_image` with `await file.read()`, then **`await db.commit()`
    explicitly before returning**. `get_db`'s own commit runs only after the response has
    been sent (FastAPI request-scoped `yield` dependencies), so without it a client that
    GETs the image right after the 201 can get a 404.
  - The 2 MB check in `prepare_image` is the authoritative per-file rule. Checking size
    inside the handler cannot prevent buffering, because Starlette has already spooled the
    whole multipart body by then. Request size is bounded **before** parsing by the body
    limit below.
  - Image upload does **not** take the live-game guard, because it doesn't write a game or its
    questions.
- **GET response headers:**
  - `Content-Type: <stored mime>`
  - `Cache-Control: private, max-age=31536000, immutable` (safe because images never change)
  - `X-Content-Type-Options: nosniff`
  - `Content-Disposition: inline`
- **No list, update, or delete endpoints in v1.** T8 adds them (see §4.16).

**Request body limit (before parsing).** A FastAPI dependency can't do this, because the form
body is parsed before dependencies run. Instead:
- **New pure ASGI middleware** `common/body_limit.py` `BodySizeLimitMiddleware`, added to the
  FastAPI `app` in `main.py`. It takes a list of `(method, path regex, max_bytes)` rules:
  - `POST ^/api/admin/images$` and `POST ^/api/host/courses/\d+/images$`: 2.5 MB (the 2 MB
    file plus multipart overhead);
  - `POST ^/api/admin/games/import$`: 26 MB.
  - Other requests are untouched.
- **Behaviour for a matching request:**
  - `Content-Length` above the limit → respond 413
    `{"error":"REQUEST_TOO_LARGE","message":...}` without reading the body.
  - Otherwise wrap `receive` and count body bytes. If the total passes the limit (a chunked
    or lying client), respond 413 the same way and stop reading.
- **nginx (dev):** `nginx/nginx.dev.conf` sets no `client_max_body_size`, so nginx's 1 MB
  default currently returns 413 for any upload over 1 MB made from the browser apps. Add
  `client_max_body_size 26m;` to the `location /api/` block.
- **Production:** whoever owns the production proxy (Traefik, outside this repo) needs the
  same ≥ 26 MB allowance on `/api/`. Record this in `backend/CLAUDE.md` Gotchas.
- **Import:** keeps its "files over 25 MB → 422" check on the bytes it read. The middleware
  is what stops a 1 GB upload.

Schema `ImageResponse` (in `schemas/admin.py`, reused by host): `id`, `mime_type`, `width`,
`height`, `byte_size`, `sha256`. Never the data.

**Access decision:** the GET has no course check. Anyone who knows an ID can read the image.
Security comes from IDs being unguessable UUIDs and from having no listing. This is acceptable
because the image is shown to every player of the question anyway. Question authoring checks
only that the image **exists**, not which course uploaded it (§4.5).

### 4.5 Question schema and validation — `backend/app/schemas/admin.py`

Add `map_pin` to the `type` pattern in **`QuestionCreate` and `QuestionUpdate`**.

Add a `map_pin` branch in `QuestionCreate.validate_structure`. Unknown keys are rejected in
both objects.

**`config`** (checked for **both** grading types):
- `imageId`: required, a non-empty string of at most 64 characters. The schema does **not**
  require UUID shape, so hand-made import bundles can use IDs like `"map1"` (§4.8). Whether the
  image exists is checked in the service; IDs created by the server are always UUIDs.
- `imageWidth`, `imageHeight`: optional on input. When present they must be positive
  integers (not `bool`), otherwise 422. The server always overwrites them (below). They are
  accepted at all only because exports carry them.
- Nothing else.

**`answer_data`** (the **same rule for both grading types**, because both show the same
reveal, see §4.6):
- `targets`: a list of **exactly 1** object `{x, y}`. `x` and `y` are valid numbers in `[0, 1]`,
  with no other keys.
- `fullRadius`: a valid number, `0.02 ≤ fullRadius`.
- `zeroRadius`: a valid number, `fullRadius < zeroRadius ≤ 2`. 2 width units covers the
  diagonal of any image up to about 1:1.7 portrait, which is more than any sensible cutoff.
- For COMPLETENESS the target and radii are used only for the reveal and the stats; scoring
  ignores them.

The 0.02 floor is a hard guard against targets that can't be hit on a phone. The editor
defaults (0.04 / 0.15) are higher (§4.12).

**Service side** (`services/question_service.py`): a new helper
`resolve_map_pin_image(db, data)`.
- **Who calls it:** `create_question` and `update_question`. **Import does not call it**
  (§4.8). Import's images aren't in the database yet when the questions are validated, so
  import sets dimensions from its own `PreparedImage`s instead.
- **What it does** for `type == "map_pin"`: loads the image metadata (`get_images_meta`),
  raises 422 `IMAGE_NOT_FOUND` if the image doesn't exist, and **overwrites**
  `config.imageWidth` / `imageHeight` with the stored dimensions.
- Images are immutable, so these copied dimensions can never go stale. Scoring therefore never
  needs a DB read.

**Update-path fix (all types).** Today `update_question` copies non-null fields onto the model
with no structural check (`schemas/CLAUDE.md` gotcha). New behaviour:
1. Build `merged` from the existing question's seven content fields: `type`,
   `grading_type`, `prompt`, `config`, `answer_data`, `time_limit_seconds`,
   `points_value`. Overlay the PUT's non-null values for those fields.
   - `QuestionCreate` has no `game_id` (it comes from the URL). It **does** have an optional
     `order_index`, as does `QuestionUpdate`, but that is positional, not content: it is left
     out of `merged` (so it defaults to `None` during validation) and, when the PUT carries
     it, applied to the row as before.
   - `config` and `answer_data` are **replaced** whole, not deep-merged. They are the only
     fields a PUT could want to "clear", and sending `{}` does that, because `{}` is not
     null. All other question columns are NOT NULL, so "non-null fields only" loses nothing.
2. Run `QuestionCreate.model_validate(merged)`. A failure raises the standard 422
   `VALIDATION_ERROR`.
3. Run `resolve_map_pin_image`, then sanitize the prompt, then apply the changes.

This is the same order create uses today: the schema validates the raw prompt when the
request is parsed, and `create_question` sanitizes it afterwards.

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
first and unchanged, so a COMPLETENESS map-pin answer gets full `points_value` and
`is_correct = True`, exactly like other types:

```
map_pin (ACCURACY):
    click = answer_data {x, y}       # already validated by the gateway (§4.7)
    target = question.answer_data.targets[0]
    d = map_pin_distance(question.config, target, click)
    frac = map_pin_fraction(d, fullRadius, zeroRadius)
    points = round(question.points_value * frac, 2)
    is_correct = (d <= fullRadius)
```

**Number types** (checked in the code; no schema change needed):
- `questions.points_value` and `session_scores.points_awarded` are already `Float` (migration
  `003_float_points`), and `ScoreResult.points_awarded` is `float`.
- `get_leaderboard` sums `points_awarded` in SQL, so totals are floats too. Values like 7.35
  are stored and summed as-is.
- **There is no speed bonus** in Buzzer. `answer_time_ms` is stored and only used for
  average-time stats. A map-pin score is exactly `round(points_value × frac, 2)`.

`calculate_score` also stays defensive on its own, because it is reachable from tests, seed
scripts and direct inserts that skip the service. It returns `ScoreResult(0, False)` and logs
`map_pin_bad_question` or `map_pin_bad_answer`, rather than raising, when:
- `x` or `y` is missing or invalid;
- `config.imageWidth` / `imageHeight` is missing or not positive;
- `targets` is missing or empty;
- the radii are missing.

**Distribution bucket** (a single helper, `map_pin_bucket(x, y) -> str`):
`bx = min(49, floor(x * 50))`, `by = min(49, floor(y * 50))`, key `"bx,by"`. Use it in:
- `record_answer`, which adds one `increment_answer_dist` per answer;
- `get_host_question_summary`, which rebuilds the distribution from `SessionScore.answer_data`;
- `report_service`.
It must be the same helper in all three, or the counts will drift (the existing fill-in
whitespace normalization already shows this happening).

**Reveal: one behaviour for both grading types.** Add one helper `map_pin_reveal(q) -> dict`.
All fields are always present and non-null, because §4.5 requires the target for both
grading types:
```
{ "type": "map_pin", "gradingType": "ACCURACY" | "COMPLETENESS",
  "imageId", "imageWidth", "imageHeight",
  "target": {x, y}, "fullRadius", "zeroRadius" }
```
In each of the four reveal copies, the `map_pin` check goes **before** the existing
`grading_type == "COMPLETENESS"` early return, so a COMPLETENESS map-pin question still gets
the full map reveal. Other types keep `{"type": "completeness"}` unchanged. The four copies
are:
- `get_player_question_summary`
- `get_host_question_summary`
- `report_service._answer_reveal`
- `websocket/gateway._answer_reveal`

Don't fold the other types into the helper in this work. The only place the two grading
types differ is `calculate_score`.

The host summary for map_pin also returns two stats. Both are computed from **geometry**
(each stored `SessionScore.answer_data` click against the target), not from `is_correct` or
points, so they mean the same thing under COMPLETENESS and when `points_value == 0`:
- **Denominator:** `n` = the scores for this question whose stored `answer_data` has a valid
  `{x, y}` (answers, not players).
- `withinFullPct`: 0–100, rounded to 1 decimal = 100 × (count with `d ≤ fullRadius`) / `n`.
  `null` when `n == 0`.
- `averageCredit`: 0–1, rounded to 3 decimals = mean of `map_pin_fraction(d, …)`. `null`
  when `n == 0`.

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
  score. The check uses `math.isfinite` explicitly: Python's `json` accepts a literal `NaN`,
  so a raw NaN can arrive. The client clamps and validates before sending (§4.10), so this
  error should only ever reach a tampered client.
- **Error codes for timing rejections (all question types).**
  - `_emit_error(sid, message, code=None)` gains an optional `code`. The payload becomes
    `{"message", "code"?}`. `message` is unchanged, so existing clients keep working.
  - Three rejections in `on_submit_answer` can happen to an honest player who presses
    Confirm, or taps an answer, in the last moments of a question. Give each a code:

    | message (unchanged) | `code` |
    |---|---|
    | "No active question" | `NO_ACTIVE_QUESTION` |
    | "Question is locked" | `QUESTION_LOCKED` |
    | "Question ID does not match the active question" | `QUESTION_MISMATCH` |

  - Every other error keeps no code and stays fatal on the player (§4.10).
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
    1. **Image list shape.** v1 bundles may not contain `images`. In v2 it is optional and holds
       at most 50 entries. Each entry needs a unique `id` (a non-empty string of at most 64
       characters; any string, not just UUIDs, so hand-made bundles can use `"map1"`), a
       `mime_type` (informational; the decoded format wins) and a `data` string.
    2. **Questions.** Run `QuestionCreate` on each question, as today.
    3. **References.** Every `map_pin` question's `config.imageId` must be one of the bundle's
       image `id`s. Otherwise 422 `"Question {n} references image {id} not in bundle"`.
       References to images already on the server are **not** allowed. That keeps bundles
       self-contained.
    4. **Referenced images only:**
       - Base64-decode each image that some question references, then run
         `image_service.prepare_image(raw, force_reencode=False)` and keep the
         `PreparedImage`. Failures map to 422 with the existing string-detail format:
         `"Image {id} invalid: ..."`.
       - Images that no question references are **ignored**: not decoded, not validated, not
         stored. A stray bad image in a bundle therefore can't block an import.
       - Hand-made bundles that carry EXIF are still cleaned. Bundles exported from Buzzer
         (already clean, §4.3 invariant) round-trip with identical bytes and no extra JPEG
         generation loss.
  - **Insert**, in the same transaction as the game:
    1. For each referenced image, `image_service.store_prepared(db, prepared, admin,
       course_id)`, which gives it a **new** UUID. Build a map from old ID to new ID.
    2. Rewrite each question's `config.imageId` through that map.
    3. Set `config.imageWidth`/`imageHeight` from that image's `PreparedImage`. Import does
       **not** call `resolve_map_pin_image` (§4.5).
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
    - A gesture that **starts** outside `[0, 1]` (in the letterbox area) is **ignored**.
    - A drag that started on the image and moves into the letterbox **clamps** the pin to the
      image edge. The pin never leaves the image.
    - Values sent to the server are clamped to `[0, 1]` anyway, as a guard against rounding.
  - **Canvas size:** this makes the CSS size fully determined.
    - CSS width = 100% of the container (the page's content width).
    - CSS height = `min(width × imageHeight / imageWidth, 0.6 × viewport height)`, in pixels,
      set by the component.
    - When the height is capped, contain-fit letterboxes the image horizontally.
    - In the editors (desktop), the cap is `0.7 × viewport height` instead.
    - Before the image's dimensions are known, use `config.imageWidth/imageHeight` from the
      question payload, so layout doesn't jump when the image arrives.
  - **Backing store:** `cssSize × devicePixelRatio`, and drawing is scaled accordingly.
  - **Resize:** on `resize` / `orientationchange`, recompute and redraw. Pins are stored as
    fractions, so they survive.
- **`lib/images.ts`** (player, host, admin): `loadImage(imageId) → Promise<HTMLImageElement>`.
  1. `fetch('/api/images/{id}')` with `Authorization: Bearer <localStorage.token>`. This is
     the same token source every app's `lib/api.ts` uses.
     - **On a 401**, call `POST /api/auth/refresh` once (same-origin; the `refresh_token`
       cookie is sent automatically).
     - On success, store the returned `access_token` in `localStorage.token` and retry the
       image fetch once. If either fails, reject.
     - **Token lifetimes (checked):** access tokens last 2 h from issue
       (`auth_service.create_access_token`), and refresh cookies last 7 d, for guests too,
       since `/auth/guest` sets one. A guest's token is issued when they join, so it outlasts
       any normal class game. A netid or local user may have logged in earlier, though, so
       the one-shot refresh covers the token expiring mid-game.
     - The socket is unaffected: it authenticates only at connect.
     - None of the apps' `api.ts` refreshes today. Don't add refresh there in this work.
  2. → `blob` → `URL.createObjectURL` → an `Image` that resolves on load.
  3. Keep a module-level cache keyed by `imageId`. It caches the **promise**, so a preload
     and a question render asking for the same ID share one request. Images are immutable,
     so the same map reused across questions is downloaded once per page load.
  4. A failed load is evicted from the cache, so a later call retries.
  5. Never revoke cached URLs during a game.
  6. `preloadImages(ids: string[])` calls `loadImage` for each ID and swallows errors. It is
     fire-and-forget.
  `lib/images.ts` is self-contained (its own `fetch`) in all three apps, rather than going
  through `api.ts`, whose wrappers parse JSON and differ per app.
  - **On failure** (after the refresh attempt), the canvas shows "Couldn't load the map" with
    a **Retry** button that calls `loadImage` again. Failed loads aren't cached.

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
- **`pages/game/GameLayout.tsx`:**
  - **Preloading:** call `preloadImages` with `imageIds` from `sync_state`, and again on the
    new `game_images` event. Add `imageIds?: string[]` to `SyncStatePayload` and a
    `GameImagesPayload` type.
  - **Non-fatal timing errors (all question types).** The `error` handler checks
    `data.code`:
    - **`QUESTION_LOCKED`, `NO_ACTIVE_QUESTION` or `QUESTION_MISMATCH`:** **don't** call
      `setError` and don't navigate. Instead:
      - set a context flag `answerRejected = true`;
      - show a non-blocking banner for about 3 s: "Too late — your answer wasn't recorded".
      - The player stays on whatever view they're on (question or results). The host's next
        `new_question` / `question_results` moves them on as usual.
      - `new_question` resets `answerRejected`.
    - **Any other error, or no code:** fatal as today (`setError`).
    - Add `code?: string` to the error payload type.
- **`pages/game/QuestionPage.tsx`:** a `map_pin` branch with `TimerBar` (same `key` / `paused`
  props as the other branches), `MapPinCanvas`, and a **Confirm** button.
  - Confirm is enabled when a pin exists, the image has loaded, the question isn't locked, and
    nothing has been submitted yet. It calls `emitAnswer(questionId, {x, y}, msSinceMount)`.
  - `answer_time_ms` is measured from mount, the same as every other type.
  - No auto-submit at time-up (§3).
  - **If `answerRejected` becomes true,** clear the local "submitted" state and keep the
    canvas and pin visible but disabled, with the text "Not recorded — time ran out". This
    applies to every type's branch, since `submitted` is set before the server acknowledges.
  - **After a successful Confirm,** save the pin to `sessionStorage` under
    `buzzer:pin:{code}:{questionId}`, wrapped in try/catch so a blocked storage doesn't break
    anything. Results can then show it after a page reload.
- **`pages/game/ResultsPage.tsx`:** for `map_pin`, `MapPinCanvas` in reveal mode with the
  reveal's image, target and circles. The same view is used for both grading types.
  - **The player's own pin** comes from local state, falling back to the `sessionStorage`
    copy. If neither exists (no answer, or storage was unavailable), draw the reveal without
    a pin.
  - **The label is computed from geometry**, using `lib/mapPin.ts` and the player's pin
    against the reveal:
    - no pin, or `answerRejected` → **"No answer"**;
    - `d ≤ fullRadius` → **"Within target"**;
    - `d < zeroRadius` → **"Partial credit"**;
    - otherwise → **"Too far"**.
  - Under COMPLETENESS, the label is followed by "· full credit for answering", because
    points don't depend on distance there.
  - Points and total are shown as today.
- **`pages/game/GameOverPage.tsx`:** the recap line for `map_pin` shows points earned / points
  possible. No image.

### 4.11 Host app — `frontend/host/src/`

- **`types/game.ts`:** same additions as the player app (no `imageIds` on the host's
  `sync_state`; the host only gets `game_images`).
- **`pages/game/GameLayout.tsx`:** on `game_images`, call `preloadImages` so the results
  heatmap draws without a wait. A host that refreshes mid-game misses `game_images`, and its
  `sync_state` carries no `imageIds`. Its `MapPinHeatmap` loads the image on demand (cache
  miss → "Loading map…"). That is acceptable for the projector.
- **`pages/game/QuestionPage.tsx`:** add `typeLabel` "Map Pin". Show the prompt as usual.
  **Do not render the map.** The projector shows the city name, and the phones show the map.
- **`components/MapPinHeatmap.tsx`** (new): draws the image (via `lib/images.ts`) and, for each
  distribution key `"bx,by"`, a translucent dot at the cell centre
  (`(bx + 0.5) / 50, (by + 0.5) / 50`). Dot area grows with the count. It also draws the target
  and both radius circles from the reveal.
- **`pages/game/ResultsPage.tsx`:** for `map_pin`, `MapPinHeatmap` instead of the bar chart.
  The same view is used for **both grading types**: image, heatmap, target and both circles.
  The only difference is that COMPLETENESS questions add a "Participation — full credit for
  answering" caption under the map. Add `typeLabel`.
- **`pages/game/GameOverPage.tsx`:** for `map_pin`, show the "Within target" % (`withinFullPct`)
  and average credit (`averageCredit` × 100, as %) from the host summary, for both grading
  types. Show "—" when they are `null` (nobody answered). No image. Add `typeLabel`.
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
  - **Radii:** for each radius, a range input (0.02–0.5, step 0.005) **paired with** a number
    input that accepts the server's full range (0.02–2, step 0.005).
    - The number input is the source of truth. The slider just shows `min(value, 0.5)`.
    - A loaded value above 0.5, e.g. from an import, is kept as it is and never clamped
      unless the author changes it.
    - Live circles reflect the true value.
    - Enforce `zeroRadius > fullRadius` in the form.
  - Show a warning (not an error) when `fullRadius < 0.04`: "may be hard to hit on a phone".
- **`formToPayload`:**
  - `config = { imageId }`
  - `answer_data = { targets: [{x: targetX, y: targetY}], fullRadius, zeroRadius }`, the same
    for both grading types (§4.5).
  - **Block saving for either grading type** when there is no image or no target. The form
    error says which is missing. That matches the server, which requires both for both
    grading types.
- **`questionToForm`:** the reverse, reading `targets[0]`.
- **List rendering:** "Map pin — target (0.42, 0.37), r 0.04 → 0.15".
- **Replacing an image:** an editor "replace image" is just uploading a new one and saving the
  question with the new `imageId`. The old image row is left in place (§4.16).

### 4.13 Report and CSV export

- **`services/report_service.py`** (standalone HTML; it cannot call the authenticated GET):
  - **Embed each image once.** At the top of the report body, add one hidden
    `<svg width="0" height="0" style="position:absolute">`. Its `<defs>` hold one
    `<image id="mapimg-{imageId}" href="data:{mime};base64,..." width="{w}" height="{h}"/>`
    per distinct map-pin image in the session.
  - **One SVG per question.** Each map-pin question renders its own inline
    `<svg viewBox="0 0 {w} {h}">` that shows the image with `<use href="#mapimg-{imageId}"/>`,
    then draws the heatmap dots (using `map_pin_bucket`), the target, and the circles in image
    pixel coordinates. A radius `r` in width units is `r × w` pixels.
  - Text stats: within-target % and average credit (the same geometry-based numbers as
    §4.6). This applies to both grading types.
  - Images are capped at 2 MB, so the report size is bounded by the distinct images in one
    game.
- **`services/export_service.py`:** CSVs are per-question points, so no change. Verify with a
  test that map-pin points appear.

### 4.14 Integration tests (T5) — `tests/integration/test_map_pin.py`

Against the live stack, following `conftest.py`. Each item is one test:
1. **Upload auth:** admin upload → 201. Course-HOST upload to their own course → 201. HOST on a
   different course → 403. GUEST → 403. No token → 401.
2. **Upload validation:**
   - Each input gets exactly one code:

     | input | expected |
     |---|---|
     | 2.2 MB PNG | 413 `IMAGE_TOO_LARGE` (passes the body limit, fails `prepare_image`) |
     | 3 MB body with an honest `Content-Length` | 413 `REQUEST_TOO_LARGE` (middleware, before parsing) |
     | SVG file | 422 `INVALID_IMAGE` (Pillow can't open it) |
     | text file renamed `.png` | 422 `INVALID_IMAGE` |
     | GIF | 415 `UNSUPPORTED_IMAGE_TYPE` |
     | animated WebP | 415 `UNSUPPORTED_IMAGE_TYPE` |
     | 9000×10 PNG | 422 `INVALID_IMAGE` |

   - A PNG uploaded with `Content-Type: image/jpeg` is stored as `image/png`: the stored
     `mime_type` comes from the content, not the declared type.
3. **Metadata stripping:**
   - Upload a JPEG carrying GPS EXIF and orientation 6 (rotate 90°), e.g. 400×200 stored.
     The GET bytes have no EXIF (re-open with Pillow: `getexif()` is empty, and there's no
     `exif` in `info`).
   - The stored `width`/`height` are 200×400 (rotated upright).
   - `byte_size` and `sha256` in the upload response match the returned bytes.
   - A PNG with a `tEXt` chunk comes back without it.
   - A JPEG with an ICC profile keeps it.
   - A JPEG with only a Photoshop APP13 (IPTC) segment comes back without it.
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
   - `imageWidth: "abc"` → 422.
   - Client-sent `imageWidth: 5` is overwritten by the stored value.
   - COMPLETENESS with `answer_data: {}` → 422 (the target is required for both grading
     types).
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
   - COMPLETENESS → full points for any valid tap, even one beyond `zeroRadius`.
   - `points_value` 7 at 50% → `points_awarded` 3.5, and the leaderboard total includes the
     3.5. This confirms floats end to end.
8. **Socket validation:** each of these → `error`, with no `SessionScore` row:
   - `{x: "0.5", y: 0.5}`;
   - `{x: null, y: 0.5}`;
   - a raw JSON `NaN` for `x` with a valid `y` (send the frame text `{"x": NaN, "y": 0.5}`;
     Python's `json` accepts it);
   - `{x: 0.5}` (missing y);
   - `{x: 0.5, y: 0.5, z: 1}` (extra key).
9. **Answer privacy and reveal:**
   - The `new_question` payload has no `targets` / radii anywhere.
   - `question_results` includes the full `map_pin` reveal (`imageId`, `target`, both radii)
     for **both** an ACCURACY and a COMPLETENESS map-pin question.
   - A COMPLETENESS **multiple_choice** question still reveals `{"type": "completeness"}`.
     This is the regression guard for moving the branch before the COMPLETENESS check.
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
13. **Late answers are non-fatal:**
    - Submit after `question_locked` → `error` with `code: "QUESTION_LOCKED"`.
    - Submit after the host advanced to results → `error` with `code: "NO_ACTIVE_QUESTION"`.
    - Submit with a stale `question_id` → `error` with `code: "QUESTION_MISMATCH"`.
    - None of these creates a `SessionScore` row.
    - The player-side handling (no error screen) is in §4.10. If the player app has no test
      runner, verify it manually and record that in the context docs.
14. **Host summary stats:** three answers at `d = 0` (within), mid-falloff (0.5 credit) and
    beyond zero → `withinFullPct` 33.3 and `averageCredit` 0.5.
    - The same on a COMPLETENESS map-pin question gives the same two numbers, even though
      every answer got full points.
    - A question nobody answered → both `null`.
15. **Import edge cases:**
    - A hand-made bundle using image ID `"map1"` imports, and the stored ID is a new UUID.
    - A bundle with an unreferenced image whose `data` isn't valid base64 still imports, and
      that image isn't stored.

Also add **backend unit tests** in `tests/unit/` for:
- `prepare_image` idempotence (§4.3 step 8 invariant): one case each for JPEG, PNG, lossy
  WebP and lossless WebP;
- the `has_metadata` allowlist, including a WebP with an `EXIF` chunk (metadata) and a clean
  Pillow-written WebP (not metadata);
- a 2-image MPO input → `image/jpeg`, one frame, output opens as plain `JPEG` with no MPF;
- `map_pin_distance` / `map_pin_fraction` / `map_pin_bucket`, including bucket 49 for
  `x = 1.0`.

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

1. Migration 005, `Image` model, `image_service` (with metadata stripping), and its unit
   tests. Then the body-limit middleware, the nginx change, and the three endpoints (+ tests
   1–4).
2. Schema `map_pin` branch, `resolve_map_pin_image`, update-path fix (+ tests 5–6).
3. Scoring (+ unit tests), bucket, reveal helper, host summary stats, gateway validation,
   error codes, `game_image_ids` + `sync_state.imageIds` + `game_images` (+ tests 7–10,
   12–14).
4. Import/export v2 (+ tests 11, 15).
5. Frontend `lib/` pieces, then editors (admin, then host), player (including non-fatal
   timing errors), host game pages.
6. Report, sample game, simulator.
7. Context hierarchy updates (§4.18).

### 4.18 Context hierarchy updates

Per `.claude/rules/context-sync.md`, update:

| file | what to add |
|---|---|
| `backend/app/models/CLAUDE.md` | `Image`, immutability, deferred `data`, no FK from questions |
| `backend/app/schemas/CLAUDE.md` | `map_pin` row in the structure table; `QuestionUpdate` is now validated on the merged result; `ImageResponse` |
| `backend/app/services/CLAUDE.md` | `image_service` (rotate + strip metadata on upload; import re-encodes only when metadata is present); map_pin scoring rules; the single bucket/reveal helpers; `game_image_ids` |
| `backend/app/websocket/CLAUDE.md` | map_pin payload validation; the "nothing secret in `config`" invariant; `sync_state.imageIds` for players and the new `game_images` event in the protocol table; `error.code` for the three timing rejections |
| `backend/app/routers/CLAUDE.md` | the three image endpoints in the access map; import/export v2 |
| `backend/app/common/CLAUDE.md` | `body_limit.py` middleware and its rules |
| `backend/app/CLAUDE.md` | migrations now 001–005; `routers/images.py`; body-limit middleware in `main.py` |
| `backend/CLAUDE.md` | Gotcha: the production proxy must allow ≥ 26 MB bodies on `/api/`; nginx dev sets `client_max_body_size 26m` |
| `frontend/*/src/{pages,components,lib}/CLAUDE.md` | new components, `lib/mapPin.ts`, `lib/images.ts` (blob URLs, one-shot refresh on 401). Player: timing errors are non-fatal (update the "One `error` event ends the game view" gotcha) |

### 4.19 Files touched

**Backend:**
- New: `migrations/versions/005_images.py`, `models/image.py`, `services/image_service.py`,
  `routers/images.py`, `common/body_limit.py`.
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

**Other:**
- `tests/integration/test_map_pin.py`;
- new unit test files under `tests/unit/` for `image_service` and the map-pin math;
- `nginx/nginx.dev.conf`;
- `sample_games/us_cities_map.json`;
- `scripts/simulate_players.py` (if needed);
- the CLAUDE.md files in §4.18.

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
- 2026-10-04 — Goldfish-test fixes:
  - **B1:** `has_metadata` is now an explicit allowlist per format (JPEG APP segments + `info`
    keys, PNG, WebP). Unknown keys count as metadata, and an idempotence invariant backs it,
    with unit tests.
  - **B2:** both grading types show the same map reveal. The target is required for both;
    only scoring differs.
  - **B3:** import doesn't call `resolve_map_pin_image`; it sets dimensions from its own
    prepared images.
  - **B4:** added `store_prepared`.
  - **B5:** stated that points and totals are already floats (migration 003) and that there's
    no speed bonus.
  - **H1:** timing rejections carry `error.code`, and the player treats them as non-fatal.
  - **H2:** canvas sizing rule.
  - **H3:** body-size middleware plus nginx `client_max_body_size`. The dev nginx 1 MB
    default would otherwise block uploads.
  - **H4:** explicit dimension check before `load()`, and exact codes per input.
  - **H5:** checked token lifetimes (2 h access / 7 d refresh); `lib/images.ts` does a
    one-shot refresh on 401.
  - **H6:** clarified the merge fields and the sanitize order.
  - **Medium items:**
    - WebP lossless detection (`VP8L`);
    - any-string bundle IDs, with the schema UUID check dropped;
    - unreferenced bundle images ignored;
    - geometry-based summary stats with defined denominators and nulls;
    - a "No answer" label and a `sessionStorage` copy of the pin;
    - host-refresh behaviour stated;
    - a `LargeBinary` variant;
    - the editor requires an image and target for both grading types.
  - **Low items:**
    - `PILImage` alias;
    - a number input for the full radius range;
    - `imageWidth` type check;
    - drag clamping;
    - a raw-NaN test;
    - animation detection;
    - SVG `<defs>`/`<use>` in the report;
    - the admin `course_id` 404 code;
    - slowapi `request` parameter;
    - a defensive `calculate_score`.
  - Tests 13–15 and the backend unit tests were added.
- 2026-10-04 — Implementation-time fixes (found probing Pillow 12.3):
  - WebP `has_metadata` is decided from RIFF chunks, not `info`: Pillow sets
    `loop`/`background`/`timestamp`/`duration` on every WebP, so the `info` allowlist broke the
    idempotence invariant.
  - MPO (multi-image JPEG from phones) is accepted as `image/jpeg`, skips the animation check,
    and is always re-encoded.
  - Status line updated.
- 2026-10-04 — Step 1 implementation fixes:
  - Upload handlers commit explicitly before responding (`get_db` commits after the response
    is sent, so an immediate GET raced the commit and 404'd).
  - Trailing data after the end of an image counts as metadata.
  - `ImageResponse` includes `sha256`.
- 2026-10-04 — Corrected §4.5: `QuestionCreate` and `QuestionUpdate` both have an optional
  `order_index`; it stays out of the merged validation and is applied from the PUT.
