/**
 * Slider geometry and formatting (T7 slider spec §4.0, §4.8).
 *
 * Copied byte-for-byte into the player, host and admin apps (they share no code);
 * change all three together. The client mirror of the server's
 * `backend/app/services/slider_math.py`: every formula here must give the same result
 * as the Python one. No app has a test runner, so this file is type-checked only; the
 * backend unit tests (`tests/unit/test_slider_math.py`) cover the same maths.
 *
 * Everything works in step indices: position k (an integer in [0, n]) has the value
 * min + k × step. Radii are fractions of the range (max − min).
 */

/** The slider keys of a question's `config` (public; the target is never in here). */
export interface SliderSettings {
  min?: number;
  max?: number;
  step?: number;
  showValue?: boolean;
  unit?: string | null;
  minLabel?: string | null;
  maxLabel?: string | null;
}

/** The server's slider reveal: the settings plus the canonical target and radii. */
export interface SliderRevealData extends SliderSettings {
  target: number | null;
  fullRadius: number | null;
  zeroRadius: number | null;
}

export interface SliderGeometry {
  min: number;
  max: number;
  step: number;
  /** Number of steps; positions are 0..n. */
  n: number;
  /** Display precision: max(decimals(min), decimals(step)). */
  decimals: number;
}

export const SLIDER_MAX_STEPS = 10000;
export const SLIDER_MIN_FULL_RADIUS = 0.01;
export const SLIDER_MAX_ABS = 1e9;
export const SLIDER_EPS = 1e-6;
const SLIDER_MAX_BINS = 20;
const SLIDER_MAX_DECIMALS = 6;

