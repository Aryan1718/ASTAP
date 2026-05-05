import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { GeneratedTestsPanel } from "../components/run/GeneratedTestsPanel";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import { apiClient } from "../lib/apiClient";
import type { Project, RunDetail } from "../types/api";

function shouldPoll(run: RunDetail | null) {
  if (!run) {
    return false;
  }

  return run.status === "queued" || run.status === "running" || run.stages.some((stage) => stage.status === "pending" || stage.status === "running");
}

export function GeneratedTestsPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
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
          title: "Unable to load generated tests",
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

  if (loading) {
    return (
      <div className="grid gap-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-[42rem] w-full" />
      </div>
    );
  }

  if (!run || !session) {
    return (
      <Card className="p-8">
        <h1 className="text-2xl font-semibold text-ink">Generated tests unavailable</h1>
        <p className="mt-3 text-sm leading-6 text-muted">The requested run could not be loaded.</p>
      </Card>
    );
  }

  return (
    <div className="grid gap-3">
      <Card className="rounded-2xl border border-line bg-white px-4 py-3 shadow-soft">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="m-0 truncate text-sm font-semibold text-ink">
              {project ? `${project.name} generated tests` : "Generated tests"}
            </p>
            <p className="mt-1 truncate text-xs text-muted">Read-only explorer for generated Python test files</p>
          </div>
          <Button variant="ghost" onClick={() => navigate(`/app/runs/${run.id}`)}>
            Back to run
          </Button>
        </div>
      </Card>

      <GeneratedTestsPanel token={session.access_token} run={run} minimal />
    </div>
  );
}
