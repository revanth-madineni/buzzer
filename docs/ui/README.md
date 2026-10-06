# T9 UI evidence: before and after screenshots

Screenshots and verification results for T9 (UI look-and-feel and theming). The design is in
[`docs/plans/t9-theming.md`](../plans/t9-theming.md); §4.16 defines this folder and §4.19 the
checklist below.

## How the screenshots were taken

**Before** (`before/`): dark only, the only theme before T9. Taken from a build of `main` before
any T9 code change.

**After** (`after/dark/`, `after/light/`): 19 screens in each theme, 38 images, taken on
2026-10-05.

- **Build:** the production build (`npm run build`) served by nginx (`docker compose up`).
- **Browser:** headless Chromium, driven by Playwright.
- **Viewports:**
  - host 1920×1080 at 1× (projector);
  - admin 1440×900 at 1×;
  - player 390×844 at 2×, so the phone shots stay legible.
- **Theme:** each screen was taken twice, switching the emulated OS colour scheme. Nothing was
  stored, so the app followed the OS, which is the first-visit behaviour.
- **Data:** one real game of
  [`sample_games/madineni_us_geography_classroom.json`](../../sample_games/madineni_us_geography_classroom.json)
  in course "CS 639 Fall 2026". It had a host, 20 simulated players
  (`scripts/simulate_players.py`) and one browser player.

**How to compare a pair.** The before images were captured from a laptop browser window, about
1400×680 CSS px at 2×, not at the viewports above. The player before images are desktop-width.
Each pair therefore compares colour and design, not layout at the target size.

## Screens

"—" means there is no before image:

- `host-results-wordcloud` and `player-question-multi` were added to the screen list after the
  before set was taken.
- The before set had no capture of the player game-over screen. A file under that name showed
  the host game-over screen and was removed.

| Screen | Before | After, dark | After, light | What changed |
|---|---|---|---|---|
| host-login | [before](before/host-login.png) | [dark](after/dark/host-login.png) | [light](after/light/host-login.png) | Card, inputs and buttons use theme tokens; light theme; theme toggle in the top-right corner. |
| host-home | [before](before/host-home.png) | [dark](after/dark/host-home.png) | [light](after/light/host-home.png) | Opaque card; selects are recessed with a visible border; disabled "Create Room" only dims. |
| host-manage-question-editor | [before](before/host-manage-question-editor.png) | [dark](after/dark/host-manage-question-editor.png) | [light](after/light/host-manage-question-editor.png) | Themed sidebar (filled active link, labelled toggle above Sign out) and form controls; the map overlays are unchanged. |
| host-lobby | [before](before/host-lobby.png) | [dark](after/dark/host-lobby.png) | [light](after/light/host-lobby.png) | QR codes on a white tile in both themes; join instructions in larger primary text; corner room code 2xl (was lg). |
| host-question | [before](before/host-question.png) | [dark](after/dark/host-question.png) | [light](after/light/host-question.png) | Timer bands from timer tokens (at least 3:1 against the track); projector text at 7:1 in both themes. |
| host-results-bars | [before](before/host-results-bars.png) | [dark](after/dark/host-results-bars.png) | [light](after/light/host-results-bars.png) | No text inside bars: the count and "✓ Correct" sit beside them. Option labels are no longer clipped ("Sprin…"). |
| host-results-wordcloud | — | [dark](after/dark/host-results-wordcloud.png) | [light](after/light/host-results-wordcloud.png) | Accepted words carry "✓" and bold weight, not just green; captions are larger. |
| host-results-heatmap | [before](before/host-results-heatmap.png) | [dark](after/dark/host-results-heatmap.png) | [light](after/light/host-results-heatmap.png) | Map overlays identical in both themes; "N / M answered" larger and in primary text. |
| host-gameover | [before](before/host-gameover.png) | [dark](after/dark/host-gameover.png) | [light](after/light/host-gameover.png) | Neutral histogram bars; larger counts and labels; breakdown options and counts at text-lg; the wrong True/False bar is neutral instead of red. |
| player-join | [before](before/player-join.png) | [dark](after/dark/player-join.png) | [light](after/light/player-join.png) | Name page: Guest/Sign In switch and inputs on tokens; toggle in the top-right corner, with content kept clear of it. |
| player-question-mc | [before](before/player-question-mc.png) | [dark](after/dark/player-question-mc.png) | [light](after/light/player-question-mc.png) | Yellow and orange answers take dark text; green, teal and pink are a shade darker, so every label reaches 4.5:1; no sticky hover shades. |
| player-question-multi | — | [dark](after/dark/player-question-multi.png) | [light](after/light/player-question-multi.png) | Selected option: accent fill with an on-accent border and a ✓ in place of the letter. |
| player-question-map | [before](before/player-question-map.png) | [dark](after/dark/player-question-map.png) | [light](after/light/player-question-map.png) | Map letterbox and Confirm button on tokens; pinch zoom re-enabled (viewport). |
| player-results-map | [before](before/player-results-map.png) | [dark](after/dark/player-results-map.png) | [light](after/light/player-results-map.png) | Outcome text in the status colour for each theme; pin and circles unchanged. |
| player-gameover | — | [dark](after/dark/player-gameover.png) | [light](after/light/player-gameover.png) | Opaque recap cards; ✓ / ✗ / ● / — glyphs, so correctness isn't colour-only. |
| admin-users | [before](before/admin-users.png) | [dark](after/dark/admin-users.png) | [light](after/light/admin-users.png) | Sidebar on tokens with a labelled toggle; user rows as panels; role badges follow the badge convention. |
| admin-access | [before](before/admin-access.png) | [dark](after/dark/admin-access.png) | [light](after/light/admin-access.png) | Shown with a course selected (the before has none): grant panels, role selects and borders on tokens. |
| admin-question-editor-map | [before](before/admin-question-editor-map.png) | [dark](after/dark/admin-question-editor-map.png) | [light](after/light/admin-question-editor-map.png) | Shown with the map-pin editor open (the before shows the question list): form controls and file button on tokens; overlays unchanged. |
| admin-sessions-export | [before](before/admin-sessions-export.png) | [dark](after/dark/admin-sessions-export.png) | [light](after/light/admin-sessions-export.png) | Status chips follow the badge convention ("Completed" is neutral); the selected export format shows a ✓. |

