# frontend/admin/src/components/

## Purpose
Presentational building blocks for the admin (desktop) app: three shadcn-style primitives
under `ui/`, styled with Tailwind for the dark slate theme, and two feature components,
`MoveGamePanel` and (T7) `MapCanvas`. Apart from the panel's single API call and the canvas's
image load (via `lib/images.ts`), there's no data fetching, game state, or role/access logic
here. The admin app has no `TimerBar` because it never runs a game.

## Contents
- `ui/button.tsx` — `Button`: native `<button>` with `variant` (`default | outline | ghost |
  destructive`) and `size` (`sm | md | lg`). Class names are merged via `cn` from `lib/utils`.
- `ui/card.tsx` — `Card`, `CardHeader`, `CardContent`: styled `<div>` wrappers.
- `ui/input.tsx` — `Input`: styled native `<input>`, full width.
- `MoveGamePanel.tsx` (T4) — assign a courseless game to a course, or move it. It calls
  `POST /admin/games/{id}/move` with `confirm=false`, lists "These users will lose access: …"
  (or "No grants will be dropped"), then calls with `confirm=true` and runs `onDone`. Without
  `fixedCourseId` it shows a course picker (excluding the current course). `GamesPage` uses it
  that way; `AccessPage` fixes the course.
- `MapCanvas.tsx` (T7) — the shared map canvas, byte-identical to the player's and host's
  copies (see `frontend/player/src/components/CLAUDE.md`). `QuestionEditorPage` uses it with
  `heightCap={0.7}` and `onPoint` to place a map-pin target, and `draw` for the live circles.

## How it fits in
- All nine pages under `pages/` import `Button` and `Input`. All except `SessionsPage` also
  use `Card` + `CardHeader` + `CardContent`; `SessionsPage` imports `Card` alone.
- `App.tsx`'s sidebar and logout button are hand-styled and don't use these.
- `lib/utils.ts` supplies `cn`. See `lib/CLAUDE.md`.

## Gotchas
- **Anything beyond these three primitives is built inline in `pages/`.** There's no `Select`,
  `Textarea`, `Modal`, `Table`, or confirm-dialog component:
  - Raw `<select>`s: the CSV column-mapping pickers in `RosterPage`, the **global** role
    picker (`USER | ADMIN`) in `UserDetailPage`, and question type / grading type in
    `QuestionEditorPage`.
  - The **per-course** `HOST | PLAYER` choice in `UserDetailPage` is a hand-rolled two-button
    toggle (raw `<button>`s, not `Button`), next to a checkbox list of courses. Game grants are a
    plain checkbox list with no role.
  - `<textarea>` in `GamesPage` and `QuestionEditorPage`.
  - Destructive actions use the browser's `window.confirm()` (`GamesPage`, `GuestsPage`,
    `UserDetailPage`, `QuestionEditorPage`). Styles for those controls are repeated per page.
- `Button` doesn't default `type`, so inside a `<form>` it acts as `type="submit"`. Pass
  `type="button"` for non-submit buttons (e.g. "Cancel" or "Add option" inside an edit form).
- **These are copies, not shared code.** The three files are byte-identical to
  `frontend/host/src/components/ui/` and differ from the player's (which is tuned for touch
  sizes). A style fix has to be made in each app.
