import { InputHTMLAttributes } from "react";

export function Checkbox({
  label,
  hint,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  return (
    <label className={`flex items-start gap-3 text-sm text-ink ${className ?? ""}`}>
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 rounded border-line text-accent focus:ring-accent/20"
        {...props}
      />
      <span className="grid gap-1">
        <span className="font-medium">{label}</span>
        {hint ? <span className="text-muted">{hint}</span> : null}
      </span>
    </label>
  );
}
