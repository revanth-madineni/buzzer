import { cn } from '../../lib/utils';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'ghost' | 'destructive';
  size?: 'sm' | 'md' | 'lg';
}

export function Button({ className, variant = 'default', size = 'md', ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-semibold transition-colors',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        variant === 'default' && 'bg-accent text-on-accent hover:bg-accent-hover',
        variant === 'outline' && 'border border-line-strong text-fg hover:bg-surface-hover',
        variant === 'ghost' && 'text-fg hover:bg-surface-hover',
        variant === 'destructive' && 'bg-danger text-on-danger hover:bg-danger-hover',
        size === 'sm' && 'px-3 py-1.5 text-sm',
        size === 'md' && 'px-4 py-2 text-base',
        size === 'lg' && 'px-6 py-3 text-lg',
        className
      )}
      {...props}
    />
  );
}
