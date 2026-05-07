import { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "../../lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: Variant;
};

export function Button({ children, className, variant = "primary", ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex min-h-11 items-center justify-center rounded-lg px-6 py-3 font-display text-base leading-none transition duration-200 focus-ring disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" && "border border-transparent bg-cream text-ink hover:opacity-90",
        variant === "secondary" && "border border-ink bg-ink text-white hover:opacity-92",
        variant === "ghost" && "border border-line bg-transparent text-ink hover:border-ink hover:bg-[#f7f3ee]",
        variant === "danger" && "border border-line bg-transparent text-ink hover:border-ink hover:bg-[#f4efea]",
        className
      )}
      style={{ fontWeight: variant === "primary" || variant === "secondary" ? 700 : 600 }}
      {...props}
    >
      {children}
    </button>
  );
}
