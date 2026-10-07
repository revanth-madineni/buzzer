# T7 — Slider Question Type (party)

Status: **implemented 2026-10-06** after a goldfish test and revision (see §7, §8). Written 2026-10-06.
Scope: the second of the two T7 types (the party one). The classroom type is `map_pin`
(`docs/plans/t7-map-pin.md`), which already satisfies T7's canvas requirement, so this type is
not canvas-based.

Architecture context lives in the CLAUDE.md hierarchy. Read `backend/app/CLAUDE.md`,
`backend/app/{schemas,services,websocket,routers}/CLAUDE.md` and `frontend/CLAUDE.md` before
implementing. `map_pin` is the worked example of a full question-type slice: where this spec
says "as map_pin does", the map_pin code is the reference.

---

## 1. Problem

Party quizzes are at their best with "closest guess" questions ("How many hot dogs did the
2024 champion eat in 10 minutes?") and "vibes" questions ("How spicy is a jalapeño, from Ice
cold to Lava?"). Buzzer's four types can only ask these as multiple choice or as an exact
numeric fill-in. Both are all-or-nothing, so "close" scores the same as "wildly wrong", and the
fun of seeing how far off the room was is lost.

We need a question where every player sets a slider between two ends and is scored by **how
close** they got to the author's target, with partial credit that falls off with distance. The
projector then shows where the room's guesses landed.

**Hard constraint (team decision):** each answer is scored **on its own**, from the question
and that answer only. Nothing in scoring may depend on other players' answers.

## 2. Technical plan (summary)

- New question `type` **`slider`**. No change to the `questions` table, so no migration.
  Everything specific to the type lives in the existing `config` and `answer_data` JSON columns.
- **One type covers two uses:**
  - **Numeric** ("closest guess"): numbers are shown, with an optional unit ("hot dogs").
  - **Spectrum** ("Ice cold ↔ Lava"): words at both ends and **no numbers shown anywhere**.
  The backend sees only numbers either way. The spectrum is an editor preset (0–100, step 1,
  `showValue: false`, both end labels).
- `config` holds `min`, `max`, `step`, `showValue`, and an optional `unit`, `minLabel` and
  `maxLabel`. `answer_data` holds `target`, `fullRadius` and `zeroRadius`.
- **Everything is on the step grid.** The range must be a whole number of steps (at most
  10,000). The target must be exactly on a step. Player answers are **rejected** outside
  `[min, max]` and **snapped** to the nearest step inside it (ties round up, the same on
  server and client). "Outside" and "on a step" are both judged in index units with a small
  tolerance (§4.0), by one helper. Internally the server works on
  **step indices** `k = (value − min) / step`, which are exact integers, so floating-point
  noise like `0.30000000000000004` never reaches scoring.
- **Scoring:**
  - distance = |guess index − target index| ÷ number of steps, a fraction of the range;
  - full points within `fullRadius`, falling in a straight line to zero at `zeroRadius`;
  - this is the same falloff as map_pin, with the same helper;
  - `is_correct` means "within `fullRadius`";
  - no speed bonus;
  - defaults: 0.05 / 0.30 (one set for both uses).
- **COMPLETENESS** gives full points for any valid answer, but shows the **same** reveal as
  ACCURACY, as map_pin does.
- **Player:** a large horizontal slider whose knob **starts at the middle step**, with − / +
  buttons that move one step, then **Confirm**. No auto-submit at time-up.
- **Host (projector):** while the question is open, the prompt plus the scale (the end labels
  or min/max with unit). On results, a histogram of guesses in up to 20 bins across the range,
  with the target marked and the full-credit band shaded.

## 3. Alternatives considered

| Alternative | Why it lost |
|---|---|
| Scoring that depends on other players (closest guess wins, Wits & Wagers betting, voting) | Team decision: each answer is scored alone. It would also need a new phase after locking, because `calculate_score` runs per answer at submit time. |
| Free-number entry (keypad) with log-ratio scoring | Answers that span orders of magnitude need log-scale distance, but log fails for years, zero and negative numbers, so it would need two tolerance modes. Typing big numbers on a phone (missing zeros) is error-prone. With a slider, `min`/`max` set the scale, so linear distance is fair. |
| Two separate types (numeric and spectrum) | Same backend, scoring and reveal. The only difference is presentation (labels vs numbers), which `showValue` and the labels express. One type halves the work in the four reveal copies, both editors and six pages. |
| Knob hidden until the first tap (no default position) | Rejected by the team in favour of starting at the middle. Accepted risk: a player who just presses Confirm answers "middle". Guards: Confirm is still required, there is no auto-submit, and the editors warn whenever not moving would earn any points, saying how many (§4.11). |
| Different default radii for numeric vs spectrum | Team decision: one set of defaults (0.05 / 0.30), which the author can change per question. |
| Target anywhere in range, not necessarily on a step | The step is the author's increment. A target between steps can't be hit exactly, and requiring it on the grid makes scoring exact integer arithmetic. |
| Accept and snap out-of-range answers | Honest clients clamp to the range before sending, so an out-of-range value means a tampered client. Rejecting it (as map_pin does with x > 1) is simpler to reason about. |
| Logarithmic slider option | Useful for "population of X" questions, but it adds a second distance model. Out of scope for v1. Authors pick a sensible linear range. |
| Unit as prefix or suffix (e.g. `$`) | One suffix `unit` string keeps formatting identical on every screen. "dollars" works as a suffix. |
| Canvas-drawn slider | Not needed: map_pin already meets the canvas requirement, and a native `<input type="range">` gives keyboard and screen-reader access for free. |

## 4. Detailed implementation

### 4.0 Conventions

- A **valid number** means what it means in map_pin's spec: a JSON number, `int` or `float`
  but **not `bool`**, and finite. Use the existing `schemas/admin.py` `is_valid_number`.
- **Indices.** For a slider config, `N = round((max − min) / step)` is the number of steps,
  and positions are the integers `k ∈ [0, N]`, where position `k` has value `min + k × step`.
  "Index" always means this integer.
- **Tolerance** `EPS = 1e-6`, in index units, everywhere a float must be checked against the
  grid.
- **Snapping** `snap(k) = floor(k + 0.5)`: ties round **up**. Never use Python's `round()`
  (it rounds ties to even, so `round(56.5) == 56`) or rely on JS `Math.round` matching it.
  Python uses `math.floor(k + 0.5)` and TypeScript `Math.floor(k + 0.5)`, so both give 57.
- **In range** always means `slider_index(config, value) is not None` (§4.3): `k = (value −
  min) / step` within `[−EPS, N + EPS]`. The validator (target), the gateway (answers) and
  stats all use this one test. There is no separate raw `min ≤ value ≤ max` comparison, so a
  target of `0.30000000000000004` on a 0–0.3 slider is in range everywhere.
- **Decimals** `D` = the display precision: `max(decimals(min), decimals(step))`, where
  `decimals(x)` is the smallest `d ∈ 0..6` with `|x × 10^d − round(x × 10^d)| ≤ 1e-9`. Values
  are always shown with exactly `D` decimals.
- **Percent position** `pct(k) = round(100 × k / N)`, a whole number 0–100. It's how a
  position is described when numbers are hidden (`showValue: false`): the report, the editor's
  question list and screen readers. It equals the value only on a 0–100 slider; on other ranges
  it's still the share of the way from the left end.
- Errors follow the existing conventions: Pydantic `ValueError` → 422 `VALIDATION_ERROR`, and
  socket errors via `_emit_error`.

### 4.1 Data shapes

**`config`** (public, sent to players in `new_question`; nothing secret goes here):

| key | required | rule |
|---|---|---|
| `min` | yes | valid number, `abs(min) ≤ 1e9`, at most 6 decimals |
| `max` | yes | valid number, `abs(max) ≤ 1e9`, `max > min` |
| `step` | yes | valid number, `step > 0`, at most 6 decimals |
| `showValue` | no, default `true` | `bool` |
| `unit` | no | string, 1–20 characters after stripping |
| `minLabel`, `maxLabel` | no | strings, 1–40 characters after stripping; **both or neither** |
| `promptImageId` | no | allowed as on every type (T8, existing `_validate_question_images`) |

Further rules:
- `n = (max − min) / step` must satisfy `|n − round(n)| ≤ EPS`, and `1 ≤ round(n) ≤ 10000`.
- `showValue: false` requires `minLabel` and `maxLabel`, otherwise the phone would show a bare
  track.
- Unknown keys → 422 (`optionImageIds` is already rejected for non-choice types).
- Why 1e9 and not larger: `1e9 × 10^6 = 1e15` is still below 2^53, so a 6-decimal value is
  exactly representable and the `decimals()` and `EPS` checks mean something. At 1e11 a double
  can't hold a 1e-6 step, and the grid checks pass or fail by accident.

**`answer_data`** (secret; the **same rule for both grading types**, because both show the
same reveal):

| key | rule |
|---|---|
| `target` | valid number, **in range** (§4.0) and **on the grid**: `kt = (target − min) / step` satisfies `|kt − snap(kt)| ≤ EPS`. Stored as sent; everything downstream uses its index, and the reveal sends the canonical `slider_value` |
| `fullRadius` | valid number, `0.01 ≤ fullRadius < 1` |
| `zeroRadius` | valid number, `fullRadius < zeroRadius ≤ 1` |

Unknown keys → 422. Radii are **fractions of the range** (`max − min`), so "0.05" means "within
5% of the slider's length".

**Player answer** (socket `submit_answer.answer_data`): exactly `{ "value": <number> }`.

**Example (numeric):**
```
config      = { "min": 0, "max": 100, "step": 1, "unit": "hot dogs", "showValue": true }
answer_data = { "target": 58, "fullRadius": 0.05, "zeroRadius": 0.3 }
```
**Example (spectrum):**
```
config      = { "min": 0, "max": 100, "step": 1, "showValue": false,
                "minLabel": "Ice cold", "maxLabel": "Lava" }
answer_data = { "target": 35, "fullRadius": 0.05, "zeroRadius": 0.3 }
```

### 4.2 Validation — `backend/app/schemas/admin.py`

- Add `slider` to `QUESTION_TYPE_PATTERN`. It is shared by `QuestionCreate` and
  `QuestionUpdate`.
- Add constants `SLIDER_MAX_STEPS = 10000`, `SLIDER_MIN_FULL_RADIUS = 0.01`,
  `SLIDER_MAX_ABS = 1e9`, `SLIDER_EPS = 1e-6`. The validator calls the §4.3 helpers
  (`slider_geometry`, `slider_index`) rather than repeating the maths. If importing
  `game_service` from `schemas` would create a cycle, put the pure helpers in a small module
  both can import (e.g. `services/slider_math.py`), and say so in the context docs.
- Add `_validate_slider(config, answer_data)`, implementing every rule in §4.1, and call it
  from `QuestionCreate.validate_structure` for `type == "slider"`. Like map_pin, it runs for
  both grading types.
- Error messages name the field, e.g. "slider target must be on a step (min + a whole number of
  steps)" and "slider range must be a whole number of steps, at most 10000".
