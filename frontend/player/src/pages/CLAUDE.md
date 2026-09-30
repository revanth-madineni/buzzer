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
  multi-select + submit) with `TimerBar`. Calls `emitAnswer(questionId, answerData, msSinceMount)`.
- `game/FeedbackPage.tsx` — static "Answer locked in!" while waiting for the reveal.
- `game/ResultsPage.tsx` — this question's outcome, your answer, points, total, and rank.
- `game/GameOverPage.tsx` — final rank/score plus a per-question recap (your answer vs.
  correct). "Play Again" clears the token and goes to `/join`.

## How it fits in
Uses `lib/api.ts` + `lib/utils.ts` (see `lib/CLAUDE.md`) and `components/ui/*` (see
`components/CLAUDE.md`). Payload types are in `../types/game.ts`. The socket protocol and phase
machine are defined server-side in `backend/app/websocket/CLAUDE.md`.

### Event → navigation (GameLayout)
| server event | effect |
|---|---|
| `sync_state` | set count/lock; if `LOBBY` → `/lobby`; if `IN_PROGRESS`, **no navigation** |
| `new_question` | reset per-question state → `/question` |
| `answer_received` | (unless `alreadyAnswered`) → `/feedback` |
| `question_locked` / `_unlocked` | toggle `questionLocked` |
| `question_results` | → `/results` |
| `game_over` | → `/gameover`, then **disconnects** the socket |
| `host_disconnected` | show banner (cleared by the next `new_question`) |
| `game_abandoned` | → `/join` |
| `error` | full-screen error view |

Answer payloads sent: MC `{selectedIndex: number}`, T/F `{selectedValue: boolean}`, fill-in
`{text}` (trimmed), multi-select `{selectedIndices: number[]}`. These match what
`services/game_service.calculate_score` expects, so the backend's type-confusion gotchas
(string `"false"`, non-int index) aren't triggered by this client.

## Gotchas
- **Any server `error` event replaces the whole game UI.** GameLayout renders only the message
  and a "Back to Join" link, and the error clears only on the next socket `connect`. A routine
  race, such as submitting just as the question auto-locks ("Question is locked" / "No active
  question"), strands the player on an error screen mid-game.
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
- `QuestionPage` sets `submitted = true` before the server acknowledges. If the server rejects the
  answer, the UI still shows "submitted" (and then the error screen).
- `answer_time_ms` is measured from `QuestionPage` mount, not from server `started_at`, so late
  joiners and slow renders skew it.
- Error text from REST calls is mostly generic. JoinPage ignores the error and always says "Room
  not found", even when the game has ended (409). LoginPage reads `detail`, which this backend's
  own errors don't include (see `lib/CLAUDE.md`).
- The OAuth2 link hits `/api/auth/oauth2-callback` directly, which depends on Traefik's OAuth2
  middleware guarding that path (see `backend/app/routers/CLAUDE.md`).
