import { cn } from "../../lib/utils";

type StatusBadgeProps = {
  status: string;
  className?: string;
};

const styles: Record<string, string> = {
  queued: "bg-white text-muted border-line",
  pending: "bg-white text-muted border-line",
  running: "bg-[#f4eefc] text-ink border-[#cbb7fb]",
  retrying: "bg-[#f4eefc] text-ink border-[#cbb7fb]",
  succeeded: "bg-[#f4eefc] text-ink border-[#cbb7fb]",
  passed: "bg-[#f4eefc] text-ink border-[#cbb7fb]",
  completed_successfully: "bg-[#f4eefc] text-ink border-[#cbb7fb]",
  failed: "bg-[#f7efee] text-ink border-line",
  completed_with_failures: "bg-[#f7efee] text-ink border-line",
  error: "bg-[#f7efee] text-ink border-line",
  skipped: "bg-white text-muted border-line",
  canceled: "bg-white text-muted border-line",
  critical: "bg-[#f7efee] text-ink border-line",
  high: "bg-[#f7f3ee] text-ink border-line",
  medium: "bg-[#fbf8f5] text-ink border-line",
  low: "bg-white text-muted border-line",
  product_failure: "bg-[#f7efee] text-ink border-line",
  baseline_failure: "bg-[#f7f3ee] text-ink border-line",
  generated_test_issue: "bg-white text-muted border-line",
  environment_issue: "bg-[#f7efee] text-ink border-line",
  flaky_suspect: "bg-[#fbf8f5] text-ink border-line",
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const normalized = status.toLowerCase();
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-lg border px-3 py-1.5 font-display text-[11px] uppercase tracking-[0.12em]",
        styles[normalized] ?? "border-line bg-white text-muted",
        className
      )}
      style={{ fontWeight: 600 }}
    >
      {normalized}
    </span>
  );
}
