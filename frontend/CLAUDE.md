# frontend/

## Purpose
The three browser clients for Buzzer, each a separate React 18 + Vite 5 + Tailwind 3 +
TypeScript single-page app:
- **`host/`**: the instructor's projector screen, which creates and drives a game.
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
  - Host endpoints (`/api/game/my-*`, `POST /game/rooms`, session tools) need `ADMIN` or
    `USER`.
  - GUESTs can only join as players.
- **Per-course `UserCourseAccess.role`** (`HOST | PLAYER`) plus **per-game `UserGameAccess`**.

| app | writes | reads (via backend checks) |
|---|---|---|
| admin | global role (USER↔ADMIN), course HOST/PLAYER grants, game grants, course rosters | — (everything is `require_admin`) |
| host | game sessions (`POST /game/rooms`) | course HOST **and** game grant to create a room (ADMIN bypasses). Only session ownership (`host_user_id`) or ADMIN to rejoin/delete/drive it later. |
| player | GUEST users (`/auth/guest`), scores (via socket) | active roster row **or** course PLAYER/HOST grant to join (ADMIN and GUEST join any room) |

**Games have no course.** A game is a reusable question bank; the course is chosen when the host
creates a room, and the two only meet on `GameSession`. To let an instructor run game G in
course C, an admin grants HOST on C **and** access to G, separately.

### One game, end to end
1. **Admin setup:** course, roster CSV, game + questions, instructor's HOST + game grants.
2. **Host creates a room:** sign in (NetID SSO or local account), pick course + game, get a
   6-char code and a QR pointing to `/player/join?code=…`.
3. **Players join:** ping the code, get a token (guest, NetID, or local account), socket
   `join_room`.
4. **The host drives each question:** `host_advance` / `host_lock_question`. Server events fan
   out, with distributions + anonymous scores to the host and personal results to each player.
5. **After the game,** the admin exports Canvas CSV or the HTML report from `SessionsPage`.

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
  Wrong-role users get into the UI and hit 403s, which show as a bare `HTTP 403`.
- **The same `detail`-vs-`message` bug in all three `lib/api.ts`.** The backend's `BuzzerError`
  sends `{error, message}`, but every wrapper reads `detail`, so most server error messages
  never reach the user.
- **No token refresh in any app.** The 2 h access token is never renewed, even though a 7-day
  refresh cookie is set.
- **Copy-pasted code instead of a shared package.** `lib/api.ts` (five variants of the same
  error handling across the three apps), `lib/utils.ts`, and `components/ui/*` are duplicated:
  host ≡ admin byte-for-byte, and player is re-tuned for touch. Socket payload types in
  `host/src/types/` and `player/src/types/` are hand-written, already drift from the server, and
  hard-code event names from `backend/app/websocket/events.py`. A fix or a new question type
  must be applied per app.
- **Adding a question type** touches the admin `QuestionEditorPage` (form + `answer_data` keys,
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
