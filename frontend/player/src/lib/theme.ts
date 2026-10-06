import { useSyncExternalStore } from 'react';

// Light/dark theme store (docs/plans/t9-theming.md §4.8). Byte-identical in all three apps.
// index.html's inline script applies the theme before first paint using the same rules as
// getStored() / resolve() below; change both together.

export type Theme = 'light' | 'dark';

const DARK_QUERY = '(prefers-color-scheme: dark)';
const root = document.documentElement;
const listeners = new Set<() => void>();

// Each app's key is declared once, as <html data-theme-key>. Without it the choice is not
// persisted, rather than silently falling back to a key shared with the other apps.
let storageKey: string | null | undefined;

function getKey(): string | null {
  if (storageKey === undefined) {
    storageKey = root.dataset.themeKey || null;
    if (!storageKey) {
      console.error('theme: <html> has no data-theme-key, so the theme choice will not be saved');
    }
  }
  return storageKey;
}

// The explicit choice made during this page's life. It holds even when it can't be persisted,
// so the OS listener can't override it.
let sessionChoice: Theme | null = null;

function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark';
}

function getStored(): Theme | null {
  const key = getKey();
  if (key) {
    try {
      const value = localStorage.getItem(key);
      if (isTheme(value)) return value;
    } catch {
      // Storage unavailable: fall back to the session choice.
    }
  }
  return sessionChoice;
}

function systemTheme(): Theme {
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light';
}

function resolve(): Theme {
  return getStored() ?? systemTheme();
}

export function getTheme(): Theme {
  const current = root.dataset.theme;
  return isTheme(current) ? current : resolve();
}

function apply(theme: Theme): void {
  root.dataset.theme = theme;
  // The browser bar follows the page background. Read after data-theme changes, so this is
  // the new theme's value.
  const page = getComputedStyle(root).getPropertyValue('--page').trim();
  if (page) {
    let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'theme-color';
      document.head.appendChild(meta);
    }
    meta.content = `rgb(${page})`;
  }
  listeners.forEach((listener) => listener());
}

export function toggleTheme(): void {
  const next: Theme = getTheme() === 'dark' ? 'light' : 'dark';
  sessionChoice = next;
  const key = getKey();
  if (key) {
    try {
      localStorage.setItem(key, next);
    } catch {
      // Not persisted; sessionChoice keeps it for this page's life.
    }
  }
  apply(next);
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const theme = useSyncExternalStore(subscribe, getTheme);
  return { theme, toggle: toggleTheme };
}

/** Call once in main.tsx, before createRoot. Never call localStorage.clear() in any app. */
export function initTheme(): void {
  // Covers the case where the inline script failed.
  apply(resolve());
  // Follow the OS live until the user makes a choice.
  window.matchMedia(DARK_QUERY).addEventListener('change', () => {
    if (getStored() === null) apply(systemTheme());
  });
  // Keep tabs of the same app in step (e.g. the projector and a management tab).
  window.addEventListener('storage', (event) => {
    const key = getKey();
    if (key && event.key === key) apply(resolve());
  });
}
