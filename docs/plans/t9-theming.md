# T9 — UI Look-and-Feel & Theming

Status: agreed design, not yet goldfish-tested. Written 2026-10-05.
Scope: all three frontends (`frontend/host`, `frontend/player`, `frontend/admin`), including the
T4 management pages and the T7/T8 image and map-pin surfaces. The backend HTML session report
is **out of scope**.

Architecture context lives in the CLAUDE.md hierarchy. Read `frontend/CLAUDE.md` and each
app's `src/CLAUDE.md`, `src/components/CLAUDE.md`, `src/lib/CLAUDE.md` and `src/pages/CLAUDE.md`
before implementing. Task text: `instructions.md`, T9.

---

## 1. Problem

All three apps hardcode one dark palette. Colour is written directly into JSX as raw Tailwind
classes: about 916 uses across 47 files, with about 70% of them slate. On top of that:

- each `src/index.css` hardcodes `#0f172a` and `#f8fafc` on `body`;
- the shared map-pin code draws with 17 `rgba()` literals.

There is no light theme, no toggle and no shared vocabulary for colour. Some text already fails
WCAG AA in the current dark theme:

- `text-slate-500` (used 90 times) on slate-900 is 3.75:1;
- `text-slate-600` is worse;
- white labels on the player's yellow, orange, green and teal answer buttons are 1.9, 2.8, 3.3
  and 3.7:1.

Focus styles use `focus:` instead of `focus-visible:`. Twenty `outline-none` uses remove the
browser's ring, and most hand-built controls have no focus style at all.

We need:

- a semantic token layer that every component uses;
- complete light and dark themes in every app, with a visible toggle that follows the OS until
  the user chooses;
- AA contrast and visible focus;
- a look that fits each context: thumb-friendly phones, a projector that is readable from the
  back of a classroom, and a dense admin console.

## 2. Technical plan (summary)

**Tokens and themes**

1. **Tokens are CSS variables holding RGB channels** (`--surface: 30 41 59`), defined in a new
   `src/theme.css` in each app. Each app's Tailwind config maps every token name to
   `rgb(var(--name) / <alpha-value>)`, so opacity modifiers such as `bg-warning/90` keep working.
2. **Token names are identical in all three apps.** `tailwind.config.ts` is byte-identical
   across the apps. The player and admin `theme.css` files are byte-identical. The host file is
   the same plus a "stage" block.
3. **Themes are set by `data-theme="light|dark"` on `<html>`.** The token values change and the
   class names stay the same. No `dark:` variants are used anywhere.
4. **Host game screens are a "stage".** Host `GameLayout` sets `data-stage` on its root
   element. Inside it, text tokens are overridden to reach at least 7:1, because projected text
   washes out. The host management area, login and home pages use the normal values.
5. **Some colours don't change with the theme**, because they sit on top of something the theme
   doesn't control:
   - the 8 player answer colours, each with its own text colour;
   - the map-overlay colours (pin, target, radius circles, heatmap), which are drawn on the map
     image;
   - the white QR-code tile.

**Toggle and persistence**

6. **Each app has its own storage key**: `buzzer:theme:host`, `buzzer:theme:player`,
   `buzzer:theme:admin`. Behind nginx the three apps share one origin and one `localStorage`,
   and the projector must not flip when the admin console does. The key is declared once per
   app, as `data-theme-key` on `<html>` in `index.html`.
7. **No flash of the wrong theme.** A small inline script at the top of each `index.html`
   resolves the theme before the first paint:
   - a stored choice wins;
   - otherwise `prefers-color-scheme` decides.

   `theme.css` sets `color-scheme` so native controls and scrollbars match the theme.
8. **The toggle has two states.** With nothing stored, the app follows the OS and updates live
   when the OS setting changes. Clicking the toggle stores an explicit `light` or `dark`. There
   is no way back to "follow the OS" except clearing site data; this is documented, not fixed.
9. **`lib/theme.ts` and `components/ThemeToggle.tsx` are byte-identical across the apps.** The
   toggle is a visible button in each app, placed where it can't be mis-tapped.

**Accessibility**

10. **Focus uses one global `:focus-visible` rule**: a 2px outline in `--focus` with a 2px
    offset. The offset is transparent, so no offset colour has to match whatever surface lies
    underneath. Every per-component `focus:ring-*` and `outline-none` is removed.

**Enforcement and evidence**

11. **Raw palette classes are first swept, then made impossible.** Each file is mapped by role
    (§4.11). Afterwards, the Tailwind palette is **replaced** with the tokens, and
    `scripts/check_theme.py` fails the build on any raw palette class, colour literal or
    `outline-none`.
12. **Contrast is checked by a script, not by eye.** `scripts/check_theme.py` parses each
    `theme.css` and checks a fixed list of token pairs: text at 4.5:1, the host stage at 7:1, and
    non-text elements (focus outline, control borders, chart bars) at 3:1.
13. **Non-colour cues** back up colour wherever correctness is shown. Most already exist; the
    word cloud is the gap (§4.14).
14. **Screenshots come first.** "Before" screenshots are taken from the current `main` build
    before any code changes. "After" screenshots are taken in both themes. They go in
    `docs/ui/`, with an index page.

## 3. Alternatives considered

