# frontend/admin/src/components/

## Purpose
Presentational building blocks for the admin (desktop) app: three shadcn-style primitives
under `ui/`, styled with the theme tokens so they work in both themes, and five feature
components: `MoveGamePanel`, (T7) `MapCanvas`, (T8) `AuthImage` + `ImagePicker` and (T9)
`ThemeToggle`. Apart from the panel's single API call and image loads (via `lib/images.ts`),
there's no data fetching, game state, or role/access logic here; `ImagePicker` gets its list
and upload calls from the caller. The admin app has no `TimerBar` because it never runs a game.

## Contents
- `ui/button.tsx` — `Button`: native `<button>` with `variant` (`default` accent fill,
  `outline` line-strong border, `ghost`, `destructive` danger fill) and `size` (`sm | md |
  lg`). Class names are merged via `cn` from `lib/utils`. Hover classes are `enabled:hover:…`,
  so a disabled button (opacity-50, not-allowed cursor) doesn't react to hover.
- `ui/card.tsx` — `Card`, `CardHeader`, `CardContent`: `<div>` wrappers; the card is an opaque
  `surface` with a `line` border.
- `ui/input.tsx` — `Input`: native `<input>`, full width, `surface-alt` with a `line-strong`
  border (a recessed control, meant to sit inside a `surface`).
- `MoveGamePanel.tsx` (T4) — assign a courseless game to a course, or move it. It calls
  `POST /admin/games/{id}/move` with `confirm=false`, lists "These users will lose access: …"
  (or "No grants will be dropped") and, since T8, "N image(s) will move to this course, M
  shared image(s) will be copied" when either count (`images_moved` / `images_copied`) is
  non-zero, then calls with `confirm=true` and runs `onDone`. Without
  `fixedCourseId` it shows a course picker (excluding the current course). `GamesPage` uses it
  that way; `AccessPage` fixes the course. It is a `surface-alt` panel, so it belongs inside a
  card.
- `MapCanvas.tsx` (T7) — the shared map canvas, byte-identical to the player's and host's
  copies (see `frontend/player/src/components/CLAUDE.md`). `QuestionEditorPage` uses it with
  `heightCap={0.7}` and `onPoint` to place a map-pin target, and `draw` for the live circles.
  Only its chrome is themed; the image and overlays look the same in both themes.
- `AuthImage.tsx` (T8) — **byte-identical in all three apps**. Renders an uploaded image by
  ID through `lib/images.ts` (Bearer header, blob URL, shared cache), always `object-contain`
  (never crops). While loading it shows a `surface-alt` box (screen-reader "Loading image…"),
  on failure "Image unavailable". Size comes from `className`. Used by `ImagePicker`,
  `ImagesPage` and `QuestionEditorPage`.
- `ImagePicker.tsx` (T8) — **byte-identical to the host's copy** (`check_theme.py` checks it).
  A `surface-alt` panel: a 3-column grid of existing images (thumbnail + alt text or "No
  description"; click to pick) and an upload form (PNG/JPEG/WebP up to 2 MB, alt text, "Upload
  and use"). The endpoints differ per app, so the caller passes `listImages` / `uploadImage`.
  It also exports the shared image types (`ImageInfo`, `ImageUsage`, `ImageListItem`), the
  alt-text constants (`ALT_TEXT_HINT`, `ALT_TEXT_MISSING`, `ALT_TEXT_MAX` = 250), `IMAGE_ACCEPT`,
  `FILE_INPUT_CLASS` and `AltTextHint` (the hint plus a non-blocking empty-alt warning), which
  `ImagesPage` and `QuestionEditorPage` import.
- `ThemeToggle.tsx` (T9) — **byte-identical in all three apps**. A 44×44 `<button>` using
  `useTheme()` (`lib/theme.ts`); its icon, `title`, `aria-label` and optional visible label
  all name the theme it switches **to**. `className` is for placement only.

## How it fits in
- All ten pages under `pages/` import `Button` and `Input`. All except `SessionsPage` and
  `ImagesPage` also use `Card` + `CardHeader` + `CardContent`; those two import `Card` alone.
- `App.tsx`'s sidebar and logout button are hand-styled and don't use the `ui/` primitives.
  The sidebar renders `ThemeToggle` (labelled, directly above Logout), and `LoginPage` renders
  it fixed top-right.
- `lib/utils.ts` supplies `cn`. See `lib/CLAUDE.md`.

## Gotchas
- **Anything beyond these three primitives is built inline in `pages/`.** There's no `Select`,
  `Textarea`, `Modal`, `Table`, or confirm-dialog component:
  - Raw `<select>`s: the CSV column-mapping pickers in `RosterPage`, the **global** role
    picker (`USER | ADMIN`) in `UserDetailPage`, and question type / grading type in
    `QuestionEditorPage`.
  - The **per-course** `HOST | PLAYER` choice in `UserDetailPage` is a hand-rolled two-button
    toggle (raw `<button>`s, not `Button`), next to a checkbox list of courses. The selected
    segment is an accent fill with "✓ " before its label. Its wrapper must not be
    `overflow-hidden`, which clipped the segments' focus outlines. Game grants are a plain
    checkbox list with no role.
  - `<textarea>` in `GamesPage` and `QuestionEditorPage`.
  - Destructive actions use the browser's `window.confirm()` (`GamesPage`, `GuestsPage`,
    `UserDetailPage`, `QuestionEditorPage`, `ImagesPage`). Styles for those controls are repeated per page:
    native controls are `surface-alt` with a `line-strong` border and `fg` text inside a card,
    and `surface` when they sit directly on the page.
- **A `className` hover override on a `Button` must use `enabled:hover:`**, because the
  variant's `enabled:hover:` rule has higher specificity than a plain `hover:`.
- **Colours come only from the theme tokens** (a raw palette class compiles to nothing; run
  `scripts/check_theme.py`). Focus comes from the global `:focus-visible` outline in
  `../index.css`, so don't add `focus:ring-*` or `outline-none`.
- `Button` doesn't default `type`, so inside a `<form>` it acts as `type="submit"`. Pass
  `type="button"` for non-submit buttons (e.g. "Cancel" or "Add option" inside an edit form).
- **These are copies, not shared code.** The three `ui/` files are byte-identical to
  `frontend/host/src/components/ui/` and differ from the player's (which is tuned for touch
  sizes). A style fix has to be made in each app.