- **Update symmetry is already handled.** map_pin's work made `question_service.update_question`
  merge the existing row with the PUT and re-run `QuestionCreate`, so the new branch applies to
  PUTs on both the admin and host routes with no service change. A test still covers it (§4.13).
- Slider has no image of its own, so `question_service.resolve_map_pin_image` doesn't apply.

### 4.3 Geometry and scoring — `backend/app/services/game_service.py`

Add a block of pure helpers next to the map_pin ones. They are the **only** slider maths on the
server; scoring, the gateway, distributions, stats and the report all call them.

```
slider_geometry(config) -> (min, step, N, D) | None
    None if min/max/step are missing or invalid, or the range isn't a whole number of steps
    1..10000. (Defensive: rows written by direct inserts or seed scripts skip validation.)

slider_index(config, value) -> int | None
    geometry = slider_geometry(config); None if geometry is None or value isn't a valid number
    k = (value - min) / step
    if k < -EPS or k > N + EPS: return None        # out of range → rejected
    return clamp(floor(k + 0.5), 0, N)              # snap(k), ties up (§4.0)

slider_value(config, k) -> int | float
    v = round(min + k * step, D)                     # the canonical value of index k
    return int(v) if D == 0 else v                   # 58, not 58.0, on whole-number sliders

slider_bins(N) -> int          B = min(N + 1, 20)
slider_bin(N, k) -> str        str((k * B) // (N + 1))       # integer division
    One bin per position when there are ≤ 20 positions, otherwise 20 near-equal bins
    (101 positions / 20 bins = 5 or 6 positions each).

slider_target_index(config, answer_data) -> int | None
    slider_index(config, answer_data.target), or None if it's missing or invalid

slider_distance(N, k_guess, k_target) -> float     abs(k_guess - k_target) / N
```

