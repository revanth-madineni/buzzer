# frontend/admin/src/lib/

## Purpose
Small shared helpers for the admin (desktop) app: a JSON fetch wrapper for the REST API with
the full set of verbs plus multipart upload and file download, and a Tailwind class-merge
helper. There is no socket code and no role logic here. The admin app never opens a socket.

## Contents
- `api.ts` — every method sends `Authorization: Bearer <localStorage.token>` when a token
  exists. On non-2xx it throws `Error(errorMessage(res))`: the body's `message`
  (`BuzzerError`), else a string `detail` (`HTTPException`), else "Invalid input" for a
  validation array, else `HTTP <status>`. Identical to the host app's `lib/api.ts`.
  - `api.get` / `post` / `put` / `patch` / `delete<T>(path, body?)` over `fetch('/api' + path)`
    with `Content-Type: application/json`. An empty response body (the many 204s) resolves to
    `{}`.
  - `api.postForm<T>(path, form: FormData)` — multipart POST with **no** `Content-Type`, so
    the browser sets the boundary. Used for the game JSON import.
  - `api.download(path)` — GET, reads the filename from `Content-Disposition:
    filename="…"` (falls back to `download`), wraps the body in a Blob, and clicks a temporary
    `<a download>`. Used for CSV/JSON/HTML exports.
- `utils.ts` — `cn(...)` (clsx + tailwind-merge), used by `components/ui/*`.

## How it fits in
Consumers (all under `pages/`), grouped by the backend guard (see
`backend/app/routers/CLAUDE.md` for the access map and `backend/app/common/CLAUDE.md` for the
dependencies):

**Admin-only (`require_admin`, everything under `/api/admin/`):**
| caller | calls |
|---|---|
| `CoursesPage` | `GET/POST /admin/courses`, `PUT /admin/courses/{id}` (incl. `allow_guests`) |
| `AccessPage` | `GET /admin/courses`, `GET /admin/users`, `GET /admin/courses/{id}/access`, `POST/DELETE /admin/users/{uid}/course-access[/{cid}]`, `GET /admin/games`, `PUT /admin/games/{id}` (`restricted`), `GET /admin/games/{id}/access`, `POST/DELETE /admin/users/{uid}/game-access[/{gid}]`, plus `MoveGamePanel` |
| `components/MoveGamePanel` | `POST /admin/games/{id}/move` (`confirm=false`, then `true`) |
| `RosterPage` | `GET /admin/courses/{id}/roster`, `POST .../roster/import` (JSON `{rows}`, parsed client-side), `PATCH .../roster/{entryId}` |
| `UsersPage` | `GET/POST /admin/users` |
| `UserDetailPage` | `GET/PUT/DELETE /admin/users/{id}`, `POST`/`DELETE .../course-access[/{courseId}]`, `POST`/`DELETE .../game-access[/{gameId}]`, plus `GET /admin/courses` and `/admin/games` for the pickers |
| `GuestsPage` | `GET /admin/users/guests`, `POST /admin/users/merge-guest`, `DELETE /admin/users/{id}` |
| `GamesPage` | `GET/POST /admin/games` (with `course_id`), `GET /admin/courses`, `PUT`/`DELETE /admin/games/{id}`, `postForm /admin/games/import` (`file` + `course_id`), plus `MoveGamePanel` |
| `QuestionEditorPage` | `GET /admin/games/{id}`, `GET/POST .../questions`, `PUT`/`DELETE .../questions/{qid}`, `POST .../questions/reorder`, `download .../export` |
| `SessionsPage` | `GET /admin/sessions[?status=]`, `download /admin/sessions/{id}/export?…` (raw or Canvas CSV), `download .../report` (HTML) |

**Not under `/admin`:**
- `LoginPage`: `POST /auth/login` (username + password only; no NetID SSO).
- `SessionsPage`: `DELETE /game/sessions/{id}`. This is the **host** endpoint
  (`require_user` + ADMIN-or-owner). There's no admin session-delete endpoint, so the admin
  app relies on the ADMIN bypass there.

Access grants are written from `AccessPage` and `UserDetailPage`. `course-access` sets a
user's per-course `HOST | PLAYER` role, and `game-access` adds a `UserGameAccess` row. The host
app's `my-courses` / `my-games` / `POST /game/rooms` and `/api/host/*` read them (see
`frontend/host/src/pages/CLAUDE.md`). Each game belongs to one course, and a game grant only
matters on a `restricted` game, for a user who is HOST on its course (see
`backend/app/models/CLAUDE.md`).

The auth token lives in `localStorage['token']`. It is written by `LoginPage`, read here, and
removed by the sidebar Logout in `App.tsx`. `App.tsx`'s `RequireAdmin` only checks that the key
is **present**, despite its name.

## Gotchas
- **No client-side admin check.** `/auth/login` issues tokens to any account with a password,
  including non-admin local `USER`s, and `RequireAdmin` doesn't look at the role. A non-admin
  gets the full sidebar, and every page fails with `require_admin`'s "Admin access required"
  instead of being turned away at login. The JWT does carry a `role` claim the client could
  decode, but the server ignores it and uses the DB role anyway (see `common/CLAUDE.md`).
- **The token is shared with the host and player apps.** Behind nginx all three apps share
  one origin and the same `localStorage['token']` key. Logging into the player app as a guest
  in the same browser silently replaces the admin's token, and logging out anywhere logs out
  everywhere. See `frontend/host/src/lib/CLAUDE.md`.
- **Admins who only have NetID can't use the admin app.** There's no SSO button here, so an
  ADMIN needs a local username + password.
- **Validation errors are generic.** A 422 `VALIDATION_ERROR` shows only "Invalid input". The
  field-level `detail` array isn't rendered.
- **Download is fragile.** The filename regex needs a double-quoted `filename="…"` (which the
  backend sends) and ignores RFC 5987 `filename*=`. The Blob URL is revoked right after
  `click()`, which some browsers can race. There's no progress indicator, and the whole file is
  buffered in memory.
- **No token refresh.** Nothing calls `/api/auth/refresh`, and there is no 401 retry. After the
  2 h access token expires every call fails, but `RequireAdmin` still lets the user in.
- JSON methods set `Content-Type: application/json` even on GET/DELETE.
- This file is identical to the host app's `lib/api.ts`, but it is a copy, not shared. All
  helpers use one `errorMessage` function. The player's `lib/api.ts` is older and still reads
  only `detail`. A fix has to be made in each app.
