# frontend/host/src/

## Purpose
The host app: a React + Vite + Tailwind single-page app that an instructor runs on the
projector. They sign in, pick a course + game to create a room (or rejoin/delete one of their
active sessions), show the QR code and room code, and drive the game (start, lock/unlock,
show results, next question) through to an anonymous score histogram and per-question
breakdown. The host is the only client that advances the game.

## Contents
Top-level files:
- `main.tsx` — Mounts `<App />` in `StrictMode` and imports `index.css`.
- `App.tsx` — `react-router` routes under basename `import.meta.env.BASE_URL` (`/host/` in
  production, `/` in dev): `/login`, `/home`, and `/game/:code/{lobby,question,results,gameover}`
  nested under `GameLayout`. `/home` and `/game/*` sit behind `RequireAuth`, which only checks
  that `localStorage.token` is **present**. Anything else redirects to `/login`.
- `index.css` — Tailwind directives and global dark-slate body styles.
- `types/game.ts` — TypeScript shapes for socket payloads (`SyncStatePayload`,
  `QuestionPayload` incl. `gradingType`/`editDistance`/`startedAt`, `HostResultsPayload`,
  `AnswerReveal`, `HostGameOverPayload`, `HostQuestionSummaryItem`, …) and `HostPhase`. It has
  no context file of its own.

Subdirectories (each has its own `CLAUDE.md`):
| dir | role |
|---|---|
| `lib/` | `api.ts` REST wrapper (`get`/`post`/`delete`, Bearer token from `localStorage.token`) and `cn()`. No role logic. |
| `components/` | `ui/` primitives (`Button`, `Card`, `Input`) and the display-only `TimerBar` (supports a mid-question `initialSeconds`). |
| `pages/` | `LoginPage`, `HomePage` (course/game pickers, active sessions), and `game/*`. `game/GameLayout.tsx` owns the socket and shares state via `useGame()`. |

## How it fits together
Dependency direction: `pages/` → `components/` + `lib/` + `types/`. There's no global store.
All live-game state is React state in `GameLayout`, exposed through context. The only
persistent client state is `localStorage.token`, which is shared with the player and admin
apps (see Gotchas).

In dev, Vite proxies `/api` and `/socket.io` to `localhost:8000`. Behind nginx, all three apps
and the API share one origin. The server side is described in `backend/app/CLAUDE.md` and its
subdirectories.

### Who may host what (all enforced server-side; the app checks nothing)
- **Two role systems.** Global `User.role` (`ADMIN | USER | GUEST`) and per-course
  `UserCourseAccess.role` (`HOST | PLAYER`). "Host" is not a global role; both are granted in
  the admin app's `UserDetailPage`.
- **What `HomePage` lists.** `my-courses` gives ADMIN every course, USER only HOST courses.
  `my-games` gives ADMIN every game, USER only games with a `UserGameAccess` grant. GUEST gets
  403 on both.
- **Games have no course.** The course and game dropdowns are independent, and they only meet
  on the `GameSession` a room creates. Any game you can use can be run in any course you host.
- **Creating a room** (`POST /game/rooms`) needs course HOST **and** the game grant; ADMIN
  bypasses both.
- **Managing a session afterwards** checks only ownership (`host_user_id`) or ADMIN. This covers
  `my-active-sessions`, delete, and socket `join_room` as HOST. Course role isn't rechecked.
- **Admin-only endpoints are never called.** Nothing under `/api/admin/*` is used. The
  host-accessible guest-merge and CSV-export endpoints exist but aren't wired into this app
  either.

### Data flow for one game
1. **Sign in.** `LoginPage`: NetID SSO (`/api/auth/oauth2-callback` → back to `/host/login` →
   `POST /api/auth/exchange-temp`) or local `POST /api/auth/login`. Token → `localStorage`,
   then → `/home`.
2. **Create or rejoin.** `HomePage` loads courses, games, and active sessions.
   `POST /api/game/rooms {course_id, game_id}` → `/game/{code}/lobby`. "Rejoin" goes to the
   same URL and `sync_state` redirects to the right phase.
3. **Connect.** `GameLayout` opens `io({ auth: { token } })` and on every `connect` emits
   `join_room {room_code, role: "HOST"}`. The server checks owner-or-ADMIN and replies
   `sync_state`, which restores the phase, question, and lock state.
4. **Lobby.** `LobbyPage` shows the QR (`{origin}/player/join?code=…`), room code, and live
   player count (`player_joined` / `player_left`), plus the auto-advance toggle. "Start Game"
   emits `host_advance`.
5. **Question.** `new_question` → `QuestionPage`: header, `TimerBar`, prompt, and an
   `answered / players` count (`answer_status`). "Lock/Unlock" emits `host_lock_question`,
   which pauses the server timer. `answer_phase_ended` arrives on timeout or when everyone has
   answered.
6. **Results.** "Show Results" (`host_advance`) → `question_results` → `ResultsPage`: bar chart,
   or word cloud for fill-in-the-blank, with correct answers highlighted. "Next Question"
   (`host_advance`) loops to step 5.
7. **End.** The last advance → `game_over` → `GameOverPage` (score histogram, stats,
   per-question breakdown). "New Game" → `/home`. `game_abandoned` → `/home`.

## Gotchas
Most important cross-cutting issues. Details are in each subdirectory's file.
- **No client-side role gate.** `RequireAuth` only checks that a token exists. A GUEST or
  non-host USER reaches `/home` and sees a vague error or empty dropdowns (`pages/CLAUDE.md`).
- **Any global ADMIN can take over any live session** by opening its URL. Socket `join_room`
  accepts ADMIN regardless of `host_user_id`, with no warning to the real host.
- **Token collision with the player/admin apps.** All three use `localStorage.token` on one
  origin. A guest join in the player app on the same browser replaces the host's login, and
  logging out anywhere logs out everywhere (`lib/CLAUDE.md`).
- **Backend error text is lost.** `api.ts` reads `detail`, but `BuzzerError` (including
  `require_user`'s 403 and `create_room`'s "no HOST access" 403) sends `message`. The host
  sees `HTTP 403`.
- **No token refresh.** The 2 h access token is never renewed, and `RequireAuth` still admits an
  expired token.
- **Reconnect gaps.** In the RESULTS phase the chart is empty (results aren't in `sync_state`).
  A COMPLETED game strands the host on an empty lobby. `TimerBar` resume and reconnect math
  use the client clock and frozen client values, so the bar can drift from the server's timer
  (`components/CLAUDE.md`).
- **Auto-advance stalls while a question is locked** (the server timer is paused, so
  `answer_phase_ended` never fires) and resets to off on reload.
- **The QR/join URL only works behind nginx.** Under `npm run dev:host` it points at the host
  app itself.
- **Duplicated code across apps.** `lib/api.ts` and `components/ui/*` are copies, not shared.
  `ui/*` is byte-identical to the admin app's and tuned differently from the player's. Question
  type labels and answer-reveal rendering are duplicated across three pages here, and the word
  cloud re-implements Levenshtein client-side, so it can disagree with server grading.
- **`types/game.ts` is hand-maintained**, not generated from the backend. It omits fields the
  server sends (e.g. `sync_state`'s `role` and `questionIndex`), and the event names are string
  literals duplicated from `backend/app/websocket/events.py`.
- `StrictMode` double-runs effects in dev, so `GameLayout` connects, disconnects, and reconnects
  on mount. A host socket disconnect during `IN_PROGRESS` auto-locks the question server-side
  and the rejoin auto-unlocks it (`websocket/CLAUDE.md`), so reloading mid-game in dev can
  show a lock/unlock blip.
