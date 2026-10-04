/**
 * Authenticated image loading for map-pin questions (T7 spec §4.9).
 *
 * Copied byte-for-byte into the player, host and admin apps; change all three
 * together. `<img src="/api/images/{id}">` can't work: the API needs the
 * `Authorization: Bearer` header from localStorage, and the refresh cookie is
 * scoped to /api/auth. So images are fetched with the header and shown via blob URLs.
 *
 * Self-contained (its own fetch) rather than going through lib/api.ts, whose
 * wrappers parse JSON and differ per app.
 */

const cache = new Map<string, Promise<HTMLImageElement>>();
let refreshing: Promise<void> | null = null;

function authHeader(): Record<string, string> {
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** One /auth/refresh at a time, shared by every image that got a 401. */
function refreshToken(): Promise<void> {
  if (!refreshing) {
    refreshing = (async () => {
      const res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' });
      if (!res.ok) throw new Error(`refresh failed: HTTP ${res.status}`);
      const body = (await res.json()) as { access_token?: string };
      if (!body.access_token) throw new Error('refresh failed: no token');
      localStorage.setItem('token', body.access_token);
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

async function fetchImage(imageId: string): Promise<Blob> {
  const url = `/api/images/${encodeURIComponent(imageId)}`;
  let res = await fetch(url, { headers: authHeader() });
  if (res.status === 401) {
    // The access token may have expired mid-game: refresh once, retry once.
    await refreshToken();
    res = await fetch(url, { headers: authHeader() });
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

function blobToImage(blob: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('image decode failed'));
    // Never revoked: images are immutable and cached for the page's lifetime.
    img.src = URL.createObjectURL(blob);
  });
}

/**
 * Load an image by ID. Caches the promise, so a preload and a render asking for the
 * same ID share one request; a failed load is evicted so a later call retries.
 */
export function loadImage(imageId: string): Promise<HTMLImageElement> {
  const cached = cache.get(imageId);
  if (cached) return cached;
  const promise = fetchImage(imageId).then(blobToImage);
  cache.set(imageId, promise);
  promise.catch(() => {
    if (cache.get(imageId) === promise) cache.delete(imageId);
  });
  return promise;
}

/** Fire-and-forget preload; errors are swallowed (the render path retries). */
export function preloadImages(imageIds: string[]): void {
  for (const id of imageIds) loadImage(id).catch(() => {});
}
