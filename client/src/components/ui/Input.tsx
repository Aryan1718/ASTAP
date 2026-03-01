import { forwardRef, InputHTMLAttributes } from "react";

import { cn } from "../../lib/utils";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
  hint?: string;
};

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, error, hint, id, label, ...props },
  ref
) {
  return (
    <label className="grid gap-2">
      <span className="text-sm font-semibold text-ink">{label}</span>
      <input
        ref={ref}
        id={id}
        className={cn(
          "focus-ring h-12 rounded-2xl border border-line bg-white px-4 text-sm text-ink placeholder:text-muted/70",
          error && "border-red-300 focus:ring-red-100 focus:border-red-500",
          className
        )}
        {...props}
      />
      {error ? <span className="text-sm text-red-600">{error}</span> : null}
      {!error && hint ? <span className="text-sm text-muted">{hint}</span> : null}
    </label>
  );
});
