#!/usr/bin/env python3
"""
Theme gate for the three frontends (T9, docs/plans/t9-theming.md §4.15).

A manual pre-MR gate: it is NOT run in CI. Run it before any MR that touches frontend/.
Once the Tailwind palette is replaced by the tokens, a leftover raw class such as
bg-slate-800 compiles to no CSS and no error, so this script is the only automated catch.

Usage (from anywhere; paths are resolved from the repo root):
    python scripts/check_theme.py [--app host|player|admin] [--check colors|contrast|identical]

Both flags may be repeated. With no flags every check runs on every app.

Checks:
    colors     raw palette classes, dark: variants, hex / rgb() / hsl() literals, quoted CSS
               colour names and outline-none in frontend/<app>/src/**/*.{ts,tsx,css}
               (src/theme.css excluded). A line containing "theme-check: ignore" is
               skipped; say why in the same comment.
    contrast   WCAG 2.1 contrast of a fixed list of token pairs in each theme.css, per theme
               (and, for the host, with the [data-stage] overrides merged in).
    identical  token names and values agree across apps, byte-identical files have one md5,
               index.html declares the app's own data-theme-key, no stale config .js files.

Exits non-zero on any failure. Each failure is printed as "path:line: message".
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
APPS = ("host", "player", "admin")

# ── Check 1: colours ─────────────────────────────────────────────────────────

PALETTE = (
    "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|"
    "cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black"
)
PREFIXES = (
    "bg|text|border(?:-[xytrblse])?|ring-offset|ring|outline|divide|fill|stroke|"
    "from|via|to|accent|caret|decoration|placeholder|shadow"
)
VARIANTS = r"(?:[\w-]+:)*"
RAW_CLASS = re.compile(
    rf"(?<![\w-]){VARIANTS}!?(?:{PREFIXES})-(?:{PALETTE})"
    rf"(?:-\d{{2,3}})?(?:/(?:[\d.]+|\[[^\]\s]*\]))?(?![\w-])"
)
DARK_VARIANT = re.compile(rf"(?:^|(?<=[\s'\"`])){VARIANTS}dark:(?=[\w!\[-])")
HEX_LITERAL = re.compile(
    r"(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b"
)
COLOR_FUNCTION = re.compile(r"\b(?:rgba?|hsla?)\(\s*\d")
NAMED_COLOR = re.compile(
    r"(['\"`])(?:white|black|red|green|blue|yellow|orange|purple|pink|gray|grey|"
    r"silver|navy|teal|maroon|lime|aqua|fuchsia|olive|cyan|magenta)\1",
    re.IGNORECASE,
)
OUTLINE_NONE = re.compile(rf"(?<![\w-]){VARIANTS}outline-none(?![\w-])")
IGNORE_MARKER = "theme-check: ignore"

COLOR_RULES = (
    (RAW_CLASS, "raw palette class"),
    (DARK_VARIANT, "dark: variant (themes come from data-theme, not dark:)"),
    (HEX_LITERAL, "hex colour literal"),
    (COLOR_FUNCTION, "numeric colour function"),
    (NAMED_COLOR, "named CSS colour"),
    (OUTLINE_NONE, "outline-none (focus comes from the global :focus-visible rule)"),
)
SCANNED_SUFFIXES = {".ts", ".tsx", ".css"}

# ── Check 2: contrast ────────────────────────────────────────────────────────

# theme.css blocks, in order (§4.4). Selectors are compared after collapsing whitespace.
SEL_INVARIANT = ":root"
SEL_DARK = ':root, :root[data-theme="dark"]'
SEL_LIGHT = ':root[data-theme="light"]'
SEL_STAGE_DARK = ':root [data-stage], :root[data-theme="dark"] [data-stage]'
SEL_STAGE_LIGHT = ':root[data-theme="light"] [data-stage]'
BASE_SELECTORS = (SEL_INVARIANT, SEL_DARK, SEL_LIGHT)
HOST_SELECTORS = BASE_SELECTORS + (SEL_STAGE_DARK, SEL_STAGE_LIGHT)
COLOR_SCHEME = {SEL_DARK: "dark", SEL_LIGHT: "light"}

# The host stage overrides exactly these tokens (§4.3).
STAGE_TOKENS = {
    "fg-muted",
    "accent-fg",
    "success-fg",
    "danger-fg",
    "warning-fg",
    "accent",
    "accent-hover",
    "success",
    "danger",
    "danger-hover",
}

# Background for text on a scrim: the scrim at 70% over a pure-white image (worst case).
SCRIM = "scrim@70%/white"
SCRIM_ALPHA = 0.70

TEXT_MIN = 4.5
STAGE_TEXT_MIN = 7.0
NON_TEXT_MIN = 3.0

SURFACES = ("page", "surface", "surface-alt")
SOFT = ("accent-soft", "success-soft", "danger-soft", "warning-soft")


@dataclass(frozen=True)
class Pair:
    fg: str
    bg: str
    kind: str  # "text" or "non-text"
    on_stage: bool = True  # also checked at 7:1 on the host stage (text pairs)
    note: str = ""

    @property
    def label(self) -> str:
        joiner = "on" if self.kind == "text" else "vs"
        return f"{self.fg} {joiner} {self.bg}" + (
            f" ({self.note})" if self.note else ""
        )


# Adding a token means adding its pairs here and in §4.15 of the spec.
PAIRS = (
    *(
        Pair(fg, bg, "text")
        for fg in (
            "fg",
            "fg-muted",
            "accent-fg",
            "success-fg",
            "danger-fg",
            "warning-fg",
        )
        for bg in SURFACES
    ),
    Pair("fg", "surface-hover", "text"),
    Pair("fg-muted", "surface-hover", "text"),
    Pair("accent-fg", "accent-soft", "text"),
    Pair("success-fg", "success-soft", "text"),
    Pair("danger-fg", "danger-soft", "text"),
    Pair("warning-fg", "warning-soft", "text"),
    Pair("on-accent", "accent", "text"),
    Pair("on-accent", "accent-hover", "text"),
    Pair("accent", "on-accent", "text", note="multi-select check"),
    Pair("on-danger", "danger", "text"),
    Pair("on-danger", "danger-hover", "text"),
    Pair("on-success", "success", "text"),
    Pair("on-warning", "warning", "text"),
    *(
        Pair(f"on-answer-{n}", f"answer-{n}", "text", on_stage=False)
        for n in range(1, 9)
    ),
    Pair("on-scrim", SCRIM, "text"),
    *(Pair("focus", bg, "non-text") for bg in (*SURFACES, "surface-hover", *SOFT)),
    Pair("on-accent", "accent", "non-text", note="data-fill focus"),
    Pair("on-success", "success", "non-text", note="data-fill focus"),
    Pair("on-danger", "danger", "non-text", note="data-fill focus"),
    Pair("on-warning", "warning", "non-text", note="data-fill focus"),
    Pair("on-scrim", SCRIM, "non-text", note="data-fill focus"),
    *(Pair("line-strong", bg, "non-text") for bg in SURFACES),
    Pair("chart-bar", "chart-track", "non-text"),
    Pair("chart-correct", "chart-track", "non-text"),
    Pair("timer-ok", "chart-track", "non-text"),
    Pair("timer-warn", "chart-track", "non-text"),
    Pair("timer-low", "chart-track", "non-text"),
)

# ── Check 3: identical ───────────────────────────────────────────────────────

IDENTICAL_GROUPS = (
    (APPS, "tailwind.config.ts"),
    (APPS, "src/lib/theme.ts"),
    (APPS, "src/components/ThemeToggle.tsx"),
    (APPS, "src/lib/mapPin.ts"),
    (APPS, "src/lib/slider.ts"),
    (APPS, "src/components/MapCanvas.tsx"),
    (APPS, "src/lib/images.ts"),
    (APPS, "src/components/AuthImage.tsx"),
    (("host", "admin"), "src/components/ImagePicker.tsx"),
    (("player", "admin"), "src/theme.css"),
    (("host", "admin"), "src/components/ui/button.tsx"),
    (("host", "admin"), "src/components/ui/card.tsx"),
    (("host", "admin"), "src/components/ui/input.tsx"),
)
STALE_CONFIGS = ("tailwind.config.js", "vite.config.js")
THEME_KEY_ATTR = re.compile(r'<html\b[^>]*\bdata-theme-key="([^"]*)"')
THEME_KEY_PREFIX = "buzzer:theme:"


# ── Shared plumbing ──────────────────────────────────────────────────────────


class Report:
    def __init__(self) -> None:
        self.failures: dict[str, list[str]] = {}
        self._seen: set[str] = set()

    def fail(self, check: str, path: Path, line: int, message: str) -> None:
        text = f"{rel(path)}:{line}: {message}"
        if text in self._seen:
            return
        self._seen.add(text)
        self.failures.setdefault(check, []).append(text)
        print(text)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def theme_css_path(app: str) -> Path:
    return FRONTEND / app / "src" / "theme.css"


# ── Check 1 ──────────────────────────────────────────────────────────────────


def check_colors(apps: list[str], report: Report) -> None:
    for app in apps:
        src = FRONTEND / app / "src"
        excluded = theme_css_path(app)
        for path in sorted(src.rglob("*")):
            if path.suffix not in SCANNED_SUFFIXES or path == excluded:
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if IGNORE_MARKER in line:
                    continue
                for pattern, what in COLOR_RULES:
                    for match in pattern.finditer(line):
                        report.fail(
                            "colors", path, lineno, f"{what}: {match.group(0)!r}"
                        )


# ── theme.css parsing ────────────────────────────────────────────────────────

RGB = tuple[float, float, float]


@dataclass
class Block:
    selector: str
    line: int
    tokens: dict[str, tuple[RGB, int]] = field(default_factory=dict)
    color_schemes: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class ThemeFile:
    path: Path
    text: str
    blocks: dict[str, Block]

    def context(self, *selectors: str) -> dict[str, tuple[RGB, int]]:
        merged: dict[str, tuple[RGB, int]] = {}
        for selector in selectors:
            merged.update(self.blocks[selector].tokens)
        return merged


BLOCK_RE = re.compile(r"([^{}]*)\{([^{}]*)\}")
TOKEN_DECL = re.compile(r"--([a-z][a-z0-9-]*)\s*:\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})")
SCHEME_DECL = re.compile(r"color-scheme\s*:\s*([a-z]+)")

_theme_cache: dict[str, ThemeFile | None] = {}


def load_theme(app: str, check: str, report: Report) -> ThemeFile | None:
    """Parse frontend/<app>/src/theme.css once; format errors go to the first `check`."""
    if app not in _theme_cache:
        _theme_cache[app] = _parse_theme(app, check, report)
    return _theme_cache[app]


def _parse_theme(app: str, check: str, report: Report) -> ThemeFile | None:
    path = theme_css_path(app)
    if not path.exists():
        report.fail(check, path, 1, "theme.css is missing (§4.4)")
        return None
    text = path.read_text(encoding="utf-8")
    expected = HOST_SELECTORS if app == "host" else BASE_SELECTORS
    blocks: dict[str, Block] = {}
    ok = True
    pos = 0
    for match in BLOCK_RE.finditer(text):
        between = text[pos : match.start()] + match.group(1)
        pos = match.end()
        selector = " ".join(match.group(1).split())
        line = line_of(
            text, match.start(1) + len(match.group(1)) - len(match.group(1).lstrip())
        )
        if "/*" in between or "/*" in match.group(2):
            report.fail(
                check, path, line, "comments are not allowed in theme.css (§4.4)"
            )
            ok = False
        index = len(blocks)
        if index >= len(expected) or selector != expected[index]:
            want = expected[index] if index < len(expected) else "(no more blocks)"
            report.fail(
                check,
                path,
                line,
                f"block {index + 1} selector is {selector!r}, expected {want!r}",
            )
            ok = False
            continue
        block = Block(selector, line)
        body_start = match.start(2)
        offset = 0
        for decl in match.group(2).split(";"):
            decl_line = line_of(
                text, body_start + offset + len(decl) - len(decl.lstrip())
            )
            offset += len(decl) + 1
            stripped = decl.strip()
            if not stripped:
                continue
            token = TOKEN_DECL.fullmatch(stripped)
            scheme = SCHEME_DECL.fullmatch(stripped)
            if token:
                name = token.group(1)
                channels = tuple(int(token.group(i)) for i in (2, 3, 4))
                if any(c > 255 for c in channels):
                    report.fail(
                        check, path, decl_line, f"--{name}: channel out of range"
                    )
                    ok = False
                if name in block.tokens:
                    report.fail(
                        check, path, decl_line, f"--{name} declared twice in one block"
                    )
                    ok = False
                block.tokens[name] = (
                    (channels[0], channels[1], channels[2]),
                    decl_line,
                )
            elif scheme and selector in COLOR_SCHEME:
                block.color_schemes.append((scheme.group(1), decl_line))
            else:
                report.fail(
                    check,
                    path,
                    decl_line,
                    f"unexpected declaration {stripped!r} (§4.4)",
                )
                ok = False
        blocks[selector] = block
    if text[pos:].strip():
        report.fail(
            check, path, line_of(text, pos), "unexpected content after the last block"
        )
        ok = False
    for selector in expected[len(blocks) :]:
        report.fail(check, path, 1, f"missing block {selector!r} (§4.4)")
        ok = False
    return ThemeFile(path, text, blocks) if ok else None


# ── Check 2 ──────────────────────────────────────────────────────────────────


def luminance(rgb: RGB) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def resolve(name: str, tokens: dict[str, tuple[RGB, int]]) -> RGB | None:
    if name == SCRIM:
        if "scrim" not in tokens:
            return None
        scrim = tokens["scrim"][0]
        return tuple(SCRIM_ALPHA * c + (1 - SCRIM_ALPHA) * 255 for c in scrim)
    entry = tokens.get(name)
    return entry[0] if entry else None


def check_contrast(apps: list[str], report: Report) -> None:
    for app in apps:
        theme = load_theme(app, "contrast", report)
        if theme is None:
            continue
        contexts = [
            ("dark", theme.context(SEL_INVARIANT, SEL_DARK), False),
            ("light", theme.context(SEL_INVARIANT, SEL_LIGHT), False),
        ]
        if app == "host":
            contexts += [
                (
                    "stage-dark",
                    theme.context(SEL_INVARIANT, SEL_DARK, SEL_STAGE_DARK),
                    True,
                ),
                (
                    "stage-light",
                    theme.context(SEL_INVARIANT, SEL_LIGHT, SEL_STAGE_LIGHT),
                    True,
                ),
            ]
        stage = app == "host"
        print(f"\ncontrast: {rel(theme.path)}")
        print(
            f"  text ≥ {TEXT_MIN}"
            + (f" (≥ {STAGE_TEXT_MIN:g} on stage)" if stage else "")
            + f", non-text ≥ {NON_TEXT_MIN:g}; ✗ marks a failure"
        )
        width = max(len(p.label) for p in PAIRS) + 2
        print(
            "  "
            + "pair".ljust(width)
            + "".join(f"{name:>13}" for name, _, _ in contexts)
        )
        failures = []
        for pair in PAIRS:
            cells = []
            for name, tokens, is_stage in contexts:
                if is_stage and pair.kind == "text" and not pair.on_stage:
                    cells.append(f"{'—':>13}")
                    continue
                if pair.kind == "non-text":
                    needed = NON_TEXT_MIN
                else:
                    needed = STAGE_TEXT_MIN if is_stage else TEXT_MIN
                fg, bg = resolve(pair.fg, tokens), resolve(pair.bg, tokens)
                if fg is None or bg is None:
                    missing = pair.fg if fg is None else pair.bg
                    cells.append(f"{'missing ✗':>13}")
                    failures.append((1, f"contrast: {missing} is not defined ({name})"))
                    continue
                ratio = contrast(fg, bg)
                passed = ratio >= needed
                cells.append(f"{ratio:11.2f}" + ("  " if passed else " ✗"))
                if not passed:
                    line = tokens[pair.fg][1] if pair.fg in tokens else 1
                    failures.append(
                        (
                            line,
                            f"contrast: {pair.label} is {ratio:.2f}:1 in {name}, "
                            f"needs {needed:g}:1",
                        )
                    )
            print("  " + pair.label.ljust(width) + "".join(cells))
        for line, message in failures:
            report.fail("contrast", theme.path, line, message)


# ── Check 3 ──────────────────────────────────────────────────────────────────


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def majority(values: dict) -> object:
    """The most common value; a tie goes to the earliest entry."""
    counts = Counter(values.values())
    best = max(counts.values())
    return next(value for value in values.values() if counts[value] == best)


def channels(rgb: RGB) -> str:
    return " ".join(f"{c:g}" for c in rgb)


def check_identical(apps: list[str], report: Report) -> None:
    check = "identical"

    # Byte-identical groups (§4.0).
    for members, relpath in IDENTICAL_GROUPS:
        if not any(app in apps for app in members):
            continue
        paths = [FRONTEND / app / relpath for app in members]
        existing = [p for p in paths if p.exists()]
        for path in paths:
            if not path.exists():
                others = ", ".join(rel(p) for p in paths if p != path)
                report.fail(
                    check, path, 1, f"missing (must be byte-identical to {others})"
                )
        if len(existing) < 2:
            continue
        hashes = {path: md5(path) for path in existing}
        expected = majority(hashes)
        agreeing = next(path for path, digest in hashes.items() if digest == expected)
        for path, digest in hashes.items():
            if digest != expected:
                report.fail(
                    check,
                    path,
                    1,
                    f"differs from {rel(agreeing)} (md5 {digest[:8]} vs {expected[:8]}); "
                    "edit one copy and copy it to the others",
                )

    # theme.css: token sets, stage overrides, colour-scheme lines, cross-app values.
    themes = {app: load_theme(app, check, report) for app in APPS}
    for app in apps:
        theme = themes[app]
        if theme is None:
            continue
        invariant = theme.blocks[SEL_INVARIANT]
        dark, light = theme.blocks[SEL_DARK], theme.blocks[SEL_LIGHT]
        for name in sorted(set(dark.tokens) ^ set(light.tokens)):
            block = dark if name in dark.tokens else light
            other = "light" if block is dark else "dark"
            line = block.tokens[name][1]
            report.fail(check, theme.path, line, f"--{name} has no {other} value")
        for name in sorted(
            set(invariant.tokens) & (set(dark.tokens) | set(light.tokens))
        ):
            line = invariant.tokens[name][1]
            report.fail(
                check, theme.path, line, f"--{name} is both invariant and themed"
            )
        for selector, scheme in COLOR_SCHEME.items():
            block = theme.blocks[selector]
            values = [value for value, _ in block.color_schemes]
            if values != [scheme]:
                report.fail(
                    check,
                    theme.path,
                    block.line,
                    f"block {selector!r} must contain exactly one 'color-scheme: {scheme}'",
                )
        if app == "host":
            for selector in (SEL_STAGE_DARK, SEL_STAGE_LIGHT):
                block = theme.blocks[selector]
                names = set(block.tokens)
                if names != STAGE_TOKENS:
                    extra = ", ".join(sorted(names - STAGE_TOKENS)) or "none"
                    absent = ", ".join(sorted(STAGE_TOKENS - names)) or "none"
                    report.fail(
                        check,
                        theme.path,
                        block.line,
                        f"stage block {selector!r} must override exactly the ten §4.3 "
                        f"tokens (extra: {extra}; missing: {absent})",
                    )

    # Every app defines the same tokens with the same values. The odd one out (by
    # majority) is the one reported.
    parsed = {app: theme for app, theme in themes.items() if theme is not None}
    values_match = True
    if len(parsed) >= 2 and any(app in apps for app in parsed):
        for selector in BASE_SELECTORS:
            blocks = {app: theme.blocks[selector] for app, theme in parsed.items()}
            names = sorted(set().union(*(block.tokens for block in blocks.values())))
            for name in names:
                values = {
                    app: block.tokens[name][0] if name in block.tokens else None
                    for app, block in blocks.items()
                }
                expected = majority(values)
                agreeing = next(
                    app for app, value in values.items() if value == expected
                )
                where = rel(parsed[agreeing].path)
                for app, value in values.items():
                    if value == expected:
                        continue
                    values_match = False
                    block = blocks[app]
                    if value is None:
                        line, problem = block.line, f"is missing (defined in {where})"
                    elif expected is None:
                        line, problem = (
                            block.tokens[name][1],
                            f"is not defined in {where}",
                        )
                    else:
                        line = block.tokens[name][1]
                        problem = f"is {channels(value)} here but {channels(expected)} in {where}"
                    report.fail(
                        check,
                        parsed[app].path,
                        line,
                        f"--{name} in {selector!r} {problem}",
                    )
        # The host file is the player/admin file plus the stage blocks (§4.4).
        host, player = themes["host"], themes["player"]
        if values_match and host and player and not host.text.startswith(player.text):
            report.fail(
                check,
                host.path,
                1,
                f"must start with the exact text of {rel(player.path)}, then add the stage blocks",
            )

    # Per-app storage key, declared only in index.html (§4.7).
    for app in apps:
        index = FRONTEND / app / "index.html"
        text = index.read_text(encoding="utf-8")
        match = THEME_KEY_ATTR.search(text)
        want = f"{THEME_KEY_PREFIX}{app}"
        if match is None:
            line = line_of(text, text.find("<html")) if "<html" in text else 1
            report.fail(check, index, line, f'<html> needs data-theme-key="{want}"')
        elif match.group(1) != want:
            line = line_of(text, match.start())
            report.fail(
                check,
                index,
                line,
                f"data-theme-key is {match.group(1)!r}, expected {want!r}",
            )
        for path in sorted((FRONTEND / app / "src").rglob("*")):
            if path.suffix not in SCANNED_SUFFIXES:
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if THEME_KEY_PREFIX in line:
                    report.fail(
                        check,
                        path,
                        lineno,
                        "theme storage key written outside index.html; read data-theme-key",
                    )

    # Stale config output that shadows the .ts configs (§4.2).
    for app in apps:
        for name in STALE_CONFIGS:
            path = FRONTEND / app / name
            if path.exists():
                report.fail(
                    check,
                    path,
                    1,
                    "stale build output shadows the .ts config; delete it",
                )


# ── Main ─────────────────────────────────────────────────────────────────────

CHECKS = {
    "colors": check_colors,
    "contrast": check_contrast,
    "identical": check_identical,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Theme gate for the frontends (manual pre-MR check, not run in CI)."
    )
    parser.add_argument(
        "--app", action="append", choices=APPS, help="narrow to one app"
    )
    parser.add_argument(
        "--check", action="append", choices=list(CHECKS), help="run one check"
    )
    args = parser.parse_args(argv)
    apps = [app for app in APPS if app in (args.app or APPS)]
    checks = [name for name in CHECKS if name in (args.check or CHECKS)]

    report = Report()
    for name in checks:
        CHECKS[name](apps, report)

    counts = ", ".join(
        f"{name} {len(report.failures.get(name, []))}" for name in checks
    )
    failed = any(report.failures.values())
    print(
        f"\ncheck_theme ({', '.join(apps)}): {counts} failure(s) — {'FAIL' if failed else 'OK'}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
