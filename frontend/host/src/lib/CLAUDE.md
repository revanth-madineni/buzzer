# frontend/host/src/lib/

## Purpose
Small shared helpers for the host (big-screen) app: a minimal JSON fetch wrapper for the REST
API and a Tailwind class-merge helper. There is no socket code and no role or course-access
logic here. The Socket.IO client is created in `pages/game/GameLayout.tsx`.

## Contents
- `api.ts` — `api.get<T>(path)`, `api.post<T>(path, body?)` and `api.delete<T>(path)` over
  `fetch('/api' + path)`. Adds `Content-Type: application/json` and
  `Authorization: Bearer <localStorage.token>` when a token exists. On non-2xx it throws
  `Error(body.detail ?? "HTTP <status>")`. An empty response body (e.g. a 204) resolves to `{}`.
- `utils.ts` — `cn(...)` (clsx + tailwind-merge), used by `components/ui/*`.

## How it fits in
Consumers, and the backend guard on each call (see `backend/app/routers/CLAUDE.md` for the
full access map and `backend/app/common/CLAUDE.md` for the role dependencies):

| caller | call | backend guard |
|---|---|---|
| `pages/LoginPage.tsx` | `POST /auth/login` | public (rate-limited) |
| `pages/HomePage.tsx` | `GET /game/my-courses` | `require_user`. ADMIN sees all courses, USER only those where they hold course `HOST`. |
| `pages/HomePage.tsx` | `GET /game/my-games` | `require_user`. ADMIN sees all games, USER only games with a `UserGameAccess` grant. |
| `pages/HomePage.tsx` | `GET /game/my-active-sessions` | `require_user`, filtered to `host_user_id == me`. |
| `pages/HomePage.tsx` | `POST /game/rooms` | `require_user`, plus course `HOST` **and** game grant (ADMIN bypasses both). |
| `pages/HomePage.tsx` | `DELETE /game/sessions/{id}` | `require_user`, plus ADMIN or session owner. |
| `pages/game/GameLayout.tsx` | `GET /game/rooms/{code}` | `get_current_user` only (GUEST allowed, no course check). |

`pages/LoginPage.tsx` also bypasses `api` and calls `fetch('/api/auth/exchange-temp')`
directly for the OAuth2 temp-token flow. The host app never calls anything under
`/api/admin/*`; those endpoints are admin-only and belong to the admin app. The host-accessible
session tools `GET /game/sessions/{id}/guests`, `POST .../merge-guest` and `GET .../export`
exist on the backend but are **not called anywhere in the host app**.

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
- **Backend error messages are dropped.** `api.ts` reads `detail`, but `BuzzerError` responses
  are `{"error": ..., "message": ...}` (see `backend/app/common/CLAUDE.md`). So a
  `ForbiddenError` from `POST /game/rooms` (missing course HOST role or game grant) surfaces
  as just `HTTP 403`. 422
  validation errors have `detail` as an **array**, which becomes the message
  `"[object Object]"`. Only `HTTPException` string details come through intact. `require_user` /
  `require_admin` raise `ForbiddenError`, so their messages are dropped too.
- **No token refresh.** Nothing calls `/api/auth/refresh`, and there is no 401 retry. After the
  2 h access token expires, API calls fail even though a 7-day refresh cookie exists, and
  `RequireAuth` still lets the user in because the stale token is present.
- The wrapper sets `Content-Type: application/json` on every request, including GETs and
  DELETEs. It has no `put`/`patch` helpers; the host app doesn't need them.
- This file is a near-copy of `frontend/player/src/lib/api.ts` (which lacks `delete`) and is
  separate from the admin app's `lib/api.ts`. A fix to error handling has to be made in each
  app.
