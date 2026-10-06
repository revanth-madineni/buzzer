import { cn } from '../../lib/utils';

type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export function Input({ className, ...props }: InputProps) {
  return (
    <input
      className={cn(
        'w-full rounded-xl border border-line-strong bg-surface-alt px-4 py-3',
        'text-fg text-base',
        className
      )}
      {...props}
    />
  );
}