| Alternative | Why it lost |
|---|---|
| Tailwind `dark:` variants (`darkMode: 'class'`) | Every colour class appears twice, and it isn't a semantic token layer, which T9 requires. It also can't express the host stage overrides without a third set of variants. |
| A shared npm workspace package for tokens and theme code | The apps deliberately share no code (`frontend/CLAUDE.md`). Byte-identical copies, checked by a script, are the convention T7 already uses (`mapPin.ts`, `images.ts`, `MapCanvas.tsx`). A workspace is a bigger change than T9. |
| One shared `theme` key for all three apps | Behind nginx, toggling the admin console would flip the projector, the same trap as the shared login token. |
| A three-state toggle (light / dark / system) | More UI to explain. The requirement only asks for "OS first, then persist". The limitation is documented (§2.8). |
| Applying the theme in React only | The page paints dark first. Users who prefer light would see a flash on every load, including a projector reload mid-class. |
| Hex values in the variables (`--surface: #1e293b`) | Tailwind 3's `/<alpha>` modifiers stop working, and the code uses them (`bg-yellow-600/90`, `bg-amber-500/15` and others). |
| Extending the palette instead of replacing it | Raw classes would still compile, so "eliminated" couldn't be enforced. Extending is used only as an interim step (§4.18 steps 3–5). |
| Map-overlay colours that change per theme | Canvases can't read classes. They would have to read computed styles and repaint on every theme change, and `MapCanvas` only repaints on resize or when `draw` changes. Overlay contrast is against the map image, not the page, so the theme gives no reason to change them. |
| Focus ring with a token `ring-offset` colour (the idea from the design discussion) | The offset colour has to match the surface under the element, which is the page on one screen and a card on another, so any single token is wrong somewhere. A transparent `outline-offset` has no colour to match. As one global rule, it also covers the hand-built selects, checkboxes and toggles in the admin pages without editing each one. |
| A Node or npm contrast tool | No app has a test runner or lint pipeline to hook it into. `scripts/` is already Python, and the check needs only arithmetic and regular expressions. |

## 4. Detailed implementation

### 4.0 Conventions

- **"Byte-identical"** means the file must have the same md5 in every app listed. Edit one copy,
  then copy it to the others. `scripts/check_theme.py` enforces this (§4.15).
- **Byte-identical groups after T9:**
  - `tailwind.config.ts`, `src/lib/theme.ts`, `src/components/ThemeToggle.tsx`,
    `src/lib/mapPin.ts`, `src/components/MapCanvas.tsx` and `src/lib/images.ts` in all three
    apps;
  - `src/theme.css` in player and admin;
  - `components/ui/{button,card,input}.tsx` in host and admin. These stay identical; the player
    copies stay different because they are tuned for touch.
- **"Token" means a name in §4.3.** "On page / surface / surface-alt" means text drawn directly
  on that background.
- **"Student-facing"** means text that students in the room must read on the projector: the
  prompt, options, counts, room code, results and scores. Operator controls (Lock, Show Results,
  Next) are not student-facing.
- **Colour values below are given in hex for readability.** In `theme.css` they are written as
  space-separated decimal channels, for example `#1e293b` becomes `30 41 59`.

### 4.1 Step 0 — "before" screenshots (must happen before any code change)

Follow §4.16 against a build of the current `main`, and commit the images to `docs/ui/before/`
on the T9 branch. Once the sweep starts, the "before" state is gone.

### 4.2 Stale build output that hides config edits

`tsconfig.node.json` in each app is `composite` and includes `vite.config.ts` and
`tailwind.config.ts`. So `tsc -b`, which runs in `npm run build`, emits `vite.config.js` and
`tailwind.config.js` next to the `.ts` files. Those files are gitignored.

Tailwind 3 and Vite 5 both look for the `.js` config **before** the `.ts` one. Under
`npm run dev`, which doesn't run `tsc`, edits to the `.ts` configs are ignored until someone
builds.

- **Fix:** add `"emitDeclarationOnly": true` to each app's `tsconfig.node.json`. Composite
  projects must still emit declarations, so `.d.ts` files keep being produced, but they don't
  shadow config resolution. Then delete the existing `frontend/*/vite.config.js` and
  `frontend/*/tailwind.config.js`.
- **Verify:** after `npm run build`, `ls frontend/*/tailwind.config.js frontend/*/vite.config.js`
  finds nothing. In `npm run dev`, a class that exists only in the `.ts` config produces CSS.

### 4.3 Token set

**Themed tokens.** Values are given as dark / light. The contrast requirements in §4.15 were
checked against these values when this spec was written, and all of them passed.

| token | role | dark | light |
|---|---|---|---|
| `page` | app background (`body`) | `#0f172a` | `#f1f5f9` |
| `surface` | cards, sidebar, panels, header bars | `#1e293b` | `#ffffff` |
| `surface-alt` | inputs, nested panels, table header rows, map letterbox | `#0f172a` | `#f8fafc` |
| `surface-hover` | hover and selected rows, ghost-button hover | `#283548` | `#e2e8f0` |
| `fg` | primary text | `#f8fafc` | `#0f172a` |
| `fg-muted` | secondary text, labels, placeholders | `#94a3b8` | `#475569` |
| `line` | dividers, card borders | `#334155` | `#e2e8f0` |
| `line-strong` | borders of form controls and outline buttons (≥ 3:1) | `#64748b` | `#64748b` |
| `accent` | primary button fill, selected toggle | `#4f46e5` | `#4f46e5` |
| `accent-hover` | primary button hover | `#4338ca` | `#4338ca` |
| `on-accent` | text on `accent` / `accent-hover` | `#ffffff` | `#ffffff` |
| `accent-fg` | links and accent-coloured text on page or surfaces | `#a5b4fc` | `#4338ca` |
| `accent-soft` | tinted selected background (text on it: `accent-fg`) | `#1e1b4b` | `#e0e7ff` |
| `focus` | focus outline (≥ 3:1 against page and surfaces) | `#818cf8` | `#4f46e5` |
| `success` | success fill | `#15803d` | `#15803d` |
| `on-success` | text on `success` | `#ffffff` | `#ffffff` |
| `success-fg` | success text on page or surfaces | `#4ade80` | `#166534` |
| `success-soft` | success badge or box background (text on it: `success-fg`) | `#052e16` | `#dcfce7` |
| `danger` | destructive fill | `#b91c1c` | `#b91c1c` |
| `danger-hover` | destructive hover | `#991b1b` | `#991b1b` |
| `on-danger` | text on `danger` / `danger-hover` | `#ffffff` | `#ffffff` |
| `danger-fg` | error text | `#f87171` | `#b91c1c` |
| `danger-soft` | error box background | `#450a0a` | `#fee2e2` |
| `warning` | warning fill (banners, timer middle band) | `#fbbf24` | `#fbbf24` |
| `on-warning` | text on `warning` | `#0f172a` | `#0f172a` |
| `warning-fg` | warning text | `#fcd34d` | `#92400e` |
| `warning-soft` | warning badge background | `#451a03` | `#fef3c7` |
| `chart-track` | timer track, empty bar background | `#334155` | `#e2e8f0` |
| `chart-bar` | neutral result bar | `#94a3b8` | `#64748b` |
| `chart-correct` | correct-answer result bar | `#22c55e` | `#15803d` |

