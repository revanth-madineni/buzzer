# Revanth Madineni — T10 individual document

## Repository and Codebase Organization

Buzzer is a real-time classroom quiz. An instructor runs the host screen on a projector, and
students answer on their phones. The repo holds one backend, three frontends, and the pieces
that run them: `docker-compose.yml`, `nginx/`, `scripts/` and `sample_games/`.

**Backend.** The backend (`backend/app/`) is a FastAPI REST API and a Socket.IO gateway served as
one app.
- `routers/` are the REST endpoints: auth, admin, the host-facing game routes, the course-host
  management API from T4, and images.
- `routers/` call `services/`, which hold the business logic: access checks, the room
  lifecycle, scoring, Redis state, rosters and exports.
- `websocket/` is the gateway that runs a live game.
- `models/` are the SQLAlchemy tables, `schemas/` the Pydantic request and response shapes, and
  `common/` the shared auth dependencies and error types.

MySQL is the durable record, and Redis holds live game state.

**Frontends.** The three apps in `frontend/` are separate React + Vite + Tailwind projects that
share no code:
- `host/`: the projector screen, plus a course management area;
- `player/`: the phones;
- `admin/`: the staff console.

All three call the backend over `/api`, and host and player also use Socket.IO. Behind nginx
they share one origin, so they also share one `localStorage` login token.

**A game round.**
1. **The host starts a question.** The host's `host_advance` makes the gateway load the next
   question, store it in Redis with a start time, broadcast `new_question` without the answers,
   and start a timer.
2. **A player answers.** The gateway checks the player's `submit_answer` (phase, lock, question
   ID, not already answered). It scores the answer with `calculate_score`, saves it as a
   `SessionScore` row, and adds it to the Redis running score and answer distribution. The
   player then gets `answer_received`, and the host gets an updated answer count.
3. **The answer phase ends.** When everyone has answered, or when time runs out (which also
   locks the question), the host gets `answer_phase_ended`.
4. **The results.** The host's next `host_advance` builds the reveal. The host gets the
   distribution, and each player gets their own points and rank.

**My context files.** I wrote the `CLAUDE.md` context files for `backend/` and every directory
under `backend/app/`, and for `frontend/player/src/` and its `lib/`, `components/` and
`pages/`. Two things stood out while writing them.
- **Authorization is split across three layers:** global roles in `common/`, course access in
  `services/`, and session ownership in the gateway. A host joining over the socket is only
  checked for ownership, so course HOST access is checked once, when the room is created.
- **Reading the code closely surfaced likely bugs** I hadn't noticed using the app. One was an
  admin who reconnects being treated as the host. Another was an "already answered" check that
  ran before the answer was saved, so two fast submits could both score.

## Design Process (Elephant/Goldfish)

I used the same loop for T4, T7 and T9:
1. a design discussion with Claude Code, with no code allowed;
2. a written spec in `docs/plans/`;
3. a Goldfish test in a fresh session that read only the spec;
4. a revision of the spec before implementing.

**T4: [host/admin restructure](plans/t4-ui-restructure.md).** The Goldfish found:
- player access wasn't stated;
- two hosts could race to attach a game to a course on its first room;
- session lists and exports skipped the restricted-game check;
- error codes, response shapes and branches weren't defined;
- editing a game could race with starting it.

Those became spec v2 and v3. Implementation added v5 to v8. One of those changes was that the
planned row lock didn't actually close the start race under MySQL's default isolation level.

**T7: [map-pin question](plans/t7-map-pin.md).** The Goldfish found:
- metadata stripping had no exact rule; it became a per-format allowlist;
- ACCURACY and COMPLETENESS questions showed different reveals; now there is one reveal and
  only scoring differs;
- the import pipeline had gaps;
- late answers couldn't be told apart from real errors; they now carry an error code;
- the dev nginx 1 MB body limit would block uploads.

A couple of its items were misreadings, because it hadn't loaded the context docs.
Implementation found more: Pillow adds extra keys to every WebP, and `get_db` commits after the
response is sent.

**T9: [theming](plans/t9-theming.md).** The Goldfish found:
- the spec said the check script "fails the build", but `.gitlab-ci.yml` can't be changed; it
  became a manual gate in the MR template;
- text drawn on chart bars couldn't reach 7:1 contrast on the projector; the labels moved beside
  the bars;
- the row describing the selected answer was wrong;
- the toggle's visible label and its `aria-label` disagreed;
- the host's game layout had no DOM element to mark; it got a `display: contents` wrapper.

