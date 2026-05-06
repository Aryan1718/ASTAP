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
      <span className="text-sm text-muted">{label}</span>
      <input
        ref={ref}
        id={id}
        className={cn(
          "focus-ring h-12 rounded-lg border border-line bg-white px-4 text-sm text-ink placeholder:text-muted",
          error && "border-[#b66f6f] focus:border-[#b66f6f] focus:ring-[#b66f6f]/25",
          className
        )}
        {...props}
      />
      {error ? <span className="text-sm text-[#8f4e4e]">{error}</span> : null}
      {!error && hint ? <span className="text-sm text-muted">{hint}</span> : null}
    </label>
  );
});
