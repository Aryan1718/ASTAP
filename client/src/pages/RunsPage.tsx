import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { RunsTable } from "../components/run/RunsTable";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { SectionHeader } from "../components/ui/SectionHeader";
import { StatusBadge } from "../components/ui/StatusBadge";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import { apiClient } from "../lib/apiClient";
import type { RunListItem } from "../types/api";

function shouldPoll(runs: RunListItem[]) {
  return runs.some((run) => run.status === "queued" || run.status === "running" || run.progress_percent < 100);
}

export function RunsPage() {
  const { session } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) {
      return;
    }

    let active = true;

    async function loadRuns() {
      try {
        const data = await apiClient.listRuns(session.access_token);
        if (!active) {
          return;
        }
        setRuns(data);
      } catch (err) {
        if (!active) {
          return;
        }
        notify({
          title: "Unable to load runs",
          description: err instanceof Error ? err.message : "Request failed",
          tone: "error",
        });
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadRuns();

    return () => {
      active = false;
    };
  }, [notify, session]);

  useEffect(() => {
    if (!session || !shouldPoll(runs)) {
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        const data = await apiClient.listRuns(session.access_token);
        setRuns(data);
      } catch {
        return;
      }
    }, 2500);

    return () => window.clearInterval(timer);
  }, [runs, session]);

  const queuedCount = runs.filter((run) => run.status === "queued").length;
  const runningCount = runs.filter((run) => run.status === "running").length;
  const completedCount = runs.filter((run) => run.status === "succeeded" || run.status === "failed" || run.status === "canceled").length;

  return (
    <div className="grid gap-8">
      <SectionHeader
        eyebrow="Runs"
        title="Run history"
        description="Every run created in this workspace remains available here, so you can reopen completed work after leaving the detail page."
        actions={
          <Button variant="ghost" onClick={() => navigate("/app/projects")}>
            Back to projects
          </Button>
        }
      />
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="p-5">
          <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Queued</p>
          <p className="mt-2 text-3xl font-semibold text-ink">{queuedCount}</p>
          <p className="mt-2 text-sm text-muted">Waiting for worker pickup.</p>
        </Card>
        <Card className="p-5">
          <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Running</p>
          <p className="mt-2 text-3xl font-semibold text-ink">{runningCount}</p>
          <p className="mt-2 text-sm text-muted">Active executions are polled automatically.</p>
        </Card>
        <Card className="p-5">
          <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Completed</p>
          <p className="mt-2 text-3xl font-semibold text-ink">{completedCount}</p>
          <div className="mt-2">
            <StatusBadge status={completedCount ? "succeeded" : "pending"} />
          </div>
        </Card>
      </div>
      <RunsTable runs={runs} loading={loading} onOpenRun={(runId) => navigate(`/app/runs/${runId}`)} />
    </div>
  );
}
