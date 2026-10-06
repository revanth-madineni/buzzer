# T9 — UI Look-and-Feel & Theming

Status: agreed design, goldfish-tested once and revised (see Revision history). Written
2026-10-05.
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
- the shared map-pin code draws with 17 `rgba()` literals and 9 `'white'` literals.

There is no light theme, no toggle and no shared vocabulary for colour. Some text already fails
WCAG AA in the current dark theme:

- `text-slate-500` (used 90 times) on slate-900 is 3.75:1;
- `text-slate-600` is worse;
- white labels on the player's yellow, orange, green and teal answer buttons are 1.9, 2.8, 3.3
  and 3.7:1;
- the host's result bars draw their counts as small white text inside the bar.

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
   `rgb(var(--name) / <alpha-value>)`, so opacity modifiers such as `bg-scrim/70` keep working.
2. **Token names are identical in all three apps.** `tailwind.config.ts` is byte-identical
   across the apps. The player and admin `theme.css` files are byte-identical. The host file is
   the same plus a "stage" block.
3. **Themes are set by `data-theme="light|dark"` on `<html>`.** The token values change and the
   class names stay the same. No `dark:` variants are used anywhere, and the check script
   rejects them.
4. **Host game screens are a "stage".** Host `GameLayout` wraps its output in a
   `<div data-stage className="contents">`. Because of `display: contents` the wrapper creates
   no box, so layout doesn't change, but tokens still inherit through it. Inside the stage:
   - five text tokens are overridden to reach at least 7:1, because projected text washes out;
   - five fill tokens (`accent`, `accent-hover`, `success`, `danger`, `danger-hover`) are
     overridden so that **any text drawn on a fill there also reaches 7:1**.

   The host management area, login and home pages use the normal values.
5. **No text is drawn inside chart bars.** Labels, counts and percentages sit beside the bar,
   on the page background.
6. **Some colours don't change with the theme**, because they sit on top of something the theme
   doesn't control:
   - the 8 player answer colours, each with its own text colour;
   - the map-overlay colours (pin, target, radius circles, heatmap, white outlines), which are
     drawn on the map image;
   - the white QR-code tile;
   - a `scrim` (black) with `on-scrim` (white) text, for anything drawn over an image or as an
     overlay.

**Toggle and persistence**

7. **Each app has its own storage key**: `buzzer:theme:host`, `buzzer:theme:player`,
   `buzzer:theme:admin`. Behind nginx the three apps share one origin and one `localStorage`,
   and the projector must not flip when the admin console does. The key is declared once per
   app, as `data-theme-key` on `<html>` in `index.html`. The check script verifies each key
   matches its app.
8. **No flash of the wrong theme.** A small inline script at the top of each `index.html`
   resolves the theme before the first paint:
   - a stored choice wins;
   - otherwise `prefers-color-scheme` decides.

   `theme.css` sets `color-scheme` so native controls and scrollbars match the theme.
9. **The toggle has two states.** With nothing stored, the app follows the OS and updates live
   when the OS setting changes. Clicking the toggle stores an explicit `light` or `dark`. There
   is no way back to "follow the OS" except clearing site data; this is documented, not fixed.
10. **`lib/theme.ts` and `components/ThemeToggle.tsx` are byte-identical across the apps.**
    - **Placement:** each page or layout that shows the toggle renders it itself. There is no
      route-path matching.
    - **Labels:** the visible label and the `aria-label` both name the theme you would switch
      **to**.

**Accessibility**

11. **Focus uses one global `:focus-visible` rule**: a 2px outline in `--focus` with a 2px
    transparent offset. Two small rules cover the cases the global rule can't:
    - a non-focusable container with a fill sets `data-fill`, which turns the focus colour of
      the elements inside it into that fill's text colour;
    - controls inside a clipping container get `focus-inset`, which draws the outline inside the
      element.

    Every per-component `focus:ring-*` and `outline-none` is removed.

**Enforcement and evidence**

12. **`scripts/check_theme.py` is a manual gate.** It is not wired into CI; `.gitlab-ci.yml`
    stays unmodified. It is listed in the root `CLAUDE.md` and in an MR template checklist. Once
    the Tailwind palette is replaced with the tokens, a leftover raw class produces **no CSS and
    no error**. Only running the script and clicking through the pages in both themes catch it.
    The spec says so plainly rather than relying on the build.
13. **Contrast is checked by the same script.** It parses each `theme.css` and checks a fixed
    list of token pairs:
    - text at 4.5:1;
    - everything on the host stage at 7:1;
    - non-text elements at 3:1 (focus on every background it can sit on, control borders, chart
      bars, timer bands);
    - text on the scrim, assuming the worst case of a white image underneath.

    Adding a token means adding its pairs to that list.
14. **Non-colour cues** back up colour wherever correctness or selection is shown.
15. **Screenshots come first.** "Before" screenshots are taken from the current `main` build
    before any code changes. "After" screenshots are taken in both themes. They go in
    `docs/ui/`, with an index page.

## 3. Alternatives considered

| Alternative | Why it lost |
|---|---|
| Tailwind `dark:` variants (`darkMode: 'class'`) | Every colour class appears twice, and it isn't a semantic token layer, which T9 requires. It also can't express the host stage overrides without a third set of variants. |
| A shared npm workspace package for tokens and theme code | The apps deliberately share no code (`frontend/CLAUDE.md`). Byte-identical copies, checked by a script, are the convention T7 already uses. A workspace is a bigger change than T9. |
| One shared `theme` key for all three apps | Behind nginx, toggling the admin console would flip the projector, the same trap as the shared login token. |
| A three-state toggle (light / dark / system) | More UI to explain. The requirement only asks for "OS first, then persist". The limitation is documented (§2.9). |
| Applying the theme in React only | The page paints dark first. Users who prefer light would see a flash on every load, including a projector reload mid-class. |
| Hex values in the variables | Tailwind 3's `/<alpha>` modifiers stop working, and the design relies on them (`bg-page/90`, `bg-scrim/70`). |
| Extending the palette instead of replacing it | Raw classes would still compile, so "eliminated" couldn't be enforced by the build's output. Extending is used only as an interim step (§4.18 steps 3–5). |
| Running `check_theme.py` in CI | `.gitlab-ci.yml` must stay unmodified (course rule), so the script is a documented manual gate instead (§4.15). |
| Text inside chart bars, with `on-chart-*` tokens | Bar fills would have to carry 7:1 text on the projector while still looking like a chart. Moving the labels beside the bar puts all chart text on the page background, which the stage text tokens already cover. |
| Map-overlay colours that change per theme | Canvases can't read classes. They would have to read computed styles and repaint on every theme change, and `MapCanvas` only repaints on resize or when `draw` changes. Overlay contrast is against the map image, not the page, so the theme gives no reason to change them. |
| Focus ring with a token `ring-offset` colour | The offset colour has to match the surface under the element, so any single token is wrong somewhere. A transparent `outline-offset` has nothing to match. As one global rule, it also covers the hand-built controls. Its two weak spots, focus inside a filled container and outlines clipped by `overflow: hidden`, are handled explicitly (§4.10). |
| Setting `data-stage` on `<body>` from an effect | It applies after the first paint, and it must be removed when the game screens unmount. The `display: contents` wrapper applies with the render and needs no cleanup. |
| A Node or npm contrast tool | No app has a test runner or lint pipeline to hook it into. `scripts/` is already Python, and the check needs only arithmetic and regular expressions. |

## 4. Detailed implementation

### 4.0 Conventions and verified facts

**Byte-identical files.** "Byte-identical" means the file must have the same md5 in every app
listed. Edit one copy, then copy it to the others. `scripts/check_theme.py` enforces this
(§4.15). The byte-identical groups after T9 are:

- `tailwind.config.ts`, `src/lib/theme.ts`, `src/components/ThemeToggle.tsx`,
  `src/lib/mapPin.ts`, `src/components/MapCanvas.tsx` and `src/lib/images.ts` in all three
  apps;