**Host stage overrides.** These apply inside `[data-stage]`, host only, and target at least
7:1. Only these five tokens change:

| token | dark stage | light stage |
|---|---|---|
| `fg-muted` | `#cbd5e1` | `#334155` |
| `accent-fg` | `#c7d2fe` | `#3730a3` |
| `success-fg` | `#86efac` | `#14532d` |
| `danger-fg` | `#fca5a5` | `#7f1d1d` |
| `warning-fg` | `#fde68a` | `#78350f` |

**Invariant tokens** have the same value in both themes:

| token | role | value | text colour |
|---|---|---|---|
| `answer-1` … `answer-8` | player answer buttons (multiple choice; True/False use 4 and 1) | red `#dc2626`, blue `#2563eb`, yellow `#facc15`, green `#15803d`, purple `#9333ea`, orange `#fb923c`, pink `#be185d`, teal `#0f766e` | `on-answer-N`: white for 1, 2, 4, 5, 7, 8; `#0f172a` for 3 (yellow) and 6 (orange) |
| `map-full` | full-credit circle stroke and target dot (alpha 1) | `#16a34a` | — |
| `map-full-fill` | full-credit circle fill (drawn at alpha 0.25) | `#22c55e` | — |
| `map-zero` | zero-credit dashed circle (alpha 0.95) | `#eab308` | — |
| `map-pin` | player's pin | `#dc2626` | — |
| `map-pin-disabled` | pin while input is disabled | `#64748b` | — |
| `map-heat` | heatmap dots (alpha 0.55) | `#ef4444` | — |
| `qr-tile` | white tile behind every QR code | `#ffffff` | — |

The map values are today's literals, unchanged, so overlays look exactly as they do now.
Yellow and orange answer buttons now take dark text. Green, pink and teal move one shade darker
so that white text reaches at least 4.5:1.

**Visual direction.** Keep Buzzer's identity: slate neutrals and one indigo accent in both
themes.

- **Dark** is today's look, tidied up: cards are opaque `surface` instead of
  `bg-slate-800/60`, and there is a single accent.
- **Light** is a cool grey page with white cards and the same indigo.
- Status colours appear only for status. Flat cards with 1px `line` borders, and the existing
  `shadow-xl` kept only where it exists today.

### 4.4 `src/theme.css` (new, one per app)

The file has exactly these blocks, in this order. `check_theme.py` parses these selectors
literally, so don't restyle them.

1. **`:root`** — the invariant tokens.
2. **`:root, :root[data-theme="dark"]`** — the dark values, plus `color-scheme: dark`. Dark is
   the fallback if the inline script fails.
3. **`:root[data-theme="light"]`** — the light values, plus `color-scheme: light`.
4. **Host only:**
   - `:root [data-stage], :root[data-theme="dark"] [data-stage]` — the dark stage overrides;
   - `:root[data-theme="light"] [data-stage]` — the light stage overrides.

Each declaration is `--<token>: R G B;`. Nothing else goes in the file.

The player and admin files are byte-identical. The host file starts with the same text and adds
block 4.

Import it from `src/main.tsx`, immediately **before** `./index.css`.

### 4.5 `tailwind.config.ts` (byte-identical, all three)

- `theme.colors` maps every token to `rgb(var(--<token>) / <alpha-value>)`. Tokens with
  numbers are nested (`answer: {1: …, …, 8: …}` and `'on-answer': {…}`), which gives class
  names like `bg-answer-3` and `text-on-answer-3`. `transparent`, `current` and `inherit` keep
  their usual values.
- **Before §4.18 step 6**, the token map goes under `theme.extend.colors`, so the raw palette
  still works while the sweep is in progress. **At step 6** it moves to `theme.colors`, which
  replaces the palette.
- Set `theme.extend.borderColor.DEFAULT` to the `line` mapping. Once the palette is replaced,
  Tailwind's default border colour (`gray.200`) no longer exists, and every bare `border` and
  the preflight default would fall back to `currentColor`.
- Set `theme.extend.ringColor.DEFAULT` to the `focus` mapping. Without it, a bare `ring` falls
  back to hardcoded blue.
- Keep the existing `fontFamily`. Don't add custom `fontSize` names: `cn()` uses
  tailwind-merge, which would mistake a custom size such as `text-display` for a colour and drop
  one of the two classes. Stock sizes (`text-xl` … `text-7xl`) are enough.

### 4.6 `src/index.css`

Keep the three `@tailwind` directives and `box-sizing`. Remove the hardcoded `body` colours. In
`@layer base`:

- **`body`:** background `rgb(var(--page))`, colour `rgb(var(--fg))`.
- **`::placeholder`:** colour `rgb(var(--fg-muted))`, `opacity: 1`. Firefox otherwise dims
  placeholders below 4.5:1.
- **`:root`:** `accent-color: rgb(var(--accent))`. This replaces the six
  `accent-indigo-500` classes on native checkboxes and range sliders.
- **`:focus-visible`:** `outline: 2px solid rgb(var(--focus)); outline-offset: 2px`.
- **Player only:**
  - keep `-webkit-tap-highlight-color: transparent`;
  - add `touch-action: manipulation` on `button`, which removes double-tap-zoom delay now that
    pinch zoom is enabled (§4.12).

