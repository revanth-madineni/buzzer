# frontend/host/src/

## Purpose
The host app: a React + Vite + Tailwind single-page app that an instructor runs on the
projector. They sign in, pick a course + game to create a room (or rejoin/delete one of their
active sessions), show the QR code and room code, and drive the game (start, lock/unlock,
show results, next question) through to an anonymous score histogram and per-question
breakdown. The host is the only client that advances the game. Course HOSTs also get a
management area (T4) for each course: games and questions, the roster, and completed-session
downloads.

## Contents
Top-level files:
- `main.tsx` — Mounts `<App />` in `StrictMode` and imports `index.css`.
- `App.tsx` — `react-router` routes under basename `import.meta.env.BASE_URL` (`/host/` in
  production, `/` in dev): `/login`, `/home`, `/game/:code/{lobby,question,results,gameover}`
  nested under `GameLayout`, and `/courses/:courseId/{games,games/:gameId/questions,roster,
  sessions}` nested under `HostLayout` (defined in `App.tsx`). `HostLayout` has a course picker
  from `my-courses`; switching course keeps the section. It also has Games / Roster / Sessions
  links, "Play" (→ `/home`) and Sign out. Everything except `/login` sits behind `RequireAuth`,
  which only checks that `localStorage.token` is **present**. Anything else redirects to
  `/login`.
- `index.css` — Tailwind directives and global dark-slate body styles.
- `types/game.ts` — TypeScript shapes for socket payloads (`SyncStatePayload`,
  `QuestionPayload` incl. `gradingType`/`editDistance`/`startedAt`, `HostResultsPayload`,
  `AnswerReveal`, `HostGameOverPayload`, `HostQuestionSummaryItem`, …) and `HostPhase`. It has
  no context file of its own.

Subdirectories (each has its own `CLAUDE.md`):
| dir | role |
|---|---|
| `lib/` | `api.ts` REST wrapper (`get`/`post`/`put`/`patch`/`delete`, `postForm`, `download`; Bearer token from `localStorage.token`; shows the server's error `message`), `cn()`, and (T7) `mapPin.ts` + `images.ts`. No role logic. |
| `components/` | `ui/` primitives (`Button`, `Card`, `Input`), the display-only `TimerBar` (supports a mid-question `initialSeconds`), and (T7) `MapCanvas` + `MapPinHeatmap`. |
| `pages/` | `LoginPage`, `HomePage` (course → that course's games, "Manage this course", active sessions), `game/*`, and `manage/*` (Games, QuestionEditor, Roster, Sessions). `game/GameLayout.tsx` owns the socket and shares state via `useGame()`. |

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
  `my-games` gives ADMIN every game; a USER gets the games of their HOST courses, minus
  restricted games they have no grant on. GUEST gets 403 on both.
- **Games belong to a course.** The game dropdown shows only the selected course's games
  (`course_id`). The server rejects a room for another course with 422 `COURSE_MISMATCH`.
- **Creating a room** (`POST /game/rooms`) needs HOST on the game's course (+ a grant if the
  game is restricted); ADMIN bypasses that.
- **The management area** calls `/api/host/*`. Every call is checked server-side against the
  course the resource belongs to (`backend/app/routers/CLAUDE.md`).
- **Managing a session afterwards** checks only ownership (`host_user_id`) or ADMIN. This covers
  `my-active-sessions`, delete, and socket `join_room` as HOST. Course role isn't rechecked.
- **Admin-only endpoints are never called.** Nothing under `/api/admin/*` is used. Results
  are downloaded via `/api/host/sessions/{id}/export|report`. The older
  `/api/game/sessions/{id}/export|guests|merge-guest` are still not wired in.

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
- **No token refresh, except for images.** The 2 h access token is renewed only when
  `lib/images.ts` gets a 401 loading a map; `RequireAuth` still admits an expired token.
- **Map pin is untested in a browser.** No test runner; the heatmap and editor canvas were only
  type-checked and built. Check them by hand.
- **Reconnect gaps.** In the RESULTS phase the chart is empty (results aren't in `sync_state`).
  A COMPLETED game strands the host on an empty lobby. `TimerBar` resume and reconnect math
  use the client clock and frozen client values, so the bar can drift from the server's timer
  (`components/CLAUDE.md`).
- **Auto-advance stalls while a question is locked** (the server timer is paused, so
  `answer_phase_ended` never fires) and resets to off on reload.
- **The QR/join URL only works behind nginx.** Under `npm run dev:host` it points at the host
  app itself.
- **Duplicated code across apps.** `lib/api.ts`, `components/ui/*` and
  `pages/manage/QuestionEditorPage.tsx` (from the admin app) are copies, not shared.
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
