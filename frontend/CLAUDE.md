# frontend/

## Purpose
The three browser clients for Buzzer, each a separate React 18 + Vite 5 + Tailwind 3 +
TypeScript single-page app:
- **`host/`**: the instructor's projector screen, which creates and drives a game, plus a
  per-course management area (games, questions, roster, session results) for course HOSTs.
- **`player/`**: students' phones, to join a room and answer.
- **`admin/`**: the staff desktop console for courses, rosters, users, games, questions,
  access grants, and session exports.

They share no code. Each talks to the same FastAPI backend (`backend/app/CLAUDE.md`) over
`/api` REST, and host + player also over Socket.IO.

## Contents
Nothing lives directly in `frontend/` except the three app directories. Each is a standalone
npm project with its own `package.json`, lockfile, `node_modules`, `vite.config.ts`,
`tailwind.config.ts`, `tsconfig*.json`, `index.html`, and `dist/` build output. Each app's
`src/` has a `CLAUDE.md` summary with per-directory files below it.

| app | `src/` summary | prod base | dev port | talks via | extra deps |
|---|---|---|---|---|---|
| `host/` | `host/src/CLAUDE.md` | `/host/` | 5173 | REST + Socket.IO (`role: "HOST"`) | `socket.io-client`, `qrcode.react` |
| `player/` | `player/src/CLAUDE.md` | `/player/` | 5174 | REST + Socket.IO (`role: "PLAYER"`) | `socket.io-client` |
| `admin/` | `admin/src/CLAUDE.md` | `/admin/` | 5175 | REST only | — |

All three share the same internal layout: `main.tsx` → `App.tsx` (routes + auth guard) →
`pages/` → `components/ui/` + `lib/` (+ `types/` in host and player). There's no global store.
Live-game state is React state in each game app's `pages/game/GameLayout.tsx`, exposed via
`useGame()`.

## How it fits together

### Running it
- **Commands** come from the repo-root `package.json`. `npm run install:all` installs all three
  apps. `npm run dev` runs all three Vite dev servers via `concurrently`, and `dev:host` /
  `dev:player` / `dev:admin` run one. `npm run build` builds all three into their `dist/`.
- **Dev servers.** Each Vite server proxies `/api` (and `/socket.io` for host/player) to
  `localhost:8000`, with base `/`, so each app runs on its own origin/port.
- **Docker / nginx** (`docker-compose.yml`, `nginx/nginx.dev.conf`, port 8080): nginx serves
  the **pre-built** `frontend/*/dist` folders at `/host/`, `/player/`, `/admin/` (SPA fallback to
  each `index.html`), proxies `/api/` and `/socket.io/` to the backend, and redirects `/` to
  `/player/`. **All three apps and the API share one origin here.**

### How the three apps relate to one role model
The backend has two separate role systems (`backend/app/models/CLAUDE.md`). No frontend
enforces either; every check is server-side (`backend/app/common/CLAUDE.md`,
`routers/CLAUDE.md`, `services/CLAUDE.md`, `websocket/CLAUDE.md`).
- **Global `User.role`** (`ADMIN | USER | GUEST`):
  - Admin endpoints (`/api/admin/*`) need `ADMIN`.
  - Host endpoints (`/api/game/my-*`, `POST /game/rooms`, session tools, and the course-host
    management API `/api/host/*`) need `ADMIN` or `USER`, plus the course checks below.
  - GUESTs can only join as players.
- **Per-course `UserCourseAccess.role`** (`HOST | PLAYER`) plus **per-game `UserGameAccess`**
  grants, which only matter for games an admin has marked `restricted`.

| app | writes | reads (via backend checks) |
|---|---|---|
| admin | global role (USER↔ADMIN), course HOST/PLAYER grants, game grants, `restricted`, game ↔ course assignment, `allow_guests`, course rosters | — (everything is `require_admin`) |
| host | game sessions (`POST /game/rooms`); for courses they HOST: games, questions, roster uploads | HOST on the **game's** course (+ a grant if the game is restricted) to run or edit it (ADMIN bypasses). Session results: HOST on the session's course. Rejoin/delete/drive a live session: ownership (`host_user_id`) or ADMIN. |
| player | GUEST users (`/auth/guest`), scores (via socket) | active roster row **or** course PLAYER/HOST grant to join (ADMIN and GUEST join any room) |