Implementation still found several gaps. Examples: white map outlines with no token, a
Tailwind ring setting that was silently ignored, and a placeholder rule that lost to Tailwind's
own base CSS.

**Did it change how I implemented?** Yes. Because every decision was written down and tested on
a reader with no context, I could tell Claude Code to treat the spec as authoritative and stop
when the spec and the code disagreed. In all three projects it did stop. The Goldfish catches
gaps in the document, not places where the document is wrong about how the system behaves at
runtime (MySQL locking, FastAPI commit timing, Pillow, Tailwind). So I treated fixing the spec,
as its own commit, as part of implementing.

## AI Tools Used

### Claude Code
All sessions are logged in `ai_log/`.

**Context files.**
- What I asked: to write my directories one at a time and stop after each so I could check it
  against the code, then `backend/CLAUDE.md`, then a step-by-step walkthrough of a quiz.
  Logs: [09-29 21:27](../ai_log/2026-09-29_21-27-29_ec73ee87.md),
  [09-29 23:55](../ai_log/2026-09-29_23-55-23_ec73ee87.md),
  [09-30 21:33](../ai_log/2026-09-30_21-33-20_ec73ee87.md).
- A side question about how `routers/` works turned into finding out why the logging hook
  failed: a `cd` moved the session's working directory, and the hook uses a relative path.
  Log: [09-29 22:28](../ai_log/2026-09-29_22-28-38_88e18b0b.md).

**T4 design.**
- The design discussion. It pushed back on retiring game grants and on backfilling a game's
  course from its most recent session, and reduced the open questions to seven decisions. I gave
  my decisions, and the spec moved to a single branch. Logs:
  [09-30 21:47](../ai_log/2026-09-30_21-47-18_47acfe76.md),
  [21:48](../ai_log/2026-09-30_21-48-13_47acfe76.md),
  [21:50](../ai_log/2026-09-30_21-50-14_47acfe76.md),
  [10-01 20:29](../ai_log/2026-10-01_20-29-49_47acfe76.md).
- The Goldfish test. Log: [09-30 22:23](../ai_log/2026-09-30_22-23-49_316760a5.md).

**T4 implementation.**
- I had it implement §4.13 piece by piece: tests, ruff and tsc, then a commit for each piece.
  It backed up the dev DB before running the migration on it.
- It stopped to fix the spec first when an error code turned out to be unreachable and when the
  row lock wasn't enough.
- Logs: [10-01 20:38](../ai_log/2026-10-01_20-38-41_a7c1a070.md),
  [20:44](../ai_log/2026-10-01_20-44-09_a7c1a070.md),
  [20:48](../ai_log/2026-10-01_20-48-56_a7c1a070.md),
  [20:51](../ai_log/2026-10-01_20-51-07_a7c1a070.md),
  [20:55](../ai_log/2026-10-01_20-55-48_a7c1a070.md),
  [21:04](../ai_log/2026-10-01_21-04-55_a7c1a070.md),
  [21:11](../ai_log/2026-10-01_21-11-11_a7c1a070.md),
  [21:22](../ai_log/2026-10-01_21-22-33_a7c1a070.md),
  [21:25](../ai_log/2026-10-01_21-25-25_a7c1a070.md),
  [21:39](../ai_log/2026-10-01_21-39-39_a7c1a070.md).

**T7 design.**
- The design discussion and spec. It pointed out that fractions of the image aren't a distance
  unit (a "circle" turns into an ellipse), so scoring got an aspect correction. Then came my
  revisions after the Goldfish. Logs:
  [10-04 11:05](../ai_log/2026-10-04_11-05-29_f20c6c51.md),
  [11:07](../ai_log/2026-10-04_11-07-33_f20c6c51.md),
  [11:11](../ai_log/2026-10-04_11-11-42_f20c6c51.md),
  [11:16](../ai_log/2026-10-04_11-16-40_f20c6c51.md),
  [11:26](../ai_log/2026-10-04_11-26-53_f20c6c51.md),
  [11:29](../ai_log/2026-10-04_11-29-20_f20c6c51.md),
  [11:34](../ai_log/2026-10-04_11-34-53_f20c6c51.md),
  [11:42](../ai_log/2026-10-04_11-42-38_f20c6c51.md),
  [11:50](../ai_log/2026-10-04_11-50-44_f20c6c51.md).
- The Goldfish test. Log: [11:32](../ai_log/2026-10-04_11-32-13_45fdfb62.md).

**T7 implementation.**
- It stopped on a Pillow WebP contradiction in the spec. It also found the
  commit-after-response race: 34 of 60 immediate GETs after an upload returned 404.
