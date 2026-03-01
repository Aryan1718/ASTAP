import type { Project, RunListItem } from "../../types/api";
import { formatDateTime } from "../../lib/utils";
import { Button } from "../ui/Button";
import { Skeleton } from "../ui/Skeleton";
import { StatusBadge } from "../ui/StatusBadge";

type ProjectsTableProps = {
  projects: Project[];
  lastRuns: Record<string, RunListItem | undefined>;
  loading?: boolean;
  startingRunId?: string | null;
  onStartRun: (project: Project) => void;
  onOpenRun: (runId: string) => void;
};

export function ProjectsTable({ projects, lastRuns, loading, onStartRun, onOpenRun, startingRunId }: ProjectsTableProps) {
  if (loading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!projects.length) {
    return (
      <div className="flex min-h-80 flex-col items-center justify-center rounded-3xl border border-dashed border-line px-6 py-12 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-3xl bg-accent-50 text-lg font-semibold text-accent-700">GH</div>
        <h3 className="mt-5 text-2xl font-semibold text-ink">No GitHub projects yet</h3>
        <p className="mt-3 max-w-md text-sm leading-6 text-muted">
          Add your first repository to begin immutable pipeline runs and capture snapshot metadata.
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      {projects.map((project) => {
        const lastRun = lastRuns[project.id];

        return (
          <div key={project.id} className="rounded-3xl border border-line bg-white p-6 md:p-7">
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_220px] lg:items-start">
              <div className="min-w-0 flex-1">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="min-w-0">
                    <p className="m-0 text-2xl font-semibold text-ink">{project.name}</p>
                    <p className="mt-2 break-all text-sm leading-6 text-muted">{project.repo_url}</p>
                  </div>
                  <div className="rounded-full bg-accent-50 px-4 py-2 text-sm font-semibold text-accent-700">
                    {project.default_branch}
                  </div>
                </div>
                <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  <div className="rounded-2xl border border-line/80 bg-canvas px-4 py-4">
                    <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Project ID</p>
                    <p className="mt-2 text-sm font-medium text-ink">{project.id.slice(0, 8)}</p>
                  </div>
                  <div className="rounded-2xl border border-line/80 bg-canvas px-4 py-4">
                    <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Created</p>
                    <p className="mt-2 text-sm font-medium text-ink">{formatDateTime(project.created_at)}</p>
                  </div>
                  <div className="rounded-2xl border border-line/80 bg-canvas px-4 py-4">
                    <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Latest run</p>
                    <div className="mt-2 flex min-h-6 items-center gap-2">
                      {lastRun ? <StatusBadge status={lastRun.status} /> : <span className="text-sm text-muted">No runs yet</span>}
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex w-full flex-col gap-3 lg:self-stretch">
                <Button
                  disabled={startingRunId === project.id}
                  onClick={() => onStartRun(project)}
                  className="w-full justify-center"
                >
                  {startingRunId === project.id ? "Starting..." : "Start Run"}
                </Button>
                {lastRun ? (
                  <Button variant="secondary" onClick={() => onOpenRun(lastRun.id)} className="w-full justify-center">
                    View Latest Run
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
