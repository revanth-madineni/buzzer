# frontend/

## Purpose
The three browser clients for Buzzer, each a separate React 18 + Vite 5 + Tailwind 3 +
TypeScript single-page app:
- **`host/`**: the instructor's projector screen, which creates and drives a game, plus a
  per-course management area (games, questions, roster, images, session results) for course
  HOSTs.
- **`player/`**: students' phones, to join a room and answer.
- **`admin/`**: the staff desktop console for courses, rosters, users, games, questions,
  images, access grants, and session exports.

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

### Theme system (T9)
Light and dark themes in all three apps, from one set of semantic colour tokens. The spec is
`docs/plans/t9-theming.md`, and the evidence (screenshots, checklist) is `docs/ui/README.md`.
- **Tokens.** Each app's `src/theme.css` defines the tokens as RGB-channel CSS variables
  (`--surface: 30 41 59`) in fixed blocks:
  - invariant tokens: answer colours, map overlays, the QR tile, the scrim;
  - dark values, which are also the fallback;
  - light values;
  - in the host only, `[data-stage]` overrides that raise projected game screens to 7:1.

  `tailwind.config.ts` maps every token to `rgb(var(--name) / <alpha-value>)` and
  **replaces** the Tailwind palette, so components use `bg-surface`, `text-fg-muted`,
  `bg-scrim/70` and so on. A raw palette class such as `bg-slate-800` compiles to nothing,
  with no error. No `dark:` variants are used anywhere.
- **Switching.** The theme is `data-theme="light|dark"` on `<html>`.
  - **First paint:** a classic inline script in each `index.html` sets it before first paint.
    A stored choice wins; otherwise `prefers-color-scheme` decides.
  - **After load:** `src/lib/theme.ts` (a small store, initialised in `main.tsx`) keeps it
    following the OS until the user toggles, then persists the choice.
  - **The toggle:** `src/components/ThemeToggle.tsx` is the button. Each page or layout
    renders its own; nothing matches route paths.
- **Per-app storage keys.** Each `index.html` declares its key once, as
  `<html data-theme-key="buzzer:theme:host|player|admin">`. Unlike the login token (see
  Gotchas), the keys are deliberately separate, so toggling the admin console on the shared
  nginx origin never flips the projector. No app may call `localStorage.clear()`.
- **Focus.** One global `:focus-visible` outline (2px `focus`, 2px transparent offset) in each
  `index.css`, with no per-component focus classes. `data-fill` (focus inside a filled
  container) and `.focus-inset` (inside clipping containers) cover the two cases it can't.
- **The gate: `python scripts/check_theme.py`.** It checks for raw colours, WCAG contrast of
  the token pairs and the byte-identical groups. It is a **manual pre-MR gate, not in CI**:
  `.gitlab-ci.yml` stays unmodified, and the MR template carries it as a checklist item.
  Narrow it while working with `--app` and `--check`.

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
| admin | global role (USER↔ADMIN), course HOST/PLAYER grants, game grants, `restricted`, game ↔ course assignment, `allow_guests`, course rosters, images (T8) | — (everything is `require_admin`) |
| host | game sessions (`POST /game/rooms`); for courses they HOST: games, questions, roster uploads, images (T8) | HOST on the **game's** course (+ a grant if the game is restricted) to run or edit it (ADMIN bypasses). Session results: HOST on the session's course. Rejoin/delete/drive a live session: ownership (`host_user_id`) or ADMIN. |
| player | GUEST users (`/auth/guest`), scores (via socket) | active roster row **or** course PLAYER/HOST grant to join (ADMIN and GUEST join any room) |

**Games belong to a course** (T4). Every HOST of course C can create, edit and run C's games.
An admin can mark a game `restricted`, and then a host also needs a per-game grant. A room can
only be created in the game's own course. To let an instructor run games in C, an admin grants
them HOST on C (admin app → Access).

### One game, end to end
1. **Admin setup:** course and the instructor's HOST grant (admin Access page). The instructor
   can then upload the roster and create games + questions in the host app's management area,
   or the admin does it in the admin app. Images (T8, `docs/plans/t8-images.md`) are uploaded
   per course (or unassigned, admin only), with alt text, from the editors' picker or the
   Images page in either app.
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
- **Almost no token refresh.** The 2 h access token is renewed only by `lib/images.ts` (T7),
  which calls `/api/auth/refresh` once when an image load (a map, or since T8 any
  `AuthImage`) gets a 401. `api.ts` in every app
  still has no refresh or 401 retry.