### 4.7 `index.html` (each app)

- **`<html>`:** `<html lang="en" data-theme-key="buzzer:theme:<app>">`, with `<app>` being
  `host`, `player` or `admin`. This attribute is the **only** place each app's key is written.
- **Inline script.** Immediately after the charset and viewport `<meta>` tags, and before any
  stylesheet or module script, add a classic inline `<script>` (not a module) that:
  1. reads the key from `data-theme-key`;
  2. reads `localStorage[key]` inside `try/catch`, so a storage error counts as "nothing
     stored";
  3. uses the stored value if it is exactly `light` or `dark`; otherwise uses `dark` if
     `matchMedia('(prefers-color-scheme: dark)').matches`, and `light` if not;
  4. sets `data-theme` on `<html>`.

  Wrap the whole script in `try/catch`. On failure it does nothing, and the CSS dark default
  applies. Nothing else goes in the script. It must agree with `lib/theme.ts` §4.8 steps 1–3,
  so if one changes, change the other.
- **Player viewport:** change to `width=device-width, initial-scale=1.0`, removing
  `maximum-scale=1.0, user-scalable=no`. Blocking pinch zoom fails WCAG 1.4.4. Inputs are
  already `text-base` (16px), so iOS won't auto-zoom when they're focused.
- **Testing the no-flash behaviour.** Use the **production build behind nginx**. In
  `npm run dev`, Vite injects CSS from JavaScript, so any dev page shows a flash of unstyled
  content regardless of the theme script.
- **CSP.** The nginx config sets no Content-Security-Policy today, so the inline script runs.
  If a CSP is ever added, it needs a hash for this script.

### 4.8 `src/lib/theme.ts` (new, byte-identical, all three)

A tiny external store with no React context.

1. **The key** is `document.documentElement.dataset.themeKey`. If it is missing, log
   `console.error` once and **don't persist**. The theme still works for the session. This
   prevents a silent fall back to a shared key.
2. **`getStored()`** reads `localStorage` inside `try/catch` and returns `'light' | 'dark' |
   null`. Any other value counts as `null`.