- It fixed the `maxPossibleScore` truncation and the answer-before-commit race, each with a
  test.
- Logs: [10-04 14:40](../ai_log/2026-10-04_14-40-08_5e4448d5.md),
  [14:59](../ai_log/2026-10-04_14-59-56_5e4448d5.md),
  [15:25](../ai_log/2026-10-04_15-25-12_5e4448d5.md),
  [15:39](../ai_log/2026-10-04_15-39-16_5e4448d5.md),
  [15:53](../ai_log/2026-10-04_15-53-11_5e4448d5.md),
  [16:07](../ai_log/2026-10-04_16-07-27_5e4448d5.md),
  [16:21](../ai_log/2026-10-04_16-21-00_5e4448d5.md),
  [16:29](../ai_log/2026-10-04_16-29-50_5e4448d5.md).

**T9 design.**
- The design discussion and spec; it proposed one global focus outline instead of focus rings.
  Logs: [10-05 16:43](../ai_log/2026-10-05_16-43-32_26f807f1.md),
  [16:44](../ai_log/2026-10-05_16-44-13_26f807f1.md).
- The Goldfish test. Log: [16:51](../ai_log/2026-10-05_16-51-26_6e13acdb.md).

**T9 implementation.**
- I had it implement the spec step by step, stopping for spec decisions such as a missing map
  outline token and a selected state that barely showed.
- It drove headless Chromium to take the 38 after screenshots and run 27 automated checks for
  `docs/ui/README.md`.
- Logs: [10-05 21:06](../ai_log/2026-10-05_21-06-49_5193c4a8.md),
  [21:56](../ai_log/2026-10-05_21-56-27_5193c4a8.md),
  [22:12](../ai_log/2026-10-05_22-12-34_5193c4a8.md),
  [22:26](../ai_log/2026-10-05_22-26-08_5193c4a8.md),
  [22:37](../ai_log/2026-10-05_22-37-23_5193c4a8.md),
  [22:48](../ai_log/2026-10-05_22-48-39_5193c4a8.md).

**T10.** This document was drafted in the same session as the T9 implementation (session
`5193c4a8`), and its log is that session's 2026-10-06 entry in `ai_log/`.

### Where it helped
- **It found real bugs, some outside the task:**
  - the commit-after-response race, which was behind an intermittently failing test;
  - the answer-before-commit race;
  - the `maxPossibleScore` truncation;
  - the gap in T4's row lock.
- **It pushed back during design:** aspect correction in T7, grants and backfill in T4, and the
  focus outline in T9.
- **It carried verification further than I would have by hand:** a migration test with a DB
  backup taken first, a contrast-checking script, and browser checks in T9.

### Where it fell short
- **It couldn't see the browser until T9.** The T4 and T7 frontends were only type-checked and
  built, so I had to test them by hand.
- **A scripted edit put the commit before the write** in four handlers. In two of them that
  would have released the live-game lock early. It was caught by reviewing the diff before
  committing.
- **The specs it wrote had inconsistencies that only showed up during implementation:** an
  unreachable error code in T4, Pillow behaviour in T7, and two T9 rules that Tailwind silently
  overrode.

## Best Practices Learned

- **Version control.**
  - Small commits, one logical piece each, with spec changes as their own commits.
  - A branch per feature and per design doc, merged through MRs.
  - One mistake: I put three bug fixes (the commit race, the `maxPossibleScore` truncation and
    the answer race) on `feat/t7-map-pin` instead of `fix/` branches, so they went in with the
    T7 MR.
- **CI/CD.** I ran `ruff format`, `ruff check` and `tsc --noEmit` before pushing, and never
  touched `.gitlab-ci.yml`. When T9 needed a new check, it became a manual gate in the MR
  template instead of a pipeline change.
- **Working in an unfamiliar codebase.** I wrote the context files first. Every later design
  session started from them, and claims were checked against the code rather than assumed.
- **Role-based design.** Check access by loading the resource. In T4, host endpoints use flat
  URLs like `/host/games/{id}`, and the server checks HOST on the game's own course; the course
  ID in the page URL is only for navigation. The frontends check nothing.
- **Testing.**
  - Integration tests run against the live Docker stack (MySQL and Redis), not mocks.
  - A test that failed intermittently (`test_host_management.py`) turned out to be a real race,
    not a bad test.
  - For a fix, write the test first and see it fail without the fix.
- **Effective AI use.**
  - Design before code, and Goldfish-test the spec.
  - Work in small pieces with a stop for review after each.
  - Fix the spec before the code.
  - Review the AI's diffs instead of trusting its summaries.
