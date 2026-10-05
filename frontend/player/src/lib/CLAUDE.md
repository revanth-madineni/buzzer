# frontend/player/src/lib/

## Purpose
Small shared helpers for the player (mobile) app: a minimal JSON fetch wrapper for the REST
API, a Tailwind class-merge helper, a client-side JWT expiry check, and (T7) map-pin geometry
and authenticated image loading. No socket code lives here. The Socket.IO client is created
in `pages/game/GameLayout.tsx`.

## Contents
- `api.ts` — `api.get<T>(path)` / `api.post<T>(path, body?)` over `fetch('/api' + path)`.
  Adds `Content-Type: application/json` and `Authorization: Bearer <localStorage.token>` when
  a token exists. On non-2xx it throws `Error(body.detail ?? "HTTP <status>")`. An empty
  response body resolves to `{}`.
- `mapPin.ts` (T7) — map-pin geometry and drawing, **byte-identical in all three apps**
  (change them together): `containFit` (image rect inside the canvas, aspect kept),
  `canvasCssHeight` (full width, capped at `cap` × viewport height), `pointerToFraction`
  (unclamped; outside [0, 1] = letterbox), `isOnImage`, `clampPoint`, `fractionToCanvas`,
  `mapPinDistance` / `mapPinFraction` (the server's formulas: aspect-corrected width units,
  linear falloff), and `drawTarget` / `drawPin` (marker tip at the point).
- `images.ts` (T7) — `loadImage(id)`: `fetch('/api/images/{id}')` with the Bearer token, then
  a blob URL in an `HTMLImageElement`. `<img src>` can't work: it would send no Bearer header,
  and the refresh cookie is scoped to `/api/auth`. On a 401 it calls `POST /api/auth/refresh`
  **once** (one refresh shared by concurrent loads), stores the new `localStorage.token`, and
  retries once. The **promise** is cached per ID (preload and render share one request), a
  failure is evicted so the next call retries, and blob URLs are never revoked.
  `preloadImages(ids)` is fire-and-forget. Self-contained on purpose, not via `api.ts`.
- `utils.ts` — `cn(...)` (clsx + tailwind-merge, used by `components/ui/*`) and
  `isTokenExpired(token)`. The latter base64url-decodes the JWT payload **without verifying
  the signature** and compares `exp` to now. Missing or malformed tokens count as expired.

## How it fits in
Consumers:
- `pages/JoinPage.tsx` calls `api.get('/game/rooms/{code}/ping')`.
- `pages/NamePage.tsx` calls `api.post('/auth/guest')` and `api.post('/auth/login')`, and uses
  `isTokenExpired`.
- `pages/game/GameLayout.tsx` uses `isTokenExpired` before opening the socket.
- `components/ui/{button,card,input}.tsx` use `cn`.

`pages/LoginPage.tsx` bypasses `api` and calls `fetch('/api/auth/exchange-temp')` directly.

The auth token lives in `localStorage['token']`. It is written by `NamePage` (guest/local
login) and `LoginPage` (OAuth2 temp-token exchange), read here and by the socket `auth`
callback, and cleared by `GameLayout` (when expired) and `GameOverPage`. See
`routers/CLAUDE.md` for the backend auth flows these call.

## Gotchas
- **Backend error messages are dropped.** `api.ts` reads `detail`, but the backend's
  `BuzzerError` handler returns `{"error": ..., "message": ...}` (see
  `backend/app/common/CLAUDE.md`). So a 404 "Room not found" or 409 "game has already ended"
  surfaces as just `HTTP 404` / `HTTP 409`. Validation errors (422) have `detail` as an
  **array**, which becomes the message `"[object Object]"`. Only `HTTPException` string
  details come through intact.
- **Token refresh only for images.** `images.ts` refreshes once on a 401 (and, as a side
  effect, updates `localStorage.token` for the socket's next reconnect). `api.ts` still has no
  401 retry. The access token lasts 2 h, even though a 7-day refresh cookie exists.
  `GameLayout` only checks expiry on mount, where it redirects to `/name/{code}`. If the token
  expires mid-game, the connected socket keeps working, but any socket **reconnect** re-sends
  the expired token and is rejected by the server.
- The token is stored in `localStorage`, so it is readable by any script on the origin.
- `isTokenExpired` is advisory only (unverified, client-clock based). The server remains the
  authority.
- **`mapPin.ts` is untested.** No app has a test runner. Its math was checked once by hand
  (compiled with `tsc`, run in Node against the backend unit-test numbers) but nothing
  re-checks it; keep it in step with `backend/app/services/game_service.py`.
- The wrapper sets `Content-Type: application/json` on every request, including GETs, and has no
  `put`/`delete`/`patch` helpers. The player app doesn't currently need them.
