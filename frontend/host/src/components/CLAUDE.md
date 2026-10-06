# frontend/host/src/components/

## Purpose
Presentational building blocks for the host (big-screen) app: three shadcn-style primitives
and the per-question countdown bar (under `ui/`), the theme toggle (T9), the map canvas
and results heatmap (T7), plus the uploaded-image view and picker (T8). Everything is styled with the theme tokens, so it works in both the
light and dark themes (`../CLAUDE.md`, `frontend/CLAUDE.md` "Theme system"). No socket access,
game state, or role/course logic here; the map canvas and `AuthImage` load images through
`lib/images.ts`, and `ImagePicker` gets its list/upload calls from the caller.

## Contents
- `ui/button.tsx` — `Button`: native `<button>` with `variant` (`default` accent fill,
  `outline` line-strong border, `ghost`, `destructive` danger fill) and `size` (`sm | md | lg`).
  Class names are merged via `cn` from `lib/utils`. Hover classes are `enabled:hover:…`, so a
  disabled button (opacity-50, not-allowed cursor) doesn't react to hover.
- `ui/card.tsx` — `Card`, `CardHeader`, `CardContent`: `<div>` wrappers; the card is an opaque
  `surface` with a `line` border.
- `ui/input.tsx` — `Input`: native `<input>`, full width, `surface-alt` with a `line-strong`
  border (a recessed control, meant to sit inside a `surface`).
- `ui/TimerBar.tsx` — `TimerBar({ totalSeconds, initialSeconds?, paused })`: client-side
  countdown bar (`timer-ok` > 60 % → `timer-warn` > 30 % → `timer-low`, on a `chart-track`
  track) with a whole-second `fg-muted` label, which the stage raises to 7:1. Starts from
  `initialSeconds ?? totalSeconds` and ticks every 100 ms against `Date.now()`. While `paused`,
  it freezes the remaining time and resumes from it. The bar width is always
  `timeLeft / totalSeconds`, so a mid-question start shows a partly drained bar.

- `MapCanvas.tsx` (T7) — the shared map canvas, byte-identical to the player's and admin's
  copies (see `frontend/player/src/components/CLAUDE.md`): contain-fit, DPR-scaled,
  resize-aware, "Loading map…" / Retry, optional pointer input that ignores letterbox starts
  and clamps drags. Only its chrome is themed (`surface-alt` letterbox, `fg-muted` loading,
  `danger-fg` error, a `line-strong` Retry); the image and overlays look the same in both themes.
- `MapPinHeatmap.tsx` (T7) — results view for a map_pin question: the image, one translucent
  dot per distribution key `"bx,by"` at the cell centre `((bx + 0.5) / 50, (by + 0.5) / 50)`
  with radius ∝ √count (so area grows with count), then the target and both radius circles on
  top. Same view for both grading types. Dots are `mapColor('heat', 0.55)` (`lib/mapPin.ts`).
- `AuthImage.tsx` (T8) — **byte-identical in all three apps**. Renders an uploaded image by
  ID through `lib/images.ts` (Bearer header, blob URL, shared cache, so a preloaded image
  renders at once), always `object-contain` (never crops). While loading: an empty
  `surface-alt` box (screen-reader "Loading image…"); on failure: "Image unavailable". Size
  comes from `className`.
- `ImagePicker.tsx` (T8) — **byte-identical to the admin app's** (checked by
  `scripts/check_theme.py`). A `surface-alt` panel with a 3-column grid of the course's images
  (thumbnail + alt text or "No description"; click to pick) and an upload form (PNG/JPEG/WebP
  up to 2 MB + alt text, "Upload and use"). The caller passes `listImages` / `uploadImage`,
  because the endpoints differ per app. It also exports the image types (`ImageInfo`,
  `ImageUsage`, `ImageListItem`), the alt-text constants (`ALT_TEXT_HINT`, `ALT_TEXT_MISSING`,
  `ALT_TEXT_MAX` = 250), `IMAGE_ACCEPT`, `FILE_INPUT_CLASS` and `AltTextHint` (hint plus a
  non-blocking empty-alt warning).
- `ThemeToggle.tsx` (T9) — **byte-identical in all three apps**. A 44×44 `<button>` using
  `useTheme()` (`lib/theme.ts`); its icon, `title`, `aria-label` and optional visible label
  (`showLabel`) all name the theme it switches **to** ("Switch to light theme"). `className`
  is for placement only.

