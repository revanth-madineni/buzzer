import { useCallback } from 'react';
import { MapCanvas } from './MapCanvas';
import { drawPin, drawTarget, type DrawRect, type Point } from '../lib/mapPin';
import type { MapPinReveal } from '../types/game';

interface MapPinCanvasProps {
  imageId: string;
  imageWidth: number;
  imageHeight: number;
  /** Interactive mode: the placed pin (null until the first tap). */
  pin?: Point | null;
  onPinChange?: (p: Point) => void;
  disabled?: boolean;
  onLoadedChange?: (loaded: boolean) => void;
  /** Reveal mode (results): target + circles, plus the player's own pin if any. */
  reveal?: MapPinReveal;
  myPin?: Point | null;
}

/**
 * The player's map (T7 spec §4.10). Interactive: tap to place the pin, tap or drag
 * to move it; the parent submits on Confirm. Reveal: the same map with the target,
 * the fullRadius / zeroRadius circles and the player's pin.
 */
export function MapPinCanvas({
  imageId,
  imageWidth,
  imageHeight,
  pin = null,
  onPinChange,
  disabled = false,
  onLoadedChange,
  reveal,
  myPin = null,
}: MapPinCanvasProps) {
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, fit: DrawRect) => {
      if (reveal) {
        drawTarget(ctx, fit, reveal.target, reveal.fullRadius, reveal.zeroRadius);
        if (myPin) drawPin(ctx, fit, myPin);
      } else if (pin) {
        drawPin(ctx, fit, pin, disabled ? 'rgb(100, 116, 139)' : undefined);
      }
    },
    [reveal, myPin, pin, disabled],
  );

  return (
    <MapCanvas
      imageId={imageId}
      imageWidth={imageWidth}
      imageHeight={imageHeight}
      draw={draw}
      onPoint={reveal ? undefined : onPinChange}
      disabled={disabled}
      onLoadedChange={onLoadedChange}
    />
  );
}