Scoring reuses **`map_pin_fraction(d, full, zero)`** as-is; the falloff is identical. Rename it
in this work **only if** the rename also updates every map_pin caller and unit test.
Otherwise leave it and add a one-line comment that slider uses it too.

**`calculate_score`:** add a `slider` branch next to the map_pin one. The existing empty-answer
and COMPLETENESS early returns stay first and unchanged, so COMPLETENESS gives full points and
`is_correct = True`.

```
_score_slider(question, answer_data):           # ACCURACY
    geometry = slider_geometry(config); kt = slider_target_index(...)
    radii = fullRadius, zeroRadius (valid numbers)
    any missing → log "slider_bad_question", return (0, False)
    k = slider_index(config, answer_data.value)
    k is None → log "slider_bad_answer", return (0, False)
    d = slider_distance(N, k, kt)
    return (round(points_value * map_pin_fraction(d, full, zero), 2), d <= full)
```
Defensive, like `_score_map_pin`: bad data scores 0 and never raises.

**`record_answer`:** for `slider`, `dist_key = slider_bin(N, k)`, where `k` comes from
`slider_index`. Skip when the geometry or answer is invalid.

**Reveal helper** `slider_reveal(grading_type, config, answer_data) -> dict`. Every key is
always present, with `null` for missing optional config:
```
{ "type": "slider", "gradingType": "ACCURACY" | "COMPLETENESS",
  "min", "max", "step", "showValue", "unit", "minLabel", "maxLabel",
  "target", "fullRadius", "zeroRadius" }
```
`showValue` defaults to `true` when absent. `target` is the canonical
`slider_value(config, kt)`, not the raw stored number. In **each of the four reveal copies** the `slider`
check goes **before** the `COMPLETENESS` early return, next to the map_pin check:
- `get_player_question_summary`
- `get_host_question_summary`
- `report_service._answer_reveal`
- `websocket/gateway._answer_reveal`