function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** Nearest index, ties up (the server's snap; never Math.round on negatives). */
export function snap(k: number): number {
  return Math.floor(k + 0.5);
}

/** Smallest d in 0..6 with x × 10^d a whole number (±1e-9), else null. */
export function decimalsOf(x: number): number | null {
  for (let d = 0; d <= SLIDER_MAX_DECIMALS; d++) {
    const scaled = x * 10 ** d;
    if (Math.abs(scaled - Math.round(scaled)) <= 1e-9) return d;
  }
  return null;
}

/** null unless min/max/step form a valid grid of 1..10000 steps (same rules as the server). */
export function sliderGeometry(config: SliderSettings | null | undefined): SliderGeometry | null {
  if (!config) return null;
  const { min, max, step } = config;
  if (!isNum(min) || !isNum(max) || !isNum(step)) return null;
  if (Math.abs(min) > SLIDER_MAX_ABS || Math.abs(max) > SLIDER_MAX_ABS) return null;
  if (step <= 0 || max <= min) return null;
  const dMin = decimalsOf(min);
  const dStep = decimalsOf(step);
  if (dMin === null || dStep === null) return null;
  const raw = (max - min) / step;
  const n = Math.round(raw);
  if (Math.abs(raw - n) > SLIDER_EPS || n < 1 || n > SLIDER_MAX_STEPS) return null;
  return { min, max, step, n, decimals: Math.max(dMin, dStep) };
}

function clampIndex(geom: SliderGeometry, k: number): number {
  return Math.min(Math.max(k, 0), geom.n);
}

/** The server's "in range": k within [−EPS, n + EPS]. */
export function inRange(geom: SliderGeometry, value: number): boolean {
  if (!isNum(value)) return false;
  const k = (value - geom.min) / geom.step;
  return k >= -SLIDER_EPS && k <= geom.n + SLIDER_EPS;
}

/** In range and within EPS of a step (the target rule). */
export function onGrid(geom: SliderGeometry, value: number): boolean {
  if (!inRange(geom, value)) return false;
  const k = (value - geom.min) / geom.step;
  return Math.abs(k - snap(k)) <= SLIDER_EPS;
}

/** Nearest index, clamped to [0, n]. */
export function snapIndex(geom: SliderGeometry, value: number): number {
  return clampIndex(geom, snap((value - geom.min) / geom.step));
}

/** The canonical value of index k (the server's slider_value). */
export function indexValue(geom: SliderGeometry, k: number): number {
  return Number((geom.min + k * geom.step).toFixed(geom.decimals));
}

/** Share of the way from the left end, 0–100. */
export function pct(geom: SliderGeometry, k: number): number {
  return snap((100 * k) / geom.n);
}

/** Where the knob starts. */
export function middleIndex(geom: SliderGeometry): number {
  return Math.floor(geom.n / 2);
}

/** One bin per position up to 20 positions, otherwise 20 near-equal bins. */
export function binCount(n: number): number {
  return Math.min(n + 1, SLIDER_MAX_BINS);
}

/** Bin of index k, matching the server's distribution keys ("0" .. B − 1). */
export function binOf(n: number, k: number): number {
  return Math.floor((k * binCount(n)) / (n + 1));
}

/** The index range [lo, hi] of bin b. */
export function binRange(geom: SliderGeometry, b: number): { lo: number; hi: number } {
  const bins = binCount(geom.n);
  return {
    lo: Math.ceil((b * (geom.n + 1)) / bins),
    hi: Math.ceil(((b + 1) * (geom.n + 1)) / bins) - 1,
  };
}

/** Distance between two indices as a fraction of the range. */
export function sliderDistance(geom: SliderGeometry, k: number, kt: number): number {
  return Math.abs(k - kt) / geom.n;
}

/** 1 within fullRadius, linear falloff to 0 at zeroRadius (map_pin's falloff). */
export function sliderFraction(d: number, full: number, zero: number): number {
  if (d <= full) return 1;
  if (d >= zero) return 0;
  return 1 - (d - full) / (zero - full);
}

function withUnit(text: string, unit: string | null | undefined): string {
  return unit ? `${text} ${unit}` : text;
}

/** Exactly `decimals` decimals with thousands separators, plus the unit if any. */
export function formatValue(
  geom: SliderGeometry,
  value: number,
  unit?: string | null,
): string {
  const text = value.toLocaleString('en-US', {
    minimumFractionDigits: geom.decimals,
    maximumFractionDigits: geom.decimals,
  });
  return withUnit(text, unit);
}

/** [left, right]: the end labels when set, else the formatted min / max with unit. */
export function endLabels(config: SliderSettings, geom: SliderGeometry): [string, string] {
  return [
    config.minLabel || formatValue(geom, geom.min, config.unit),
    config.maxLabel || formatValue(geom, geom.max, config.unit),
  ];
}

/** How a position is described: its value, or "35% of the way from A to B" without numbers. */
export function positionText(config: SliderSettings, geom: SliderGeometry, k: number): string {
  if (config.showValue === false) {
    const [left, right] = endLabels(config, geom);
    return `${pct(geom, k)}% of the way from ${left} to ${right}`;
  }
  return formatValue(geom, indexValue(geom, k), config.unit);
}

/**
 * "Target: 58 hot dogs · full credit within ±5 hot dogs", or for a spectrum
 * "Target: 35% of the way from Ice cold to Lava". The same text as the server's
 * slider_target_line (the report).
 */
export function targetLine(reveal: SliderRevealData): string {
  const geom = sliderGeometry(reveal);
  if (!geom || reveal.target === null || !inRange(geom, reveal.target)) return 'Target: —';
  const kt = snapIndex(geom, reveal.target);
  if (reveal.showValue === false) return `Target: ${positionText(reveal, geom, kt)}`;
  let line = `Target: ${formatValue(geom, geom.min + kt * geom.step, reveal.unit)}`;
  if (isNum(reveal.fullRadius)) {
    const width = (reveal.fullRadius * (geom.max - geom.min)).toLocaleString('en-US', {
      minimumFractionDigits: 0,
      maximumFractionDigits: geom.decimals + 2,
    });
    line += ` · full credit within ±${withUnit(width, reveal.unit)}`;
  }
  return line;
}

/** Share of the points a player gets for not moving the knob from the middle. */
export function freePoints(geom: SliderGeometry, kt: number, full: number, zero: number): number {
  return sliderFraction(sliderDistance(geom, middleIndex(geom), kt), full, zero);
}
