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
  - **Create Game Room**: two independent dropdowns, course and quiz (auto-selected when
    there's exactly one), then `POST /game/rooms {course_id, game_id}` →
    `/game/{room_code}/lobby`.
  - "Sign Out" removes the token and goes to `/login`.
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
  where they hold `HOST`. `my-games`: ADMIN gets every game, USER only games with a
  `UserGameAccess` grant. GUEST gets 403 on both.
- **Games are not tied to courses.** There is no `course_id` on `Game`; a course and a game
  only meet on `GameSession`, when a room is created. So the two dropdowns are independent, and
  any game you can use can be run in any course you host.
- **Creating a room** (`POST /game/rooms`): HOST on the course **and** a grant for the game,
  both checked independently. ADMIN bypasses both. There's also a server cap of 50 concurrent
  rooms.
- **Managing a session afterwards** checks only ownership, not course role:
  `my-active-sessions` lists only sessions where `host_user_id == me`, `DELETE` needs owner or
  ADMIN, and socket `join_room` as HOST needs `user.id == session.host_user_id` or global
  `ADMIN`. A co-host with HOST on the same course can't rejoin or delete someone else's
  session. A host who has since lost course HOST access can still run their existing sessions.
- The host app never calls `/api/admin/*`. Course/roster/game/question editing, access grants,
  and Canvas/HTML reports are admin-only and live in the admin app.

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
- **Error messages are mostly lost.** A 403 from `POST /game/rooms` (no HOST access or no game
  grant) shows as `HTTP 403`, because `api.ts` reads `detail` but `BuzzerError` sends `message`.
  The OAuth2 exchange path in `LoginPage` has the same `detail`-only parsing.
- **The per-question UI is split across files.** `typeLabel` and `optionLabel` are duplicated
  in `QuestionPage`, `ResultsPage`, and `GameOverPage`. The word cloud's Levenshtein grading is
  a client-side re-implementation used only for colouring, so it can disagree with the server's
  fuzzy match. A new question type needs changes in all three files plus `types/game.ts`.
- `GameOverPage` percentages use `totalPlayers` as the bar denominator but `totalAnswered` for
  "% accuracy". Scores are floats server-side and are bucketed with `Math.floor`.
