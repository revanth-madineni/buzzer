# frontend/player/src/components/

## Purpose
Presentational building blocks for the player (mobile) app. Everything lives under `ui/`:
three shadcn-style primitives styled with Tailwind for the dark slate theme, plus the
per-question countdown bar. No data fetching, socket access, or game state here.

## Contents
- `ui/button.tsx` — `Button`: native `<button>` with `variant` (`default | outline | ghost |
  destructive`) and `size` (`sm | md | lg`). Class names are merged via `cn` from `lib/utils`.
- `ui/card.tsx` — `Card`, `CardHeader`, `CardContent`: styled `<div>` wrappers.
- `ui/input.tsx` — `Input`: styled native `<input>`, full width.
- `ui/TimerBar.tsx` — `TimerBar({ totalSeconds, paused })`: client-side countdown bar
  (green > 60 % → yellow > 30 % → red) with a whole-second label. Ticks every 100 ms from
  `Date.now()` at mount. While `paused`, it freezes the remaining time and resumes from it.

## How it fits in
- `JoinPage` and `NamePage` use `Button`, `Input`, and `Card*`. `GameOverPage` uses `Button`.
- `pages/game/QuestionPage.tsx` renders `TimerBar` once per question-type branch, as
  `key={questionId}` / `totalSeconds={timeLimitSeconds}` / `paused={questionLocked}`. The `key`
  is what remounts it for each new question.
- `lib/utils.ts` supplies `cn`. See `lib/CLAUDE.md`.

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
- The primitives are copies local to the player app. The host and admin apps have their own
  `components/`, so a style change here doesn't propagate.
