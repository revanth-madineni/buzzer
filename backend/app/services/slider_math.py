"""Slider geometry (T7 slider spec §4.0, §4.3). The only slider maths on the server.

Pure and import-free on purpose: `schemas/admin.py` validates with these helpers and
`game_service` scores with them, and `game_service` already imports `schemas.admin`, so
this module can't live in `game_service` without an import cycle.

Everything works in step indices: `k = (value - min) / step` snapped to an integer in
[0, N], so float noise like 0.30000000000000004 never reaches scoring.
`lib/slider.ts` in each frontend app mirrors these formulas; keep them in step.
"""

from __future__ import annotations

import math

SLIDER_MAX_STEPS = 10000
SLIDER_MIN_FULL_RADIUS = 0.01
SLIDER_MAX_ABS = 1e9
SLIDER_EPS = 1e-6
SLIDER_MAX_BINS = 20
SLIDER_MAX_DECIMALS = 6


def _is_num(value: object) -> bool:
    """Same rule as `schemas.admin.is_valid_number` (can't import it: cycle)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def snap(k: float) -> int:
    """Nearest index, ties up. Never Python's round(): it rounds ties to even."""
    return math.floor(k + 0.5)


def decimals(x: float) -> int | None:
    """Smallest d in 0..6 with x × 10^d a whole number (±1e-9), else None."""
    for d in range(SLIDER_MAX_DECIMALS + 1):
        scaled = x * 10**d
        if abs(scaled - round(scaled)) <= 1e-9:
            return d
    return None


def slider_geometry(config: object) -> tuple[float, float, float, int, int] | None:
    """(min, max, step, N, D), or None if the config isn't a valid slider.

    Defensive: rows written by direct inserts or seed scripts skip validation."""
    if not isinstance(config, dict):
        return None
    lo, hi, step = config.get("min"), config.get("max"), config.get("step")
    if not (_is_num(lo) and _is_num(hi) and _is_num(step)):
        return None
    if abs(lo) > SLIDER_MAX_ABS or abs(hi) > SLIDER_MAX_ABS:
        return None
    if step <= 0 or hi <= lo:
        return None
    d_min, d_step = decimals(lo), decimals(step)
    if d_min is None or d_step is None:
        return None
    n = (hi - lo) / step
    n_steps = round(n)
    if abs(n - n_steps) > SLIDER_EPS or not 1 <= n_steps <= SLIDER_MAX_STEPS:
        return None
    return float(lo), float(hi), float(step), n_steps, max(d_min, d_step)


def slider_index(config: object, value: object) -> int | None:
    """The snapped index of `value`, or None if the config is invalid, `value` isn't a
    valid number, or it's out of range. This is the one "in range" test (§4.0)."""
    geometry = slider_geometry(config)
    if geometry is None or not _is_num(value):
        return None
    lo, _hi, step, n_steps, _d = geometry
    k = (value - lo) / step
    if k < -SLIDER_EPS or k > n_steps + SLIDER_EPS:
        return None
    return min(max(snap(k), 0), n_steps)


def slider_on_grid(config: object, value: object) -> bool:
    """In range and within EPS of a step (the target rule, §4.1)."""
    geometry = slider_geometry(config)
    if geometry is None or slider_index(config, value) is None:
        return False
    lo, _hi, step, _n, _d = geometry
    k = (value - lo) / step
    return abs(k - snap(k)) <= SLIDER_EPS


def slider_value(config: object, k: int) -> int | float:
    """The canonical value of index `k`: 58 (an int) on whole-number sliders."""
    geometry = slider_geometry(config)
    if geometry is None:
        raise ValueError("invalid slider config")
    lo, _hi, step, _n, d = geometry
    v = round(lo + k * step, d)
    return int(v) if d == 0 else v


def slider_bins(n_steps: int) -> int:
    """One bin per position up to 20 positions, otherwise 20 near-equal bins."""
    return min(n_steps + 1, SLIDER_MAX_BINS)


def slider_bin(n_steps: int, k: int) -> str:
    """Distribution key of index `k`: "0" .. str(B - 1)."""
    return str((k * slider_bins(n_steps)) // (n_steps + 1))


def slider_target_index(config: object, answer_data: object) -> int | None:
    if not isinstance(answer_data, dict):
        return None
    return slider_index(config, answer_data.get("target"))


def slider_distance(n_steps: int, k_guess: int, k_target: int) -> float:
    """Distance as a fraction of the range."""
    return abs(k_guess - k_target) / n_steps


def slider_pct(n_steps: int, k: int) -> int:
    """Share of the way from the left end, 0–100 (§4.0). Ties up, like `snap`."""
    return snap(100 * k / n_steps)


# --- Formatting (the same text as `lib/slider.ts`) -------------------------------


def format_number(value: float, d: int) -> str:
    """Exactly `d` decimals with thousands separators (JS `toLocaleString('en-US')`)."""
    return f"{value:,.{d}f}"


def _format_trimmed(value: float, max_d: int) -> str:
    """Up to `max_d` decimals, trailing zeros trimmed."""
    s = f"{value:,.{max_d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _with_unit(text: str, unit: object) -> str:
    return f"{text} {unit}" if isinstance(unit, str) and unit else text


def slider_target_line(reveal: dict) -> str:
    """ "Target: 58 hot dogs · full credit within ±5 hot dogs", or for a spectrum
    "Target: 35% of the way from Ice cold to Lava" (§4.6). Shared by the report and
    (via `lib/slider.ts` `targetLine`) the host game-over page."""
    geometry = slider_geometry(reveal)
    kt = slider_index(reveal, reveal.get("target"))
    if geometry is None or kt is None:
        return "Target: —"
    lo, hi, step, n_steps, d = geometry
    unit = reveal.get("unit")
    if reveal.get("showValue", True) is False:
        left = reveal.get("minLabel") or _with_unit(format_number(lo, d), unit)
        right = reveal.get("maxLabel") or _with_unit(format_number(hi, d), unit)
        return f"Target: {slider_pct(n_steps, kt)}% of the way from {left} to {right}"
    target = format_number(lo + kt * step, d)
    line = f"Target: {_with_unit(target, unit)}"
    full = reveal.get("fullRadius")
    if _is_num(full):
        width = _format_trimmed(full * (hi - lo), d + 2)
        line += f" · full credit within ±{_with_unit(width, unit)}"
    return line
