import { useCallback } from 'react';
import { MapCanvas } from './MapCanvas';
import { drawTarget, fractionToCanvas, mapColor, type DrawRect } from '../lib/mapPin';
import type { MapPinReveal } from '../types/game';

/** The server buckets taps on this grid (game_service.map_pin_bucket). */
const GRID = 50;

/**
 * Projector results for a map_pin question (T7 spec §4.11): the image, one translucent
 * dot per tapped 2% cell (area grows with the count), then the target and both radius
 * circles on top. The same view for both grading types.
 */
export function MapPinHeatmap({
  reveal,
  distribution,
}: {
  reveal: MapPinReveal;
  distribution: Record<string, number>;
}) {
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, fit: DrawRect) => {
      const cells = Object.entries(distribution)
        .map(([key, count]) => {
          const [bx, by] = key.split(',').map(Number);
          return { bx, by, count };
        })
        .filter((c) => Number.isInteger(c.bx) && Number.isInteger(c.by) && c.count > 0);
      const maxCount = Math.max(1, ...cells.map((c) => c.count));
      const dotColor = mapColor('heat', 0.55);
      ctx.save();
      for (const { bx, by, count } of cells) {
        const centre = fractionToCanvas({ x: (bx + 0.5) / GRID, y: (by + 0.5) / GRID }, fit);
        // Radius ∝ √count, so dot area grows with the number of taps.
        const r = fit.drawW * (0.006 + 0.02 * Math.sqrt(count / maxCount));
        ctx.beginPath();
        ctx.arc(centre.x, centre.y, r, 0, Math.PI * 2);
        ctx.fillStyle = dotColor;
        ctx.fill();
      }
      ctx.restore();
      drawTarget(ctx, fit, reveal.target, reveal.fullRadius, reveal.zeroRadius);
    },
    [distribution, reveal],
  );

  return (
    <MapCanvas
      imageId={reveal.imageId}
      imageWidth={reveal.imageWidth}
      imageHeight={reveal.imageHeight}
      draw={draw}
    />
  );
}