- `src/theme.css` in player and admin;
- `components/ui/{button,card,input}.tsx` in host and admin. These stay identical; the player
  copies stay different because they are tuned for touch.

**Terms.**

- **"Token"** means a name in §4.3. "On page / surface / surface-alt" means text drawn directly
  on that background.
- **"Student-facing"** means text that students in the room must read on the projector: the
  prompt, options, counts, room code, results and scores. Operator controls (Lock, Show Results,
  Next) are not student-facing, but stage fills are overridden so that they reach 7:1 anyway
  (§4.3).
- **Colour values** are given in hex for readability. In `theme.css` they are written as
  space-separated decimal channels, for example `#1e293b` becomes `30 41 59`.

**Facts checked against the repo on 2026-10-05:**

- The three `tailwind.config.ts` files are identical today (one md5), so the shared config
  replaces identical files.
- Tailwind 3.4.19 is installed in all three apps (`package.json` says `^3.4.11`), so the 3.4
  utilities used here (`min-h-11`, `min-w-11`, `contents`) exist.
- Each app exports `cn` from `src/lib/utils.ts`. Components import it as `../lib/utils`, with
  no path aliases, so a byte-identical `ThemeToggle.tsx` resolves it in every app.
- `.gitignore` already ignores `*.tsbuildinfo` and `frontend/*/{vite,tailwind}.config.d.ts`.
- The host never renders the `answer-N` colours. Only the player does.

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
  projects must still emit declarations; those `.d.ts` files and `.tsbuildinfo` are already
  gitignored (§4.0) and don't shadow config resolution. Then delete the existing
  `frontend/*/vite.config.js` and `frontend/*/tailwind.config.js`.
- **CI is unaffected.** CI's `frontend-typecheck` job runs `tsc --noEmit` on `tsconfig.json`,
  not `tsc -b`.
- **Verify:** after `npm run build`, `ls frontend/*/tailwind.config.js frontend/*/vite.config.js`
  finds nothing. In `npm run dev`, a class that exists only in the `.ts` config produces CSS.

### 4.3 Token set

**Themed tokens.** Values are given as dark / light. Every pair in §4.15 was checked against
these values while writing this spec, and all of them passed.

| token | role | dark | light |
|---|---|---|---|
| `page` | app background (`body`) | `#0f172a` | `#f1f5f9` |
| `surface` | cards, sidebar, panels, header bars | `#1e293b` | `#ffffff` |
| `surface-alt` | recessed areas **inside a `surface`**: inputs, nested panels, table header rows, map letterbox | `#0f172a` | `#f8fafc` |
| `surface-hover` | hover and selected rows, ghost-button hover | `#283548` | `#e2e8f0` |
| `fg` | primary text | `#f8fafc` | `#0f172a` |
| `fg-muted` | secondary text, labels, placeholders | `#94a3b8` | `#475569` |
| `line` | dividers, card borders | `#334155` | `#e2e8f0` |
| `line-strong` | borders of form controls and outline buttons (≥ 3:1) | `#64748b` | `#64748b` |
| `accent` | primary button fill, selected state | `#4f46e5` | `#4f46e5` |
| `accent-hover` | primary button hover | `#4338ca` | `#4338ca` |
| `on-accent` | text, glyphs and borders on `accent` / `accent-hover` | `#ffffff` | `#ffffff` |
| `accent-fg` | links and accent-coloured text on page or surfaces | `#a5b4fc` | `#4338ca` |
| `accent-soft` | tinted selected background (text on it: `accent-fg`) | `#1e1b4b` | `#e0e7ff` |
| `focus` | focus outline | `#818cf8` | `#4f46e5` |
| `success` | success fill | `#15803d` | `#15803d` |
| `on-success` | text on `success` | `#ffffff` | `#ffffff` |
| `success-fg` | success text on page or surfaces | `#4ade80` | `#166534` |
| `success-soft` | success badge or box background (text on it: `success-fg`) | `#052e16` | `#dcfce7` |
| `danger` | destructive fill | `#b91c1c` | `#b91c1c` |
| `danger-hover` | destructive hover | `#991b1b` | `#991b1b` |
| `on-danger` | text on `danger` / `danger-hover` | `#ffffff` | `#ffffff` |
| `danger-fg` | error text | `#f87171` | `#b91c1c` |
| `danger-soft` | error box background | `#450a0a` | `#fee2e2` |
| `warning` | warning fill (banners) | `#fbbf24` | `#fbbf24` |
| `on-warning` | text on `warning` | `#0f172a` | `#0f172a` |
| `warning-fg` | warning text | `#fcd34d` | `#92400e` |
| `warning-soft` | warning badge background | `#451a03` | `#fef3c7` |
| `chart-track` | empty part of a result bar or timer | `#334155` | `#e2e8f0` |
| `chart-bar` | neutral result bar: incorrect options, and every bar of a question with no right answer | `#94a3b8` | `#64748b` |
| `chart-correct` | correct-answer result bar | `#22c55e` | `#15803d` |
| `timer-ok` | timer bar above 60% | `#4ade80` | `#15803d` |
| `timer-warn` | timer bar from 30% to 60% | `#fbbf24` | `#b45309` |
| `timer-low` | timer bar at or below 30% | `#f87171` | `#b91c1c` |

**Host stage overrides.** These apply inside `[data-stage]`, host only. There are exactly ten,
and nothing else is overridden.

| token | dark stage | light stage | why |
|---|---|---|---|
| `fg-muted` | `#cbd5e1` | `#334155` | 7:1 text on page or surfaces |
| `accent-fg` | `#c7d2fe` | `#3730a3` | 7:1 |
| `success-fg` | `#86efac` | `#14532d` | 7:1 |
| `danger-fg` | `#fca5a5` | `#7f1d1d` | 7:1 |
| `warning-fg` | `#fde68a` | `#78350f` | 7:1 |
| `accent` | `#4338ca` | `#4338ca` | `on-accent` reaches 7.9:1 (normal is 6.3) |
| `accent-hover` | `#3730a3` | `#3730a3` | 9.9:1 |
| `success` | `#166534` | `#166534` | `on-success` reaches 7.1:1 |
| `danger` | `#991b1b` | `#991b1b` | `on-danger` reaches 8.3:1 |
| `danger-hover` | `#7f1d1d` | `#7f1d1d` | 10:1 |

`warning` needs no override: `on-warning` on it is already 10.7:1.

**What the host draws on fills on stage screens today** (checked in source):

- **Result-bar counts.** These are white `text-sm` inside the bar today. They move beside the
  bar (§4.12).
- **`Button` fills.** These are the `accent` fills of Start Game, Show Results, Next and New
  Game. They are covered by the overrides above.
- **No other text on fills.** The histogram, the GameOver answer bars, the lobby switch and the
  QR tile carry no text on a fill.

The host doesn't use `answer-N`. If it ever does, add stage overrides first.

**Invariant tokens** have the same value in both themes:

| token | role | value | text colour |
|---|---|---|---|
| `answer-1` … `answer-8` | player multiple-choice answer buttons; True/False use 4 and 1 | red `#dc2626`, blue `#2563eb`, yellow `#facc15`, green `#15803d`, purple `#9333ea`, orange `#fb923c`, pink `#be185d`, teal `#0f766e` | `on-answer-N`: white for 1, 2, 4, 5, 7, 8; `#0f172a` for 3 (yellow) and 6 (orange) |
| `map-full` | full-credit circle stroke and target dot (alpha 1) | `#16a34a` | — |
| `map-full-fill` | full-credit circle fill (drawn at alpha 0.25) | `#22c55e` | — |
| `map-zero` | zero-credit dashed circle (alpha 0.95) | `#eab308` | — |
| `map-pin` | player's pin | `#dc2626` | — |
| `map-pin-disabled` | pin while input is disabled | `#64748b` | — |
| `map-heat` | heatmap dots (alpha 0.55) | `#ef4444` | — |
| `map-outline` | outline of the target dot and the pin, and the pin's inner dot (alpha 1) | `#ffffff` | — |
| `qr-tile` | white tile behind every QR code | `#ffffff` | — |
| `scrim` | overlay behind anything drawn over an image, and modal backdrops; always used with alpha | `#000000` | `on-scrim` `#ffffff` |

