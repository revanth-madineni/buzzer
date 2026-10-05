# frontend/player/src/pages/

## Purpose
Route components for the player (mobile) app: find a room, authenticate, then play through
lobby → question → feedback → results → game over. All live-game state comes from one
Socket.IO connection owned by `game/GameLayout.tsx` and shared via React context.

## Contents
Routes are defined in `../App.tsx` (basename `/player/` in production):
- `JoinPage.tsx` — `/join`: 6-char room code input and `GET /api/game/rooms/{code}/ping`, then
  `/name/{code}`. Auto-submits when opened with `?code=` (QR code).
- `NamePage.tsx` — `/name/:code`: three ways in:
  - **Guest**: display name + email → `POST /auth/guest`. Name and email are remembered in
    localStorage.
  - **NetID**: link to `/api/auth/oauth2-callback?redirect_to=/player/login`. The room code is
    stashed in `sessionStorage.joinRoomCode`.
  - **Local account**: `POST /auth/login`.
  If a non-expired token is already present, the toggle is hidden and a single "Join Game"
  button is shown. Every path ends at `/game/{code}/lobby`.
- `LoginPage.tsx` — `/login`: OAuth2 return. Parses `#oauth2_data`, `POST /auth/exchange-temp`
  with the temp token, stores the access token, and returns to `/name/{joinRoomCode}`.
- `game/GameLayout.tsx` — `/game/:code/*`: parent route. Checks the token (redirects to
  `/name/{code}` if missing/expired), opens the socket with `auth: {token}`, emits
  `join_room {room_code, role: "PLAYER"}` on **every** `connect`, maps server events to state and
  navigation, and exposes `useGame()` (phase, currentQuestion, questionLocked, results, gameOver,
  `emitAnswer`, …). It also renders the "host disconnected" banner and a full-screen error view.
