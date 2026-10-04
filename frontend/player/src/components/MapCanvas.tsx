import { useEffect, useRef, useState } from 'react';
import { loadImage } from '../lib/images';
import {
  canvasCssHeight,
  clampPoint,
  containFit,
  isOnImage,
  pointerToFraction,
  type DrawRect,
  type Point,
} from '../lib/mapPin';

/**
 * Shared map-pin canvas (T7 spec §4.9): the image drawn contain-fit at full container
 * width, height capped at `heightCap` × viewport height, backing store scaled by
 * devicePixelRatio, redrawn on resize/orientation change. Loads the image through
 * lib/images.ts and shows "Loading map…" / "Couldn't load the map" + Retry.
 *
 * Copied into the player, host and admin apps; change all three together.
 */
export interface MapCanvasProps {
  imageId: string;
  /** From the question config, so layout doesn't jump when the image arrives. */
  imageWidth: number;
  imageHeight: number;
  /** Max CSS height as a fraction of viewport height: 0.6 on phones, 0.7 in editors. */
  heightCap?: number;
  /** Overlays, drawn after the image in CSS pixels. Re-run when its identity changes. */
  draw?: (ctx: CanvasRenderingContext2D, fit: DrawRect) => void;
  /**
   * Interactive mode. A gesture that starts on the image reports its point and then
   * every drag position, clamped to the image. Gestures starting in the letterbox
   * are ignored.
   */
  onPoint?: (p: Point) => void;
  disabled?: boolean;
  onLoadedChange?: (loaded: boolean) => void;
}

type Status = 'loading' | 'ready' | 'error';

export function MapCanvas({
  imageId,
  imageWidth,
  imageHeight,
  heightCap = 0.6,
  draw,
  onPoint,
  disabled = false,
  onLoadedChange,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const draggingRef = useRef(false);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [attempt, setAttempt] = useState(0);
  const [size, setSize] = useState({ width: 0, viewportH: window.innerHeight, dpr: 1 });

  useEffect(() => {
    let alive = true;
    setStatus('loading');
    setImage(null);
    onLoadedChange?.(false);
    loadImage(imageId)
      .then((img) => {
        if (!alive) return;
        setImage(img);
        setStatus('ready');
        onLoadedChange?.(true);
      })
      .catch(() => {
        if (alive) setStatus('error');
      });
    return () => {
      alive = false;
    };
    // onLoadedChange is a notification, not an input.
  }, [imageId, attempt]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () =>
      setSize({
        width: el.clientWidth,
        viewportH: window.innerHeight,
        dpr: window.devicePixelRatio || 1,
      });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    window.addEventListener('resize', measure);
    window.addEventListener('orientationchange', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
      window.removeEventListener('orientationchange', measure);
    };
  }, []);

  const imgW = image?.naturalWidth || imageWidth;
  const imgH = image?.naturalHeight || imageHeight;
  const cssW = size.width;
  const cssH = cssW > 0 ? canvasCssHeight(cssW, imgW, imgH, size.viewportH, heightCap) : 0;
  const fit = containFit(cssW, cssH, imgW, imgH);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || cssW <= 0 || cssH <= 0) return;
    canvas.width = Math.round(cssW * size.dpr);
    canvas.height = Math.round(cssH * size.dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(size.dpr, 0, 0, size.dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    if (!image) return;
    ctx.drawImage(image, fit.offsetX, fit.offsetY, fit.drawW, fit.drawH);
    draw?.(ctx, fit);
    // fit is derived from the listed values.
  }, [image, cssW, cssH, size.dpr, draw]);

  const interactive = !!onPoint && !disabled && status === 'ready';

  function pointAt(e: React.PointerEvent<HTMLCanvasElement>): Point {
    return pointerToFraction(e.clientX, e.clientY, e.currentTarget.getBoundingClientRect(), fit);
  }

  return (
    <div ref={containerRef} className="relative w-full select-none">
      <canvas
        ref={canvasRef}
        style={{
          width: '100%',
          height: cssH,
          display: 'block',
          touchAction: onPoint ? 'none' : 'auto',
          cursor: interactive ? 'crosshair' : 'default',
        }}
        className="rounded-xl bg-slate-800"
        onPointerDown={(e) => {
          if (!interactive) return;
          const p = pointAt(e);
          if (!isOnImage(p)) return; // started in the letterbox: ignore the gesture
          e.currentTarget.setPointerCapture(e.pointerId);
          draggingRef.current = true;
          onPoint!(clampPoint(p));
        }}
        onPointerMove={(e) => {
          if (!draggingRef.current || !interactive) return;
          onPoint!(clampPoint(pointAt(e))); // a drag never leaves the image
        }}
        onPointerUp={() => {
          draggingRef.current = false;
        }}
        onPointerCancel={() => {
          draggingRef.current = false;
        }}
      />
      {status === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center text-slate-400 text-sm">
          Loading map…
        </div>
      )}
      {status === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-sm">
          <p className="text-red-400">Couldn't load the map</p>
          <button
            type="button"
            onClick={() => setAttempt((n) => n + 1)}
            className="rounded-lg border border-slate-500 px-4 py-2 text-slate-200 hover:bg-slate-700"
          >
            Retry
          </button>
        </div>
      )}
    </div>
  );
}
