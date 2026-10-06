/**
 * An uploaded image shown by ID (T8 spec §4.10).
 *
 * Copied byte-for-byte into the player, host and admin apps; change all three
 * together. Loads through lib/images.ts (Bearer header, blob URL, shared cache), so a
 * preloaded image renders at once. Never crops (`object-contain`).
 */
import { useEffect, useState } from 'react';
import { loadImage } from '../lib/images';

interface AuthImageProps {
  imageId: string;
  alt: string;
  className?: string;
}

type LoadState = { status: 'loading' } | { status: 'ready'; src: string } | { status: 'error' };

export function AuthImage({ imageId, alt, className = '' }: AuthImageProps) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    let active = true;
    setState({ status: 'loading' });
    loadImage(imageId).then(
      (img) => {
        if (active) setState({ status: 'ready', src: img.src });
      },
      () => {
        if (active) setState({ status: 'error' });
      },
    );
    return () => {
      active = false;
    };
  }, [imageId]);

  if (state.status === 'ready') {
    return <img src={state.src} alt={alt} className={`object-contain ${className}`} />;
  }
  if (state.status === 'error') {
    return (
      <div
        className={`flex items-center justify-center rounded bg-surface-alt p-2 text-sm text-fg-muted ${className}`}
      >
        Image unavailable
      </div>
    );
  }
  return (
    <div className={`flex items-center justify-center rounded bg-surface-alt ${className}`}>
      <span className="sr-only">Loading image…</span>
    </div>
  );
}