## Verification checklist (§4.19)

Results from 2026-10-05, against the nginx build. "Automated" checks were scripted in headless
Chromium, and each one asserts a measured value, not just that the page loaded.

### Theme and toggle

- [x] **First visit follows the OS.** In a fresh profile, all three apps load light with the OS
  set to light and dark with it set to dark. *(Automated.)*
- [x] **No flash.** A stored choice that differs from the OS is already applied in the first
  animation frame, before first paint: the right `data-theme` and page background. Checked on
  load and reload for all three apps, and on a host reload mid-game on the question screen.
  *(Automated.)*
- [x] **Persistence.** After toggling, the choice survives a reload, and changing the OS setting
  no longer changes it. *(Automated.)*
- [x] **Session choice without storage.** With `localStorage` writes failing, a toggle still
  holds across OS changes for the session. *(Automated.)*
- [x] **Keys are separate.** On one origin, toggling admin leaves host and player alone, and
  `localStorage` ends up with three keys: `buzzer:theme:admin`, `buzzer:theme:host` and
  `buzzer:theme:player`. *(Automated.)*
- [x] **Tabs stay in step.** Toggling one of two host tabs updates the other. *(Automated.)*
- [x] **Logging out keeps the theme.** Admin Logout, host Sign Out (home), host Sign out
  (management) and the player's "Play Again" each remove the login token and keep the theme
  key. *(Automated.)*
- [x] **Labels.** The visible label, `aria-label` and `title` all name the theme you would switch
  to, for example "Light theme" and "Switch to light theme" while in dark. *(Automated.)*
- [x] **Placement.** *(Automated.)*
  - **Player, at 360×640:** the toggle is on join, name, lobby, feedback, results and game over,
    and nothing sits under it. It is absent on the question screen.
  - **Host, at 1920×1080 and 1280×720:** there is one toggle on the lobby, question, results and
    game-over screens. It overlaps no content and not the QR panel.
  - **Everywhere else:** exactly one toggle on each of the 14 host-management and admin pages
    checked.

### Accessibility

- [x] **Keyboard focus.** Tabbing through 8 representative pages in each theme gave 253 focus
  stops per theme. Each one showed the 2px outline in that theme's focus colour, on buttons,
  links, inputs, selects, checkboxes, range sliders and the file input. *(Automated.)*
  - **Clipping:** scrolling every focusable control on all admin, host-management, login and join
    pages into view, none of their outlines is clipped by a scrolling or `overflow-hidden`
    container.
  - **Mouse:** clicking a button shows no outline.
- [x] **Native controls.** `color-scheme` on `<html>` matches the active theme in all three apps,
  which is what themes native selects, checkboxes and scrollbars. *(Automated.)* Native drop-down
  pop-ups can't be rendered headless, so their look wasn't captured.
- [ ] **Pinch zoom on a real phone, and no double-tap zoom on answer buttons.** Owner: Revanth
  (needs a phone). *Already checked automatically:* the player viewport no longer sets
  `maximum-scale` or `user-scalable=no`, and buttons compute `touch-action: manipulation`.

### Canvas and QR

- [x] **Map overlays.** In both editors (admin and host), a fresh load in each theme draws
  pixel-identical canvas output. The `--map-*` tokens are invariant, which `check_theme.py`
  enforces. Only the letterbox and the loading and error text are themed. *(Automated.)*
- [ ] **QR scanning.** Scan the lobby QR code and the corner QR code with a phone, in both
  themes. Owner: Revanth (needs a phone). *Already checked automatically:* both QR codes sit on
  a white tile (`rgb(255, 255, 255)`) in both themes.

### Checks and evidence

- [x] **Host readability.** The §4.12 proxy check passes in both themes: 1920×1080 screens
  scaled to 480px wide still show a legible prompt, option labels, counts and room code. No
  text is drawn inside a result bar.
- [ ] **Real classroom projector (open question O1).** Run a game on the actual projector in
  both themes and record the result here. Owner: Revanth (needs the room).
- [x] **Scripts.** `python scripts/check_theme.py` passes: colours 0, contrast 0, identical 0.
  Every byte-identical group (§4.0) has a single md5.
- [x] **CI and build.** `git diff main -- .gitlab-ci.yml` is empty, and `npm run build` succeeds
  for all three apps.

## Known limitations

- **Map pins are pointer-only.** The map canvas isn't keyboard-focusable (open question O3).
- **No way back to "follow the OS".** Once someone toggles, the only way to make the app follow
  the OS again is to clear site data (§2.9).
- **Browser bar colour on phones.** It shows its default colour until the app's JavaScript runs,
  a few milliseconds after load (open question O4).
- **A bug older than T9.** The question lists in both editors show a literal `·`. This is
  the escape-sequence bug already described in `frontend/admin/src/pages/CLAUDE.md`, and it is
  outside T9's scope.
