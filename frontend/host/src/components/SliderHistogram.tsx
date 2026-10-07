import {
  binCount,
  endLabels,
  formatValue,
  indexValue,
  inRange,
  sliderGeometry,
  snapIndex,
  type SliderGeometry,
} from '../lib/slider';
import type { SliderConfig, SliderReveal } from '../types/game';

function EndLabels({ left, right }: { left: string; right: string }) {
  return (
    <div className="flex justify-between gap-6 text-fg text-xl font-semibold">
      <span className="text-left">{left}</span>
      <span className="text-right">{right}</span>
    </div>
  );
}

/**
 * The scale under the prompt while a slider question is open (T7 slider spec §4.10): the
 * end labels (or min / max with unit) at either end of a plain track, with no knob.
 */
export function SliderScale({ config }: { config: SliderConfig }) {
  const geom = sliderGeometry(config);
  if (!geom) return null;
  const [left, right] = endLabels(config, geom);
  const stepNote =
    config.showValue !== false && geom.step !== 1
      ? `steps of ${formatValue(geom, geom.step, config.unit)}`
      : null;
  return (
    <div className="w-full max-w-3xl flex flex-col gap-3">
      <div className="h-4 rounded-full bg-chart-track" />
      <EndLabels left={left} right={right} />
      {stepNote && <p className="text-center text-fg-muted text-lg">{stepNote}</p>}
    </div>
  );
}

/** Percent position of index k on the track (index k sits at k / n). */
function pos(geom: SliderGeometry, k: number): number {
  return (k / geom.n) * 100;
}

/** Keeps a callout on screen near the ends instead of centring it on the marker. */
function calloutStyle(p: number): React.CSSProperties {
  if (p < 15) return { left: `${p}%` };
  if (p > 85) return { right: `${100 - p}%` };
  return { left: `${p}%`, transform: 'translateX(-50%)' };
}

/**
 * Results for a slider question (T7 slider spec §4.10), the same for both grading types.
 * One coordinate system: bar b spans [b/B, (b+1)/B] of the width, and index k sits at k/n,
 * which always falls inside its own bin's bar. The target marker is at its exact position
 * and the full-credit band (target ± fullRadius × n indices) is shaded behind the bars.
 * Counts sit above the bars, on the page background, never on a fill.
 */
export function SliderHistogram({
  reveal,
  distribution,
}: {
  reveal: SliderReveal;
  distribution: Record<string, number>;
}) {
  const geom = sliderGeometry(reveal);
  if (!geom) return <p className="text-fg-muted text-lg text-center">Slider settings unavailable</p>;
  const bins = binCount(geom.n);
  const counts = Array.from({ length: bins }, (_, b) => distribution[String(b)] ?? 0);
  const maxCount = Math.max(0, ...counts);
  const kt =
    reveal.target !== null && inRange(geom, reveal.target) ? snapIndex(geom, reveal.target) : null;
  const halfBand = kt !== null && reveal.fullRadius !== null ? reveal.fullRadius * geom.n : null;
  const showValue = reveal.showValue !== false;
  const [left, right] = endLabels(reveal, geom);
  const targetPos = kt !== null ? pos(geom, kt) : null;

  return (
    <div className="w-full flex flex-col gap-3">
      <div className="relative h-10">
        {targetPos !== null && (
          <p
            className="absolute bottom-0 text-success-fg text-2xl font-bold whitespace-nowrap"
            style={calloutStyle(targetPos)}
          >
            {showValue && kt !== null
              ? `Answer: ${formatValue(geom, indexValue(geom, kt), reveal.unit)}`
              : 'Target'}
          </p>
        )}
      </div>
      <div
        className="relative h-72 border-b-4 border-line-strong"
        role="img"
        aria-label={`Histogram of guesses in ${bins} groups, with the target marked`}
      >
        {kt !== null && halfBand !== null && (
          <div
            className="absolute inset-y-0 bg-success-soft"
            style={{
              left: `${pos(geom, Math.max(0, kt - halfBand))}%`,
              right: `${100 - pos(geom, Math.min(geom.n, kt + halfBand))}%`,
            }}
          />
        )}
        <div className="absolute inset-0 flex items-end">
          {counts.map((count, b) => (
            <div key={b} className="h-full flex-1 flex flex-col justify-end items-center px-0.5">
              {count > 0 && (
                <>
                  {/* Above the target marker, on the page background, so the line never crosses it. */}
                  <span className="relative z-10 rounded bg-page px-1 text-fg text-lg font-bold tabular-nums">
                    {count}
                  </span>
                  <div
                    className="w-full rounded-t-md bg-chart-bar"
                    style={{ height: `calc(${(count / maxCount) * 100}% - 1.75rem)`, minHeight: '0.5rem' }}
                  />
                </>
              )}
            </div>
          ))}
        </div>
        {targetPos !== null && (
          <div
            className="absolute inset-y-0 w-1.5 -translate-x-1/2 rounded-full bg-success"
            style={{ left: `${targetPos}%` }}
            aria-hidden
          />
        )}
        {maxCount === 0 && (
          <p className="absolute inset-0 flex items-center justify-center text-fg-muted text-xl">
            No answers
          </p>
        )}
      </div>
      <EndLabels left={left} right={right} />
    </div>
  );
}