3. **`resolve()`** returns `getStored()` if it isn't null; otherwise the `prefers-color-scheme:
   dark` media query decides.
4. **`getTheme()`** returns the current `data-theme` on `<html>`, validated, or `resolve()` if
   it isn't set.
5. **`apply(theme)`** does three things:
   - sets `data-theme` on `<html>`;
   - updates `<meta name="theme-color">` to `rgb(<channels of --page>)` read with
     `getComputedStyle`, creating the meta element in `<head>` if it doesn't exist. Mobile
     browsers use it to colour the browser bar; desktop browsers mostly ignore it;
   - notifies subscribers.
6. **`toggleTheme()`** writes the opposite of `getTheme()` to storage (inside `try/catch`), then
   applies it.
7. **`subscribe(listener)`** returns an unsubscribe function.
8. **`useTheme()`** returns `{ theme, toggle }` via React 18's `useSyncExternalStore(subscribe,
   getTheme)`.
9. **`initTheme()`** is called once in `main.tsx` before `createRoot`. It:
   - applies `resolve()`, which covers the case where the inline script failed;
   - adds a `change` listener on the `prefers-color-scheme: dark` media query that re-applies
     the OS theme **only if `getStored()` is null**;
   - adds a `storage` listener that re-applies `resolve()` when `event.key` is this app's key,
     so a projector window and a management tab of the same app stay in step.

**Rule for every app:** never call `localStorage.clear()`. The existing token removals use
`removeItem('token')`, which leaves the theme alone.

### 4.9 `src/components/ThemeToggle.tsx` (new, byte-identical, all three)

- **Element and labels.**
  - It is a `<button type="button">` using `useTheme()`.
  - It shows lucide-react's `Moon` icon in light mode and `Sun` in dark mode. All three apps
    already depend on `lucide-react`.
  - `aria-label` and `title` read "Switch to dark theme" or "Switch to light theme". There is
    no `aria-pressed`, because the label states the action.
- **Props:**
  - `className` (merged with `cn`) is used for placement;
  - `showLabel` (default `false`) shows the text "Dark theme" or "Light theme" next to the
    icon.
- **Base styling.**
  - At least 44×44 px: `min-h-11 min-w-11`.
  - `rounded-lg text-fg-muted hover:text-fg hover:bg-surface-hover`.
  - Icon size 20.
- **Placement:**

| app | where |
|---|---|
| host | **Management area:** inside `HostLayout`'s header, next to Sign out, with `showLabel`. **Everywhere else** (`/login`, `/home`, every `/game/*` screen): rendered once by `App.tsx`, fixed at `top-4 right-4 z-40`, unless the path starts with `/courses/`. On game screens the corner QR panel is bottom-right, so they don't collide. |
| player | Rendered once by `App.tsx`, fixed at `top-3 right-3 z-40`, **hidden on `/game/:code/question`** so it can never be mis-tapped during a timed answer. The host-disconnected and "too late" banners (`z-50`) cover it while they show. `GameOverPage`, whose content starts at the top, gets `pt-16` so the button doesn't overlap its heading. Check at 360×640 that nothing else overlaps. |
| admin | `AdminLayout` sidebar, directly above Logout, with `showLabel`. On `/login`: fixed at `top-4 right-4`, rendered by `App.tsx` for that route. |

### 4.10 Focus states

- The global `:focus-visible` rule (§4.6) is the only focus style.
- Remove every `focus:outline-none`, `outline-none`, `focus:ring-*`, `focus:ring-offset-*` and
  `focus:border-*` class from primitives and pages. That is 77 `focus:` uses and 20
  `outline-none` uses today.
- `check_theme.py` rejects `outline-none` from then on.
- Inputs show the outline on mouse focus too. That is correct `:focus-visible` behaviour for
  text inputs.
- The map canvas isn't keyboard-focusable and pin placement is pointer-only. That stays as it
  is; it is recorded as open question O3.

### 4.11 Role mapping (raw class → token)

Map by **role in context, not by shade.** The same shade plays different roles in different
places: `bg-slate-700` is a hover in one place, a chip in another and a timer track in a third.
Work file by file and apply this table.

| today | role | token class |
|---|---|---|
| `bg-slate-900`, `bg-slate-900/90` | page background, full-screen views, the host QR panel | `bg-page`, `bg-page/90` |
| `bg-slate-800`, `bg-slate-800/60`, `/50`, `/40` | card, panel, sidebar, header | `bg-surface` (opaque; drop the `/NN`) |
| `bg-slate-800` on an `<input>`, `<select>` or `<textarea>`; nested boxes inside a card | recessed control or panel | `bg-surface-alt` |
| `bg-slate-700`, `/50`, `/30`, `bg-slate-600`, `hover:bg-slate-700`, `hover:bg-slate-600`, `hover:bg-slate-800/30` | hover, selected row, chip | `bg-surface-hover` / `hover:bg-surface-hover` |
| `bg-slate-700` behind a progress bar or timer | track | `bg-chart-track` |
| `border-slate-700`, `/50`, `/60` | divider, card border | `border-line` (or a bare `border`, which now defaults to `line`) |
| `border-slate-600`, `border-slate-500`, `hover:border-slate-500` | form control or outline-button border | `border-line-strong` |
| `text-slate-100`, `-200`, `-300`, `text-white` on page or surfaces, `hover:text-slate-100`/`-200`, `group-hover:text-slate-200` | primary text | `text-fg` / `hover:text-fg` |
| `text-slate-400`, `-500`, `-600`, `hover:text-slate-300` | secondary text, labels | `text-fg-muted` (this fixes today's 3.75:1 failures) |
| `placeholder-slate-400`, `placeholder:text-slate-400` | placeholder | remove; the base rule covers it |
| `text-white` on an indigo, red or green fill | text on a fill | `text-on-accent` / `text-on-danger` / `text-on-success` |
| `text-white` on an answer button | text on an answer colour | `text-on-answer-N` (matching its fill) |
| `bg-indigo-600`, `bg-indigo-500`, `hover:bg-indigo-500` | primary action | `bg-accent hover:bg-accent-hover` |
| `text-indigo-300`, `-400`, `-700` | link, accent text | `text-accent-fg` |
| `bg-indigo-900`, `border-indigo-400`/`-500` | selected state (for example the HOST/PLAYER two-button toggle) | `bg-accent-soft text-accent-fg border-accent` |
| `accent-indigo-500` | native checkbox or slider | remove; the base `accent-color` covers it |
| any `focus:*` colour or offset class, `outline-none` | focus | remove (§4.10) |
| `text-green-300`, `-400`, `-500` | success or correct text | `text-success-fg` |
| `bg-green-500`, `-600` as a result bar | correct bar | `bg-chart-correct` |
| `bg-green-600`, `-700`, `hover:bg-green-500` as a button | success action | `bg-success text-on-success` |
| `bg-green-900`, `/50`, `/20`, `border-green-500`/`-700` | success box or badge | `bg-success-soft border-success` |
| `text-red-300`, `-400` | error text | `text-danger-fg` |
| `bg-red-500`, `-600`, `-700`, `hover:bg-red-500` | destructive action | `bg-danger hover:bg-danger-hover text-on-danger` |
| `bg-red-900`, `bg-red-500/15`, `border-red-500` | error box | `bg-danger-soft border-danger` |
| `text-amber-400`, `text-amber-50` | warning text | `text-warning-fg` |
| `bg-amber-500/15`, `/10`, `border-amber-500`, `/40` | warning badge or box | `bg-warning-soft border-warning` |
| `bg-amber-600/95`, `bg-yellow-600/90` + `text-yellow-100` | banner | `bg-warning text-on-warning` |
| `bg-green-500` / `bg-yellow-400` / `bg-red-500` in `TimerBar` | timer bands | `bg-success` / `bg-warning` / `bg-danger` |
| the player's `OPTION_COLORS` entries | answer buttons | `bg-answer-N text-on-answer-N border-answer-N`. Drop the `hover:` shade (hover sticks on touch screens). Keep the strings as **full literal class names** so Tailwind can find them. |
| `bg-white` behind `QRCodeSVG` | QR tile | `bg-qr-tile`. The QR itself keeps the library's default black on white. Never pass theme colours to it. |
| `border-white` (selected answer outline) | selection outline on an answer colour | `border-fg`; check it is visible on all 8 fills in both themes |

Anything not covered here (one-offs such as `text-slate-900`, `bg-slate-600` in a chip):
choose the token by role, and if no token fits, **add a token** to §4.3, `theme.css` and the
config, rather than using a near miss. Record the addition in this spec's revision history.

**Badge convention for the admin and host management pages** (Restricted, Unassigned, Guests
allowed, status chips): `rounded px-1.5 py-0.5 text-xs font-semibold`, with
`bg-<status>-soft text-<status>-fg`, or `bg-surface-alt text-fg-muted` for neutral badges. Use
the same badge for the same meaning everywhere:

- Restricted → warning;
- Unassigned → neutral;
- Guests allowed → success;
- live session → accent.

### 4.12 Per-app notes

**Host**

- **Stage.** In `pages/game/GameLayout.tsx`, wrap the rendered output in an element with
  `data-stage`: the `<Outlet/>`, the QR panel and the full-screen error view.
- **Readability on stage screens** (lobby, question, results, game over):
  - No student-facing text below `text-lg`. Today's QR-panel "Room Code" label is
    `text-[10px]`; make it `text-sm` and leave the code itself as it is.
  - Student-facing content (prompt, options, counts, scores) uses `text-fg`, never `fg-muted`.
    Muted is for labels only.
  - Never make anything smaller than it is today.
  - **Proxy check:** a 1920×1080 screenshot scaled down to 480px wide must still have a
    readable prompt, option labels, counts and room code. Do this in both themes.
- **Results:**
  - The bar chart's correct bar is `bg-chart-correct`, other bars `bg-chart-bar`, the track
    `bg-chart-track`.
  - The existing "✓ Correct" label stays and uses `text-success-fg`.
  - The word cloud is covered in §4.14.
- **Management area** (`HostLayout`, `manage/*`, HomePage, LoginPage) uses the normal token
  values. `manage/QuestionEditorPage.tsx` is swept in step with the admin copy (same role
  choices for the same markup).

**Player**

- **Thumb-friendliness.** Answer buttons stay full-width, and their sizes and spacing don't
  change. Every new tappable element is at least 44×44 px.
- **True/False** use `answer-4` (green, True) and `answer-1` (red, False), with their
  `on-answer` text.
- **Banners** (host disconnected, "too late") use `bg-warning text-on-warning`.
- **The map** is covered in §4.13. The map-pin Confirm button is a primary action (`accent`).

**Admin**

- **Density.** Keep it: don't change padding, font sizes or table layout.
- **Table header rows:** `bg-surface-alt text-fg-muted`. **Row dividers:** `line`. **Row
  hover:** `surface-hover`.
- **Native controls.** Raw `<select>`, `<textarea>` and checkboxes get `bg-surface-alt
  border-line-strong text-fg`. `color-scheme` (§4.4) makes their drop-down lists follow the
  theme.
- **The sidebar** is `bg-surface border-r border-line`. The active link is `bg-accent-soft
  text-accent-fg`.

### 4.13 Canvas and map code

- **`lib/mapPin.ts`** (byte-identical ×3) gets one helper,
  `mapColor(name: 'full' | 'full-fill' | 'zero' | 'pin' | 'pin-disabled' | 'heat', alpha = 1)`.
  It:
  - reads `getComputedStyle(document.documentElement).getPropertyValue('--map-' + name)`;
  - trims the result;
  - returns `rgb(<channels> / <alpha>)`.

  Replace each literal with a call: the zero circle is `mapColor('zero', 0.95)`, the full-credit
  fill is `('full-fill', 0.25)`, the full-credit stroke and target dot are `('full')`. The
  default colour of `drawPin` becomes `mapColor('pin')`, resolved inside the function and not
  as a default-parameter literal. These tokens never change with the theme, so no repaint
  logic is needed.
- **`player/src/components/MapPinCanvas.tsx`:** the disabled pin uses
  `mapColor('pin-disabled')`.
- **`host/src/components/MapPinHeatmap.tsx`:** dots use `mapColor('heat', 0.55)`.
- **`components/MapCanvas.tsx`** (byte-identical ×3): only its surrounding elements change.
  - The canvas background (letterbox) becomes `bg-surface-alt`.
  - "Loading map…" becomes `text-fg-muted`.
  - "Couldn't load the map" becomes `text-danger-fg`.
  - Retry becomes `border-line-strong text-fg hover:bg-surface-hover`.

  The map image and overlays are unchanged.

### 4.14 Non-colour cues

Each place where colour alone says "correct", "wrong" or "time running out" must also carry
text or a glyph.

| place | today | change |
|---|---|---|
| host `ResultsPage` bar chart | "✓ Correct" label on correct bars | none |
| host `ResultsPage` word cloud | accepted words are only coloured green | prefix accepted words with "✓ " and make them `font-bold` |
| host `GameOverPage` breakdown | ✓ on correct rows | none |
| player `ResultsPage` | "Correct!" / "Incorrect" text; map labels "Within target" / "Partial credit" / "Too far" | none |
| player `GameOverPage` recap | audit during the sweep | if correctness is shown by colour only, add ✓ / ✗ |
| `TimerBar` (both) | bar width plus "Ns" label | none; the label becomes `text-fg-muted` (the stage value on the host) |

### 4.15 `scripts/check_theme.py` (new)

The script uses only the Python standard library. It runs from the repo root and exits non-zero
on any failure. Each failure prints `path:line: message`.

- **Usage:** `python scripts/check_theme.py [--app host|player|admin] [--check
  colors|contrast|identical]`.
- **Defaults:** with no flags it runs every check on every app. The flags narrow it while
  sweeping.

**Check 1: colours.** Scans `frontend/<app>/src/**/*.{ts,tsx,css}`, excluding `src/theme.css`,
and flags:

- **Raw palette classes.** Any of these prefixes followed by a palette name:
  - prefixes (optionally after variant prefixes such as `hover:` or `md:`): `bg`, `text`,
    `border`, `ring`, `ring-offset`, `outline`, `divide`, `fill`, `stroke`, `from`, `via`, `to`,
    `accent`, `caret`, `decoration`, `placeholder`, `shadow`;
  - palette names: `slate`, `gray`, `zinc`, `neutral`, `stone`, `red`, `orange`, `amber`,
    `yellow`, `lime`, `green`, `emerald`, `teal`, `cyan`, `sky`, `blue`, `indigo`, `violet`,
    `purple`, `fuchsia`, `pink`, `rose`, `white`, `black`;
  - optionally followed by a `-<shade>` and a `/<opacity>`.
- **Hex literals:** `#` followed by 3, 6 or 8 hex digits at a word boundary.
- **Numeric colour functions:** `rgb(`, `rgba(`, `hsl(` or `hsla(` followed by a digit. The
  `mapColor` template and `rgb(var(--…))` don't match.
