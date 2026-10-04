# frontend/player/src/components/

## Purpose
Presentational building blocks for the player (mobile) app: three shadcn-style primitives
styled with Tailwind for the dark slate theme and the per-question countdown bar (under
`ui/`), plus the map-pin canvas (T7). No socket access or game state here; the map canvas
loads its image through `lib/images.ts`.

## Contents
- `ui/button.tsx` — `Button`: native `<button>` with `variant` (`default | outline | ghost |
  destructive`) and `size` (`sm | md | lg`). Class names are merged via `cn` from `lib/utils`.
- `ui/card.tsx` — `Card`, `CardHeader`, `CardContent`: styled `<div>` wrappers.
- `ui/input.tsx` — `Input`: styled native `<input>`, full width.
- `ui/TimerBar.tsx` — `TimerBar({ totalSeconds, paused })`: client-side countdown bar
  (green > 60 % → yellow > 30 % → red) with a whole-second label. Ticks every 100 ms from
  `Date.now()` at mount. While `paused`, it freezes the remaining time and resumes from it.

- `MapCanvas.tsx` (T7) — the shared map canvas, **byte-identical in all three apps**. Draws
  the image contain-fit at 100% container width and `canvasCssHeight` (cap `heightCap`, 0.6 by
  default), with the backing store × `devicePixelRatio`; recomputes on resize and
  orientation change. Shows "Loading map…", or "Couldn't load the map" + Retry. Overlays come
  from a `draw(ctx, fit)` prop (re-run when its identity changes, so pass a `useCallback`).
  With `onPoint`, it's interactive: a gesture that **starts** in the letterbox is ignored, a
  drag is clamped to the image, and `touch-action: none` is set on the canvas only.
- `MapPinCanvas.tsx` (T7) — the player's map on top of `MapCanvas`. Interactive (`pin`,
  `onPinChange`, `disabled`): tap places the pin, tap/drag moves it, the marker tip sits on
  the point. Reveal (`reveal`, `myPin`): target dot, solid `fullRadius` and dashed
  `zeroRadius` circles (r × drawW pixels), and the player's own pin.

## How it fits in
- `JoinPage` and `NamePage` use `Button`, `Input`, and `Card*`. `GameOverPage` uses `Button`.
- `pages/game/QuestionPage.tsx` renders `TimerBar` once per question-type branch, as
  `key={questionId}` / `totalSeconds={timeLimitSeconds}` / `paused={questionLocked}`. The `key`
  is what remounts it for each new question.
- `lib/utils.ts` supplies `cn`. See `lib/CLAUDE.md`.
- `QuestionPage`'s map_pin branch and `ResultsPage` use `MapPinCanvas`.

## Gotchas
- **`TimerBar` is display-only and not synced to the server.** The server decides when
  answers stop: it auto-locks 0.5 s after its own timer (see
  `backend/app/websocket/CLAUDE.md`). The bar just counts down from `totalSeconds` at mount.
  It reaching 0 doesn't disable input; the `questionLocked` / `question_locked` event does.
- **Resume ignores the server's remaining time.** `question_unlocked` carries
  `remainingSeconds`, but `TimerBar` resumes from its own frozen client value. After a host
  lock/unlock, or a host disconnect/reconnect, the bar can drift from the server's timer.
- `TimerBar` reads `totalSeconds` only at mount (the effect has `[]` deps). Changing the prop
  without changing `key` does nothing. Late joiners get a server-adjusted `timeLimitSeconds`
  (≥ 5 s), so their bar starts from that remaining value, but the 100 % width then represents
  the *remaining* time, not the full limit.
- `totalSeconds <= 0` skips the interval, and `timeLeft / totalSeconds` yields `NaN` for the
  bar width.
- `Button` doesn't default `type`, so inside a `<form>` it acts as `type="submit"`. Pass
  `type="button"` for non-submit buttons.
- **The map canvas is untested in a browser by automation.** No test runner; verify pointer,
  drag, DPR and Retry behaviour by hand on a phone after changing it.
- The primitives are copies local to the player app. The host and admin apps have their own
  `components/`, so a style change here doesn't propagate.
