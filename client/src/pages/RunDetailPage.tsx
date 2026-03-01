import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { ArtifactsPanel } from "../components/run/ArtifactsPanel";
import { StageTimeline } from "../components/run/StageTimeline";
import { Card } from "../components/ui/Card";
import { ProgressBar } from "../components/ui/ProgressBar";
import { SectionHeader } from "../components/ui/SectionHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import { apiClient } from "../lib/apiClient";
import { formatDateTime } from "../lib/utils";
import type { Project, RunDetail } from "../types/api";

function shouldPoll(run: RunDetail | null) {
  if (!run) {
    return false;
  }

  return run.status === "queued" || run.status === "running" || run.stages.some((stage) => stage.status === "pending" || stage.status === "running");
}

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const { session } = useAuth();
  const { notify } = useToast();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session || !runId) {
      return;
    }

    let active = true;

    async function loadRun() {
      setLoading(true);
      try {
        const [runData, projects] = await Promise.all([
          apiClient.getRun(session.access_token, runId),
          apiClient.listProjects(session.access_token),
        ]);

        if (!active) {
          return;
        }

        setRun(runData);
        setProject(projects.find((entry) => entry.id === runData.project_id) ?? null);
      } catch (err) {
        if (!active) {
          return;
        }

        notify({
          title: "Unable to load run",
          description: err instanceof Error ? err.message : "Request failed",
          tone: "error",
        });
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadRun();

    return () => {
      active = false;
    };
  }, [notify, runId, session]);

  useEffect(() => {
    if (!session || !runId || !shouldPoll(run)) {
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        const latest = await apiClient.getRun(session.access_token, runId);
        setRun(latest);
      } catch {
        return;
      }
    }, 2500);

    return () => window.clearInterval(timer);
  }, [run, runId, session]);

  const errorMessage = useMemo(() => run?.stages.find((stage) => stage.error_message)?.error_message, [run]);

  async function copyValue(label: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      notify({ title: `${label} copied`, description: "Value copied to clipboard.", tone: "success" });
    } catch {
      notify({ title: "Copy failed", description: "Clipboard access was unavailable.", tone: "error" });
    }
  }

  if (loading) {
    return (
      <div className="grid gap-6">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-72 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (!run) {
    return (
      <Card className="p-8">
        <h1 className="text-2xl font-semibold text-ink">Run not found</h1>
        <p className="mt-3 text-sm leading-6 text-muted">The requested run could not be loaded from the API.</p>
      </Card>
    );
  }

  return (
    <div className="grid gap-8">
      <SectionHeader
        eyebrow="Run detail"
        title={project ? `${project.name} execution` : "Run execution"}
        description="Monitor ingest and discover progress, resolved commit metadata, and immutable snapshot details for this run."
        actions={<StatusBadge status={run.status} className="text-[11px]" />}
      />

      <Card className="p-6 md:p-8">
        <div className="grid gap-8 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="grid gap-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Repository</p>
                <p className="mt-2 break-all text-sm text-ink">{project?.repo_url ?? "Not available"}</p>
              </div>
              <div>
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Requested ref</p>
                <p className="mt-2 text-sm text-ink">{run.ref_requested}</p>
              </div>
              <div>
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Resolved commit</p>
                <p className="mt-2 break-all text-sm text-ink">{run.ref_resolved ?? "Awaiting ingest completion"}</p>
              </div>
              <div>
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Created</p>
                <p className="mt-2 text-sm text-ink">{formatDateTime(run.created_at)}</p>
              </div>
            </div>
            <div className="rounded-3xl border border-line bg-canvas px-5 py-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Progress</p>
                  <p className="mt-2 text-3xl font-semibold text-ink">{run.progress_percent}%</p>
                </div>
                <p className="m-0 text-sm text-muted">Progress is weighted evenly across ingest and discover.</p>
              </div>
              <div className="mt-5">
                <ProgressBar value={run.progress_percent} />
              </div>
            </div>
          </div>
          <div className="rounded-3xl border border-accent/15 bg-accent-50/60 p-6">
            <p className="m-0 text-xs font-semibold uppercase tracking-[0.24em] text-accent-700">Run summary</p>
            <div className="mt-5 grid gap-4 text-sm">
              <div>
                <p className="m-0 text-muted">Started</p>
                <p className="mt-1 font-medium text-ink">{formatDateTime(run.started_at)}</p>
              </div>
              <div>
                <p className="m-0 text-muted">Finished</p>
                <p className="mt-1 font-medium text-ink">{formatDateTime(run.finished_at)}</p>
              </div>
              <div>
                <p className="m-0 text-muted">Run ID</p>
                <p className="mt-1 break-all font-medium text-ink">{run.id}</p>
              </div>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-8 2xl:grid-cols-[1.15fr_0.85fr]">
        <StageTimeline stages={run.stages} />
        <ArtifactsPanel snapshot={run.snapshot} onCopy={copyValue} />
      </div>

      {errorMessage ? (
        <Card className="border-red-200 bg-red-50 p-6">
          <p className="m-0 text-xs font-semibold uppercase tracking-[0.24em] text-red-700">Error</p>
          <h2 className="mt-2 text-2xl font-semibold text-red-900">Execution failed</h2>
          <p className="mt-3 text-sm leading-6 text-red-800">{errorMessage}</p>
        </Card>
      ) : null}
    </div>
  );
}