## How it fits in
- `pages/LoginPage.tsx` uses `Button`, `Input`, and `Card*`. `pages/HomePage.tsx` uses
  `Button` and `Card*`. `LobbyPage`, `QuestionPage`, `ResultsPage`, and `GameOverPage` under
  `pages/game/` use `Button`.
- `pages/game/QuestionPage.tsx` renders `TimerBar` once, as `key={questionId}` /
  `totalSeconds={timeLimitSeconds}` / `initialSeconds={remainingSeconds}` /
  `paused={questionLocked}`. The `key` is what remounts it for each new question.
  `remainingSeconds` is the server's `lockedTimerSeconds` if the question is locked, otherwise
  computed from `startedAt` (only sent in the `sync_state` reconnect payload), otherwise the
  full limit.
- `lib/utils.ts` supplies `cn`. See `lib/CLAUDE.md`.
- `ThemeToggle` is rendered by each page or layout itself, with no route matching: the
  `HostLayout` sidebar in `../App.tsx` (labelled, above Sign out), `LoginPage`, `HomePage` and
  both returns of `game/GameLayout` (fixed top-right).
- `pages/game/ResultsPage.tsx` uses `MapPinHeatmap`; `pages/manage/QuestionEditorPage.tsx`
  uses `MapCanvas` directly (`heightCap={0.7}`) to place the target.
- `AuthImage` (T8) is used by `game/QuestionPage` (prompt image, `max-h-[45vh]`),
  `game/ResultsPage` and `game/GameOverPage` (thumbnails), and by `ImagePicker`,
  `manage/ImagesPage` and `manage/QuestionEditorPage`. The last two also import
  `ImagePicker`'s types and alt-text helpers; the editor opens the picker itself.
- The heatmap's 50-cell grid must match `game_service.map_pin_bucket` on the server.

## Gotchas
- **`TimerBar` is display-only and not synced to the server.** The server's timer task decides
  when answers stop: it sends `answer_phase_ended` and auto-locks 0.5 s later (see
  `backend/app/websocket/CLAUDE.md`). The bar reaching 0 changes nothing by itself.
- **Resume ignores the server's remaining time.** The host's `question_unlocked` handler in
  `GameLayout` doesn't read a remaining-time value, and `TimerBar` resumes from its own frozen
  client value. The server pauses and resumes its timer on `host_lock_question`, so the two can
  drift after a lock/unlock.
- **Reconnect math uses the client clock.** `remainingSeconds` subtracts the server's
  `startedAt` timestamp from the host machine's `Date.now()`, so clock skew between the host
  laptop and the server shifts the bar after a reconnect.
- `TimerBar` reads `totalSeconds` and `initialSeconds` only at mount (the effect has `[]`
  deps). Changing either prop without changing `key` does nothing.
- `totalSeconds <= 0` skips the interval, and `timeLeft / totalSeconds` yields `NaN` for the
  bar width.
- `Button` doesn't default `type`, so inside a `<form>` it acts as `type="submit"`. Pass
  `type="button"` for non-submit buttons.
- **A `className` hover override on a `Button` must use `enabled:hover:`.** The variant's
  `enabled:hover:` rule has higher specificity than a plain `hover:`, which would lose.
- **Colours come only from the theme tokens.** The Tailwind palette is replaced, so a raw class
  such as `bg-slate-800` compiles to nothing, with no error; run `scripts/check_theme.py`.
- **No per-component focus styles.** Focus comes from the global `:focus-visible` outline in
  `../index.css`; don't add `focus:ring-*` or `outline-none` (the check script rejects the
  latter). A control inside an `overflow-hidden/-auto` container can get `focus-inset`, but
  never a filled button.
- **These are copies, not shared code.** They differ from `frontend/player/src/components/ui/`:
  host sizing is tuned for a projector (tighter button/input padding, bigger timer bar and
  label), and only the host `TimerBar` has `initialSeconds`. `ui/{button,card,input}.tsx` and
  (T8) `ImagePicker.tsx` are byte-identical to the admin app's, and `AuthImage.tsx`,
  `MapCanvas.tsx` and `ThemeToggle.tsx` to both other apps' (all checked by
  `scripts/check_theme.py`), so edit one and copy it. A fix to the player copy doesn't propagate.
