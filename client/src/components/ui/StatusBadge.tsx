import { cn } from "../../lib/utils";

type StatusBadgeProps = {
  status: string;
  className?: string;
};

const styles: Record<string, string> = {
  queued: "bg-slate-100 text-slate-700 border-slate-200",
  pending: "bg-slate-100 text-slate-700 border-slate-200",
  running: "bg-accent-50 text-accent-700 border-accent-200",
  retrying: "bg-accent-50 text-accent-700 border-accent-200",
  succeeded: "bg-emerald-50 text-emerald-700 border-emerald-200",
  failed: "bg-red-50 text-red-700 border-red-200",
  canceled: "bg-slate-100 text-slate-700 border-slate-200",
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const normalized = status.toLowerCase();
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.16em]",
        styles[normalized] ?? "border-line bg-white text-muted",
        className
      )}
    >
      {normalized}
    </span>
  );
}
