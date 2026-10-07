import {
  endLabels,
  formatValue,
  indexValue,
  inRange,
  positionText,
  sliderGeometry,
  snapIndex,
  type SliderGeometry,
} from '../lib/slider';
import type { SliderConfig, SliderReveal } from '../types/game';

interface SliderInputProps {
  config: SliderConfig;
  /** Interactive mode: the knob's step index. */
  index?: number;
  onIndexChange?: (k: number) => void;
  disabled?: boolean;
  /** Reveal mode (results): the target, the full-credit band and the player's own marker. */
  reveal?: SliderReveal;
  myIndex?: number | null;
}

/** Left edge of index k, as a % of the track. */
function at(geom: SliderGeometry, k: number): string {
  return `${(k / geom.n) * 100}%`;
}

function StepButton({
  label,
  symbol,
  disabled,
  onClick,
}: {
  label: string;
  symbol: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="w-12 h-12 shrink-0 rounded-xl border-2 border-line-strong bg-surface text-fg text-2xl font-black enabled:active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
    >
      {symbol}
    </button>
  );
}

function EndLabels({ left, right }: { left: string; right: string }) {
  return (
    <div className="flex justify-between gap-4 text-fg-muted text-sm font-semibold">
      <span className="text-left">{left}</span>
      <span className="text-right">{right}</span>
    </div>
  );
}

/**
 * The player's slider (T7 slider spec §4.9). Works in step indices: the parent holds the
 * index and turns it into a value with `indexValue` when it submits. Interactive: a native
 * range input (keyboard and screen readers for free) with − / + buttons. Reveal: a static
 * track with the full-credit band, the target and the player's own marker.
 */
export function SliderInput({
  config,
  index = 0,
  onIndexChange,
  disabled = false,
  reveal,
  myIndex = null,
}: SliderInputProps) {
  const geom = sliderGeometry(reveal ?? config);
  if (!geom) {
    return <p className="text-fg-muted text-center p-6">This question can't be answered.</p>;
  }
  const settings = reveal ?? config;
  const showValue = settings.showValue !== false;
  const [left, right] = endLabels(settings, geom);

  if (reveal) {
    const kt =
      reveal.target !== null && inRange(geom, reveal.target) ? snapIndex(geom, reveal.target) : null;
    const band = kt !== null && reveal.fullRadius !== null ? reveal.fullRadius * geom.n : null;
    return (
      <div className="w-full flex flex-col gap-2 px-2">
        <div className="relative h-16">
          <div className="absolute inset-x-0 top-8 h-3 rounded-full bg-chart-track" />
          {kt !== null && band !== null && (
            <div
              className="absolute top-7 h-5 rounded-full bg-success-soft border-2 border-success"
              style={{
                left: at(geom, Math.max(0, kt - band)),
                right: `${100 - (Math.min(geom.n, kt + band) / geom.n) * 100}%`,
              }}
            />
          )}
          {kt !== null && (
            <div className="absolute top-0 -translate-x-1/2 flex flex-col items-center" style={{ left: at(geom, kt) }}>
              <span className="text-success-fg text-xs font-bold whitespace-nowrap">
                {showValue ? formatValue(geom, indexValue(geom, kt), settings.unit) : 'Target'}
              </span>
              <span className="mt-0.5 w-1.5 h-9 rounded-full bg-success" aria-hidden />
            </div>
          )}
          {myIndex !== null && (
            <div className="absolute top-6 -translate-x-1/2 flex flex-col items-center" style={{ left: at(geom, myIndex) }}>
              <span className="w-7 h-7 rounded-full bg-accent border-4 border-on-accent" aria-hidden />
              <span className="text-accent-fg text-xs font-bold whitespace-nowrap mt-0.5">
                {showValue ? `You: ${formatValue(geom, indexValue(geom, myIndex), settings.unit)}` : 'You'}
              </span>
            </div>
          )}
        </div>
        <div className="mt-6">
          <EndLabels left={left} right={right} />
        </div>
      </div>
    );
  }

  const k = Math.min(Math.max(index, 0), geom.n);
  const move = (next: number) => onIndexChange?.(Math.min(Math.max(next, 0), geom.n));
  return (
    <div className="w-full flex flex-col gap-3">
      {showValue && (
        <p className="text-center text-fg text-4xl font-black tabular-nums" aria-hidden>
          {formatValue(geom, indexValue(geom, k), settings.unit)}
        </p>
      )}
      <div className="flex items-center gap-2">
        <StepButton label="One step left" symbol="−" disabled={disabled || k <= 0} onClick={() => move(k - 1)} />
        <input
          type="range"
          min={0}
          max={geom.n}
          step={1}
          value={k}
          disabled={disabled}
          onChange={(e) => move(Number(e.target.value))}
          aria-label="Your answer"
          aria-valuetext={positionText(settings, geom, k)}
          className="slider-range flex-1 min-w-0"
        />
        <StepButton label="One step right" symbol="+" disabled={disabled || k >= geom.n} onClick={() => move(k + 1)} />
      </div>
      <div className="px-14">
        <EndLabels left={left} right={right} />
      </div>
    </div>
  );
}