- **`outline-none`.**
- **Escape hatch.** A line containing `theme-check: ignore` is skipped. Every use must say why
  in the same comment. There should be close to zero.

**Check 2: contrast.** For each app, parse `theme.css` using the selectors in §4.4. Then, for
each theme (and the host stage blocks merged over it), compute the WCAG 2.1 contrast ratio for
these pairs:

- **4.5:1:**
  - `fg`, `fg-muted`, `accent-fg`, `success-fg`, `danger-fg` and `warning-fg` on `page`,
    `surface` and `surface-alt`;
  - `fg` and `fg-muted` on `surface-hover`;
  - `accent-fg` on `accent-soft`, `success-fg` on `success-soft`, `danger-fg` on
    `danger-soft`, `warning-fg` on `warning-soft`;
  - `on-accent` on `accent` and `accent-hover`;
  - `on-danger` on `danger` and `danger-hover`;
  - `on-success` on `success`, `on-warning` on `warning`;
  - `on-answer-N` on `answer-N` for N = 1–8.
- **7:1 (host stage blocks only):** the same text pairs as above, except the `on-*` pairs,
  which stay at 4.5 because they are operator buttons.
- **3:1 (non-text):**
  - `focus` and `line-strong` against `page`, `surface` and `surface-alt`;
  - `chart-bar` and `chart-correct` against `chart-track`.