**Notes on the invariant tokens:**

- **Map values** are today's literals, unchanged, so overlays look exactly as they do now.
- **Answer colours.** Yellow and orange buttons now take dark text. Green and teal move one
  shade darker so that white text reaches at least 4.5:1. Pink already passes at 4.6:1 but only
  barely, so it also moves to `pink-700` (6.0:1). That gives margin on phones turned down to
  low brightness.
- **Scrim.** Text on a scrim uses `bg-scrim/70` or darker. At 70%, white text has 8.5:1 even
  over a pure-white image, which covers the 7:1 stage target too. A scrim used only as a modal
  backdrop with no text on it may be lighter.

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
2. **`:root, :root[data-theme="dark"]`** — the dark values. Dark is the fallback if the inline
   script fails.
3. **`:root[data-theme="light"]`** — the light values.
4. **Host only:**
   - `:root [data-stage], :root[data-theme="dark"] [data-stage]` — the dark stage overrides;
   - `:root[data-theme="light"] [data-stage]` — the light stage overrides.

What the blocks contain:

- Every block holds `--<token>: R G B;` declarations.
- **Blocks 2 and 3 also contain exactly one `color-scheme` declaration each** (`dark` and
  `light`).
- Nothing else goes in the file: no rules, no comments between declarations.
- `check_theme.py` reads only the `--` declarations, and separately checks that blocks 2 and 3
  each contain their `color-scheme` line.

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
- Set `theme.extend.ringColor.DEFAULT` to the `focus` colour. Without it, a bare `ring` falls
  back to hardcoded blue. Use Tailwind's function form (`({ opacityValue }) =>
  rgb(var(--focus) / <opacityValue>)`, cast to `string` for the types), not the
  `<alpha-value>` string: Tailwind builds the default ring colour with `withAlphaValue()`, which
  can't parse that string and silently keeps the blue.
- Keep the existing `fontFamily` and `content` globs. Don't add custom `fontSize` names: `cn()`
  uses tailwind-merge, which would mistake a custom size such as `text-display` for a colour
  and drop one of the two classes. Stock sizes (`text-xl` … `text-7xl`) are enough.

### 4.6 `src/index.css`

Keep the three `@tailwind` directives and `box-sizing`. Remove the hardcoded `body` colours.

**In `@layer base`:**

- **`body`:** background `rgb(var(--page))`, colour `rgb(var(--fg))`.
- **`::placeholder`:** colour `rgb(var(--fg-muted))`, `opacity: 1`. Firefox otherwise dims
  placeholders below 4.5:1.
- **`:root`:** `accent-color: rgb(var(--accent))`. This replaces the six
  `accent-indigo-500` classes on native checkboxes and range sliders.
- **`:focus-visible`:** `outline: 2px solid rgb(var(--focus)); outline-offset: 2px`.
- **Focus inside a filled container.** Five rules that redefine `--focus` for everything inside
  a container with a fill:
  - `[data-fill="accent"]` → `var(--on-accent)`;
  - `[data-fill="success"]` → `var(--on-success)`;
  - `[data-fill="danger"]` → `var(--on-danger)`;
  - `[data-fill="warning"]` → `var(--on-warning)`;
  - `[data-fill="scrim"]` → `var(--on-scrim)`.

  See §4.10 for when to use these.
- **Player only:**
  - keep `-webkit-tap-highlight-color: transparent`;
  - add `touch-action: manipulation` on `button`, which removes the double-tap-zoom delay now
    that pinch zoom is enabled (§4.7).

**In `@layer utilities`:** `.focus-inset:focus-visible { outline-offset: -2px; }` (§4.10).

### 4.7 `index.html` (each app)

- **`<html>`:** `<html lang="en" data-theme-key="buzzer:theme:<app>">`, with `<app>` being
  `host`, `player` or `admin`. This attribute is the **only** place each app's key is written.
  `check_theme.py` verifies that `<app>` matches the directory.
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
- **`theme-color` isn't set here.** The inline script doesn't touch `<meta name="theme-color">`,
  because CSS variables may not be loaded yet when it runs. On phones, the browser bar shows its
  default colour until the app's JavaScript runs (§4.8 step 5). This is accepted (O4).
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
   `console.error` once and **don't persist**. This prevents a silent fall back to a shared
   key.
2. **A module-level `sessionChoice`** (`'light' | 'dark' | null`, initially `null`) holds the
   explicit choice made during this page's life. `getStored()` reads `localStorage[key]` inside
   `try/catch` and returns `'light'` or `'dark'`. Any other value, a missing key or a storage
   error falls back to `sessionChoice`. So a toggle sticks for the session even when it can't
   be persisted, and the OS listener in step 9 can't override it.
3. **`resolve()`** returns `getStored()` if it isn't null; otherwise the `prefers-color-scheme:
   dark` media query decides.
4. **`getTheme()`** returns the current `data-theme` on `<html>`, validated, or `resolve()` if
   it isn't set.
5. **`apply(theme)`** does three things:
   - sets `data-theme` on `<html>`;
   - updates `<meta name="theme-color">` to `rgb(<channels of --page>)` read with
     `getComputedStyle`, creating the meta element in `<head>` if it doesn't exist;
   - notifies subscribers.
6. **`toggleTheme()`** sets `sessionChoice` to the opposite of `getTheme()`, writes it to
   storage if there is a key (inside `try/catch`), then applies it.
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
  - It always names the theme you would switch **to**:
    - currently light: `Moon` icon, `aria-label` and `title` "Switch to dark theme", visible
      label (when shown) "Dark theme";
    - currently dark: `Sun` icon, "Switch to light theme", "Light theme".

    The visible label is contained in the accessible name, as WCAG 2.5.3 requires. There is no
    `aria-pressed`, because the label states the action. Icons come from `lucide-react`, which
    all three apps already depend on.
- **Props:**
  - `className` (merged with `cn` from `../lib/utils`) is used for placement;
  - `showLabel` (default `false`).
- **Base styling.**
  - At least 44×44 px: `min-h-11 min-w-11`.
  - `rounded-lg text-fg-muted hover:text-fg hover:bg-surface-hover`.
  - Icon size 20.
- **Placement.** Each listed page or layout renders the toggle itself. Nothing matches route
  paths.

| app | rendered by | position |
|---|---|---|
| host | `HostLayout` (in `App.tsx`): covers games, questions, roster and sessions | sidebar, directly above Sign out (in the bottom section with Play), `showLabel`. `HostLayout` has no header. |
| host | `LoginPage`, `HomePage` | `fixed top-4 right-4 z-40` |
| host | `game/GameLayout` (inside the stage wrapper, in both its normal and error returns): covers lobby, question, results and game over | `fixed top-4 right-4 z-40`. The corner QR panel is bottom-right. Every stage page centres its content at `max-w-4xl` (896px, the heatmap) or narrower, so the top-right 64×64 px is empty at both 1280×720 and 1920×1080. Confirm this on the screenshots. |
| player | `JoinPage`, `NamePage`, `game/LobbyPage`, `game/FeedbackPage`, `game/ResultsPage`, `game/GameOverPage` | `fixed top-3 right-3 z-40`. Each of these pages adds `pt-16` to its root element so content can never slide under the button, including when it overflows at 360×640. |
| player | **not** `game/QuestionPage` (no mis-taps during a timed answer), `LoginPage` (the OAuth return flashes past) or the `GameLayout` error view | — |
| admin | `AdminLayout` (in `App.tsx`) | sidebar, directly above Logout, `showLabel` |
| admin | `LoginPage` | `fixed top-4 right-4` |

The player's banners (`z-50`) cover the toggle while they show.

### 4.10 Focus states

- **One global rule.** The `:focus-visible` rule (§4.6) is the only focus style. Remove every
  `focus:outline-none`, `outline-none`, `focus:ring-*`, `focus:ring-offset-*` and
  `focus:border-*` class from primitives and pages. That is 77 `focus:` uses and 20
  `outline-none` uses today. `check_theme.py` rejects `outline-none` from then on.
- **Where the outline sits.** Because of the 2px offset, the outline is drawn **outside** the
  element, on whatever surrounds it. A filled button on the page (an answer button, a `Button`)
  is outlined against the page, not its own fill. That is why `focus` is checked against the
  backgrounds that can surround an element: page, the surfaces, `surface-hover` and every
  `-soft` background.
- **Focusable elements inside a filled container.** Examples are a button on a warning banner,
  or a link on a scrim over an image. Here the outline would sit on the fill: `focus` on
  `warning` is only 1.8:1 in dark. The container gets `data-fill="<accent|success|danger|warning|scrim>"`,
  and everything inside it focuses in that fill's text colour.
  - The container itself must not be focusable. Its own outline would also switch colour, and
    `on-*` colours can vanish against a light page.
  - No current screen has this case; the rule is for future UI.
- **Clipping containers.** A control inside an `overflow-hidden` or `overflow-auto` container
  can lose the outside outline, for example a button in the first column of a scrolling admin
  table. Such a control gets the `focus-inset` class, which moves the outline inside its
  border.
  - Use `focus-inset` only on elements with a non-fill background: inputs, rows, ghost and
    outline buttons, links. Their own background is one that `focus` is checked against.
  - Never use it on filled buttons. If a filled button gets clipped, give the container padding
    instead.
- **Inputs show the outline on mouse focus too.** That is correct `:focus-visible` behaviour
  for text inputs.
- **The map canvas isn't keyboard-focusable** and pin placement is pointer-only. That stays as
  it is; it is recorded as open question O3.

### 4.11 Role mapping (raw class → token)

Map by **role in context, not by shade.** The same shade plays different roles in different
places: `bg-slate-700` is a hover in one place, a chip in another and a timer track in a third.
Work file by file and apply this table.

| today | role | token class |
|---|---|---|
| `bg-slate-900`, `bg-slate-900/90` | page background, full-screen views, the host QR panel | `bg-page`, `bg-page/90` |
| `bg-slate-800`, `bg-slate-800/60`, `/50`, `/40` | card, panel, sidebar, header, the word-cloud box | `bg-surface` (opaque; drop the `/NN`) |
| `bg-slate-800` on an `<input>`, `<select>` or `<textarea>`; nested boxes inside a card | recessed control or panel | `bg-surface-alt` (only inside a `surface`; see the rule below) |
| `bg-slate-700`, `/50`, `/30`, `bg-slate-600`, `hover:bg-slate-700`, `hover:bg-slate-600`, `hover:bg-slate-800/30` | hover, selected row, chip | `bg-surface-hover` / `hover:bg-surface-hover` |
| `bg-slate-700` / `bg-slate-800` behind a result bar, histogram column or timer | track | `bg-chart-track` |
| `border-slate-700`, `/50`, `/60` | divider, card border | `border-line` (or a bare `border`, which now defaults to `line`) |
| `border-slate-600`, `border-slate-500`, `hover:border-slate-500` | form control or outline-button border | `border-line-strong` |
| `text-slate-100`, `-200`, `-300`, `text-white` on page or surfaces, `hover:text-slate-100`/`-200`, `group-hover:text-slate-200` | primary text | `text-fg` / `hover:text-fg` |
| `text-slate-400`, `-500`, `-600`, `hover:text-slate-300` | secondary text, labels | `text-fg-muted` (this fixes today's 3.75:1 failures) |
| `placeholder-slate-400`, `placeholder:text-slate-400` | placeholder | remove; the base rule covers it |
| `text-white` on an indigo, red or green fill | text on a fill | `text-on-accent` / `text-on-danger` / `text-on-success` |
| `bg-indigo-600`, `bg-indigo-500`, `hover:bg-indigo-500` | primary action | `bg-accent hover:bg-accent-hover` |
| `text-indigo-300`, `-400`, `-700` | link, accent text | `text-accent-fg` |
| `bg-indigo-600 text-white` on the selected segment of an admin choice control: the HOST/PLAYER two-button toggle (`UserDetailPage`), and the export-format buttons (`SessionsPage`, also `border-indigo-500`) | selected state on a desktop control | `bg-accent text-on-accent` (plus `border-accent` where the control has its own border), and a **✓ before the selected label**, so selection isn't shown by colour alone. Unselected: `text-fg-muted enabled:hover:text-fg`, or `border-line-strong text-fg enabled:hover:bg-surface-hover` for bordered buttons. (`accent-soft` is not used for selection: it is 1.1–1.2:1 against the surfaces.) |
| `accent-indigo-500` | native checkbox or slider | remove; the base `accent-color` covers it |
| any `focus:*` colour or offset class, `outline-none` | focus | remove (§4.10) |
| `text-green-300`, `-400`, `-500` | success or correct text | `text-success-fg` |
| `bg-green-500` as a result bar (host `ResultsPage`, `GameOverPage`) | correct bar | `bg-chart-correct` |
| `bg-slate-600`, `bg-red-700` (wrong True/False in `GameOverPage`), `bg-indigo-500` (question with no right answer in `ResultsPage`) as a result bar; `bg-indigo-500` histogram column | neutral bar | `bg-chart-bar` |
| `bg-green-600`, `-700`, `hover:bg-green-500` as a button | success action | `bg-success text-on-success` |
| `bg-green-900`, `/50`, `/20`, `border-green-500`/`-700` | success box or badge | `bg-success-soft border-success` |
| `text-red-300`, `-400` | error text | `text-danger-fg` |
| `bg-red-500`, `-600`, `-700`, `hover:bg-red-500` as a button | destructive action | `bg-danger hover:bg-danger-hover text-on-danger` |
| `bg-red-900`, `bg-red-500/15`, `border-red-500` | error box | `bg-danger-soft border-danger` |
| `text-amber-400`, `text-amber-50` | warning text | `text-warning-fg` |
| `bg-amber-500/15`, `/10`, `border-amber-500`, `/40` | warning badge or box; the host's locked "Unlock" outline button (`border-amber-500 text-amber-400 hover:bg-amber-500/10`) | `bg-warning-soft border-warning`; for the button `border-warning text-warning-fg hover:bg-warning-soft` |
| `bg-amber-600/95` + `text-amber-50`, `bg-yellow-600/90` + `text-yellow-100` | banner (player "too late", "host disconnected") | `bg-warning text-on-warning` |
| `bg-green-500` / `bg-yellow-400` / `bg-red-500` in `TimerBar` | timer bands | `bg-timer-ok` / `bg-timer-warn` / `bg-timer-low` |
| the player's `OPTION_COLORS` entries (single-choice MC; a tap submits at once, so there is no selected state) | answer buttons | `bg-answer-N text-on-answer-N border-answer-N`. Drop the `hover:` shade (hover sticks on touch screens). Keep the strings as **full literal class names** so Tailwind can find them. |
| True/False buttons (`bg-green-600`/`bg-red-600`, `border-green-500`/`border-red-500`) | answer buttons | `answer-4` (True) and `answer-1` (False), same pattern as above |
| multi-select option, unselected (`bg-slate-700 border-slate-600 text-slate-200 hover:bg-slate-600`) | neutral option | `bg-surface border-line-strong text-fg hover:bg-surface-hover`; its check square `border-line-strong text-fg-muted`, showing the option letter |
| multi-select option, selected (`bg-indigo-600 border-indigo-400 text-white`) | selected option | `bg-accent border-on-accent text-on-accent`: the border uses the fill's text colour. Its check square is `bg-on-accent border-on-accent text-accent` and shows **✓** instead of the letter (as today), so selection is never colour-only. |
| `bg-indigo-500` / `bg-slate-600` track and `bg-white` knob of the host lobby's auto-advance switch | switch | on: `bg-accent`; off: `bg-line-strong`; knob: `bg-on-accent`. The state is also shown by the knob position. |
| `bg-white` behind `QRCodeSVG` | QR tile | `bg-qr-tile`. The QR itself keeps the library's default black on white. Never pass theme colours to it. |
| `bg-black/NN` overlays, or any text or control placed over an image (none today; future T8 prompt or option images) | scrim | `bg-scrim/70 text-on-scrim`, plus `data-fill="scrim"` if it contains focusable elements |
| `disabled:opacity-40` / `-50`, `opacity-50 cursor-not-allowed` | disabled state | standardise on `disabled:opacity-50 disabled:cursor-not-allowed` (see below) |

**Rules that go with the table:**

- **Recessed surfaces.** `surface-alt` is used only inside a `surface`. Against the page it is
  1.0:1 in dark and nearly 1:1 in light, so it doesn't read as a separate area there. A nested
  panel sitting directly on the page uses `surface`. Every form control carries a
  `border-line-strong` border. That border is what identifies the control: it is at least 3:1
  against page and surfaces, checked by the script.
- **Disabled state.** Disabled controls keep their normal tokens and add
  `disabled:opacity-50 disabled:cursor-not-allowed`, or the same classes applied conditionally
  where `disabled` isn't used (the player's answer buttons). WCAG exempts inactive controls
  from contrast, so these pairs aren't in the contrast list.
  - Don't build a separate "disabled" colour.
  - Don't show "disabled" by colour alone on a control that is actually enabled.
  - The map pin uses `map-pin-disabled`.
  - The `Button` variants' hover classes are `enabled:hover:…`, so a disabled button doesn't
    react to hover. A `className` that overrides a `Button`'s hover must also use
    `enabled:hover:`: the `:enabled` pseudo-class gives the variant rule higher specificity than
    a plain `hover:` override, which would otherwise lose.
- **Anything not covered here** (one-offs such as `text-slate-900` or `bg-slate-600` in a chip):
  choose the token by role. If no token fits, **add a token** to §4.3, `theme.css` (all three
  apps) and the config, **and add its pairs to the contrast list in `check_theme.py` and
  §4.15**. Don't use a near miss. Record the addition in this spec's revision history.
- **Badge convention for the admin and host management pages** (Restricted, Unassigned, Guests
  allowed, status chips): `rounded px-1.5 py-0.5 text-xs font-semibold`, with
  `bg-<status>-soft text-<status>-fg`, or `bg-surface-alt text-fg-muted` for neutral badges
  inside a card. Use the same badge for the same meaning everywhere:
  - Restricted → warning;
  - Unassigned → neutral;
  - Guests allowed → success;
  - live session → accent.

  Session status chips (admin `SessionsPage`): `LOBBY` and `IN_PROGRESS` → accent (both are
  live sessions), `COMPLETED` → neutral, `ABANDONED` → danger. The common case stays quiet,
  so live and abandoned sessions stand out.

### 4.12 Per-app notes

**Host**

- **Stage wrapper.** In `pages/game/GameLayout.tsx`, wrap **both** return paths in
  `<div data-stage className="contents">`: the normal path (`<Outlet/>`, the QR panel and the
  toggle) and the full-screen error view.
  - `GameLayout` currently returns a context provider, which has no DOM element. With
    `display: contents` the wrapper adds no box, so `min-h-screen`, flex and fixed positioning
    behave exactly as today.
- **Readability on stage screens** (lobby, question, results, game over):
  - **Body text.** Student-facing body text (prompt, options, counts, word-cloud words,
    "N / M answered", captions such as "Participation — full credit for answering") is at least
    `text-lg`.
  - **Labels.** Short uppercase labels that name a value shown right next to them may be
    `text-sm`, but no smaller. This covers the QR panel's "Room Code", the GameOver stat labels,
    the histogram bucket labels and axis caption, and the question metadata line above the
    prompt. The values those labels name are at least `text-2xl`.
  - **Changes this implies:**
    - QR-panel label `text-[10px]` → `text-sm`;
    - corner room code `text-lg` → `text-2xl`;
    - histogram counts `text-sm` → `text-lg`;
    - GameOver stat labels and bucket labels `text-xs` → `text-sm`;
    - result-bar counts and "✓ Correct" (`text-sm`) → `text-lg`;
    - "N / M answered" `text-sm` → `text-lg`.
  - **Colour.** Student-facing content uses `text-fg`, never `fg-muted`. Muted is for labels
    only.
  - **Never make anything smaller than it is today.**
  - **Proxy check:** a 1920×1080 screenshot scaled down to 480px wide must still have a
    readable prompt, option labels, counts and room code. Do this in both themes.
- **Result bars (`ResultsPage` `AnswerBarChart`).** The count moves **out of the bar**. Each row
  becomes, in order:
  1. option label (`text-fg`, `text-xl font-bold`);
  2. track `bg-chart-track` holding the bar, which is `bg-chart-correct` for correct options
     and `bg-chart-bar` otherwise. The bar contains no text.
  3. the count (`text-fg text-lg font-bold tabular-nums`, fixed width, shown even when it is 0);
  4. "✓ Correct" (`text-success-fg text-lg font-semibold`) on correct rows.

  The bar's minimum visible width stays as it is today.
- **GameOver answer bars** already put the label and count beside the bar. Correct bars use
  `bg-chart-correct`, all others `bg-chart-bar`, including wrong True/False, which is red-700
  today. The ✓ glyph stays and becomes `text-success-fg text-sm` or larger. **Histogram:**
  columns `bg-chart-bar`, track `bg-chart-track`; the counts above the columns stay outside
  them.
- **Management area** (`HostLayout`, `manage/*`, HomePage, LoginPage) uses the normal token
  values. `manage/QuestionEditorPage.tsx` is swept in step with the admin copy (same role
  choices for the same markup).

**Player**

- **Thumb-friendliness.** Answer buttons stay full-width, and their sizes and spacing don't
  change. Every new tappable element is at least 44×44 px.
- **Multiple choice and True/False** submit on tap and have no selected state. Multi-select
  options toggle and are styled as in §4.11.
- **Banners** (host disconnected, "too late") use `bg-warning text-on-warning`. Neither contains
  a focusable element today. If one ever does, add `data-fill="warning"`.
- **The map** is covered in §4.13. The map-pin Confirm button is a primary action (`accent`).

**Admin**

- **Density.** Keep it: don't change padding, font sizes or table layout.
- **Table header rows:** `bg-surface-alt text-fg-muted`. **Row dividers:** `line`. **Row
  hover:** `surface-hover`. Controls inside scrolling tables get `focus-inset` (§4.10).
- **Native controls.** Raw `<select>`, `<textarea>` and checkboxes get `bg-surface-alt
  border-line-strong text-fg`. `color-scheme` (§4.4) makes their drop-down lists follow the
  theme.
- **The sidebar** (here and in the host's `HostLayout`) is `bg-surface border-r border-line`.
  The active link is `bg-accent text-on-accent`, as it is today; `accent-soft` would be 1.1:1
  against the sidebar in dark.

### 4.13 Canvas and map code

- **`lib/mapPin.ts`** (byte-identical ×3) gets one helper,
  `mapColor(name: 'full' | 'full-fill' | 'zero' | 'pin' | 'pin-disabled' | 'heat' | 'outline', alpha = 1)`:
  - It reads `getComputedStyle(document.documentElement).getPropertyValue('--map-' + name)`,
    trims it, and **caches it per name** in a module-level map. The `--map-*` tokens are
    invariant, so the cache never goes stale. The heatmap calls the helper once per dot, so
    without the cache that would be one style lookup per dot.
  - It returns `rgb(<channels> / <alpha>)`.
  - If the value is empty (only possible if `theme.css` wasn't imported, which would visibly
    break the whole app), it logs `console.error` once for that name, returns `'transparent'`,
    and doesn't cache, so the next call retries.

  Replace each literal with a call: the zero circle is `mapColor('zero', 0.95)`, the full-credit
  fill is `('full-fill', 0.25)`, the full-credit stroke and target dot are `('full')`. The
  three `'white'` literals (the target dot's outline in `drawTarget`, and the pin's outline and
  inner dot in `drawPin`) become `mapColor('outline')`. The default colour of `drawPin`
  becomes `mapColor('pin')`, resolved inside the function and not as a default-parameter
  literal.
- **`player/src/components/MapPinCanvas.tsx`:** the disabled pin uses
  `mapColor('pin-disabled')`.
- **`host/src/components/MapPinHeatmap.tsx`:** dots use `mapColor('heat', 0.55)`.
- **`components/MapCanvas.tsx`** (byte-identical ×3): only its surrounding elements change.
  - The canvas background (letterbox) becomes `bg-surface-alt`. The canvas always sits inside a
    card or panel; if it is ever placed directly on the page, use `bg-surface`.
  - "Loading map…" becomes `text-fg-muted`.
  - "Couldn't load the map" becomes `text-danger-fg`.
  - Retry becomes `border-line-strong text-fg hover:bg-surface-hover`.

  The map image and overlays are unchanged.

### 4.14 Non-colour cues

Each place where colour alone says "correct", "wrong", "selected" or "time running out" must
also carry text, a glyph or position.

| place | today | change |
|---|---|---|
| host `ResultsPage` bar chart | "✓ Correct" label on correct bars | keep it, beside the bar (§4.12) |
| host `ResultsPage` word cloud | accepted words are only coloured green | accepted words: "✓ " prefix, `font-bold`, `text-success-fg`; other words: `text-fg`, their current weight. The "Correct answer: …" line above stays. |
| host `GameOverPage` breakdown | ✓ on correct rows | none |
| player `ResultsPage` | "Correct!" / "Incorrect" text; map labels "Within target" / "Partial credit" / "Too far" | none |
| player `GameOverPage` recap | audit during the sweep | if correctness is shown by colour only, add ✓ / ✗ |
| player multi-select | selected options show ✓ in place of the letter | none (§4.11) |
| host lobby auto-advance switch | knob position | none |
| admin HOST/PLAYER toggle, export-format buttons | accent fill on the selected segment | add "✓ " before the selected label (§4.11) |
| `TimerBar` (both) | bar width plus "Ns" label | none. The "Ns" label is the main signal and uses `text-fg-muted` (the stage value on the host). The bands are also checked at 3:1 against the track (§4.15), so the bar is readable without the label. |

### 4.15 `scripts/check_theme.py` (new) — a manual gate

The script uses only the Python standard library. It runs from the repo root and exits non-zero
on any failure. Each failure prints `path:line: message`.

- **Usage:** `python scripts/check_theme.py [--app host|player|admin] [--check
  colors|contrast|identical]`.
- **Defaults:** with no flags it runs every check on every app. The flags narrow it while
  sweeping.

**Where it runs.** It is **not** in CI, and `.gitlab-ci.yml` must stay unmodified. It is a
manual gate:

- the root `CLAUDE.md` lists it under Scripts as "run before any MR that touches `frontend/`";
- a new MR template, `.gitlab/merge_request_templates/Default.md`, has a checklist item
  "`python scripts/check_theme.py` passes (frontend changes only)";
- the author runs it, and the reviewer ticks it.

Nothing enforces it automatically. That matters most after the palette is replaced, when a raw
class compiles to nothing without any error.

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
- **`dark:` variants.** `dark:` at the start of a class (after whitespace, a quote or a
  backtick).
- **Hex literals:** `#` followed by 3, 6 or 8 hex digits at a word boundary. It must not be
  preceded by `&` or a word character, so HTML entities such as `&#215;` don't match.
- **Numeric colour functions:** `rgb(`, `rgba(`, `hsl(` or `hsla(` followed by a digit. The
  `mapColor` template and `rgb(var(--…))` don't match.
- **Named CSS colours:** any quoted string whose whole content is a common CSS colour name,
  case-insensitive. The names are `white`, `black`, `red`, `green`, `blue`, `yellow`, `orange`,
  `purple`, `pink`, `gray`, `grey`, `silver`, `navy`, `teal`, `maroon`, `lime`, `aqua`,
  `fuchsia`, `olive`, `cyan` and `magenta`. This catches `fill="black"`, `fillStyle = 'white'`
  and `style={{ color: 'red' }}`. `transparent`, `currentColor` and `none` are allowed.
- **`outline-none`.**
- **Escape hatch.** A line containing `theme-check: ignore` is skipped. Every use must say why
  in the same comment. There should be close to zero.

**Check 2: contrast.** For each app, parse `theme.css` using the selectors in §4.4. Then, for
each theme (and, for the host, the stage blocks merged over it), compute the WCAG 2.1 contrast
ratio for these pairs.

**Text, at least 4.5:1:**

- `fg`, `fg-muted`, `accent-fg`, `success-fg`, `danger-fg` and `warning-fg` on `page`,
  `surface` and `surface-alt`;
- `fg` and `fg-muted` on `surface-hover`;
- `accent-fg` on `accent-soft`, `success-fg` on `success-soft`, `danger-fg` on `danger-soft`,
  `warning-fg` on `warning-soft`;
- `on-accent` on `accent` and `accent-hover`; `accent` on `on-accent` (the ✓ in the selected
  multi-select square);
- `on-danger` on `danger` and `danger-hover`; `on-success` on `success`; `on-warning` on
  `warning`;
- `on-answer-N` on `answer-N` for N = 1–8;
- `on-scrim` on `scrim` blended at 0.70 over pure white (the worst-case image).

**Host stage, at least 7:1:** **every** text pair above that can appear on host screens, with
the stage values. That means all of them except the `on-answer-N` pairs: the host never renders
answer colours (§4.0).

**Non-text, at least 3:1:**

- `focus` against `page`, `surface`, `surface-alt`, `surface-hover`, `accent-soft`,
  `success-soft`, `danger-soft` and `warning-soft`;
- focus inside a filled container (§4.10): `on-accent` vs `accent`, `on-success` vs
  `success`, `on-danger` vs `danger`, `on-warning` vs `warning`, and `on-scrim` vs the 0.70
  scrim over white;
- `line-strong` against `page`, `surface` and `surface-alt`;
- `chart-bar` and `chart-correct` against `chart-track`;
- `timer-ok`, `timer-warn` and `timer-low` against `chart-track`.

The output is a table of every pair, with failures marked. **Any token added later must add its
pairs here** (§4.11).

**Check 3: identical.**

- Every app defines exactly the same set of token names. The host stage blocks override exactly
  the ten tokens in §4.3 and no others.
- The invariant, dark and light values are identical across the three apps.
- Blocks 2 and 3 each contain their `color-scheme` declaration.
- The byte-identical groups in §4.0 have one md5 each.
- Each `frontend/<app>/index.html` has `data-theme-key="buzzer:theme:<app>"` with the matching
  `<app>`.
- No `frontend/*/tailwind.config.js` or `frontend/*/vite.config.js` exists (§4.2).

**While sweeping**, run `--check colors --app <app>`. From §4.18 step 6 on, the whole script
must pass.

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

**Data and procedure (one game, one room).**
`sample_games/madineni_us_geography_classroom.json` contains every question type: map pin
(×2), multiple choice (one ACCURACY, one COMPLETENESS), fill-in-the-blank, multi-select and
True/False. One room therefore produces every screen.

1. **Admin login.** Use `ADMIN_USERNAME` / `ADMIN_PASSWORD` from your `.env`. The backend
   creates this account on first start (see `README.md`). Log in to the admin app with it, and
   import the geography game on the Games page into a course.
2. **Host.** Log in to the host app with the same account (ADMIN can host any course), pick the
   course and game, and create a room.
3. **Simulated players.** With the Python venv active (`scripts/simulate_players.py` needs
   `httpx`; see `README.md`), run:

   `python scripts/simulate_players.py --room <CODE> --players 20 --game-json sample_games/madineni_us_geography_classroom.json`

   These flags exist. The simulator answers map-pin questions as well (commit `9276c43`), so
   the bar chart, word cloud and heatmap have data.
4. **Your player.** Join once from a 390×844 browser window as a guest.
5. **Capture as you go.** Advance through the game, taking each screen as its question type
   comes up. The management and admin screens can be taken before or after the game.

| app | screens (`<screen>` names) |
|---|---|
| host | `login`, `home`, `manage-question-editor` (map-pin question open, with the image and target placed), `lobby`, `question`, `results-bars` (ACCURACY multiple choice), `results-wordcloud`, `results-heatmap`, `gameover` |
| player | `join` (`NamePage`, "Join Room …", which is what the before image shows), `question-mc`, `question-multi` (one option selected), `question-map`, `results-map`, `gameover` |
| admin | `users`, `access`, `question-editor-map`, `sessions-export` (export panel open) |

That is 19 screens, so 38 "after" images. There are 17 "before" images: `host-results-wordcloud`
and `player-question-multi` were added to this list after the "before" set was taken, and they
have **no before image**. They need only the two "after" images, and their `docs/ui/README.md`
rows show "—" in the before column.

**Before-image size.** The committed "before" images were captured from a laptop browser window
(about 1400×680 CSS px at 2×), not at the viewports above; the player ones are desktop-width.
The "after" images are still taken at the viewports above, and `docs/ui/README.md` says in one
line that the before set is at a different size, so the pairs compare colour and design, not
layout at the target size.

### 4.17 T8 and later code

At the time of writing, the only image surfaces in the source (on `main` and this branch) are
the ones T7 delivered:

- image upload in both question editors;
- the map canvas in all three apps.

Any further T8 UI, such as image management or delete, or prompt and option images, is written
against tokens from the start:

- text or controls over an image use the scrim (§4.11);
- the UI must pass `scripts/check_theme.py` before it merges, as an MR-checklist item (§4.15).

If such UI merges between §4.18 steps 5 and 6, sweep it as part of step 5.

### 4.18 Implementation order

0. "Before" screenshots (§4.1, §4.16). Commit them.
1. Stale build output fix (§4.2). Verify it.
2. `scripts/check_theme.py` (§4.15), the MR template
   (`.gitlab/merge_request_templates/Default.md`), and the root `CLAUDE.md` Scripts entry. The
   script will report hundreds of colour failures; that is expected. Contrast and identical
   checks run once `theme.css` exists.
3. Token layer, per app:
   - `theme.css` (§4.4) and its import in `main.tsx`;
   - `tailwind.config.ts` with the tokens under `extend` (§4.5);
   - `index.css` (§4.6), including the `data-fill` rules, `.focus-inset` and the player's
     `touch-action`;
   - `index.html` (§4.7), including the player viewport change;
   - `lib/theme.ts` (§4.8) and the `initTheme()` call;
   - `ThemeToggle` (§4.9) and its placement on the pages and layouts listed there.

   Then run `--check contrast` and `--check identical`, which must pass. The apps should look
   almost unchanged in dark mode at this point.
4. Primitives:
   - `components/ui/*` in each app; host and admin stay identical;
   - `TimerBar`, using the timer tokens;
   - the `MapCanvas` chrome and `mapPin.ts` `mapColor`, copied to all three apps (§4.13);
   - `MapPinCanvas` and `MapPinHeatmap`;
   - removal of focus classes from primitives (§4.10).
5. Sweep host (including the stage wrapper in `GameLayout`), then player, then admin, page by
   page, using §4.11. Run `--check colors --app <app>` until it is clean. Sweep the two
   `QuestionEditorPage`s together.
6. Move the tokens from `extend.colors` to `colors` (§4.5) and rebuild. Click through every
   page in both themes looking for unstyled elements, which would be raw classes the regex
   missed, for example ones built from template strings. The full `check_theme.py` must pass.
7. Context-fit work:
   - host stage readability and the result-bar layout (§4.12);
   - non-colour cues (§4.14);
   - badge convention (§4.11);
   - `focus-inset` on controls in scrolling admin tables (§4.10).
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
- [ ] **Session choice without storage.** In a private window where storage writes fail, a
  toggle still holds for the session when the OS setting changes.
- [ ] **Keys are separate.** Behind nginx, on one browser, toggling admin doesn't change host or
  player. `localStorage` shows three separate `buzzer:theme:*` keys.
- [ ] **Tabs stay in step.** With two host tabs open, toggling one updates the other.
- [ ] **Logging out keeps the theme.** The player's "Play Again" and every logout remove the
  login token but not the theme key.
- [ ] **Labels.** The visible toggle label and the `aria-label` both name the theme you would
  switch to.
- [ ] **Placement.** The player toggle is absent on the question screen and present on join,
  name, lobby, feedback, results and game over, with nothing underneath it at 360×640. The host
  toggle doesn't overlap the QR panel or any stage content at 1280×720 or 1920×1080. Exactly
  one toggle shows on every host and admin page.

**Accessibility**

- [ ] **Keyboard focus.** Tabbing through each page shows a visible outline on every button,
  link, input, select, checkbox and slider, in both themes. Nothing is clipped in scrolling
  admin tables. Clicking or tapping a button shows no outline.
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

- [ ] **Host readability.** The stage proxy check passes in both themes (§4.12), and no text is
  drawn inside a result bar. If you have access to the real classroom projector, test there too
  (O1).
- [ ] **Scripts.** `python scripts/check_theme.py` passes, and every `md5` group is a single
  hash.
- [ ] **CI and build.** `.gitlab-ci.yml` is unchanged (`git diff main -- .gitlab-ci.yml` is
  empty). `npm run build` succeeds for all three apps.

### 4.20 Context hierarchy updates

Per `.claude/rules/context-sync.md`, update:

| file | what to change |
|---|---|
| `frontend/CLAUDE.md` | A theme-system section covering: tokens in `theme.css`, `data-theme` / `data-theme-key`, per-app keys, the new byte-identical groups, `check_theme.py` as a manual gate (not in CI), the stale build output gotcha (now fixed) and how to verify it. |
| `frontend/*/src/CLAUDE.md` | `index.css` is no longer "dark-slate body styles": it now holds the token-based base rules, `data-fill` and `.focus-inset`. Add `theme.css`; add `buzzer:theme:<app>` to the localStorage list; the inline script in `index.html`. Player: the viewport change. |
| `frontend/*/src/components/CLAUDE.md` | Replace "styled for the dark slate theme" with tokens. Add `ThemeToggle`. Focus comes from the global `:focus-visible` rule. Map chrome tokens. Timer tokens. |
| `frontend/*/src/lib/CLAUDE.md` | `theme.ts`, including the session choice; `mapPin.ts`'s cached `mapColor` and the invariant `--map-*` tokens. |
| `frontend/host/src/pages/CLAUDE.md` | The `data-stage` wrapper in `GameLayout` and what it overrides; no text inside result bars; which pages render the toggle. |
| `frontend/player/src/pages/CLAUDE.md` | Which pages render the toggle (not `QuestionPage`); the answer-colour tokens; multi-select selected state. |
| `frontend/admin/src/pages/CLAUDE.md` | The badge convention; `focus-inset` in scrolling tables. |
| `CLAUDE.md` (root) | `python scripts/check_theme.py` under Scripts, marked as a manual pre-MR gate. |

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
  `src/pages/game/GameLayout.tsx` (stage wrapper and toggle).
- **Player:** `src/components/ui/TimerBar.tsx`, `src/components/MapPinCanvas.tsx`.
- **Admin:** `src/components/MoveGamePanel.tsx`.

**Repository files:**

- `scripts/check_theme.py` (new);
- `.gitlab/merge_request_templates/Default.md` (new; `.gitlab-ci.yml` is **not** touched);
- `docs/ui/**` (new);
- the context files in §4.20.

## 5. Open questions

- **O1 — Real projector.** The 7:1 stage target and the scaled-screenshot proxy are
  monitor-based. Projectors in lit rooms crush dark greys and wash out light themes. Test on the
  actual classroom projector if possible, and record the result in `docs/ui/README.md`.
- **O2 — Light-theme answer buttons against the page. Resolved: no change.** Yellow and orange
  fills are about 1.5:1 against the light page, so the button edge is faint. Under WCAG 1.4.11,
  a button whose own text identifies it doesn't need a 3:1 boundary. Each answer button carries
  its option letter and text at 4.5:1 or better. No extra border is added; the button border is
  always `border-answer-N`. The earlier fallback (`border-line-strong`) would have clashed with
  the answer and selected borders, so it is dropped.
- **O3 — Keyboard access to the map canvas.** Pin placement is pointer-only. That is out of
  scope for T9; record it as a known limitation in the T10 write-up.
- **O4 — `theme-color` before JavaScript. Accepted.** On phones the browser bar shows its
  default colour until `lib/theme.ts` runs, which takes milliseconds after load. Fixing it would
  mean putting hex values in `index.html` and checking that they match `theme.css`. That's not
  worth it for a cosmetic browser-bar colour that has no contrast impact.

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
- 2026-10-05 — Goldfish-test revision.

  **User decisions:**

  - **#1 Enforcement:** `check_theme.py` is a documented manual gate (root `CLAUDE.md` plus an
    MR template checklist). `.gitlab-ci.yml` stays unmodified. The spec no longer claims the
    script "fails the build".
  - **#2/#3 Text on fills:** no text inside chart bars; counts and labels move beside them.
    Student-facing text on a fill on host stage screens must reach 7:1. After checking what the
    host renders, stage overrides were added for `accent`, `accent-hover`, `success`, `danger`
    and `danger-hover` (ten overrides in total), and all `on-*` pairs are checked at 7:1 on
    stage.
  - **#4 Selected answer:** the selected border uses the fill's text colour, and selection
    shows ✓. In source, the only selected state is the multi-select option, which is drawn on
    `accent`, not on `answer-N`. So the rule is applied as `border-on-accent`, and the existing
    ✓ check square is kept. The earlier role-table row ("`border-white` = selected answer
    outline") was wrong and is replaced.
  - **#5 Toggle label:** the visible label names the theme you would switch to, matching the
    `aria-label`.
  - **#11 Overlays and disabled states:** invariant `scrim` and `on-scrim` tokens, a rule of 70%
    or darker for text over images, and disabled-state guidance.

  **Other fixes:**

  - **Timer:** dedicated `timer-ok`, `timer-warn` and `timer-low` tokens, checked at 3:1
    against the track.
  - **Focus:** checked against `surface-hover` and every `-soft` background; `data-fill` rules
    for focusable elements inside fills; `focus-inset` for clipping containers.
  - **Host toggle placement:** each page or layout renders its own toggle, with no path
    matching. The player pages that show the toggle all get `pt-16`.
  - **`theme.css` format:** the `color-scheme` contradiction in §4.4 is resolved.
  - **Stage readability:** the label-size rule and its list of concrete size changes.
  - **Stage wrapper:** a `display: contents` wrapper, because `GameLayout` has no DOM root
    element.
  - **`lib/theme.ts`:** a session choice for when the key or storage is missing.
  - **`mapColor`:** caches its values and handles an empty value.
  - **`check_theme.py`:** now rejects `dark:` variants and named CSS colours, ignores HTML
    entities, and checks that `data-theme-key` matches its app. New tokens must add their
    contrast pairs.
  - **`surface-alt`** is used only inside a `surface`.
  - **Word cloud:** the colour and weight of non-accepted words.
  - **O2** is resolved (no change), and **O4** is added.
  - **Pink:** the reason it moved one shade darker.
  - **Screenshots:** one game and one room (the geography game has every type), where the admin
    login comes from, the verified simulator flags, and two added screens
    (`results-wordcloud`, `question-multi`).
  - **Facts:** a "verified facts" list in §4.0.
  - **Cross-references:** the pinch-zoom reference now points to §4.7, and step 7 no longer
    repeats step 3.
  - **Values:** all new pairs were computed from the stated values and pass.
- 2026-10-05 — Implementation: the "before" set (step 0) was taken before the goldfish revision
  added `host-results-wordcloud` and `player-question-multi`. Those two screens get "after"
  images only (§4.16); 17 "before" images, 38 "after".
- 2026-10-05 — Implementation review before step 3. **User decisions:**
  - **`map-outline` token added.** `mapPin.ts` draws the target dot's outline, the pin's
    outline and the pin's inner dot in `'white'` (9 literals across the three copies), which no
    token covered and which §4.15's named-colour check rejects. The new invariant token is
    `map-outline` (`#ffffff`), and `mapColor` gains `'outline'` (§4.3, §4.13). Like the other
    map tokens it is drawn on the image, so it has no contrast pairs. The escape hatch was
    rejected: it would have meant 9 ignored lines.
  - **Host toggle placement.** `HostLayout` has no header; Sign out is at the bottom of its
    sidebar. The toggle goes in the sidebar directly above Sign out (§4.9), as in the admin
    app. A fixed top-right toggle was rejected because management pages scroll inside an
    `overflow-auto` `<main>` with their own top-right actions.
  - **Session status chips.** `LOBBY` and `IN_PROGRESS` → accent, `COMPLETED` → neutral,
    `ABANDONED` → danger (§4.11 badge convention).
- 2026-10-05 — Implementation review after step 3:
  - **`ringColor.DEFAULT` uses Tailwind's function form** (§4.5). Written as the
    `<alpha-value>` string, the setting was silently ignored and the default ring stayed blue,
    because Tailwind's ring default goes through `withAlphaValue()`. The function form gives
    `rgb(var(--focus) / 0.5)`; it needs a cast because Tailwind's types omit it.
  - **Screenshots (user decision).** The "before" set turned out to be laptop-window captures,
    not taken at §4.16's viewports, and `player-join` shows `NamePage`. The "after" images stay at
    the spec viewports, `docs/ui/README.md` notes the size mismatch, and the `player-join`
    "after" image shows `NamePage` to match (§4.16).
- 2026-10-05 — Implementation review after step 4 (user decision): the `Button` variants'
  hover classes become `enabled:hover:…`. Replacing `disabled:pointer-events-none` with the
  standard `disabled:cursor-not-allowed` had made disabled buttons react to hover. Hover
  overrides passed to a `Button` must use `enabled:hover:` too (§4.11, disabled state).
- 2026-10-05 — Implementation review during step 5 (user decision): the §4.11 row for
  selected admin controls described the HOST/PLAYER toggle as `bg-indigo-900` (it is
  `bg-indigo-600 text-white`) and mapped it to `accent-soft`, which is 1.1–1.2:1 against the
  surfaces in both themes, so the selected segment would barely show. Selected segments are now
  `bg-accent text-on-accent` with a ✓ before the label (§4.11, §4.14); the accent fill alone is
  2.3–2.8:1 against dark surfaces, so the ✓ carries the state. Both sidebars' active link also
  uses the accent fill (§4.12).
