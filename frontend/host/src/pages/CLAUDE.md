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
  resource's own course.
  - `manage/GamesPage.tsx` — `.../games`: the course's games (`GET /host/courses/{id}/games`)
    with question count and a read-only **Restricted** badge. Create (`POST`, lands in this
    course, unrestricted), edit title/description/max players (`PUT /host/games/{id}`), and
    delete (`DELETE`). Delete shows the server's message, e.g. `GAME_HAS_RESULTS` or
    `GAME_LIVE`.
  - `manage/QuestionEditorPage.tsx` — `.../games/:gameId/questions`: an **adapted copy of the
    admin app's `QuestionEditorPage`**, pointed at `/host/games/{id}/questions…`, with
    "Back" → this course's games and no JSON export (hosts have no export endpoint). The form
    logic (`FormState`, `formToPayload`, the `points_value` derivation) must be kept in step
    with the admin copy by hand.
  - `manage/RosterPage.tsx` — `.../roster`: active/inactive tables
    (`GET /host/courses/{id}/roster`). Upload of the **Canvas gradebook CSV** only (no
    column-mapping wizard; that's admin-only), with mode "Add / update only" (default,
    `add_update`) or "Replace roster" (`replace`, behind a browser confirm). It shows the
    added/updated/deactivated counts and the parser's `errors`.
  - `manage/SessionsPage.tsx` — `.../sessions`: COMPLETED sessions of the course, any host
    (`?status=COMPLETED`), with "Download scores (CSV)" and "Download summary (HTML)"
    (`api.download` of `/host/sessions/{id}/export|report`).
- `game/GameLayout.tsx` — `/game/:code/*`: parent route. Fetches the title via
  `GET /game/rooms/{code}` (failure ignored), opens the socket with `auth: {token}`, emits
  `join_room {room_code, role: "HOST"}` on **every** `connect`, maps server events to state and
  navigation, and exposes `useGame()` (phase, players, currentQuestion, answer counts, lock
  state, results, gameOver, `autoAdvance`, `emitAdvance`, `emitLockQuestion`). Always renders a
  corner QR code + room code. Any `error` event replaces the page with a message and
  "Back to Home".
- `game/LobbyPage.tsx` — big QR code (`{origin}/player/join?code=…`), room code, player count,
  the auto-advance toggle, and "Start Game" (`host_advance`; disabled at 0 players).
- `game/QuestionPage.tsx` — question header (number, type, Accuracy/Participation, typo
  tolerance), `TimerBar`, prompt (hidden while locked), `answered / players` count, a
  "Lock/Unlock Question" toggle (`host_lock_question`), and "Show Results" (`host_advance`,
  always enabled). With auto-advance on, it advances 1.5 s after `answer_phase_ended`.
- `game/ResultsPage.tsx` — per-question distribution: word cloud for fill-in-the-blank
  (client-side Levenshtein colours accepted answers), otherwise a bar chart (correct options
  green; COMPLETENESS questions have no right/wrong). "Next Question" / "Show Final Results"
  (`host_advance`). With auto-advance on, a 10 s countdown then advances.
- `game/GameOverPage.tsx` — anonymous score histogram (~8 buckets up to `maxPossibleScore`),
  average/high/player count, "New Game" (→ `/home`), and a per-question breakdown card
  (distribution, accepted answers, correct %, response rate, average answer time).

## How it fits in
Uses `lib/api.ts` + `lib/utils.ts` (see `lib/CLAUDE.md`) and `components/ui/*` (see
`components/CLAUDE.md`). Payload types are in `../types/game.ts`. The socket protocol and phase
machine are defined server-side in `backend/app/websocket/CLAUDE.md`.

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
| `error` / `connect_error` | full-screen error view |

## Gotchas
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
- **The per-question UI is split across files.** `typeLabel` and `optionLabel` are duplicated
  in `QuestionPage`, `ResultsPage`, and `GameOverPage`. The word cloud's Levenshtein grading is
  a client-side re-implementation used only for colouring, so it can disagree with the server's
  fuzzy match. A new question type needs changes in all three files plus `types/game.ts`.
- `GameOverPage` percentages use `totalPlayers` as the bar denominator but `totalAnswered` for
  "% accuracy". Scores are floats server-side and are bucketed with `Math.floor`.
