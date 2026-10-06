import { cn } from '../../lib/utils';

type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export function Input({ className, ...props }: InputProps) {
  return (
    <input
      className={cn(
        'w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2',
        'text-fg',
        className
      )}
      {...props}
    />
  );
}
