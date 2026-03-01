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
        "inline-flex items-center justify-center rounded-full px-4 py-2.5 text-sm font-semibold transition duration-200 focus:outline-none focus:ring-4 disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" && "bg-accent text-white shadow-soft hover:-translate-y-0.5 hover:shadow-panel focus:ring-accent/20",
        variant === "secondary" && "border border-accent/25 bg-accent-50 text-accent-700 hover:bg-accent-100 focus:ring-accent/15",
        variant === "ghost" && "border border-line bg-white text-ink hover:border-accent/40 hover:text-accent-700 focus:ring-accent/10",
        variant === "danger" && "bg-red-600 text-white hover:bg-red-700 focus:ring-red-200",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
