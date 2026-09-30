# frontend/player/src/

## Purpose
The player app: a React + Vite + Tailwind single-page app that students open on their phones
to join a room by code, sign in (guest, UW NetID, or local account), and answer questions in
real time. It shows answer controls and personal feedback only. The question prompt,
leaderboard, and answer distributions are on the host's big screen.

## Contents
Top-level files:
- `main.tsx` — Mounts `<App />` in `StrictMode` and imports `index.css`.
- `App.tsx` — `react-router` routes under basename `import.meta.env.BASE_URL` (`/player/` in
  production, `/` in dev): `/join`, `/login`, `/name/:code`, and `/game/:code/{lobby,question,
  feedback,results,gameover}` nested under `GameLayout`. Anything else redirects to `/join`.
- `index.css` — Tailwind directives and global styles.
- `types/game.ts` — TypeScript shapes for socket payloads (`SyncStatePayload`,
  `QuestionPayload`, `AnswerResultPayload`, `PlayerResultsPayload`, `PlayerAnswerReveal`,
  `PlayerGameOverPayload`, …) and `PlayerPhase`. It has no context file of its own.

Subdirectories (each has its own `CLAUDE.md`):
| dir | role |
|---|---|
| `lib/` | `api.ts` REST wrapper (Bearer token from `localStorage.token`), `cn()`, `isTokenExpired()`. |
| `components/` | `ui/` primitives (`Button`, `Card`, `Input`) and the client-side `TimerBar`. |
| `pages/` | Route components. `game/GameLayout.tsx` owns the socket and shares game state via `useGame()`. |

## How it fits together
Dependency direction: `pages/` → `components/` + `lib/` + `types/`. There's no global store.
All live-game state is React state in `GameLayout`, exposed through context. The only
persistent client state is in `localStorage`:
- `token`: shared with the host and admin apps, see Gotchas.
- `playerName` / `playerEmail`: guest pre-fill.
- `sessionStorage.joinRoomCode`: survives the OAuth2 round trip.

In dev, Vite proxies `/api` and `/socket.io` to `localhost:8000`. In production, both are
same-origin paths. The server side of every call below is described in
`backend/app/CLAUDE.md` and its subdirectories.

### Data flow for one game
1. **Find the room.** `JoinPage` checks `GET /api/game/rooms/{code}/ping` (public; `?code=`
   from a QR code auto-submits) and navigates to `/name/{code}`.
2. **Get a token.** `NamePage`:
   - Guest: `POST /api/auth/guest`.
   - Local account: `POST /api/auth/login`.
   - NetID: link to `/api/auth/oauth2-callback`. The backend redirects to `/player/login`,
     where `LoginPage` swaps the temp token via `POST /api/auth/exchange-temp` and returns to
     `/name/{code}`.
   The access token is stored in `localStorage.token`. Then → `/game/{code}/lobby`.
3. **Connect.** `GameLayout` checks `isTokenExpired` and opens `io({ auth: { token } })`. On
   every `connect` it emits `join_room {room_code, role: "PLAYER"}`. The server replies
   `sync_state`; `LOBBY` goes to `LobbyPage`, and the player count updates via `player_joined`.
4. **Question.** `new_question` stores `currentQuestion`, resets per-question state, and goes to
   `QuestionPage`. That page renders controls by `type` and a `TimerBar` keyed by `questionId`.
5. **Answer.** Tapping calls `emitAnswer` → `submit_answer {question_id, answer_data,
   answer_time_ms}`. `answer_received` goes to `FeedbackPage`, which deliberately doesn't
   show whether the answer was right.
6. **Lock.** `question_locked` / `question_unlocked` toggle `questionLocked`, which disables
   the controls and pauses `TimerBar`. The timer is cosmetic; the server lock is what stops
   answers.
7. **Reveal.** When the host advances, `question_results` (your points, total, rank, answer
   reveal) goes to `ResultsPage`. The next `new_question` loops back to step 4.
8. **End.** `game_over` goes to `GameOverPage` (final rank, per-question recap) and the socket is
   **disconnected**. "Play Again" clears the token and goes to `/join`. `game_abandoned` goes
   straight to `/join`, and `host_disconnected` shows a banner.

Answer payloads (`{selectedIndex}`, `{selectedValue: boolean}`, `{text}`,
`{selectedIndices: number[]}`) match the keys `backend/app/services/game_service.calculate_score`
reads.

## Gotchas
Most important cross-cutting issues. Details are in each subdirectory's file.
- **One `error` event ends the game view.** Any server `error` (even a routine "Question is
  locked" race) replaces the whole UI with a full-screen message until the next reconnect
  (`pages/CLAUDE.md`).
- **Token collision with the host/admin apps.** All three apps use `localStorage.token`, and in
  production they're served from `/player/`, `/host/`, and `/admin/` on what appears to be one
  origin. A signed-in host or admin is silently reused as the player, and "Play Again" logs them
  out.
- **No token refresh.** The 2 h access token is never renewed (`/auth/refresh` is unused). A
  socket reconnect after expiry is rejected (`lib/CLAUDE.md`).
- **Refresh/reconnect can strand the player.** State is only in React, and `sync_state` for an
  in-progress game doesn't navigate or restore the question or results. The server re-sends
  only an open, unlocked, unanswered question.
- **Backend error text is lost.** `api.ts` and `LoginPage` read `detail`, but most backend
  errors use `message` (`backend/app/CLAUDE.md`, error shape).
- **Client and server disagree on "correct".** The client shows "Correct!" for any
  `points > 0`, while the server's `isCorrect` requires full points.
- **`types/game.ts` is hand-maintained** and already lags the server. `QuestionPayload` omits
  `gradingType`/`editDistance`/`orderIndex`, and `SyncStatePayload` omits `currentQuestion`,
  `hasAnswered`, and `yourScore`, all of which the server sends. Nothing is generated from the
  backend, and the event names are string literals duplicated from
  `backend/app/websocket/events.py`.
- `StrictMode` double-runs effects in dev, so `GameLayout` connects, disconnects, and reconnects
  on mount. Expect a `player_left` / `player_joined` blip on the host screen in development only.