The output is a table of every pair, with failures marked.

**Check 3: identical.**

- Every app defines exactly the same set of token names. Host stage blocks may only override
  the five tokens in §4.3.
- The invariant, dark and light values are identical across the three apps.
- The byte-identical groups in §4.0 have one md5 each.
- No `frontend/*/tailwind.config.js` or `frontend/*/vite.config.js` exists (§4.2).

**While sweeping**, run `--check colors --app <app>`. From §4.18 step 6 on, the whole script
must pass. Add the command to the root `CLAUDE.md`'s Scripts list.

### 4.16 Screenshot evidence (`docs/ui/`)

- **Layout:**
  - `docs/ui/before/<app>-<screen>.png`: dark only, because that is the only theme today;
  - `docs/ui/after/dark/<app>-<screen>.png` and `docs/ui/after/light/<app>-<screen>.png`;
  - `docs/ui/README.md`: a table with one row per screen, linking before, after-dark and
    after-light, plus one line saying what changed.

  T10 documents link to that README.
- **Build:** the production build behind nginx (`npm run build`, then `docker compose up`), so
  the no-flash behaviour and paths are real.
- **Viewports** (browser devtools device mode):
  - host 1920×1080 (projector);
  - player 390×844;
  - admin 1440×900.
- **Data.**
  - Import `sample_games/madineni_us_geography_classroom.json` (it has map-pin questions) and
    `sample_games/cs_first_day.json` (multiple choice) through the admin Games page.
  - Start a room from the host app.
  - Run `python scripts/simulate_players.py --room <CODE> --players 20 --game-json <same
    file>`. It answers map-pin questions as well, so the bar chart and heatmap have data.
  - Join once from a phone-sized browser as a guest for the player screenshots.

| app | screens (`<screen>` names) |
|---|---|
| host | `login`, `home`, `manage-question-editor` (map-pin question open, with the image and target placed), `lobby`, `question`, `results-bars`, `results-heatmap`, `gameover` |
| player | `join`, `question-mc`, `question-map`, `results-map`, `gameover` |
| admin | `users`, `access`, `question-editor-map`, `sessions-export` (export panel open) |

That is 17 screens, so 17 "before" images and 34 "after" images.

### 4.17 T8 and later code

At the time of writing, the only image surfaces in the source (on `main` and this branch) are
the ones T7 delivered:

- image upload in both question editors;
- the map canvas in all three apps.

Any further T8 UI, such as image management or delete, or prompt and option images, is written
against tokens from the start. It must pass `scripts/check_theme.py` before it merges. If such
UI merges between §4.18 steps 5 and 6, sweep it as part of step 5.

### 4.18 Implementation order

0. "Before" screenshots (§4.1, §4.16). Commit them.
1. Stale build output fix (§4.2). Verify it.
2. `scripts/check_theme.py` (§4.15). It will report hundreds of colour failures; that is
   expected. Contrast and identical checks run once `theme.css` exists.
3. Token layer, per app:
   - `theme.css` (§4.4) and its import in `main.tsx`;
   - `tailwind.config.ts` with the tokens under `extend` (§4.5);
   - `index.css` (§4.6);
   - `index.html` (§4.7);
   - `lib/theme.ts` (§4.8) and the `initTheme()` call;
   - `ThemeToggle` (§4.9) and its placement.

   Then run `--check contrast` and `--check identical`, which must pass. The apps should look
   almost unchanged in dark mode at this point.
4. Primitives:
   - `components/ui/*` in each app; host and admin stay identical;
   - `TimerBar`;
   - the `MapCanvas` chrome and `mapPin.ts` `mapColor`, copied to all three apps (§4.13);
   - `MapPinCanvas` and `MapPinHeatmap`;
   - removal of focus classes from primitives (§4.10).
5. Sweep host, then player, then admin, page by page, using §4.11. Run `--check colors
   --app <app>` until it is clean. Sweep the two `QuestionEditorPage`s together.
6. Move the tokens from `extend.colors` to `colors` (§4.5) and rebuild. Click through every
   page in both themes looking for unstyled elements, which would be raw classes the regex
   missed, for example ones built from template strings. The full `check_theme.py` must pass.
7. Context-fit work:
   - host stage readability (§4.12);
   - player viewport and `touch-action` (§4.6, §4.7);
   - non-colour cues (§4.14);
   - badge convention (§4.11).
8. Verification checklist (§4.19), then the "after" screenshots and `docs/ui/README.md`.
9. Context hierarchy updates (§4.20).

### 4.19 Verification checklist (manual; there is no frontend test runner)

**Theme and toggle**

- [ ] **First visit follows the OS.** For each app, in a fresh profile, set the OS to light: the
  page loads light. Set it to dark: the page loads dark.
- [ ] **No flash.** Reloading the nginx build with a stored choice that differs from the OS
  shows no flash, including a host reload mid-game.
- [ ] **Persistence.** After toggling, the choice persists across reloads, and changing the OS
  setting afterwards no longer changes the theme.
