# frontend/player/src/lib/

## Purpose
Small shared helpers for the player (mobile) app: a minimal JSON fetch wrapper for the REST
API, a Tailwind class-merge helper, a client-side JWT expiry check, and (T7) map-pin geometry
and authenticated image loading, and (T9) the light/dark theme store. No socket code lives
here. The Socket.IO client is created
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
  linear falloff), and `drawTarget` / `drawPin` (marker tip at the point). Every drawing colour
  comes from `mapColor(name, alpha = 1)` (T9), which reads the invariant `--map-<name>` token
  (`full`, `full-fill`, `zero`, `pin`, `pin-disabled`, `heat`, `outline`) once per name, caches
  it, and returns `rgb(R G B / alpha)`. The overlays sit on the map image, so these tokens don't
  change with the theme and the cache never goes stale. If a token is empty (`theme.css` not
  imported), it logs once, returns `'transparent'` and doesn't cache. `drawPin`'s colour
  defaults to `map-pin` inside the function.
- `slider.ts` (T7 slider) — **byte-identical in all three apps**; the client mirror of
  `backend/app/services/slider_math.py` (`sliderGeometry`, `snap` = floor(k + 0.5),
  `inRange`, `onGrid`, `snapIndex`, `indexValue`, `pct`, `middleIndex`, `binCount` /
  `binOf` / `binRange`, `sliderDistance` / `sliderFraction`, `formatValue` (en-US, exactly
  `decimals`), `endLabels`, `positionText`, `targetLine`, `freePoints`). Defines its own
  `SliderSettings` / `SliderRevealData` types, which `types/game.ts` extends. Type-checked
  only; checked once against the Python in Node.
- `theme.ts` (T9) — the light/dark theme store, **byte-identical in all three apps**, with no
  React context:
  - the storage key comes only from `<html data-theme-key>` (`buzzer:theme:player` here). If
    it is missing, it logs once and never persists, rather than falling back to a key shared
    with the other apps;
  - `getStored()` reads `localStorage[key]` (`light` or `dark`; anything else, or a storage
    error, falls back to a module-level `sessionChoice`), and `resolve()` uses that or the
    `prefers-color-scheme` query;
  - `apply()` sets `data-theme` on `<html>`, points `<meta name="theme-color">` at the page
    background and notifies subscribers;
  - `toggleTheme()` sets `sessionChoice` and stores it (inside `try/catch`), so a toggle
    holds for the session even when storage writes fail;
  - `useTheme()` reads it with `useSyncExternalStore`;
  - `initTheme()`, called once in `main.tsx` before `createRoot`, re-applies the theme, follows
    OS changes while nothing is stored, and listens for `storage` events on its own key so
    tabs of the same app stay in step.

  The inline script in `../index.html` applies the same rules before first paint, so change
  both together.
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
callback, and cleared by `GameLayout` (when expired) and `GameOverPage`. Both use
`removeItem('token')`, so the theme key `buzzer:theme:player` survives "Play Again". See
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
- **Never call `localStorage.clear()`** in any app: it would also wipe the theme keys, and the
  three apps share one origin behind nginx.
- **`theme.ts` is untested by automation in the repo.** Its behaviour (OS follow, persistence,
  session choice, per-app keys, tab sync) was checked with a headless browser for T9; see
  `docs/ui/README.md`.
