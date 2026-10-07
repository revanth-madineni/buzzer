# Individual Report — sbmarcus2 (Sebastian Marcus)

## Repository and Codebase Organization

Buzzer is three React apps talking to one FastAPI backend. The **host** app is the big screen (projector), the **player** app is the phone, and the **admin** app is for managing users, courses, games and access. In production nginx serves all three as static builds under `/host/`, `/player/` and `/admin/`, and forwards `/api/` and `/socket.io/` to the backend. Everything runs in Docker: the backend, MySQL, Redis and nginx.

The backend (`backend/app/`) is split by job:
- `routers/` are the HTTP endpoints (admin, host, auth, game). They check who you are and hand off to services.
- `services/` is where the actual logic lives: scoring (`game_service.py`), live game state in Redis (`state_service.py`), images, reports, exports. The slider math lives in its own pure file (`slider_math.py`) so the schemas can validate with it without an import cycle.
- `websocket/` is the live game loop over Socket.IO. `events.py` has every event name, and `gateway.py` has the handlers.
- `models/` are the SQLAlchemy tables, and `schemas/` are the Pydantic shapes. The per-question-type validation rules (what a slider's `config` and `answer_data` must look like) live in `schemas/admin.py`.
- `common/` holds shared plumbing like auth dependencies and error types.

The rest of the repo: `sample_games/` holds the importable game JSON, `scripts/` has the seeding, simulating and checking tools, `tests/integration/` runs pytest against the live Docker stack, `docs/plans/` has the design specs, `ai_log/` has the session logs, and `.claude/` has the skills and rules we used for the design process.

The main split to keep in your head: **Redis holds what is happening right now, and MySQL holds the permanent record.**

**Flow of a game round** (using my slider type as the example):
- The host picks a course and a game on the home page, which `POST`s `/api/game/rooms` and lands them in the lobby with a room code.
- Players join on their phones (room code → name → guest login), open a socket, and emit `join_room`. The host's lobby count goes up as `player_joined` comes in.
- The host clicks Start, which emits `host_advance`. The gateway starts the game and broadcasts `new_question` to the whole room. The payload includes the question's `config` (for a slider: min, max, step, unit), but **never** `answer_data`, so the answer is never in a browser.
- A player slides the knob and hits Confirm, which emits `submit_answer` with `{value: -0.38}`. The gateway checks that it's a real player, that a question is open and not locked, that it's the right question, and that the player hasn't already answered. Only then does it call `game_service.record_answer`.
- `record_answer` dispatches on the question type. For a slider, it snaps the value to a step index, takes the distance to the target as a fraction of the range, and gives full points inside `fullRadius`, nothing past `zeroRadius`, and a linear falloff in between. The answer is written to MySQL, and the running score goes into Redis.
- The server then sends three different messages: `answer_received` to that player only, `answer_status` ("12/21 answered") to the host only, and `answer_phase_ended` to the host if that was the last player. The question timer doesn't advance anything; it just locks the question.
- The host clicks Show Results, which is another `host_advance`. The server broadcasts `question_results` with the reveal: the target and the histogram for the host, and each player's own outcome ("Close — partial credit") on their phone.
- Next Question repeats this, and after the last question the server sends `game_over`. Reports and CSV exports are built later from the MySQL record.

**Context files.** We used nested `CLAUDE.md` files instead of READMEs, built bottom-up. I wrote the frontend side for the host and admin apps:
- `frontend/host/src/{lib,components,pages}/CLAUDE.md` and `frontend/admin/src/{lib,components,pages}/CLAUDE.md`
- the roll-ups for `frontend/host/src/`, `frontend/admin/src/` and `frontend/CLAUDE.md`

Revanth did the backend and player ones. I later kept a lot of both halves up to date as T8 images and the slider changed them (schemas, services, websocket, and all three apps' pages, components and lib).

The thing I learned writing them is how much is duplicated across the apps on purpose. The host's question editor is an adapted copy of the admin one that has to be kept in sync by hand. Some lib files (`slider.ts`, `AuthImage.tsx`, `ThemeToggle.tsx`) are byte-identical in all three apps, and the backend's `slider_math.py` is mirrored formula for formula in TypeScript. You can't see any of that from inside a single file. Writing it down in the context docs is what kept later AI sessions (and me) from changing one copy and forgetting the other. I also learned that the host's `RequireAuth` only checks that a token exists, which matters when you're reasoning about access control.

## Design Process (Elephant/Goldfish)

I followed the Elephant/Goldfish process for everything I designed, using the repo's skills: `design-discussion` → `write-spec` → `goldfish-test` in a fresh session → revise → implement. My design docs:
- [docs/plans/t8-images.md](plans/t8-images.md): image support (T8)
- [docs/plans/t7-slider.md](plans/t7-slider.md): the slider question type, our party type (T7)
- [docs/plans/t6-sbmarcus2-games.md](plans/t6-sbmarcus2-games.md): my two sample games (T6)
- [docs/plans/course-delete.md](plans/course-delete.md): an admin course delete, so the tests can clean up after themselves (T5)

**T8 images.** The Elephant session started from instructions.md and the codebase, and the design discussion was mostly me answering its questions:
- Prompt images are projector-only.
- Options can mix images and text.
- Phones get the real alt text, and the editor warns when alt text is missing.

The goldfish test found real holes:
- lock ordering between image deletes and question edits, which could deadlock and needed to become a clean 409;
- what happens to images when a game moves between courses (the Elephant had them stay behind; we decided exclusive images move with the game and shared ones are copied);
- keeping image options aligned for multi-select;
- missing alt text in the admin's question response.

The spec grew by about 200 lines from that pass before any code was written.

**T7 slider.** The design discussion started with a constraint I set: no scoring that depends on other players' answers. We landed on a "closest guess" slider with a min, max and step, and optional word labels at the two ends ("Ice cold" to "Lava"), so it works for both numeric guesses and spectrum questions. The goldfish test caught things that would have been real bugs:
- There was no single rule for rounding a value exactly halfway between two steps. The backend and the three frontends could have disagreed on a player's score, so we picked one rule ("ties round up, never Python's `round`") and used it everywhere.
- "In range" was defined twice in slightly different ways.
- The host game-over breakdown wasn't specified at all.

After implementing, I updated the spec and context docs to match what was actually built.

**T6 games.** The goldfish test found four things that would have made me stop and guess during the build:
- how to turn latitude/longitude into a pixel on the US map;
- what to do if the map's licence was unknown;
- the JSON key order;
- the alt text for every image.

It also suggested changing question-type behaviour, which I said was out of scope; this task was game files only. During the build, the map turned out to include Alaska and Hawaii insets, so the agreed alt text ("contiguous United States") was wrong. I fixed the spec first and then the file, which is the order T3 asks for.

**Course delete.** This one came out of T6: our integration tests had left 713 junk courses in the dev database, because nothing could delete a course. The design discussion was short. I chose:
- refuse to delete a course that still has games, sessions or images (409 `COURSE_NOT_EMPTY`), since a played course is gradebook history;
- delete its roster and access grants along with it, since those are just configuration;
- leave alone a separate bug it found (the admin game delete doesn't clear Redis).

The goldfish test found the most important hole of any of my specs. The spec said to delete the course the normal SQLAlchemy way and relied on MySQL to refuse if a game was added in the middle. But SQLAlchemy's ORM looks at `Course.games` first and quietly sets each game's `course_id` to NULL, so the delete would have *succeeded* and unassigned the game. No test would have caught it, because the race window can't be hit reliably. The fix was to switch to a "Core" delete: one plain `DELETE FROM courses WHERE id = ?` statement, so only the database's own rules decide. I had to ask what a Core delete was before agreeing to it. The goldfish also flagged assumptions it couldn't confirm from the context docs (that the roster and access tables really cascade, that `GET /admin/courses/{id}` exists, and that a missing token gets 401 rather than 403). Checking them in the code proved them all right, so the spec now cites where each one comes from instead of just asserting it.

**Did it change how I implemented?** Yes, mostly in where the time went. Implementation was the fast part, because the spec already said which files to touch and what every edge case should do. The goldfish tests were worth it every time: each one found at least one thing where two parts of the system would have quietly disagreed. Those are exactly the bugs that are hard to find later. The cost is that it's slower to get started, and the specs get long. The slider spec is detailed enough that reviewing it took real effort.

The slider screens are themed with T9's tokens and are in the screenshot set: [docs/ui/README.md](ui/README.md) (`*-slider` rows), for example [player question, dark](ui/after/dark/player-question-slider.png) and [host results, light](ui/after/light/host-results-slider.png). They have no "before" images, because the slider was built after T9 merged.

## AI Tools Used

I used Claude Code, mostly through the VS Code extension. I used it for everything: reading the codebase, the design discussions, writing and goldfish-testing specs, implementing, testing, screenshots, and drafting MRs. I also used the repo's `.claude/` skills (`design-discussion`, `write-spec`, `goldfish-test`) and rules (`no-code-during-design`, `sycophant-challenge`).

**Where it helped:**
- **Big vertical slices.** T8 and the slider each touched the backend, the three frontends, tests, the simulator and the context docs. With a goldfish-tested spec, it could implement them in one pass, including integration tests.
- **Checking its own numbers.** For the sample games, it generated the correlation charts with the exact target r by construction. It measured the map targets from the image's state borders instead of guessing, and drew every target with its radius circles so I could check them by eye.
- **Doing the tedious verification.** It ran ruff, `tsc` and `check_theme.py` before every MR, imported the games through the API, and captured the slider screenshots by driving a real game with Playwright. For course delete it ran the full integration suite against the live stack (188 passed, 2 skipped) and counted the courses in the database before and after, 2 both times, to prove the tests no longer leak. It also clicked the new Delete button in a headless browser: cancel, delete an empty course, and the 409 message for a course with a game.

**Where it fell short:**
- **Its first spec can be confidently wrong.** The course-delete spec claimed MySQL would catch a race that the ORM would actually have hidden. The Elephant session wrote that with full confidence; only the fresh goldfish session caught it. It also used terms like "Core delete" without explaining them until I asked.
- **Scope.** It tends to drift. In the T6 goldfish test it suggested changing question-type behaviour, and I had to pull it back to "game files only". I also had to push back during the T8 design (multi-select image options, whether images should move between courses).
- **Wordy writing.** Specs and MR descriptions are long. Push options can't even fit its MR descriptions, so it gave me a separate one to paste.
- **Destructive actions.** When it tried to delete the leftover game sessions from its screenshot runs, auto mode's permission check blocked it, and it left them for me instead of working around the block. That's the right behaviour, but I still had to clean up.
- **Things I still had to do.** I did the T6 play check myself, clicking through every reveal in both themes. It can drive a headless browser (it did for the screenshots), but judging whether a screen looks right was mine. It also told me it wouldn't make "before" screenshots of a slider that never existed on the old theme, rather than faking them.

My workflow was the same as last project: have it get situated, have it propose, push back, and only then let it write. The difference this time is that the "propose" step was a committed, goldfish-tested spec instead of a chat message.

**My session logs (all in `ai_log/`):**

T0 logging verification (branch `Verify-Session-Logging`):
- `2026-09-29_22-06-33_20c53dc0.md`: read instructions.md and follow every T0 step
- `2026-09-29_22-07-49_20c53dc0.md`: switch back to my NetID email and get a log with it as proof

Context hierarchy for host and admin (branch `docs/context-host-admin`):
- `2026-09-29_23-06-35_65686f32.md`: do the context docs on a new branch
- `2026-09-29_23-07-21_65686f32.md`: put all the doc additions on one branch off main
- `2026-09-29_23-09-04_65686f32.md`: approve `frontend/host/src/lib`, continue
- `2026-09-29_23-12-43_65686f32.md`: approve `frontend/host/src/components`, continue
- `2026-09-29_23-14-06_65686f32.md`: continue through the admin directories
- `2026-09-29_23-28-23_65686f32.md`: approve `frontend/host/src/pages`, continue
- `2026-09-29_23-29-44_65686f32.md`: write the top-level `frontend/CLAUDE.md`
- `2026-09-29_23-34-53_65686f32.md`: commit and open the MR

Catching up and planning the remaining work:
- `2026-10-05_21-40-27_4c3000e1.md`: fix a stale remote branch ref and pull in my teammate's merged MRs
- `2026-10-05_21-43-45_153caebe.md`: what work is outstanding in instructions.md
- `2026-10-05_23-06-33_153caebe.md`: whether images and the party type should share a design doc; what steps T3 requires

T8 image support (branch `feat/t8-images`):
- `2026-10-05_23-20-37_153caebe.md`: open the branch and re-read the codebase
- `2026-10-06_00-13-35_153caebe.md`: start the design discussion
- `2026-10-06_00-20-44_153caebe.md`: answer the design questions (projector-only prompt images, etc.)
- `2026-10-06_00-24-17_153caebe.md`: mixed image/text options, alt text, what the results screens show
- `2026-10-06_00-31-36_153caebe.md`: alt text on phones and an editor warning; write the spec
- `2026-10-06_00-37-38_153caebe.md`: why the work spans 25 files, with one line per file
- `2026-10-06_00-38-14_153caebe.md`: commit the spec
- `2026-10-06_00-41-32_d5f5de62.md`: goldfish test in a fresh session
- `2026-10-06_00-47-55_d5f5de62.md`: answer the goldfish gaps; question why images wouldn't move with a game
- `2026-10-06_00-54-54_d5f5de62.md`: accept its suggestion, revise the spec and commit
- `2026-10-06_00-59-48_d5f5de62.md`: decide on multi-select image options and update the spec status
- `2026-10-06_01-00-57_d5f5de62.md`: what the HTML report is
- `2026-10-06_01-01-49_d5f5de62.md`: whether multi-select image options were an original gap or my teammate's
- `2026-10-06_01-25-01_d5f5de62.md`: implement
- `2026-10-06_01-29-11_d5f5de62.md`: subagent hand-back during implementation
- `2026-10-06_01-33-53_d5f5de62.md`: start the local server and tell me what to check

T7 slider question type (branch `feat/t7-party-question-type`):
- `2026-10-06_17-04-23_57380888.md`: new branch; get situated in the codebase for the party type
- `2026-10-06_18-30-34_57380888.md`: brainstorm party question types, with no scoring that depends on other players
- `2026-10-06_18-33-13_57380888.md`: pick "closest guess" with min/max/step and two labelled extremes
- `2026-10-06_18-34-15_57380888.md`: settle the name, the middle start, the defaults and the step
- `2026-10-06_18-38-01_57380888.md`: write the spec
- `2026-10-06_18-45-09_57380888.md`: commit the spec
- `2026-10-06_19-00-12_6bcf0752.md`: goldfish test in a fresh session
- `2026-10-06_19-30-07_6bcf0752.md`: implement
- `2026-10-06_19-32-48_6bcf0752.md`: what's left in instructions.md
- `2026-10-06_19-40-24_6bcf0752.md`: check that against instructions.md

T6 sample games (branch `feat/t6-sbmarcus2-sample-games`, merged through the slider branch):
- `2026-10-06_19-45-57_6bcf0752.md`: start the design discussion for my two games
- `2026-10-06_19-48-00_6bcf0752.md`: every game gets every question type; keep the MR to JSON only
- `2026-10-06_19-49-31_6666da68.md`: goldfish test in a separate session
- `2026-10-06_19-53-43_6bcf0752.md`: write the spec
- `2026-10-06_19-58-13_6bcf0752.md`: commit it
- `2026-10-06_20-00-04_641d2cec.md`: goldfish test in a fresh session
- `2026-10-06_20-02-32_641d2cec.md`: keep the revision to game files only; revise and commit
- `2026-10-06_20-11-02_641d2cec.md`: implement (charts, map targets, overlays, import check)
- `2026-10-06_20-12-42_641d2cec.md`: merge into the slider branch and open MR !14
- `2026-10-06_20-16-12_641d2cec.md`: prune the 713 leftover test courses and add the prune script to the MR
- `2026-10-06_20-31-15_641d2cec.md`: start the server so I can play-test

Wrap-up (branches `docs/t9-slider-screenshots`, `docs/sbmarcus2-t10`):
- `2026-10-06_20-36-45_641d2cec.md`: what's left in instructions.md if my changes merge
- `2026-10-06_20-45-37_641d2cec.md`: play check done; drop the licensing gate; capture slider screenshots
- `2026-10-06_20-52-27_641d2cec.md`: open MR !15 for the screenshots and draft this document

Course delete (branch `feat/course-delete`):
- `2026-10-06_21-08-32_641d2cec.md`: new branch; scope the course-delete design
- `2026-10-06_21-13-33_641d2cec.md`: answer the design questions (refuse if not empty, roster goes with the course, leave the Redis bug alone); write and commit the spec
- `2026-10-06_21-15-07_fc00faae.md`: goldfish test in a fresh session
- `2026-10-06_21-16-22_fc00faae.md`: what a Core delete is
- `2026-10-06_21-18-07_fc00faae.md`: accept the Core delete; revise the spec and commit
- `2026-10-06_21-23-53_fc00faae.md`: implement, then test it live (full suite, course counts, browser click-through)
- later logs from session `fc00faae`: merge main and bring this document up to date

## Best Practices Learned

- **Spec-first moves the work, it doesn't remove it.** Writing and goldfish-testing a spec is slower up front, but implementation becomes almost mechanical. The goldfish test's real value is catching places where two parts of the system would disagree (backend vs. frontend rounding, two definitions of "in range"). No single-file review catches those.
- **Duplication needs to be written down.** When code is copied on purpose (the host and admin editors, byte-identical lib files in three apps, Python math mirrored in TypeScript), the context docs are the only thing that tells the next person, or the next AI session, to change both.
- **Tests that create things need to clean them up.** Our integration tests made a new course every run with no way to delete it, and the dev database ended up with 713 junk courses in every course picker. The prune script cleaned up once, but the real fix was a delete path plus teardown, so I built it: an admin course delete, and test helpers that delete every course they create, last. A full run now leaves the course count exactly where it started.
- **Trust the database, not the ORM, for safety rules.** An ORM does its own work before it talks to the database (here, nulling foreign keys), and that work can quietly undo a constraint you're counting on. When a rule like "don't delete a course that has games" matters, let the database's foreign keys enforce it, and check what the ORM will actually send.
- **Keep MRs to one task.** I merged my T6 games into the slider branch and opened one MR for both. It worked, but it made the MR harder to review than two small ones would have been.
- **Verify with the real thing.** Lint and type checks passing didn't tell me the games worked. Importing them through the API, drawing the map targets on the images, and playing a round with simulated players did.
