import { InputHTMLAttributes } from "react";

export function Checkbox({
  label,
  hint,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  return (
    <label className={`flex items-start gap-3 text-sm text-muted ${className ?? ""}`}>
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 rounded border-line bg-white text-link focus:ring-accent/35"
        {...props}
      />
      <span className="grid gap-1">
        <span className="text-ink">{label}</span>
        {hint ? <span className="text-muted">{hint}</span> : null}
      </span>
    </label>
  );
}
