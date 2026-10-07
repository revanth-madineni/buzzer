# T6 — Sebastian's sample games (sbmarcus2)

Status: **spec, not built**. Branch `feat/t6-sbmarcus2-sample-games` (off the slider branch, so
the `slider` type exists when the files are imported).

## 1. Problem

T6 (`instructions.md`) asks each member for two game JSON files under `sample_games/`: one
**classroom** game (educational, professional tone) and one **party** game (fun, broadly
accessible). Each game must import cleanly and use both `ACCURACY` and `COMPLETENESS`.

**Agreed reading of the type rule:** *every* game includes at least one question of *every*
supported type — the four originals **and** the team's two T7 types, `map_pin` and `slider`.
This is stricter than the minimum ("each new type in at least one game per member") and
satisfies both readings.

Also agreed: at least one `map_pin` or `slider` question per game uses `COMPLETENESS`, so both
grading types are shown on the new types.

## 2. Technical plan

Two hand-authored **version-2** bundles (every game has a `map_pin`, and `map_pin` needs an
embedded image):

| File | Title | Questions |
|---|---|---|
| `sample_games/sbmarcus2_intro_stats_classroom.json` | Intro Statistics: Reading the Data | 10 |
| `sample_games/sbmarcus2_ballpark_party.json` | Ballpark: The Guessing Game | 11 |