**Stats** `slider_stats(config, answer_data, answers) -> {withinFullPct, averageCredit}`: the
**same keys and meaning** as `map_pin_stats`. They are computed from geometry, not from points,
so they mean the same under COMPLETENESS and with `points_value == 0`:
- the denominator is the answers whose `value` gives a non-None `slider_index`;
- both are `None` when there are no such answers;
- `withinFullPct` is rounded to 1 decimal, `averageCredit` to 3.

`get_host_question_summary` returns them for slider exactly as it does for map_pin, and rebuilds
the distribution with `slider_bin`.

### 4.4 Socket gateway — `backend/app/websocket/gateway.py`

- **`on_submit_answer`**, next to the map_pin check:
  - If `answer_data` isn't exactly `{"value": ...}`, or `slider_index(question.config, value)`
    is `None` → `_emit_error(sid, "slider answer must include a value within the slider's
    range")` with **no code** (fatal on the player, like map_pin's bad-payload error; only a
    tampered client can trigger it). Don't score.
  - Otherwise **replace** `answer_data` with `{"value": slider_value(config, k)}` before
    `record_answer`. The stored `SessionScore.answer_data` is then always the canonical,
    snapped value.
- **`_answer_reveal`:** the slider branch (§4.3).
- **`_question_payload`:** no change. `config` is public by design, and the target is in
  `answer_data`, which is never sent.
- **Preloading:** none. Slider has no images beyond the generic `promptImageId`, which already
  flows through `question_image_ids`.

### 4.5 Import / export — `backend/app/routers/admin.py`

No format change; slider questions travel as plain `config` / `answer_data`. Import already
runs `QuestionCreate` on every question, so invalid slider questions are rejected with the
existing error format. Bundle version stays as it is today (v1 and v2 import; export writes
v2). Verify with a round-trip test (§4.13).

### 4.6 Report and CSV — `backend/app/services/report_service.py`, `export_service.py`

- `_answer_reveal`: the slider branch.
- `_extract_answer_key`: for `slider`, `slider_bin(N, slider_index(config, value))`. The
  function only receives `q_type` today, so give it the question's `config` too and update its
  callers.
- Type badge: `"slider": ("Slider", "badge-slider")`. Add the `badge-slider` CSS next to the
  existing badges in the report's stylesheet.
- New `_render_slider(reveal, dist)`: a horizontal bar histogram over the `B` bins in plain
  inline HTML/CSS:
  - with `showValue`: each bin labelled with its value range (formatted per §4.0, plus unit);
  - without `showValue`: the end labels only, under the first and last bin;
  - the bin containing the target highlighted, and a text line under the chart: "Target: 58
    hot dogs · full credit within ±5 hot dogs" (numeric), or "Target: 35% of the way from Ice
    cold to Lava" (spectrum, `showValue: false`; the number is `pct(kt)`, §4.0).
  - The full-credit width is `fullRadius × (max − min)`, formatted with up to `D + 2` decimals
    and trailing zeros trimmed. Plain `D` would print 0.05 × a range of 7 (step 1) as "±0";
    this prints "±0.35".
  - This target line is the **same text** the host GameOverPage shows (§4.10). Build it once
    per side: `slider_target_line(reveal)` in Python and `targetLine(reveal)` in
    `lib/slider.ts`.
- Text stats: within-target % and average credit from `slider_stats`, as for map_pin.
- `export_service` (CSV): per-question points, so no change. A test confirms slider points
  appear.

### 4.7 Simulator — `scripts/simulate_players.py`

Add a `slider` branch in the answer generator:
- with `--game-json` and the target known: with probability `p.accuracy`, a value near the
  target (Gaussian, σ = 5% of the range);
- otherwise uniform over the range;
- always clamped to `[min, max]` and snapped to the grid with the same formula as §4.3.

Extend `_answer_str` to print `value 58`, and update the module docstring's per-type list.

### 4.8 Frontend shared helper — `lib/slider.ts` (player, host, admin; byte-identical)

One file, copied into all three apps, and added to `IDENTICAL_GROUPS` in
`scripts/check_theme.py` next to `src/lib/mapPin.ts`. It is the client mirror of §4.3, and
must give the same results:

- `sliderGeometry(config) → { min, max, step, n, decimals } | null` (same rules as the
  server).
- `snapIndex(geom, value) → number`: `Math.floor((value − min) / step + 0.5)`, clamped to
  `[0, n]` (ties up, §4.0).
