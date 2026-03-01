import type { RunListItem } from "../../types/api";
import { formatDateTime } from "../../lib/utils";
import { Button } from "../ui/Button";
import { ProgressBar } from "../ui/ProgressBar";
import { Skeleton } from "../ui/Skeleton";
import { StatusBadge } from "../ui/StatusBadge";

type RunsTableProps = {
  runs: RunListItem[];
  loading?: boolean;
  onOpenRun: (runId: string) => void;
};

export function RunsTable({ runs, loading, onOpenRun }: RunsTableProps) {
  if (loading) {
    return (
      <div className="surface overflow-hidden">
        <div className="grid gap-4 p-6">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      </div>
    );
  }

  if (!runs.length) {
    return (
      <div className="surface flex min-h-72 flex-col items-center justify-center px-6 py-10 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-3xl bg-accent-50 text-accent-700">02</div>
        <h3 className="mt-5 text-xl font-semibold text-ink">No runs yet</h3>
        <p className="mt-3 max-w-md text-sm leading-6 text-muted">
          Start a pipeline run from the Projects page and it will remain listed here even after you leave the detail screen.
        </p>
      </div>
    );
  }

  return (
    <div className="surface overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-left">
          <thead className="bg-canvas">
            <tr className="text-xs uppercase tracking-[0.16em] text-muted">
              <th className="px-6 py-4 font-semibold">Project</th>
              <th className="px-6 py-4 font-semibold">Status</th>
              <th className="px-6 py-4 font-semibold">Reference</th>
              <th className="px-6 py-4 font-semibold">Progress</th>
              <th className="px-6 py-4 font-semibold">Created</th>
              <th className="px-6 py-4 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-t border-line/70">
                <td className="px-6 py-5">
                  <div>
                    <p className="m-0 font-semibold text-ink">{run.project_name}</p>
                    <p className="mt-1 text-sm text-muted">{run.id.slice(0, 8)}</p>
                  </div>
                </td>
                <td className="px-6 py-5">
                  <StatusBadge status={run.status} />
                </td>
                <td className="px-6 py-5">
                  <p className="m-0 text-sm font-medium text-ink">{run.ref_requested}</p>
                  <p className="mt-1 break-all text-sm text-muted">{run.ref_resolved ?? "Awaiting commit resolution"}</p>
                </td>
                <td className="px-6 py-5">
                  <div className="min-w-40">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <span className="text-sm text-muted">Pipeline</span>
                      <span className="text-sm font-semibold text-ink">{run.progress_percent}%</span>
                    </div>
                    <ProgressBar value={run.progress_percent} />
                  </div>
                </td>
                <td className="px-6 py-5 text-sm text-muted">{formatDateTime(run.created_at)}</td>
                <td className="px-6 py-5 text-right">
                  <Button variant="secondary" onClick={() => onOpenRun(run.id)}>
                    Open run
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