- `game/LobbyPage.tsx` — room code, spinner, and player count.
- `game/QuestionPage.tsx` — answer UI per type (MC buttons, True/False, fill-in text input,
  multi-select + submit, map pin) with `TimerBar`. Calls `emitAnswer(questionId, answerData,
  msSinceMount)`. map_pin (T7) is a `MapPinQuestion` sub-component keyed by `questionId`:
  place/move a pin on `MapPinCanvas`, then **Confirm** (enabled once a pin exists, the image
  has loaded, and the question isn't locked or rejected). No auto-submit at time-up. After a
  timing rejection every branch clears `submitted`, disables input and shows "Not recorded —
  time ran out".
- `game/FeedbackPage.tsx` — static "Answer locked in!" while waiting for the reveal.
- `game/ResultsPage.tsx` — this question's outcome, your answer, points, total, and rank.
  map_pin: `MapPinCanvas` in reveal mode for both grading types, with a label computed from
  geometry (`mapPinDistance` vs the reveal): "No answer" (no pin, or `answerRejected`) /
  "Within target" / "Partial credit" / "Too far", plus "· full credit for answering" under
  COMPLETENESS. The pin comes from `lastAnswerData`, else `sessionStorage`.
- `game/GameOverPage.tsx` — final rank/score plus a per-question recap (your answer vs.
  correct; map_pin shows points earned / possible, no image). "Play Again" clears the token
  and goes to `/join`.

## How it fits in
Uses `lib/api.ts` + `lib/utils.ts` (see `lib/CLAUDE.md`) and `components/ui/*` (see
`components/CLAUDE.md`). Payload types are in `../types/game.ts`. The socket protocol and phase
machine are defined server-side in `backend/app/websocket/CLAUDE.md`.

### Event → navigation (GameLayout)
| server event | effect |
|---|---|
| `sync_state` | set count/lock; preload `imageIds`; if `LOBBY` → `/lobby`; if `IN_PROGRESS`, **no navigation** |
| `game_images` (T7) | `preloadImages(imageIds)` |
| `new_question` | reset per-question state (incl. `answerRejected`) → `/question` |
| `answer_received` | (unless `alreadyAnswered`) save an accepted map pin to `sessionStorage` `buzzer:pin:{code}:{questionId}`; → `/feedback` |
| `question_locked` / `_unlocked` | toggle `questionLocked` |
| `question_results` | → `/results` |
| `game_over` | → `/gameover`, then **disconnects** the socket |
| `host_disconnected` | show banner (cleared by the next `new_question`) |
| `game_abandoned` | → `/join` |
| `error` with `code` `QUESTION_LOCKED` / `NO_ACTIVE_QUESTION` / `QUESTION_MISMATCH` | **non-fatal** (T7): `answerRejected = true`, 3 s "Too late — your answer wasn't recorded" banner, no navigation |
| any other `error` | full-screen error view |

Answer payloads sent: MC `{selectedIndex: number}`, T/F `{selectedValue: boolean}`, fill-in
`{text}` (trimmed), multi-select `{selectedIndices: number[]}`, map pin `{x, y}` (clamped to
[0, 1]). These match what
`services/game_service.calculate_score` expects, so the backend's type-confusion gotchas
(string `"false"`, non-int index) aren't triggered by this client.

## Gotchas
- **Late answers are non-fatal; other errors still end the game view.** Since T7 the three
  timing rejections (by `error.code`) only show a banner and mark the answer as not recorded.
  Any other server `error` still replaces the whole UI with the message and a "Back to Join"
  link until the next socket `connect`. Verified by reading only; there's no test runner, so
  check the banner by hand (e.g. confirm a pin right as a 2 s question locks).
- **Shared token with host/admin apps (same origin).** All three apps use
  `localStorage['token']`, and in production they're served from `/player/`, `/host/`, and
  `/admin/` on what appears to be one origin. On a shared browser:
  - The player app picks up a signed-in host's or admin's token ("Join Game" with no login).
    Admins pass `authorise_player` for any room.
  - The player's "Play Again" logs the host/admin out.
- **Only `join_room` is used; `rejoin_room` is never sent.** Reconnects go through full player
  authorisation. That avoids the backend `rejoin_room` bugs (admin-becomes-host, no question
  resend).
- **Refresh or reconnect mid-game can strand the player.** State lives only in React. On
  reconnect, the server re-pushes `new_question` only if the question is open, unlocked, and
  unanswered. Otherwise `sync_state(IN_PROGRESS)` doesn't navigate or restore data, so
  `/question` shows "Loading question…" and `/results` shows "Loading results…" until the host
  advances.
- `sync_state` only ever sets `questionLocked` to `true`, never back to `false`.
- **The question prompt is never shown on the phone.** `QuestionPage` renders only options/input
  (the prompt is on the host screen). `GameOverPage` does show prompts, as plain text, so
  allowed `<b>/<i>/<u>/<br>` tags appear literally.
- **"Correct" is judged client-side as `points > 0`** (ResultsPage and GameOverPage). The server's
  `isCorrect` (points == full value) is ignored, so partial credit shows as "Correct!". The
  `answer_received` payload's `isCorrect`/`pointsAwarded` are stored but not shown until the
  reveal.
- ResultsPage shows "You answered" for MC/TF/fill-in but not multi-select, and shows the correct
  answer only for fill-in. For multi-select, GameOverPage treats any option with `answerPoints > 0`
  as correct.
- `QuestionPage` sets `submitted = true` before the server acknowledges. A timing rejection
  undoes it (`answerRejected`); any other rejection still leaves "submitted" and then shows
  the error screen.
- **A map pin survives a reload only once accepted.** It's written to `sessionStorage` on
  `answer_received`, not on Confirm, so a rejected pin is never shown as yours.
- `answer_time_ms` is measured from `QuestionPage` mount, not from server `started_at`, so late
  joiners and slow renders skew it.
- Error text from REST calls is mostly generic. JoinPage ignores the error and always says "Room
  not found", even when the game has ended (409). LoginPage reads `detail`, which this backend's
  own errors don't include (see `lib/CLAUDE.md`).
- The OAuth2 link hits `/api/auth/oauth2-callback` directly, which depends on Traefik's OAuth2
  middleware guarding that path (see `backend/app/routers/CLAUDE.md`).