- `inRange(geom, value) → boolean` (the server's `slider_index(...) is not None`) and
  `onGrid(geom, value) → boolean` (the §4.1 target rule), both with `EPS`.
- `indexValue(geom, k) → number`, rounded to `decimals` (the server's `slider_value`).
- `pct(geom, k) → number` (§4.0).
- `middleIndex(geom) → Math.floor(n / 2)`, the knob's starting position.
- `binCount(n)` / `binOf(n, k)` / `binRange(geom, b) → { lo, hi }` (the index range of bin `b`:
  `lo = ceil(b × (n+1) / B)`, `hi = ceil((b+1) × (n+1) / B) − 1`).
- `sliderDistance(geom, k, kt)` and `sliderFraction(d, full, zero)` for the player's result
  label.
- `formatValue(geom, value, unit?) → string`: `toLocaleString('en-US', { minimumFractionDigits:
  decimals, maximumFractionDigits: decimals })`, plus `" " + unit` when there is a unit.
- `endLabels(config, geom) → [left, right]`: `minLabel`/`maxLabel` when set, else the
  formatted `min`/`max` with unit.
- `positionText(config, geom, k) → string`: `formatValue` with `showValue`, else
  "35% of the way from Ice cold to Lava". Used for `aria-valuetext` and the editor list.
- `targetLine(reveal) → string`: the §4.6 target line, identical to the server's.
- `freePoints(geom, kt, full, zero) → number`: `sliderFraction(sliderDistance(geom,
  middleIndex(geom), kt), full, zero)`, the share of points a player gets for not moving the
  knob (§4.11 warning).

There is no frontend test runner (`frontend/CLAUDE.md`), so record in the context docs that this
file is type-checked only. The backend unit tests (§4.13) cover the same maths.

### 4.9 Player app — `frontend/player/src/`

- **`types/game.ts`:**
  - add `'slider'` to `QuestionType`;
  - add a `SliderConfig` (§4.1 config keys) that `QuestionConfig` also extends (`Partial`);
  - add `SliderAnswer { value: number }`;
  - add a `SliderReveal` (the §4.3 shape) to the reveal union.
- **New `components/SliderInput.tsx`:**
  - Props: `config`, `index`, `onIndexChange`, `disabled`, and optional `reveal` and `myIndex`
    for results.
  - **Interactive mode:**
    - a native `<input type="range" min=0 max=n step=1>`, working **in indices**;
    - full width, with a large thumb (at least 44 px touch target), themed with tokens only;
    - `minLabel`/`maxLabel` (or the formatted ends) under the two ends;
    - with `showValue`, the current value in large type above the track;
    - − / + buttons on either side, each moving one step and disabled at the ends;
    - holding a button is **not** required in v1;
    - `aria-valuetext` = `positionText(...)`, so with `showValue: false` a screen reader hears
      "35% of the way from Ice cold to Lava", not the raw index "35"; the input's
      `aria-label` is "Your answer"; the − / + buttons are labelled "One step left/right".
  - **Reveal mode** (static, no input): a track with the player's own marker, the target
    marker, and the full-credit band shaded (`target ± fullRadius × n` indices, clamped). With
    `showValue`, values label both markers.
- **`pages/game/QuestionPage.tsx`:** a `slider` branch modelled on `MapPinQuestion`, keyed by
  `questionId`:
  - The index starts at `middleIndex(geom)`.
  - **Confirm** is enabled when the question isn't locked and nothing has been submitted yet.
    No "moved" requirement (team decision, §3).
  - Confirm sends `emitAnswer(questionId, { value: indexValue(geom, k) }, msSinceMount)`.
  - `answerRejected` handling, the "submitted — waiting" text and the "locked" text are the
    same as map_pin's.
  - No auto-submit at time-up.
  - A malformed config (`sliderGeometry` null) shows "This question can't be answered." with
    no input.
- **`pages/game/GameLayout.tsx`:** on `answer_received` for a pending `slider` answer, save it
  to `sessionStorage` under `buzzer:slider:{code}:{questionId}`, in a try/catch, mirroring the
  map_pin pin storage, so results survive a reload. The stored value is
  `JSON.stringify(value)`, the number the client sent. On read, anything that isn't a finite
  number is ignored.
- **`pages/game/ResultsPage.tsx`:** for `slider`, `SliderInput` in reveal mode. The own value
  comes from local state, falling back to `sessionStorage`. The label is computed from
  geometry, as map_pin's is:
  - no answer, or `answerRejected` → "No answer";
  - `d ≤ fullRadius` → "Spot on";
  - `d < zeroRadius` → "Close — partial credit";
  - otherwise → "Way off".
  Under COMPLETENESS, append "· full credit for answering". Points and total are shown as
  today.
- **`pages/game/GameOverPage.tsx`:**
  - The recap for `slider` counts as completeness when `gradingType === 'COMPLETENESS'`, as
    map_pin does.
  - With `showValue`, it shows "You: 42 hot dogs · Answer: 58 hot dogs".
  - Without `showValue`, it shows points earned / possible, as map_pin does.

### 4.10 Host app — `frontend/host/src/`

- **`types/game.ts`:** the same `QuestionType`, `SliderConfig` and `SliderReveal` additions.
- **`pages/game/QuestionPage.tsx`:**
  - Add `slider: 'Slider'` to `typeLabel`.
  - Under the prompt, show the **scale**: the two `endLabels` at either end of a plain track
    (no knob), large enough for the back of the room.
  - With `showValue`, also show the step when it isn't 1 (e.g. "steps of 0.5").
  - The scale hides while the question is locked, as the prompt does.
- **New `components/SliderHistogram.tsx`:**
  - Props: `reveal`, `distribution` (bin key → count).
  - Draws `B` vertical bars across the track in theme tokens; their heights are relative to
    the largest bin.
  - **One coordinate system.** Bar `b` spans `[b/B, (b+1)/B]` of the track width. Index `k`
    sits at `k/N`, which always falls inside its own bin's span. The target marker is at
    `kt/N` (its exact position, not its bin's centre), and the full-credit band at
    `[(kt − fullRadius × N)/N, (kt + fullRadius × N)/N]`, clamped to `[0, 1]`, shaded behind
    the bars.
  - **No answers** (every bin 0, or an empty distribution): no bars, the band and marker
    still drawn, and "No answers" in the chart area. Never divide by a zero maximum.
  - End labels sit under the track.
  - With `showValue`, a callout above the marker says "Answer: 58 hot dogs".
  - Without `showValue`, the marker is labelled "Target", with no number.
  - Must read from the back of a classroom in both themes and under `[data-stage]`.
- **`pages/game/ResultsPage.tsx`:** for `slider`, `SliderHistogram` instead of the bar chart,
  for both grading types. COMPLETENESS adds the "Participation — full credit for answering"
  caption, as map_pin does. (`typeLabel` lives only in `QuestionPage` and `GameOverPage`;
  nothing to add here.)
- **`pages/game/GameOverPage.tsx`:**
  - Add `slider: 'Slider'` to `typeLabel`.
  - For `slider`, show `withinFullPct` and `averageCredit` exactly as for map_pin ("—" when
    null). Generalise the map_pin condition at the stats block to
    `type === 'map_pin' || type === 'slider'`.
  - In the per-question breakdown card, a slider question does **not** render the generic
    distribution bar chart (its keys are bin numbers like `"7"`, meaningless as labels). It
    shows the `targetLine(reveal)` text in its place, plus the stats above. Correct %
    (= within `fullRadius`), response rate and average time stay as for other types.

### 4.11 Question editors — admin and host

Make these changes in **both** `frontend/admin/src/pages/QuestionEditorPage.tsx` and
`frontend/host/src/pages/manage/QuestionEditorPage.tsx`.

- **Type select:** add "Slider (closest guess)".
- **`FormState` / `defaultForm`:** `sliderMin` (0), `sliderMax` (100), `sliderStep` (1),
  `sliderUnit` (""), `sliderShowValue` (true), `sliderMinLabel` (""), `sliderMaxLabel` (""),
  `sliderTarget` (50), `sliderFullRadius` (5), `sliderZeroRadius` (30) — percentages, see
  below. Keep the existing
  map_pin radius fields separate; don't reuse them.
- **Preset buttons** above the fields:
  - **Numeric** sets `showValue: true` and leaves the range alone.
  - **Spectrum** sets min 0, max 100, step 1, `showValue: false`, clears the unit, and fills
    the labels with "Cold" / "Hot" **only if they are empty**.
  Presets only fill fields; nothing about them is saved. A preset changes the range, so the
  target snapping rule below applies to it too.
- **Points:** an entered points value, exactly as map_pin's (same input, default and limits).
  Slider has no per-option points to derive it from, so the `points_value` derivation used
  for multiple_choice etc. doesn't apply.
- **Fields:** min, max and step (number inputs), unit, the two end labels, a "Show numbers to
  players" checkbox, and the two radii.
- **Radii are entered as percentages.** The author types `5` for 5% of the range. Inputs:
  `fullRadius` 1–99, `zeroRadius` up to 100, `step="any"`, labelled "Full credit within ±…%"
  and "No credit beyond ±…%". `formToPayload` divides by 100 and rounds to 6 decimals;
  `questionToForm` multiplies by 100. The `FormState` fields therefore hold percentages
  (defaults 5 and 30), not fractions.
- **Target:** a live preview of the player's slider: a plain `<input type="range">` in
  indices, built in the editor with the app's copy of `lib/slider.ts`, **not** the player's
  `SliderInput` component (that lives only in the player app). Dragging it sets `sliderTarget`,
  so the target is always on the grid. A number input next to it shows the snapped value.
  Typing an off-grid value shows the same error the server would.
- **When the range changes** (min, max or step committed on blur, or a preset clicked; not on
  every keystroke, because typing "100" into max passes through 1 and would clamp the target):
  - if the new geometry is valid, `sliderTarget` is **re-snapped and clamped** to the new grid
    (`indexValue(geom, clamp(snapIndex(geom, target), 0, n))`), silently;
  - if the new geometry is invalid (e.g. max ≤ min while typing), the target is left as it
    is, the preview is replaced by the geometry error, and saving is blocked until it's fixed.
- **Client checks** (block saving, with the message shown): every §4.1 rule, so the form
  rarely hits a server 422. The server stays authoritative.
- **Warnings** (shown, never block):
  - not moving earns points (`freePoints(...) > 0`): "Players who don't move the slider get
    N% of the points" (N = `round(100 × freePoints)`). Checking only `fullRadius` would miss
    most of the risk: with the default radii, any target within 30% of the middle (60% of
    all targets) gives a player who doesn't move some points. For example, a target at 60% of
    the range gives them 80%;
  - `showValue` on with no unit: "Consider a unit so players know what they're guessing".
- **`formToPayload`:**
  - `config = { min, max, step, showValue }`, plus `unit` / `minLabel` / `maxLabel` only when
    non-empty, plus `promptImageId` as today;
  - `answer_data = { target, fullRadius, zeroRadius }` for both grading types (radii as
    fractions, see above).
- **`questionToForm`:** the reverse. Missing `showValue` → `true`.
- **List rendering:** "Slider — 0–100 hot dogs, target 58, ±5% → 30%", or for a spectrum
  "Slider — Ice cold ↔ Lava, target 35%" (`pct(kt)`, §4.0).

### 4.12 Context docs

Per `.claude/rules/context-sync.md`, update the `CLAUDE.md` files that describe question types
and identical groups. That means at least `backend/app/schemas/`, `services/` and `websocket/`,
`frontend/CLAUDE.md` (the "Adding a question type" gotcha and the byte-identical list), and the
player/host `pages/` and `components/` files.

### 4.13 Tests

**Unit — `tests/unit/test_slider_math.py`** (pure helpers, no stack):
1. `slider_geometry`:
   - 0–100 step 1 → N = 100;
   - 0–1 step 0.1 → N = 10;
   - 0–0.3 step 0.1 → N = 3 (float noise);
   - 0–10 step 3 → None (not whole);
   - 0–1e6 step 1 → None (> 10000 steps).
2. `slider_index`:
   - snaps 57.4 → 57 and 57.6 → 58;
   - **ties round up:** 56.5 → 57 and 57.5 → 58 (Python's `round` would give 56 for the
     first);
   - `min − 1` → None;
   - `max + 1` → None;
   - exactly `min` → 0 (a value of `0` is a real answer, not an empty one);
   - exactly `max` → N;
   - `0.30000000000000004` on 0–0.3 step 0.1 → 3 (in range by `EPS`);
   - NaN, `"5"` and `True` → None.
3. `slider_value`:
   - 0–0.3 step 0.1, index 3 → `0.3` exactly, not `0.30000000000000004`;
   - 0–100 step 1, index 58 → `58` as an `int`.
3a. Target line: 0–7 step 1, `fullRadius` 0.05 → "±0.35", not "±0"; spectrum target 35 on
   0–100 → "Target: 35% of the way from Ice cold to Lava".
4. `slider_bin`: N = 10 → 11 bins, bin = k. N = 100 → 20 bins: k = 0 → "0", k = 100 → "19",
   and the bins cover 0..100 with no gaps.
5. The §4.1 validator: every rule has one rejecting case and one accepting case, including
   "`showValue: false` without labels", "only one label", "target off-grid", "radius 0.009",
   "`min` = 2e9" (over the 1e9 limit) and "target `0.30000000000000004` on 0–0.3" (accepted).

**Integration — `tests/integration/test_slider.py`** (against the live stack, using
`conftest.py` and the `t4_helpers.py` game helpers):
1. **Create validation (admin and host routes):** a valid numeric and a valid spectrum
   question → 201. An off-grid target, `fullRadius ≥ zeroRadius`, `max ≤ min`, 10001 steps,
   or a missing `target` under COMPLETENESS → 422.
2. **Update symmetry:** a PUT changing only `answer_data.target` to an off-grid value → 422,
   and the row is unchanged. A PUT changing `type` from `multiple_choice` to `slider` without a
   slider config → 422. A valid PUT → 200. Covered on both admin and host routes.
3. **Scoring** (drive a real game; 0–100 step 1, target 50, full 0.05, zero 0.30,
   `points_value` 10):
   - value 50 → 10 points, `is_correct`;
   - value 55 (d = 0.05, at the boundary) → 10, `is_correct`;
   - value 67.5 → snapped to 68, d = 0.18 → `10 × (1 − 0.13/0.25)` = 4.8 points, not correct;
   - value 80 → 0 points;
   - on a second question with target 0: value 0 → 10 points, `is_correct` (guards against
     the existing empty-answer check treating `{value: 0}` as empty);
   - the leaderboard total includes the 4.8 (floats end to end).
4. **COMPLETENESS:** a value of 100 against target 50 → full points, and the reveal still
   carries `target` and both radii.
5. **Socket validation:** `{value: 101}`, `{value: "50"}`, `{value: null}`, `{}`,
   `{value: 50, extra: 1}` and a raw `NaN` → `error`, and no `SessionScore` row.
6. **Canonical storage:** submit `0.30000000000000004` to a 0–1 step 0.1 question → the stored
   `answer_data` is `{"value": 0.3}`.
7. **Distribution and reveal:** after several answers, the host's `question_results` has bin
   keys matching `slider_bin`, and the reveal has every §4.3 key (optional ones `null`). The
   host summary at game over has `withinFullPct` and `averageCredit` with the expected values.
8. **Import/export:** export a game containing both slider presets, then import it → identical
   `config` / `answer_data`. Importing a bundle with an off-grid target → 422.
9. **Report and CSV:** the HTML report for a session with a slider question contains the
   slider badge and the target line. The CSV includes the slider points.

### 4.14 Sample games (T6)

Not part of this spec's implementation, but it unblocks them: each member's party game must
contain at least one slider question. Ship both presets in the first one (see §4.1 examples).

## 5. Out of scope

- Logarithmic sliders; prefix units (`$58`); several targets or target ranges.
- Holding the − / + buttons to repeat.
- Any scoring that looks at other players' answers.
- Server-measured answer time (the existing gotcha, unchanged).

## 6. Known risks

- **The middle default gives free points** when the target is near the middle, and more of
  them than it first looks. With the default radii, a player who never moves gets partial
  credit for any target within 30% of the middle, which is 60% of possible targets. A
  target at 60% of the range gives them 80% of the points. It's accepted and mitigated by an
  editor warning only, and the warning names the exact free share (§4.11).
- **Phone slider precision:** at 10,000 steps a drag lands only within about 30 steps, so
  hitting the exact target takes − / + taps. Full credit covers at least 1% of the range
  (minimum `fullRadius`, about 100 steps at the cap), so precision affects bragging, not
  scoring.
- **Spectrum targets are subjective.** Generous default radii and a clear reveal are the
  mitigation; arguing about it is part of the party.
- **The frontend maths isn't tested** (no runner). The backend tests cover the same formulas,
  and §4.8 requires the client copy to match them line for line.

## 7. Goldfish revisions (2026-10-06)

A fresh session read the spec and the context hierarchy, with no access to the design
discussion. Changes made in response:

| Gap found | Resolution |
|---|---|
| No `points_value` input specified for slider | Entered, like map_pin (§4.11) |
| Python `round` (ties to even) ≠ JS `Math.round` (ties up) | `snap(k) = floor(k + 0.5)` on both sides (§4.0, §4.3, §4.8); tie tests added |
| "In range" defined as both a raw comparison and an `EPS` index check | One definition through `slider_index` (§4.0, §4.1); the reveal sends the canonical target |
| Host GameOverPage would chart bin numbers as labels | Breakdown card shows the target line instead of the distribution chart (§4.10) |
| Editor target undefined after a range change or preset | Re-snapped and clamped when the geometry is valid; otherwise blocked (§4.11) |
| Spectrum "35%" had no formula | `pct(k) = round(100 × k / N)` (§4.0) |
| Middle-default warning only checked `fullRadius` | Warns whenever not moving earns points, and names the share (§4.11, §6) |
| Full-credit width could print "±0" | Up to `D + 2` decimals, trailing zeros trimmed (§4.6) |
| `abs ≤ 1e12` too large for 6-decimal exactness | Lowered to 1e9 (§4.1) |
| Radius inputs: percent or fraction? | Percent in the form, fraction in the payload (§4.11) |
| Screen readers would read raw numbers on a spectrum | `aria-valuetext` = `positionText` (§4.9) |
| Smaller gaps | Empty-histogram state and one bar/marker coordinate system (§4.10); scale hidden while locked; editor preview is a plain range input; `sessionStorage` format; `typeLabel` location; `slider_value` returns `int` when `D = 0`; value-0 scoring test |

## 8. Implementation notes (2026-10-06)

Where the code differs from, or adds to, the text above:

- **`services/slider_math.py`** holds every pure helper (§4.2 allowed this). `game_service`
  imports `schemas.admin`, so the validator couldn't import `game_service`. `game_service`
  keeps only the pieces that need `map_pin_fraction` or the question row (`slider_reveal`,
  `slider_stats`, `slider_answer_index`, `slider_dist_key`, `_score_slider`).
- **`slider_geometry` returns `(min, max, step, N, D)`**: `max` is needed for formatting.
- **Range re-snap on blur** in the editors (§4.11 now says so).
- **`points_awarded` is a single-precision column**, so a slider total such as 4.8 + 10 reads
  back as 14.800000190734863. This existed before; the integration test compares with a
  tolerance.
- **Found while clicking through, not fixed (out of scope):** both game apps' `GameLayout`
  socket effect depends on `[code, navigate]`, and `navigate` changes on every route change,
  so the socket reconnects on every phase navigation. An event that arrives in that gap is
  lost; in one headless run a player missed its `question_results`.
