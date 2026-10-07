# frontend/host/src/pages/

## Purpose
Route components for the host (big-screen) app: sign in, pick a course + game to create a room
(or rejoin/delete an active one), then drive the game lobby → question → results → … → game
over. All live-game state comes from one Socket.IO connection owned by `game/GameLayout.tsx`
and shared via React context. The host is the only client that advances the game.

## Contents
Routes are defined in `../App.tsx` (basename `/host/` in production). `/home` and `/game/*`
are wrapped in `RequireAuth`, which only checks that `localStorage.token` exists.
- `LoginPage.tsx` — `/login`: two ways in:
  - **NetID SSO**: link to `/api/auth/oauth2-callback?redirect_to=/host/login`. On return
    (`?from=oauth2`), parses `#oauth2_data`, `POST /auth/exchange-temp` with the temp token as
    Bearer, stores the access token.
  - **Local account**: `POST /auth/login` with username + password.
  Both end at `/home`. No role check: any account that can log in lands on `/home`.
- `HomePage.tsx` — `/home`: loads `GET /game/my-courses`, `/game/my-games`, and
  `/game/my-active-sessions` in parallel.
  - **Active Sessions** card: each of *my* LOBBY/IN_PROGRESS sessions, with "Rejoin" (→
    `/game/{code}/lobby`; `sync_state` then redirects to the right phase) and "Delete"
    (two-step confirm → `DELETE /game/sessions/{id}`).
  - **Create Game Room**: course first, then quiz. The quiz dropdown lists only `my-games`
    items whose `course_id` equals the selected course (both auto-select when there's exactly
    one). Then `POST /game/rooms {course_id, game_id}` → `/game/{room_code}/lobby`.
    "Manage this course" (disabled until a course is picked) → `/courses/{id}/games`. If
    `my-courses` is empty: "You don't host any courses yet — ask an admin for HOST access" and
    no dropdowns.
  - "Sign Out" removes the token and goes to `/login`.
- `manage/*` — the per-course management area (T4), rendered inside `App.tsx`'s `HostLayout`
  at `/courses/:courseId/…`. `:courseId` is only for navigation. Game, question and session
  calls use the flat `/host/games/…` and `/host/sessions/…` URLs, so the server checks the
  resource's own course. Images (T8) are listed and uploaded per course
  (`/host/courses/{id}/images`) and edited flat (`/host/images/{id}`).
  - `manage/GamesPage.tsx` — `.../games`: the course's games (`GET /host/courses/{id}/games`)
    with question count and a read-only **Restricted** badge. Create (`POST`, lands in this
    course, unrestricted), edit title/description/max players (`PUT /host/games/{id}`), and
    delete (`DELETE`). Delete shows the server's message, e.g. `GAME_HAS_RESULTS` or
    `GAME_LIVE`.
  - `manage/QuestionEditorPage.tsx` — `.../games/:gameId/questions`: an **adapted copy of the
    admin app's `QuestionEditorPage`**, pointed at `/host/games/{id}/questions…`, with
    "Back" → this course's games and no JSON export (hosts have no export endpoint). The form
    logic (`FormState`, `formToPayload`, the `points_value` derivation) must be kept in step
    with the admin copy by hand. Map pin (T7): image upload (or, since T8, "Choose from
    images"), click/drag the image to set the target, radius number inputs (source of
    truth, 0.02–2) paired with 0.02–0.5 sliders, a warning below 0.04, and saving blocked
    without an image and target for both grading types. Map pin questions take an entered
    points value. "Replace image" uploads a new one; the target fractions are kept.
    Slider (T7): the same slider form as the admin copy (`frontend/admin/src/pages/CLAUDE.md`).
    Images (T8) work as in the admin copy (`frontend/admin/src/pages/CLAUDE.md`): a prompt
    image on every type, text-or-image options on multiple_choice / multi_select
    (`config.optionImageIds` parallel to `options`, `""` text for image options), the
    `ImagePicker` for choosing/uploading with alt text, and alt text from
    `QuestionResponse.image_alt`. The only difference from the admin copy's
    `listImages` / `uploadImage`: both use `/host/courses/{course}/images` with the **game's
    own `course_id`** (from `GET /host/games/{id}`), never the `:courseId` route param; for a
    courseless game they throw "This game has no course, so it has no images".
  - `manage/RosterPage.tsx` — `.../roster`: active/inactive tables
    (`GET /host/courses/{id}/roster`). Upload of the **Canvas gradebook CSV** only (no
    column-mapping wizard; that's admin-only), with mode "Add / update only" (default,
    `add_update`) or "Replace roster" (`replace`, behind a browser confirm). It shows the
    added/updated/deactivated counts and the parser's `errors`.
  - `manage/ImagesPage.tsx` — `.../images` (T8): an adapted copy of the admin `ImagesPage`
    without the course filter or course badges. Lists and uploads (file + alt text) via
    `GET/POST /host/courses/{courseId}/images` (the route param, here); each card has the
    thumbnail (click → full-size overlay), size and date, inline alt-text edit
    (`PATCH /host/images/{id}`), **Used by** (links to each question editor under that game's
    own course, plus "+ N in games you can't access" from `hidden_usage_count`), **Replace**
    (`POST /host/images/{id}/replace`, with an "updates N question(s) in M game(s)" confirm)
    and **Delete** (disabled while in use; a 409 race reloads and shows the message).
  - `manage/SessionsPage.tsx` — `.../sessions`: COMPLETED sessions of the course, any host
    (`?status=COMPLETED`), with "Download scores (CSV)" and "Download summary (HTML)"
    (`api.download` of `/host/sessions/{id}/export|report`).
