import { formatDateTime } from "../../lib/utils";
import type { GeneratedTestManifest } from "../../types/api";
import { StatusBadge } from "../ui/StatusBadge";

type GeneratedTestsHeaderProps = {
  manifest: GeneratedTestManifest;
  runStatus: string;
  generatedCount: number;
  testCaseCount: number;
};

export function GeneratedTestsHeader({ manifest, runStatus, generatedCount, testCaseCount }: GeneratedTestsHeaderProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line/80 px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-lg border border-line bg-[#f7f3ee] px-3 py-1 font-display text-xs uppercase tracking-[0.12em] text-ink">
          Generated Tests
        </span>
        <p className="m-0 text-sm text-muted">
          <span className="font-medium text-ink">{generatedCount}</span> file{generatedCount === 1 ? "" : "s"}
        </p>
        <p className="m-0 text-sm text-muted">
          <span className="font-medium text-ink">{testCaseCount}</span> test case{testCaseCount === 1 ? "" : "s"}
        </p>
        <p className="m-0 text-sm text-muted">Generated {formatDateTime(manifest.generated_at)}</p>
      </div>
      <div className="flex items-center gap-3 text-sm text-muted">
        <span>Run</span>
        <StatusBadge status={runStatus} className="text-[10px]" />
      </div>
    </div>
  );
}
