# frontend/host/src/lib/

## Purpose
Small shared helpers for the host (big-screen) app: a JSON fetch wrapper for the REST API
(including multipart upload and file download for the management area), a Tailwind
class-merge helper, and (T7) map-pin geometry and authenticated image loading. There is no socket code and no role or course-access
logic here. The Socket.IO client is created in `pages/game/GameLayout.tsx`.

## Contents
- `api.ts` — the same file as the admin app's `lib/api.ts`:
  - `api.get` / `post` / `put` / `patch` / `delete<T>` over `fetch('/api' + path)`, with
    `Content-Type: application/json` and `Authorization: Bearer <localStorage.token>` when a
    token exists. An empty response body (e.g. a 204) resolves to `{}`.
  - `api.postForm<T>(path, FormData)` (multipart, no `Content-Type`) and `api.download(path)`
    (Blob + `Content-Disposition` filename).
  - On non-2xx, every helper throws `Error(errorMessage(res))`. That message is the body's
    `message` (`BuzzerError`), else a string `detail`, else "Invalid input" for a validation
    array, else `HTTP <status>`.
- `utils.ts` — `cn(...)` (clsx + tailwind-merge), used by `components/ui/*`.
- `mapPin.ts` (T7) — map-pin geometry and drawing, **byte-identical to the player's and
  admin's copies**; see `frontend/player/src/lib/CLAUDE.md` for the full description.
  Untested (no test runner).
- `images.ts` (T7) — `loadImage` / `preloadImages`: images fetched with the Bearer token as
  blob URLs (an `<img src>` would 401), the promise cached per ID, failures evicted, and one
  shared `POST /api/auth/refresh` + retry on a 401. Byte-identical to the other apps' copies.

## How it fits in
Consumers, and the backend guard on each call (see `backend/app/routers/CLAUDE.md` for the
full access map and `backend/app/common/CLAUDE.md` for the role dependencies):

| caller | call | backend guard |
|---|---|---|
| `pages/LoginPage.tsx` | `POST /auth/login` | public (rate-limited) |
| `pages/HomePage.tsx` | `GET /game/my-courses` | `require_user`. ADMIN sees all courses, USER only those where they hold course `HOST`. |
| `pages/HomePage.tsx` | `GET /game/my-games` | `require_user`. ADMIN sees all games; USER sees the games of their HOST courses, minus restricted games without a grant. |
| `pages/HomePage.tsx` | `GET /game/my-active-sessions` | `require_user`, filtered to `host_user_id == me`. |
| `pages/HomePage.tsx` | `POST /game/rooms` | `require_user`, plus HOST on the game's course (+ grant if restricted); course must match the game's (ADMIN bypasses the access part, not the match). |
| `pages/HomePage.tsx` | `DELETE /game/sessions/{id}` | `require_user`, plus ADMIN or session owner. |
| `pages/game/GameLayout.tsx` | `GET /game/rooms/{code}` | `get_current_user` only (GUEST allowed, no course check). |
| `App.tsx` (`HostLayout`) | `GET /game/my-courses` | as above |
| `pages/manage/GamesPage.tsx` | `GET/POST /host/courses/{cid}/games`, `PUT/DELETE /host/games/{gid}` | `require_course_host` / `require_game_host` |
| `pages/manage/QuestionEditorPage.tsx` | `GET /host/games/{gid}`, `GET/POST .../questions`, `PUT/DELETE .../questions/{qid}`, `POST .../questions/reorder` | `require_game_host` / `require_question_host`; writes 409 `GAME_LIVE` during a game |
| `pages/manage/QuestionEditorPage.tsx` | `postForm /host/courses/{cid}/images` (map-pin image upload, T7) | `require_course_host` |
| `lib/images.ts` (via `components/MapCanvas`) | `GET /images/{id}`, and `POST /auth/refresh` once on a 401 | `get_current_user` |
| `pages/manage/RosterPage.tsx` | `GET /host/courses/{cid}/roster`, `postForm` same path (`file`, `mode`) | `require_course_host` |
| `pages/manage/SessionsPage.tsx` | `GET /host/courses/{cid}/sessions?status=COMPLETED`, `download /host/sessions/{sid}/export\|report` | `require_course_host` / `require_session_host` |

`pages/LoginPage.tsx` also bypasses `api` and calls `fetch('/api/auth/exchange-temp')`
directly for the OAuth2 temp-token flow. The host app never calls anything under
`/api/admin/*`; those endpoints are admin-only and belong to the admin app. The older
host-accessible session tools `GET /game/sessions/{id}/guests`, `POST .../merge-guest` and
`GET .../export` exist on the backend but are **not called anywhere in the host app**.

The auth token lives in `localStorage['token']`. It is written by `LoginPage` (password login
and temp-token exchange), read here and by the socket `auth` callback in `GameLayout`, and
cleared by `HomePage` on logout. `App.tsx`'s `RequireAuth` only checks that the key is
**present**, not the user's role or the token's expiry.

## Gotchas
- **No client-side role check.** The host UI never looks at the user's role. A GUEST token
  gets past `RequireAuth`, and the backend then 403s the `require_user` calls on `HomePage`.
  A USER with no course `HOST` access simply sees empty course/game lists. Authorization is
  entirely server-side.
- **The token is shared with the player and admin apps.** Behind nginx (`nginx/nginx.dev.conf`)
  all three apps are served from one origin under `/host/`, `/player/` and `/admin/`, and all
  use the same `localStorage['token']` key. Joining as a guest in the player app on the same
  browser overwrites the host's token, and logging out of any app logs out all of them.
- **Validation errors are generic.** A 422 `VALIDATION_ERROR` shows only "Invalid input". The
  field-level `detail` array isn't rendered.
- **Token refresh only for images.** Only `images.ts` calls `/api/auth/refresh` (once, on a 401
  for an image); `api.ts` has no 401 retry. After the
  2 h access token expires, API calls fail even though a 7-day refresh cookie exists, and
  `RequireAuth` still lets the user in because the stale token is present.
- The JSON helpers set `Content-Type: application/json` on every request, including GETs and
  DELETEs.
- This file is identical to the admin app's `lib/api.ts`, but it is a copy, not shared. The
  player's `lib/api.ts` is older and still reads only `detail`. A fix has to be made in each
  app.