- **Copy-pasted code instead of a shared package.** `lib/api.ts`, `lib/utils.ts`, and
  `components/ui/*` are duplicated. Host ≡ admin byte-for-byte (including `api.ts` since T4);
  the player's `api.ts` is older, and its `ui/*` are re-tuned for touch. Socket payload types in
  `host/src/types/` and `player/src/types/` are hand-written, already drift from the server, and
  hard-code event names from `backend/app/websocket/events.py`. A fix or a new question type
  must be applied per app. Some files are kept **byte-identical** on purpose, and
  `scripts/check_theme.py` checks it (one md5 per group). Edit one copy, then copy it to the
  others:
  - in all three apps: `tailwind.config.ts`, `lib/theme.ts`, `components/ThemeToggle.tsx`
    (T9), `lib/mapPin.ts`, `lib/slider.ts` (T7 slider: the client mirror of
    `backend/app/services/slider_math.py`), `lib/images.ts`, `components/MapCanvas.tsx` (T7) and
    `components/AuthImage.tsx` (T8: an uploaded image by ID, `object-contain`, with loading
    and error placeholders);
  - in player and admin: `src/theme.css` (the host's is the same text plus the stage blocks);
  - in host and admin: `components/ui/{button,card,input}.tsx` and `components/ImagePicker.tsx`
    (T8: list/upload course images with alt text; the caller passes the per-app endpoints, and
    it exports the shared image types and alt-text helpers).
- **Two question editors.** The host `pages/manage/QuestionEditorPage.tsx` is an adapted copy of
  the admin one (host endpoints, no JSON export). A form change must be made in both. Since T8
  both support a prompt image on every type and image options on multiple_choice /
  multi_select (`config.optionImageIds` parallel to `options`). The host copy lists and uploads
  images under the **game's** `course_id`, not the `:courseId` route param. The host
  `pages/manage/ImagesPage.tsx` is likewise an adapted copy of the admin `ImagesPage` (one
  course, no course filter).
- **Adding a question type** touches both `QuestionEditorPage`s (form + `answer_data` keys,
  which mix `answer_points` with fill-in-the-blank's camelCase), the host `QuestionPage` /
  `ResultsPage` / `GameOverPage`, the player `QuestionPage` / `ResultsPage` / `GameOverPage`,
  both `types/game.ts`, and the backend scoring and reveal code. map_pin (T7) is the worked
  example: see `docs/plans/t7-map-pin.md`. slider (T7, `docs/plans/t7-slider.md`) touched
  the same set plus a new byte-identical `lib/slider.ts`, the player `SliderInput` and the
  host `SliderHistogram`. T8's prompt and option images touched the same set
  of files without a new type (`docs/plans/t8-images.md`).
- **No frontend test runner.** `lib/slider.ts` was compiled with `tsc` and checked in Node
  against `slider_math.py` on 9 configs (indices, values, bins, target lines all equal), and
  the slider UI was clicked through once in headless Chromium (editor, a live game with two
  phone-sized players in both themes, game over, report). Nothing re-runs either.
  None of the three apps can run tests, so the map-pin canvas,
  pointer handling, image loading and the player's non-fatal late-answer handling were only
  type-checked and built. The T8 image UI (editors' image fields, `ImagePicker`, both Images
  pages, the player's image-option grid, the host's prompt image and all the thumbnails) has
  never been run in a browser. Verify them by hand on a phone and a projector.
- **Stale config build output (fixed in T9).** `tsconfig.node.json` is composite and includes
  `vite.config.ts` and `tailwind.config.ts`. Before T9, `tsc -b` (in `npm run build`) emitted
  `vite.config.js` and `tailwind.config.js` beside them. Vite and Tailwind load the `.js`
  config before the `.ts` one, so `.ts` edits were silently ignored under `npm run dev`.
  `"emitDeclarationOnly": true` now stops that.
  - **To verify:** after `npm run build`, `ls frontend/*/tailwind.config.js
    frontend/*/vite.config.js` finds nothing (`check_theme.py --check identical` also fails if
    one exists).
  - **Old checkouts:** a checkout from before T9 may still have the old `.js` files; delete
    them.
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
