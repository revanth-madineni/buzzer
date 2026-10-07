# frontend/player/src/components/

## Purpose
Presentational building blocks for the player (mobile) app: three shadcn-style primitives
and the per-question countdown bar (under `ui/`), the theme toggle (T9), the map-pin
canvas (T7), plus the uploaded-image view `AuthImage` (T8). Everything is styled with the theme
tokens, so it works in both themes (`frontend/CLAUDE.md` "Theme system"). No socket access or
game state here; the map canvas and `AuthImage` load images through `lib/images.ts`.

## Contents
- `ui/button.tsx` — `Button`: native `<button>` with `variant` (`default` accent fill,
  `outline` line-strong border, `ghost`, `destructive` danger fill) and `size` (`sm | md |
  lg`). Class names are merged via `cn` from `lib/utils`. Hover classes are `enabled:hover:…`,
  so a disabled button (opacity-50, not-allowed cursor) doesn't react to hover.
- `ui/card.tsx` — `Card`, `CardHeader`, `CardContent`: `<div>` wrappers; the card is an opaque
  `surface` with a `line` border.
- `ui/input.tsx` — `Input`: native `<input>`, full width, `surface-alt` with a `line-strong`
  border (a recessed control, meant to sit inside a `surface`).
- `ui/TimerBar.tsx` — `TimerBar({ totalSeconds, paused })`: client-side countdown bar
  (`timer-ok` > 60 % → `timer-warn` > 30 % → `timer-low`, on a `chart-track` track) with a
  whole-second `fg-muted` label. Ticks every 100 ms from
  `Date.now()` at mount. While `paused`, it freezes the remaining time and resumes from it.

- `MapCanvas.tsx` (T7) — the shared map canvas, **byte-identical in all three apps**. Draws
  the image contain-fit at 100% container width and `canvasCssHeight` (cap `heightCap`, 0.6 by
  default), with the backing store × `devicePixelRatio`; recomputes on resize and
  orientation change. Shows "Loading map…", or "Couldn't load the map" + Retry. Overlays come
  from a `draw(ctx, fit)` prop (re-run when its identity changes, so pass a `useCallback`).
  With `onPoint`, it's interactive: a gesture that **starts** in the letterbox is ignored, a
  drag is clamped to the image, and `touch-action: none` is set on the canvas only. Only its
  chrome is themed (`surface-alt` letterbox, `fg-muted` loading, `danger-fg` error, a
  `line-strong` Retry); the image and overlays look the same in both themes.
- `MapPinCanvas.tsx` (T7) — the player's map on top of `MapCanvas`. Interactive (`pin`,
  `onPinChange`, `disabled`): tap places the pin, tap/drag moves it, the marker tip sits on
  the point. Reveal (`reveal`, `myPin`): target dot, solid `fullRadius` and dashed
  `zeroRadius` circles (r × drawW pixels), and the player's own pin. While `disabled`, the pin
  is drawn in `mapColor('pin-disabled')` (`lib/mapPin.ts`).
- `SliderInput.tsx` (T7 slider) — works in step indices. Interactive (`config`, `index`,
  `onIndexChange`, `disabled`): a native `<input type="range" class="slider-range">` (44px
  thumb, styled in `../index.css` from tokens) between "One step left/right" buttons, the
  value in large type when `showValue`, end labels below, `aria-valuetext` from
  `positionText` (so a spectrum reads "35% of the way from Ice cold to Lava"). Reveal
  (`reveal`, `myIndex`): a static track with the full-credit band (`success-soft`), the
  target (`success`) and the player's marker (`accent`).
- `AuthImage.tsx` (T8) — **byte-identical in all three apps**. Renders an uploaded image by
  ID (`imageId`, `alt`, `className`) through `lib/images.ts` (Bearer header, blob URL, shared
  cache, so an image preloaded from `game_images` renders at once), always `object-contain`
  (never crops). While loading: an empty `surface-alt` box (screen-reader "Loading image…");
  on failure: "Image unavailable".
- `ThemeToggle.tsx` (T9) — **byte-identical in all three apps**. A 44×44 `<button>` using
  `useTheme()` (`lib/theme.ts`); its icon, `title`, `aria-label` and optional visible label
  all name the theme it switches **to**. `className` is for placement only.

## How it fits in
- `JoinPage` and `NamePage` use `Button`, `Input`, and `Card*`. `GameOverPage` uses `Button`.
- `pages/game/QuestionPage.tsx` renders `TimerBar` once per question-type branch, as
  `key={questionId}` / `totalSeconds={timeLimitSeconds}` / `paused={questionLocked}`. The `key`
  is what remounts it for each new question.
- `lib/utils.ts` supplies `cn`. See `lib/CLAUDE.md`.
- `QuestionPage`'s map_pin branch and `ResultsPage` use `MapPinCanvas`.
- `AuthImage` (T8) is used by `QuestionPage` (image options in the 2-column grid, with
  `alt=""` because the button carries the label), `ResultsPage` and `GameOverPage`
  (thumbnails).
- `ThemeToggle` is rendered by `JoinPage`, `NamePage` and the game's `LobbyPage`,
  `FeedbackPage`, `ResultsPage` and `GameOverPage`, never by `QuestionPage`
  (`pages/CLAUDE.md`).

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
- **A `className` hover override on a `Button` must use `enabled:hover:`.** The variant's
  `enabled:hover:` rule has higher specificity than a plain `hover:`, which would lose.
- **Colours come only from the theme tokens.** The Tailwind palette is replaced, so a raw class
  such as `bg-slate-800` compiles to nothing, with no error; run `scripts/check_theme.py`.
- **No per-component focus styles.** Focus comes from the global `:focus-visible` outline in
  `../index.css`; don't add `focus:ring-*` or `outline-none`.
- **The map canvas and `AuthImage` are untested in a browser by automation.** No test runner;
  verify pointer, drag, DPR and Retry behaviour, and image loading/placeholders, by hand on a
  phone after changing them.
- The primitives are copies local to the player app. The host and admin apps have their own
  `components/`, so a style change here doesn't propagate. `MapCanvas`, `AuthImage` and
  `ThemeToggle` are the exceptions: byte-identical across all three apps (checked by
  `scripts/check_theme.py`), so edit one and copy it.