- [ ] **Keys are separate.** Behind nginx, on one browser, toggling admin doesn't change host or
  player. `localStorage` shows three separate `buzzer:theme:*` keys.
- [ ] **Tabs stay in step.** With two host tabs open, toggling one updates the other.
- [ ] **Logging out keeps the theme.** The player's "Play Again" and every logout remove the
  login token but not the theme key.
- [ ] **Placement.** The player toggle is absent on the question screen and present on join,
  name, lobby, feedback, results and game over. The host toggle doesn't overlap the QR panel or
  any stage content.

**Accessibility**

- [ ] **Keyboard focus.** Tabbing through each page shows a visible outline on every button,
  link, input, select, checkbox and slider, in both themes. Clicking or tapping a button shows
  no outline.
- [ ] **Native controls.** Native selects, checkboxes, sliders and scrollbars match the theme
  (`color-scheme`).
- [ ] **Pinch zoom** works on the player on a real phone, and answer buttons don't double-tap
  zoom.

**Canvas and QR**

- [ ] **Map overlays.** The map editor (admin and host), the player's map question and reveal,
  and the host heatmap look identical in both themes apart from the letterbox and loading/error
  states.
- [ ] **QR scanning.** The QR codes (lobby and corner) scan from a phone in both themes.

**Checks and evidence**

- [ ] **Host readability.** The stage proxy check passes in both themes (§4.12). If you have
  access to the real classroom projector, test there too (open question O1).
- [ ] **Scripts.** `python scripts/check_theme.py` passes, and every `md5` group is a single
  hash.
- [ ] **Build.** `npm run build` succeeds for all three apps.

### 4.20 Context hierarchy updates

Per `.claude/rules/context-sync.md`, update:

| file | what to change |
|---|---|
| `frontend/CLAUDE.md` | A theme-system section covering: tokens in `theme.css`, `data-theme` / `data-theme-key`, per-app keys, the new byte-identical groups, `check_theme.py`, the stale build output gotcha (now fixed) and how to verify it. |
| `frontend/*/src/CLAUDE.md` | `index.css` is no longer "dark-slate body styles"; add `theme.css`; add `buzzer:theme:<app>` to the localStorage list; the inline script in `index.html`. Player: the viewport change. |
| `frontend/*/src/components/CLAUDE.md` | Replace "styled for the dark slate theme" with tokens. Add `ThemeToggle`. Focus comes from the global `:focus-visible` rule. Map chrome tokens. |
| `frontend/*/src/lib/CLAUDE.md` | `theme.ts`; `mapPin.ts`'s `mapColor` and the invariant `--map-*` tokens. |
| `frontend/host/src/pages/CLAUDE.md` | `data-stage` on `GameLayout` and what it overrides; where the toggle lives. |
| `frontend/player/src/pages/CLAUDE.md` | The toggle is hidden on the question route; the answer-colour tokens. |
| `frontend/admin/src/pages/CLAUDE.md` | The badge convention. |
| `CLAUDE.md` (root) | `python scripts/check_theme.py` under Scripts. |

### 4.21 Files touched

**All three apps** (`frontend/{host,player,admin}/`):

- **Config and entry files:** `tsconfig.node.json`, `tailwind.config.ts`, `index.html`,
  `src/main.tsx`, `src/index.css`, `src/App.tsx`.
- **New files:** `src/theme.css`, `src/lib/theme.ts`, `src/components/ThemeToggle.tsx`.
- **Shared map and UI files:** `src/lib/mapPin.ts`, `src/components/MapCanvas.tsx`,
  `src/components/ui/{button,card,input}.tsx`.
- **Every page** listed in that app's `pages/CLAUDE.md`.
- **Deleted:** the stale `vite.config.js` and `tailwind.config.js` (untracked).

**App-specific files:**

- **Host:** `src/components/ui/TimerBar.tsx`, `src/components/MapPinHeatmap.tsx`,
  `src/pages/game/GameLayout.tsx` (`data-stage`).
- **Player:** `src/components/ui/TimerBar.tsx`, `src/components/MapPinCanvas.tsx`.
- **Admin:** `src/components/MoveGamePanel.tsx`.

**Repository files:**

- `scripts/check_theme.py` (new);
- `docs/ui/**` (new);
- the context files in §4.20.

## 5. Open questions

- **O1 — Real projector.** The 7:1 stage target and the scaled-screenshot proxy are
  monitor-based. Projectors in lit rooms crush dark greys and wash out light themes. Test on the
  actual classroom projector if possible, and record the result in `docs/ui/README.md`.
- **O2 — Light-theme answer buttons against the page.** Yellow (`answer-3`) and orange
  (`answer-6`) fills are about 1.5:1 against the light page. Their text passes, but the button
  edge is faint. Non-text contrast (WCAG 1.4.11) isn't in T9's table. If the after screenshots
  look weak, add `border-line-strong` to answer buttons in both themes. Decide from the
  screenshots.
- **O3 — Keyboard access to the map canvas.** Pin placement is pointer-only. That is out of
  scope for T9; record it as a known limitation in the T10 write-up.

## Revision history

- 2026-10-05 — Initial spec from the design discussion. Decisions:
  - per-app storage keys;
  - invariant map-overlay, answer and QR colours;
  - the same token names everywhere, with 7:1 overrides on host game screens only;
  - the token layer and check script land before any further T8 UI;
  - stale build output fixed first;
  - channel tokens with `<alpha-value>`;
  - an inline no-flash script plus `color-scheme` and `theme-color`;
  - role-based mapping, then the palette replaced and enforced by script;
  - paired text colours for answer and status fills;
  - chart tokens; a fixed black-on-white QR code; the HTML report out of scope;
  - a contrast-check script; non-colour cues;
  - follow the OS until the user toggles;
  - pinch zoom re-enabled on the player.

  Focus was specified as an outline with a transparent offset instead of a ring with a token
  offset colour (see §3).
