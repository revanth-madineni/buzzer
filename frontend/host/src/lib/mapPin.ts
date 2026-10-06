/**
 * Map-pin geometry and drawing (T7 spec §4.6, §4.9).
 *
 * Copied byte-for-byte into the player, host and admin apps (they share no code);
 * change all three together. Points are fractions of the image: x left→right of the
 * width, y top→bottom of the height, both in [0, 1]. Radii are in image-width units,
 * so a radius r is r × drawW pixels in every direction.
 */

export interface Point {
  x: number;
  y: number;
}

/** Where the image is drawn inside the canvas (CSS pixels), aspect preserved. */
export interface DrawRect {
  offsetX: number;
  offsetY: number;
  drawW: number;
  drawH: number;
}

export function containFit(
  canvasW: number,
  canvasH: number,
  imageW: number,
  imageH: number,
): DrawRect {
  const scale = Math.min(canvasW / imageW, canvasH / imageH);
  const drawW = imageW * scale;
  const drawH = imageH * scale;
  return { offsetX: (canvasW - drawW) / 2, offsetY: (canvasH - drawH) / 2, drawW, drawH };
}

/**
 * CSS height of a map canvas: the image's height at full container width, capped at
 * `cap` × viewport height (0.6 on phones, 0.7 in the editors). When capped, contain-fit
 * letterboxes the image horizontally.
 */
export function canvasCssHeight(
  cssWidth: number,
  imageW: number,
  imageH: number,
  viewportH: number,
  cap: number,
): number {
  return Math.min((cssWidth * imageH) / imageW, cap * viewportH);
}

/** Pointer position → image fraction. Unclamped: values outside [0, 1] are letterbox. */
export function pointerToFraction(
  clientX: number,
  clientY: number,
  canvasRect: { left: number; top: number },
  fit: DrawRect,
): Point {
  return {
    x: (clientX - canvasRect.left - fit.offsetX) / fit.drawW,
    y: (clientY - canvasRect.top - fit.offsetY) / fit.drawH,
  };
}

export function isOnImage(p: Point): boolean {
  return p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1;
}

export function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}

export function clampPoint(p: Point): Point {
  return { x: clamp01(p.x), y: clamp01(p.y) };
}

export function fractionToCanvas(p: Point, fit: DrawRect): Point {
  return { x: fit.offsetX + p.x * fit.drawW, y: fit.offsetY + p.y * fit.drawH };
}

/** Same formula as the server's map_pin_distance: result in image-width units. */
export function mapPinDistance(
  imageW: number,
  imageH: number,
  target: Point,
  click: Point,
): number {
  const aspect = imageW / imageH;
  const dx = click.x - target.x;
  const dy = (click.y - target.y) / aspect;
  return Math.hypot(dx, dy);
}

/** Same as the server's map_pin_fraction: 1 within full, linear to 0 at zero. */
export function mapPinFraction(d: number, fullRadius: number, zeroRadius: number): number {
  if (d <= fullRadius) return 1;
  if (d >= zeroRadius) return 0;
  return 1 - (d - fullRadius) / (zeroRadius - fullRadius);
}

// ---------------------------------------------------------------------------
// Colours (T9 spec §4.13): the invariant --map-* tokens in theme.css
// ---------------------------------------------------------------------------

export type MapColorName =
  | 'full'
  | 'full-fill'
  | 'zero'
  | 'pin'
  | 'pin-disabled'
  | 'heat'
  | 'outline';

const mapChannels = new Map<MapColorName, string>();
const missingReported = new Set<MapColorName>();

/**
 * A map-overlay colour, `rgb(R G B / alpha)`, from the `--map-<name>` token. The tokens are
 * the same in both themes (overlays sit on the map image, not the page), so each value is
 * read once and cached; the heatmap draws many dots. An empty value means theme.css wasn't
 * imported: log once per name, return 'transparent' and don't cache, so the next call retries.
 */
export function mapColor(name: MapColorName, alpha = 1): string {
  let channels = mapChannels.get(name);
  if (channels === undefined) {
    channels = getComputedStyle(document.documentElement)
      .getPropertyValue(`--map-${name}`)
      .trim();
    if (!channels) {
      if (!missingReported.has(name)) {
        missingReported.add(name);
        console.error(`mapColor: --map-${name} is not defined (is theme.css imported?)`);
      }
      return 'transparent';
    }
    mapChannels.set(name, channels);
  }
  return `rgb(${channels} / ${alpha})`;
}

// ---------------------------------------------------------------------------
// Drawing (coordinates in CSS pixels; the caller has scaled for devicePixelRatio)
// ---------------------------------------------------------------------------

/** Target dot plus the fullRadius (solid) and zeroRadius (dashed) circles. */
export function drawTarget(
  ctx: CanvasRenderingContext2D,
  fit: DrawRect,
  target: Point,
  fullRadius: number,
  zeroRadius: number,
): void {
  const c = fractionToCanvas(target, fit);
  ctx.save();
  ctx.beginPath();
  ctx.arc(c.x, c.y, zeroRadius * fit.drawW, 0, Math.PI * 2);
  ctx.setLineDash([6, 5]);
  ctx.lineWidth = 2;
  ctx.strokeStyle = mapColor('zero', 0.95);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.beginPath();
  ctx.arc(c.x, c.y, fullRadius * fit.drawW, 0, Math.PI * 2);
  ctx.fillStyle = mapColor('full-fill', 0.25);
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = mapColor('full');
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(c.x, c.y, 4, 0, Math.PI * 2);
  ctx.fillStyle = mapColor('full');
  ctx.fill();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = mapColor('outline');
  ctx.stroke();
  ctx.restore();
}

/** A map marker whose tip sits exactly at `p`. `color` defaults to the map-pin token. */
export function drawPin(
  ctx: CanvasRenderingContext2D,
  fit: DrawRect,
  p: Point,
  color?: string,
): void {
  const { x, y } = fractionToCanvas(p, fit);
  const r = 9;
  const head = y - 22;
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x - r * 0.8, head + r * 0.6);
  ctx.arc(x, head, r, Math.PI * 0.8, Math.PI * 0.2);
  ctx.closePath();
  ctx.fillStyle = color ?? mapColor('pin');
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = mapColor('outline');
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(x, head, r * 0.35, 0, Math.PI * 2);
  ctx.fillStyle = mapColor('outline');
  ctx.fill();
  ctx.restore();
}
