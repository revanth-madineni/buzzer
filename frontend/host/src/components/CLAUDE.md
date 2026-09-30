# frontend/host/src/components/

## Purpose
Presentational building blocks for the host (big-screen) app. Everything lives under `ui/`:
three shadcn-style primitives styled with Tailwind for the dark slate theme, plus the
per-question countdown bar. No data fetching, socket access, game state, or role/course logic
here.

## Contents
- `ui/button.tsx` — `Button`: native `<button>` with `variant` (`default | outline | ghost |
  destructive`) and `size` (`sm | md | lg`). Class names are merged via `cn` from `lib/utils`.
- `ui/card.tsx` — `Card`, `CardHeader`, `CardContent`: styled `<div>` wrappers.
- `ui/input.tsx` — `Input`: styled native `<input>`, full width.
- `ui/TimerBar.tsx` — `TimerBar({ totalSeconds, initialSeconds?, paused })`: client-side
  countdown bar (green > 60 % → yellow > 30 % → red) with a whole-second label. Starts from
  `initialSeconds ?? totalSeconds` and ticks every 100 ms against `Date.now()`. While `paused`,
  it freezes the remaining time and resumes from it. The bar width is always
  `timeLeft / totalSeconds`, so a mid-question start shows a partly drained bar.

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
- **These are copies, not shared code.** They differ from `frontend/player/src/components/ui/`:
  host sizing is tuned for a projector (tighter button/input padding, bigger timer bar and
  label), and only the host `TimerBar` has `initialSeconds`. The admin app has its own
  `components/` too. A fix to one copy doesn't propagate.
