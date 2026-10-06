import type { Config } from 'tailwindcss';

// Byte-identical in all three apps (scripts/check_theme.py checks it). The colour tokens are
// RGB-channel CSS variables defined in src/theme.css (docs/plans/t9-theming.md §4.3), so
// opacity modifiers such as bg-scrim/70 keep working.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const numbered = (prefix: string) =>
  Object.fromEntries([1, 2, 3, 4, 5, 6, 7, 8].map((n) => [n, token(`${prefix}-${n}`)]));

const tokens = {
  page: token('page'),
  surface: token('surface'),
  'surface-alt': token('surface-alt'),
  'surface-hover': token('surface-hover'),
  fg: token('fg'),
  'fg-muted': token('fg-muted'),
  line: token('line'),
  'line-strong': token('line-strong'),
  accent: token('accent'),
  'accent-hover': token('accent-hover'),
  'on-accent': token('on-accent'),
  'accent-fg': token('accent-fg'),
  'accent-soft': token('accent-soft'),
  focus: token('focus'),
  success: token('success'),
  'on-success': token('on-success'),
  'success-fg': token('success-fg'),
  'success-soft': token('success-soft'),
  danger: token('danger'),
  'danger-hover': token('danger-hover'),
  'on-danger': token('on-danger'),
  'danger-fg': token('danger-fg'),
  'danger-soft': token('danger-soft'),
  warning: token('warning'),
  'on-warning': token('on-warning'),
  'warning-fg': token('warning-fg'),
  'warning-soft': token('warning-soft'),
  'chart-track': token('chart-track'),
  'chart-bar': token('chart-bar'),
  'chart-correct': token('chart-correct'),
  'timer-ok': token('timer-ok'),
  'timer-warn': token('timer-warn'),
  'timer-low': token('timer-low'),
  answer: numbered('answer'),
  'on-answer': numbered('on-answer'),
  'map-full': token('map-full'),
  'map-full-fill': token('map-full-fill'),
  'map-zero': token('map-zero'),
  'map-pin': token('map-pin'),
  'map-pin-disabled': token('map-pin-disabled'),
  'map-heat': token('map-heat'),
  'map-outline': token('map-outline'),
  'qr-tile': token('qr-tile'),
  scrim: token('scrim'),
  'on-scrim': token('on-scrim'),
};

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    // The tokens replace Tailwind's palette, so a raw class such as bg-slate-800 compiles to
    // nothing (and no error). scripts/check_theme.py is what catches one.
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      inherit: 'inherit',
      ...tokens,
    },
    extend: {
      borderColor: { DEFAULT: token('line') },
      // Tailwind builds the default ring colour with withAlphaValue(), which can't parse an
      // <alpha-value> string and would fall back to a hardcoded blue. The function form works
      // at runtime but isn't in Tailwind's types, hence the cast.
      ringColor: {
        DEFAULT: (({ opacityValue }: { opacityValue?: string }) =>
          opacityValue === undefined
            ? 'rgb(var(--focus))'
            : `rgb(var(--focus) / ${opacityValue})`) as unknown as string,
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [],
} satisfies Config;