- **Classroom** is built around the instructions' own example, *Guess the Correlation*: estimate
  r from a scatter plot on a slider (full credit within ±0.05, nothing beyond ±0.10). The
  `map_pin` questions are on generated charts ("tap the outlier", "tap the bar that contains
  the median").
- **Party** is an estimation night: mostly sliders with numeric answers people argue about,
  plus two `map_pin` questions on the existing `sample_games/assets/us-map.png`.
- **The MR contains JSON only** (plus this spec). The classroom charts are drawn once by a
  throwaway script in the session scratchpad that is **not committed**. To keep the answers
  checkable anyway, §6 (Build record) is filled in at build time with each chart's data
  summary.
- **Facts must be stable.** No current records, no "% of people" survey numbers, nothing that
  changes year to year. Every fact has a source in §5.

## 3. Alternatives considered

- **Food-themed party game ("Snack Attack", an earlier draft).** Dropped: it nearly duplicates
  the starter game `food_myths_and_facts.json`, and its pepper "spectrum" question had no
  defensible answer (linear vs. log Scoville scale gives 0% vs. ~60%).
- **Spectrum sliders (`showValue: false`) for opinions.** Dropped: the reveal always shows a
  "Target", even under `COMPLETENESS`, so an opinion poll would look like it had a right answer.
  No spectrum sliders in either game.
- **A box-plot "tap the median" `map_pin`.** Dropped: a median is a line segment and `map_pin`
  has one point target, so a correct tap at the end of the line would score badly. Only
  point-like targets (a dot; the top-centre of a bar).
- **Committing the chart generator under `scripts/`.** Reproducible, but it adds code to
  review and lint (CI pins ruff 0.15.21) to what should be a content MR. Decided against;
  §6 is the substitute.
- **Map_pin only in the classroom game, party version 1.** Lighter file, but fails the agreed
  "every game, every type" rule.
- **A new map image for the party game.** No source or licence to check; reusing the team's
  existing asset is simpler. (Its provenance is still an open item; §7 has the gate and a
  public-domain fallback.)

## 4. Detailed implementation

### 4.1 Bundle shape (both files)

```
{ "format": "buzzer/game", "version": 2,
  "game": { "title", "description", "max_players": 150 },
  "questions": [ ... ],
  "images": [ { "id", "mime_type": "image/png", "alt_text", "data": <base64> } ] }
```

- Top-level key order is exactly `format, version, game, questions, images` (the order of the
  existing `madineni_us_geography_classroom.json` and of the server's export). Question keys:
  `type, grading_type, prompt, config, answer_data, time_limit_seconds, points_value`.

- Image IDs are readable strings (allowed for bundles): `scatter-warmup`, `scatter-negative`,
  `scatter-outlier`, `histogram-wait`, `us-map`. Import replaces them with UUIDs.
- `map_pin` config: `{ "imageId": "<id>" }` only; the server fills `imageWidth`/`imageHeight`.
- `slider` prompt images go in `config.promptImageId`.
- Field names and the per-type `config`/`answer_data` shapes are those in
  `backend/app/schemas/CLAUDE.md` ("Question structure rules"). For MC / TF / multi-select,
  `answer_points` hold the actual points and `points_value` equals the best achievable total
  (the convention of the starter games). Multi-select uses −1 for wrong options.
- `COMPLETENESS` questions: `answer_data: {}`, except `map_pin`/`slider`, which still need their
  target and radii (both grading types show the same reveal).
- Map radii are in **image-width units**; slider radii are **fractions of the range**.
- **Alt text, verbatim** (neutral: no trend, no answer, no state names):

  | Image id | `alt_text` |
  |---|---|
  | `scatter-warmup` | Scatter plot of 50 points; x axis Hours studied, y axis Exam score. |
  | `scatter-negative` | Scatter plot of 50 points; x axis Hours of screen time, y axis Hours of sleep. |
  | `scatter-outlier` | Scatter plot of 40 points; x axis Hours studied, y axis Exam score. |
  | `histogram-wait` | Histogram of 50 customers; x axis Minutes waited in 5-minute bins from 0 to 40, y axis Number of customers. |
  | `us-map` | Outline map of the contiguous United States showing state borders, with no labels. |

### 4.2 Points and time limits

| Kind | `points_value` | `time_limit_seconds` |
|---|---|---|
| slider / map_pin, ACCURACY | 2 | 30 |
| slider / map_pin, COMPLETENESS | 1 | 30 |
| multiple_choice | 1 | 20 |
| true_false | 1 | 15 |
| fill_in_the_blank | 1 | 25 |
| multi_select | 3 | 30 |

The new types are worth 2 because they take longer to answer and give partial credit.

### 4.3 Classroom — "Intro Statistics: Reading the Data"

Description: *"Read scatter plots, histograms and summary statistics the way a statistician
would: estimate, locate, and explain."*

Correlation sliders all use `min −1, max 1, step 0.01, showValue true` (no unit).
N = 200 steps, so 0.025 of the range = ±0.05 in r and 0.05 = ±0.10 in r.

| # | Type | Grading | Prompt | Answer / config |
|---|---|---|---|---|
| 1 | slider | COMPLETENESS | "Warm-up (everyone scores): estimate the correlation coefficient r for this scatter plot." | image `scatter-warmup`; target **0.78**; fullRadius 0.025, zeroRadius 0.05 |
| 2 | slider | ACCURACY | "Estimate the correlation coefficient r for this scatter plot." | image `scatter-negative`; target **−0.45**; fullRadius 0.025, zeroRadius 0.05 |
| 3 | slider | ACCURACY | "In a normal distribution, about what percentage of values lie within one standard deviation of the mean?" | min 0, max 100, step 1, unit `%`; target **68**; fullRadius 0.02 (±2), zeroRadius 0.10 (±10) |
| 4 | map_pin | ACCURACY | "One point doesn't follow the pattern. Tap the outlier." | image `scatter-outlier`; target = the outlier's centre; fullRadius 0.025, zeroRadius 0.07 |
| 5 | map_pin | ACCURACY | "Tap the top edge of the bar that contains the median wait time." | image `histogram-wait`; target = top-centre of bar 3 (10–15 min); radii from the bar pitch (below) |
| 6 | multiple_choice | ACCURACY | "Which measure of center is least affected by extreme outliers?" | Mean / **Median** / Mode / Range → `[0,1,0,0]` |
| 7 | true_false | ACCURACY | "A correlation of r = −0.9 describes a weaker linear relationship than r = 0.5." | **false** → `{"true":0,"false":1}` |
| 8 | fill_in_the_blank | ACCURACY | "The middle value of an ordered data set is called the ___." | accepted `["median"]`, points `[1]`, editDistance 1 |
| 9 | multi_select | ACCURACY | "Which of these measure the spread of a data set? Select all that apply." | **Range**, **Standard deviation**, Mean, **Interquartile range**, Mode → `[1,1,-1,1,-1]` |
| 10 | multiple_choice | COMPLETENESS | "Which topic would you like to review next class?" | Correlation / Measures of center / Measures of spread / Reading histograms |

**Charts** (PNG, 1200 × 800, white background, dark axes, no title, no gridlines):
- **No chart may give away its answer.** No r value, no regression line, no highlighted point,
  no median marker. Alt text describes the chart neutrally, e.g. *"Scatter plot of 50 points;
  x axis Hours studied, y axis Exam score"*, without the trend. (This is a deliberate trade-off:
  a screen-reader user can't answer these from the alt text alone.)
- `scatter-warmup`: n = 50, "Hours studied" vs "Exam score", sample Pearson r within ±0.005
  of **0.78**.
- `scatter-negative`: n = 50, "Hours of screen time" vs "Hours of sleep", sample r within
  ±0.005 of **−0.45**.
- Hit the target r exactly by construction (e.g. orthogonalise the noise against x and scale
  it), not by retrying seeds.
- `scatter-outlier`: n = 40, a strong positive trend (r ≈ 0.9 without the outlier) plus **one**
  point far below the trend, placed in the middle of the x range. It must be at least 0.10
  image widths from every other point, so there is only one sensible tap. Markers about
  0.012 image widths across.
- `histogram-wait`: "Minutes waited" (bins 0–5, 5–10, …, 35–40) vs "Number of customers";
  counts **[14, 10, 8, 6, 5, 4, 2, 1]** (n = 50, right-skewed). The 25th and 26th values both
  fall in bar 3 (10–15 min; the running total is 14, 24, 32), while the tallest bar is bar 1.
  The question tests the "median = peak" misconception.
  - Target: the top-centre of bar 3.
  - fullRadius = 0.45 × bar pitch; zeroRadius = 1.0 × bar pitch, so a tap on a neighbouring
    bar's top-centre scores 0. Bar pitch is the distance between neighbouring bar centres, in
    image widths, measured on the rendered image.
  - Bars touch (no gaps, width = pitch) with a dark outline; y axis fixed at 0–16 with
    ticks every 2. A tap on the edge of bar 3's top (0.5 pitch out) still gets partial credit.
  - **Accepted consequence:** a tap in the middle of bar 3, rather than on its top edge,
    lands roughly 0.1+ widths below the target and scores little or nothing. The prompt says
    "top edge" for that reason; the reveal shows the target, so the rule is learnable.
- Map targets are the **rendered** pixel positions divided by width/height, read from the
  plotting library's transform. Never estimate them by eye.

**Free-points check.** An untouched slider sits at the middle (r = 0; 50%). Q2's target
(−0.45) is 0.225 of the range from the middle, and Q3's (68) is 0.18 away, both beyond
zeroRadius, so leaving the knob alone scores 0. Q1 is COMPLETENESS, so it doesn't matter.

### 4.4 Party — "Ballpark: The Guessing Game"

Description: *"Close enough counts. Slide, tap and guess your way through history, the human
body and the map."*

| # | Type | Grading | Prompt | Answer / config |
|---|---|---|---|---|
| 1 | slider | COMPLETENESS | "Warm-up (everyone scores): in what year was the first Super Bowl played?" | 1950–2000 step 1; target **1967**; fullRadius 0.02 (±1 yr), zeroRadius 0.10 (±5 yr) |
| 2 | slider | ACCURACY | "In what year did the Titanic sink?" | 1800–2000 step 1; target **1912**; fullRadius 0.01 (±2 yr), zeroRadius 0.05 (±10 yr) |
| 3 | slider | ACCURACY | "How many keys are on a standard modern piano?" | 0–300 step 1, unit `keys`; target **88**; fullRadius 0.017 (±5), zeroRadius 0.08 (±24) |
| 4 | slider | ACCURACY | "How many bones are in the adult human body?" | 0–500 step 1, unit `bones`; target **206**; fullRadius 0.02 (±10), zeroRadius 0.07 (±35) |
| 5 | map_pin | ACCURACY | "Roswell, New Mexico — home of the famous 1947 'UFO crash'. Tap where Roswell is." | image `us-map`; target Roswell (33.39° N, 104.52° W); fullRadius 0.03, zeroRadius 0.10 |
| 6 | map_pin | COMPLETENESS | "Everyone scores: where is the geographic center of the contiguous United States? Take a guess." | image `us-map`; target near Lebanon, Kansas (39.83° N, 98.58° W); fullRadius 0.03, zeroRadius 0.10 |
| 7 | multiple_choice | ACCURACY | "Which country spans the most time zones (counting overseas territories)?" | Russia / United States / **France** / China → `[0,0,1,0]` |
| 8 | true_false | ACCURACY | "Bananas are slightly radioactive." | **true** → `{"true":1,"false":0}` |
| 9 | fill_in_the_blank | ACCURACY | "The little plastic tube on the end of a shoelace is called an ___." | accepted `["aglet"]`, points `[1]`, editDistance 1 |
| 10 | multi_select | ACCURACY | "Which of these animals are mammals? Select all that apply." | **Dolphin**, Shark, **Bat**, Penguin, **Platypus** → `[1,-1,1,-1,1]` |
| 11 | multiple_choice | COMPLETENESS | "Most important party snack — go:" | Chips & salsa / Pizza / Candy / Veggie tray (bold choice) |

- **Free-points check.** The slider ranges are chosen so the range itself doesn't hint at the
  answer, and so leaving the knob at the middle scores 0. Each middle is beyond zeroRadius:
  - Q2: 1900 is 12 years off, beyond ±10. (A 1850–2000 range was rejected: its middle, 1925,
    is only 13 years off.)
  - Q3: 150 is 62 off, beyond ±24.
  - Q4: 250 is 44 off, beyond ±35.
  - Q1 (1975, 8 off, beyond ±5) is COMPLETENESS anyway.
- **Q5 names the state on purpose.** Party players get a foothold ("New Mexico"); the skill
  tested is placing Roswell within it, and zeroRadius ≈ "the right state or a neighbour"
  means knowing the state alone earns only partial credit.
- **`us-map` targets.** The map has state outlines and no labels or graticule, so place targets
  relative to state borders measured on the full-resolution image (3580 × 2282) with this
  recipe, which tolerates a tilted-meridian projection:
  1. Make a first-guess pixel from the rough numbers below.
  2. **x:** on that pixel row, find the state's west and east border pixels; interpolate
     linearly by longitude between the borders' longitudes
     (New Mexico 109.05° W – 103.04° W; Kansas 102.05° W – 94.6° W at that latitude;
     use the border actually crossed on the row).
  3. **y:** on the resulting pixel column, find the state's north and south border pixels;
     interpolate linearly by latitude (New Mexico 37° N – 32° N; Kansas 40° N – 37° N).
  4. Repeat steps 2–3 once from the new pixel; stop when it moves less than 5 px.
  5. Target = pixel ÷ (3580, 2282). Confirm with the overlay check (§4.5 step 4).
  - **Roswell:** about 1.5° west of New Mexico's east border (103° W) and about 1.4° north of
    its southern border along the Texas line (32° N). Roughly (0.39, 0.68).
  - **Lebanon, KS:** about 3.4° east of Kansas's west border (102° W), just south of the
    Kansas–Nebraska border (40° N). Roughly (0.50, 0.47).
  - The rough numbers come from a downscaled preview and are a sanity check only. The real
    values come from the border measurement. A final target more than 0.03 from its rough
    number means a border was misread; re-measure.
  - New Mexico is about 0.10 image widths wide, so fullRadius 0.03 is "the right corner of the
    right state" and zeroRadius 0.10 is "the right state or a neighbour".

### 4.5 Build and verification (all in the scratchpad; nothing but the two JSONs, this spec and its §6 committed)

1. Draw the four charts. Record the §6 values from the actual data and rendered positions.
2. Measure the two `us-map` targets on the full-resolution image.
3. Write both bundles, embedding `us-map.png` byte-for-byte from `sample_games/assets/`.
   - JSON indented with 2 spaces, key order like the existing v2 file, `ensure_ascii` off.
   - Each image ≤ 2 MB; the bundle well under 25 MB.
4. **Overlay check (by eye):** for every `map_pin`, render the target with both radius circles
   on its image and look at it. For `scatter-outlier`, confirm only the outlier is inside
   zeroRadius.
5. **Import check:** import both files through the admin API (`course_id` as a form field)
   into a course named **"Sample games"** on the running stack. If it doesn't exist, create it
   once through the admin API; never a throwaway test course (see the course-leak note in §7).
   Expect success, 10 and 11 questions, and 4 and 1 images.
6. **Play check:** host each game once with `scripts/simulate_players.py`, and click through
   every question's reveal on the host to confirm the images, sliders and target lines render
   in both themes.
7. Fill in §6, then commit the two JSONs and this spec together.

## 5. Sources

| Fact | Source |
|---|---|
| 68 % within 1 SD (68–95–99.7 rule) | OpenIntro Statistics, 4th ed., §4.1 |
| Median is resistant to outliers; mean is not | OpenIntro Statistics, 4th ed., §2.1 |
| \|r\| measures strength; sign is direction | OpenIntro Statistics, 4th ed., §8.1 |
| Range, SD, IQR measure spread | OpenIntro Statistics, 4th ed., §2.1 |
| First Super Bowl: 15 Jan 1967 | NFL.com, Super Bowl history |
| Titanic sank 15 Apr 1912 | Encyclopaedia Britannica, "Titanic" |
| Standard modern piano: 88 keys | Encyclopaedia Britannica, "piano" |
| Adult human skeleton: 206 bones | Encyclopaedia Britannica, "human skeleton" |
| Roswell incident 1947; Roswell at 33.39° N 104.52° W | Britannica, "Roswell incident"; USGS GNIS |
| Geographic center of contiguous US near Lebanon, KS (39°50′ N, 98°35′ W) | USGS / National Geodetic Survey |
| France spans 12 time zones (most of any country) | CIA World Factbook, France: "Time difference" note |
| Bananas contain radioactive potassium-40 | Health Physics Society, "banana equivalent dose" |
| "Aglet" | Merriam-Webster |
| Dolphins, bats, platypuses are mammals; sharks, penguins are not | Encyclopaedia Britannica |

**Overlap check (done).** None of these facts appear in the existing `sample_games/`.
Octopus hearts, flamingo collective nouns, honey and banana-berries were considered and dropped
because `surprising_facts.json` already uses them.

## 6. Build record (filled in at build time)

| Item | Value |
|---|---|
| `scatter-warmup` | n, actual r (3 dp), x/y ranges |
| `scatter-negative` | n, actual r (3 dp), x/y ranges |
| `scatter-outlier` | n, r without / with outlier, outlier data coords, target (x, y), nearest other point's distance |
| `histogram-wait` | counts, bar pitch, target (x, y), radii |
| `us-map` Roswell | target (x, y) and how it was measured |
| `us-map` Lebanon, KS | target (x, y) and how it was measured |
| `us-map` source | `sample_games/assets/us-map.png` (provenance confirmed by Revanth) or the Census fallback (§7) |
| Import check | course, result, question/image counts |

## 7. Risks and open items

- **`us-map.png` provenance is unknown.** Revanth added it (`2601bfe`) with no source or
  licence. Ask Revanth now. The build does not wait: build and verify with `us-map.png`.
  **Gate before opening the MR:** if the source and licence aren't confirmed by then, switch
  this game to the fallback below and re-run §4.5 steps 3–6 for the party file.
  - **Fallback map:** in the scratchpad, render the contiguous US state outlines from the
    US Census Bureau cartographic boundary file `cb_2018_us_state_20m` (public domain,
    US government work) in the same style (outlines only, no labels, white background),
    at 3580 × 2282 or smaller, ≤ 2 MB. Same id `us-map` and same alt text. Targets then come
    straight from the plotting transform of the two coordinates in §5 (no border
    interpolation needed); the radii are unchanged. Record the source in §6.
  - Revanth's own game is theirs to fix; tell them the outcome.
- **The charts can't be regenerated by a TA**, because the script isn't committed. §6 is the
  mitigation; it makes the answers checkable but not reproducible.
- **"Counting overseas territories" (party Q7)** is the only fact with a definitional caveat.
  The prompt states the condition explicitly; without it the answer would be Russia.
- **Alt text vs. answerability.** Chart alt text is neutral, so screen-reader users can't
  answer the chart questions. That's accepted for a visual-estimation game. The map questions
  have the same limit.
- **Course list.** The dev database already has ~713 leftover test courses (no
  course-delete path). Import into one named real course, so this work adds no more litter.
- **Team overlap.** Revanth's party game doesn't exist yet. Tell them this one is a
  slider-heavy estimation game, so theirs can differ.