**Games belong to a course** (T4). Every HOST of course C can create, edit and run C's games.
An admin can mark a game `restricted`, and then a host also needs a per-game grant. A room can
only be created in the game's own course. To let an instructor run games in C, an admin grants
them HOST on C (admin app → Access).

### One game, end to end
1. **Admin setup:** course and the instructor's HOST grant (admin Access page). The instructor
   can then upload the roster and create games + questions in the host app's management area,
   or the admin does it in the admin app.
2. **Host creates a room:** sign in (NetID SSO or local account), pick course + game, get a
   6-char code and a QR pointing to `/player/join?code=…`.
3. **Players join:** ping the code, get a token (guest, NetID, or local account), socket
   `join_room`.
4. **The host drives each question:** `host_advance` / `host_lock_question`. Server events fan
   out, with distributions + anonymous scores to the host and personal results to each player.
5. **After the game,** any HOST of the course downloads the score CSV or HTML summary from the
   host app's Sessions page; the admin can also export Canvas CSV from the admin `SessionsPage`.

## Gotchas
Cross-app issues. Per-app details are in each `src/CLAUDE.md`.
- **One login token for all three apps.** All use `localStorage['token']`, and behind nginx
  they share an origin. Signing in anywhere replaces the token everywhere:
  - A player's guest join logs out the host or admin in the same browser.
  - A host's token is silently reused when opening the player app.
  - Logout in any app logs out all three.
  In Vite dev (separate ports = separate origins) this **doesn't** happen, so it only shows up
  under nginx.
- **No client-side role gates anywhere.** Each `App.tsx` guard only checks that a token exists.
  Wrong-role users get into the UI and hit 403s. Host and admin show the server's message; the
  player app shows a bare `HTTP 403`.
- **Error messages: fixed in host and admin, not in player.** The backend's `BuzzerError` sends
  `{error, message}`. The host and admin `lib/api.ts` read `message`, then a string `detail`,
  then "Invalid input" for validation arrays (T4). The player wrapper still reads only `detail`.
- **No token refresh in any app.** The 2 h access token is never renewed, even though a 7-day
  refresh cookie is set.
- **Copy-pasted code instead of a shared package.** `lib/api.ts`, `lib/utils.ts`, and
  `components/ui/*` are duplicated. Host ≡ admin byte-for-byte (including `api.ts` since T4);
  the player's `api.ts` is older, and its `ui/*` are re-tuned for touch. Socket payload types in
  `host/src/types/` and `player/src/types/` are hand-written, already drift from the server, and
  hard-code event names from `backend/app/websocket/events.py`. A fix or a new question type
  must be applied per app.
- **Two question editors.** The host `pages/manage/QuestionEditorPage.tsx` is an adapted copy of
  the admin one (host endpoints, no JSON export). A form change must be made in both.
- **Adding a question type** touches both `QuestionEditorPage`s (form + `answer_data` keys,
  which mix `answer_points` with fill-in-the-blank's camelCase), the host `QuestionPage` /
  `ResultsPage` / `GameOverPage`, the player `QuestionPage` / `ResultsPage` / `GameOverPage`,
  both `types/game.ts`, and the backend scoring and reveal code.
- **`docker compose up` doesn't build the frontends.** nginx mounts `frontend/*/dist`
  read-only. Run `npm run build` first, and again after every frontend change; there's no hot
  reload through nginx. Use `npm run dev` for iterative work.
- **Some links assume the nginx layout.** The host's QR code and the OAuth2 `redirect_to`
  targets (`/host/login`, `/player/login`) use prefixed paths on the current origin. Under
  separate Vite dev servers (base `/`, one app per port) those paths don't resolve to the
  intended app. SSO also depends on the Traefik OAuth2 proxy headers (`routers/CLAUDE.md`), so
  it can't be exercised in plain Vite dev anyway.
- `StrictMode` is on in all three, so in dev every mount effect runs twice. For host/player
  that means a socket connect → disconnect → reconnect blip.
