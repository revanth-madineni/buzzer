import { Moon, Sun } from 'lucide-react';
import { useTheme } from '../lib/theme';
import { cn } from '../lib/utils';

interface ThemeToggleProps {
  /** Placement classes, merged over the base styling. */
  className?: string;
  showLabel?: boolean;
}

/**
 * Switches between the light and dark themes. Byte-identical in all three apps. The icon,
 * label and accessible name all name the theme it switches *to*.
 */
export function ThemeToggle({ className, showLabel = false }: ThemeToggleProps) {
  const { theme, toggle } = useTheme();
  const toDark = theme === 'light';
  const action = toDark ? 'Switch to dark theme' : 'Switch to light theme';
  const Icon = toDark ? Moon : Sun;
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={action}
      title={action}
      className={cn(
        'inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-lg text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg',
        showLabel && 'px-3',
        className,
      )}
    >
      <Icon size={20} aria-hidden="true" />
      {showLabel && <span className="text-sm font-medium">{toDark ? 'Dark theme' : 'Light theme'}</span>}
    </button>
  );
}