- `game/GameLayout.tsx` — `/game/:code/*`: parent route. Fetches the title via
  `GET /game/rooms/{code}` (failure ignored), opens the socket with `auth: {token}`, emits
  `join_room {room_code, role: "HOST"}` on **every** `connect`, maps server events to state and
  navigation, and exposes `useGame()` (phase, players, currentQuestion, answer counts, lock
  state, results, gameOver, `autoAdvance`, `emitAdvance`, `emitLockQuestion`). Preloads
  images on `game_images` (T7). Since T8 the host receives it twice at game start: the room
  broadcast (the players' set: maps and option images) and a host-only one that adds the
  prompt images; `lib/images.ts` caches per ID, so the overlap is fetched once. Always renders a corner QR code + room code and the theme
  toggle. Any `error` event replaces the page with a message and "Back to Home". Both returns
  are wrapped in the T9 stage, `<div data-stage className="contents">` (see "The stage" below).
- `game/LobbyPage.tsx` — big QR code (`{origin}/player/join?code=…`), room code, player count,
  the auto-advance toggle, and "Start Game" (`host_advance`; disabled at 0 players).
- `game/QuestionPage.tsx` — question header (number, type, Accuracy/Participation, typo
  tolerance), `TimerBar`, prompt (hidden while locked; for map_pin **only** the prompt, the
  map is on the phones), (T8) the prompt image under it via `AuthImage` (`max-h-[45vh]`,
  alt from `imageAlt`, also hidden while locked; option images are not shown here, only on
  the phones), `answered / players` count, a
  "Lock/Unlock Question" toggle (`host_lock_question`), and "Show Results" (`host_advance`,
  always enabled). With auto-advance on, it advances 1.5 s after `answer_phase_ended`.
- `game/ResultsPage.tsx` — per-question distribution: word cloud for fill-in-the-blank
  (client-side Levenshtein marks accepted answers with "✓ ", bold and `success-fg`),
  `MapPinHeatmap` for map_pin (both grading types; COMPLETENESS adds a "Participation — full
  credit for answering" caption), otherwise a bar chart. Each bar row is the label, the bar
  (`chart-correct` for correct options, `chart-bar` otherwise; COMPLETENESS questions have no
  right/wrong), the count and "✓ Correct" **beside** the bar, never inside it. An image
  option (T8) is labelled with its letter plus an `h-16` thumbnail instead of text.
  "Next Question" / "Show Final Results" (`host_advance`). With auto-advance on, a 10 s
  countdown then advances.
- **slider (T7)**: `QuestionPage` shows `SliderScale` (end labels on a plain track, "steps
  of 0.5" when the step isn't 1) under the prompt, hidden while locked. `ResultsPage` uses
  `SliderHistogram` for both grading types (+ the Participation caption). `GameOverPage`
  shows `targetLine(reveal)` instead of a distribution chart (its keys are bin numbers),
  plus `withinFullPct` / `averageCredit` like map_pin.
- `game/GameOverPage.tsx` — anonymous score histogram (~8 buckets up to `maxPossibleScore`),
  average/high/player count, "New Game" (→ `/home`), and a per-question breakdown card
  (distribution, accepted answers, correct %, response rate, average answer time; for map_pin,
  "within target" % and average credit from the host summary, "—" when nobody answered, and
  no map image). Since T8 a prompt image shows as a thumbnail beside the prompt and image
  options as thumbnails in the distribution, with alt text from the summary's `imageAlt`.

## How it fits in
Uses `lib/api.ts` + `lib/utils.ts` (see `lib/CLAUDE.md`) and `components/ui/*` (see
`components/CLAUDE.md`). Payload types are in `../types/game.ts`. The socket protocol and phase
machine are defined server-side in `backend/app/websocket/CLAUDE.md`.

### The stage and the theme toggle (T9)
- **The stage.** `GameLayout` wraps the game screens (lobby, question, results, game over, and
  its error view) in `<div data-stage className="contents">`. `display: contents` adds no box,
  so layout is unchanged, but the tokens inherit through it. Inside it, `../theme.css`
  overrides ten tokens:
  - five text tokens (`fg-muted`, `accent-fg`, `success-fg`, `danger-fg`, `warning-fg`) are
    raised to 7:1, because projected text washes out;
  - five fills (`accent`, `accent-hover`, `success`, `danger`, `danger-hover`) are darkened, so
    text on them also reaches 7:1.

  The management area, login and home use the normal values.
- **Readability on the stage.** Student-facing text (prompt, options, counts, word-cloud
  words, "N / M answered", captions) is at least `text-lg` and `text-fg`. Short uppercase
  labels next to the value they name may be `text-sm`, never smaller. Don't make anything
  smaller than it is.
- **No text on chart fills.** Counts and labels sit beside the bars, on the page background,
  which the stage text tokens already cover.
- **Where the toggle renders.** Each page renders it itself: `LoginPage` and `HomePage`
  (fixed top-right), `GameLayout` (both returns, fixed top-right), and the `HostLayout` sidebar
  in `../App.tsx` (labelled, above Sign out). Stage content stays within `max-w-4xl`, so the
  top-right corner is clear for the toggle; the corner QR panel is bottom-right.

### Who can host what (all enforced server-side; the pages do no checks)
Two separate role systems apply (see `backend/app/models/CLAUDE.md`): the **global**
`User.role` (`ADMIN | USER | GUEST`) and the **per-course** `UserCourseAccess.role`
(`HOST | PLAYER`). "Host" is not a global role.
- **What the dropdowns show.** `my-courses`: ADMIN gets every course, USER only courses
  where they hold `HOST`. `my-games`: ADMIN gets every game; a USER gets the games of their
  HOST courses, minus restricted games they have no grant on. GUEST gets 403 on both.
- **Games belong to a course** (`Game.course_id`), so the quiz dropdown is filtered by the
  chosen course. A room in another course is rejected with 422 `COURSE_MISMATCH`.
- **Creating a room** (`POST /game/rooms`): HOST on the game's course, plus a grant if the game
  is restricted. ADMIN bypasses the access part (an admin's first room attaches a game that
  has no course). There's also a server cap of 50 concurrent rooms.
- **Managing a session afterwards** checks only ownership, not course role:
  `my-active-sessions` lists only sessions where `host_user_id == me`, `DELETE` needs owner or
  ADMIN, and socket `join_room` as HOST needs `user.id == session.host_user_id` or global
  `ADMIN`. A co-host with HOST on the same course can't rejoin or delete someone else's
  session. A host who has since lost course HOST access can still run their existing sessions.
- **The management area** uses `/api/host/*` (course HOST on the resource's course). Results
  belong to the course a session was **played in**, so any co-host can download them, but a
  host who lost HOST cannot. Editing a game or its questions is blocked with 409 `GAME_LIVE`
  while it is being played.
- The host app never calls `/api/admin/*`. Access grants, `restricted`, moving games between
  courses, the roster column-mapping import and Canvas export stay in the admin app.

### Event → navigation (GameLayout)
| server event | effect |
|---|---|
| `sync_state` | set players/count; `LOBBY` → `/lobby`; `IN_PROGRESS` → restore question + lock state, then `/question` or `/results` by `questionPhase`; `COMPLETED`/`ABANDONED` → **no navigation** |
| `player_joined` / `player_left` | update list and count |
| `new_question` | reset per-question state → `/question` |
| `answer_status` | update answered count |
| `answer_phase_ended` | set `answerPhaseEnded` (+ `allAnswered`); ignored if for a stale `questionId` |
| `question_locked` / `_unlocked` | toggle `questionLocked`, store server `remainingSeconds` |
| `question_results` | → `/results` |
| `game_over` | → `/gameover` (socket stays connected) |
| `game_abandoned` | → `/home` |
| `game_images` (T7) | `preloadImages(imageIds)`; arrives twice since T8 (player set, then host set incl. prompt images) |
| `error` / `connect_error` | full-screen error view |

## Gotchas
- **Every phase navigation reconnects the socket** (`GameLayout` effect deps `[code,
  navigate]`); see `frontend/player/src/pages/CLAUDE.md`.
- **No client-side role gate.** A GUEST token (e.g. left over from the player app, which shares
  `localStorage.token`; see `lib/CLAUDE.md`) gets into `/home`. All three list calls then 403,
  and the page shows the generic "Failed to load courses or games. Are you still logged in?"
  with no redirect to `/login`. A USER with no HOST access just sees empty dropdowns and no
  explanation.
- **Any global ADMIN can take over any session as host.** Socket `join_room` with
  `role: "HOST"` lets ADMIN in regardless of `host_user_id`. Opening `/host/game/{code}/lobby`
  as an admin cancels the real host's abandon timer and becomes `host_sid`. There's no warning
  on either screen.
- **Non-owners get a dead end.** A USER who opens another host's `/game/{code}/…` URL gets the
  full-screen "Not authorised as host for this session" error.
- **Rejoin mid-results loses the chart.** `sync_state` has no question-results data, so a host
  who reconnects in the `RESULTS` phase sees the header and "Next Question" but an empty
  results area until the next advance.
- **Rejoin after the game ended does nothing useful.** `sync_state` with `COMPLETED` doesn't
  navigate, so the host sits on an empty lobby screen. `my-active-sessions` hides those sessions,
  but a bookmarked URL doesn't.
- **Auto-advance stalls while locked.** `QuestionPage` auto-advances only after
  `answer_phase_ended`. Locking pauses the server timer, so while locked that event never
  arrives and nothing advances. Auto-advance is also plain `useState` in `GameLayout`, so it
  resets to off on reload or reconnect.
- **"Show Results" is always enabled**, so the host can end the answer phase at any moment,
  including before anyone answers.
- **Delete works on live games.** "Delete all data?" on an IN_PROGRESS session wipes Redis and
  the DB row (all scores), but the server doesn't notify connected players.
- **The player join URL assumes the nginx layout.** The QR codes point at
  `{window.location.origin}/player/join`. Under `npm run dev:host` (Vite on :5173, base `/`)
  that's the host app itself, which redirects to `/login`. It only works behind nginx, where
  all apps share an origin.
- **Error messages.** Since T4, `api.ts` shows the server's `message` (e.g. "You do not have
  HOST access to this course", "This game is being played right now"). The OAuth2 exchange
  path in `LoginPage` bypasses `api.ts` and still reads only `detail`.
- **Refresh mid-game loses the preload.** `game_images` is sent only at start, and the host's
  `sync_state` has no `imageIds`, so after a reload the results heatmap and (T8) prompt and
  option images load on demand (a blank `AuthImage` placeholder or "Loading map…" briefly).
- **The T8 image UI was never run in a browser.** No test runner; the prompt image on the
  projector, the results/game-over thumbnails, the editor's image fields and `ImagesPage`
  need checking by hand.
- **The game-over histogram assumes whole-number scores.** Since `maxPossibleScore` is no
  longer truncated, a fractional maximum (e.g. 8.75) gives slightly odd bucket labels
  ("8–8.75"), though the bucketing still works.
- **The per-question UI is split across files.** `typeLabel` lives in `QuestionPage` and
  `GameOverPage`, `optionLabel` in all three game pages. The word cloud's Levenshtein grading is
  a client-side re-implementation used only for marking accepted words, so it can disagree with
  the server's fuzzy match. A new question type needs changes in all three files plus
  `types/game.ts`.
- `GameOverPage` percentages use `totalPlayers` as the bar denominator but `totalAnswered` for
  "% accuracy". Scores are floats server-side and are bucketed with `Math.floor`.
- **The host never renders the `answer-N` colours** (only the player does), so the stage has
  no overrides for them. If a host screen ever shows them, add stage overrides first and
  extend the contrast list in `scripts/check_theme.py`.
