import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ExecutionSummaryPanel } from "../components/run/ExecutionSummaryPanel";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";
import { useAuth } from "../hooks/useAuth";
import { apiClient } from "../lib/apiClient";
import { formatDateTime } from "../lib/utils";
import type { Project, RunDetail } from "../types/api";

function shouldPoll(run: RunDetail | null) {
  if (!run) {
    return false;
  }

  return (
    run.status === "queued" ||
    run.status === "running" ||
    run.stages.some((stage) => stage.status === "pending" || stage.status === "running")
  );
}

function findStage(run: RunDetail, stageName: string) {
  return run.stages.find((stage) => stage.stage === stageName) ?? null;
}

export function ExecutionReportPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const { session } = useAuth();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!session || !runId) {
      return;
    }

    let active = true;

    async function loadPage() {
      setLoading(true);
      setErrorMessage(null);

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

        setErrorMessage(err instanceof Error ? err.message : "Unable to load execution report");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadPage();

    return () => {
      active = false;
    };
  }, [runId, session]);

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
      <div className="grid gap-4">
        <Skeleton className="h-52 w-full rounded-2xl" />
        <Skeleton className="h-[56rem] w-full rounded-2xl" />
      </div>
    );
  }

  if (!run || !session) {
    return (
      <Card className="p-8">
        <h1 className="font-display text-[2rem] leading-[0.96] text-ink" style={{ fontWeight: 460 }}>
          Execution unavailable
        </h1>
        <p className="mt-3 text-base leading-6 text-muted">The requested run could not be loaded.</p>
      </Card>
    );
  }

  const executeStage = findStage(run, "execute_tests");

  return (
    <div className="grid gap-4">
      <section className="overflow-hidden rounded-2xl border border-white/20 bg-[#1b1938] text-white shadow-none">
        <div
          className="px-5 py-5 sm:px-6 md:px-8 md:py-7"
          style={{
            background:
              "radial-gradient(circle at top right, rgba(203, 183, 251, 0.2), transparent 30%), linear-gradient(135deg, #1b1938 0%, #231f47 52%, #1b1938 100%)",
          }}
        >
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0 flex-1">
              <p className="m-0 text-xs uppercase tracking-[0.28em] text-white/80">Execution report</p>
              <h1 className="mt-4 max-w-4xl font-display text-[36px] leading-[0.96] text-white md:text-[48px]" style={{ fontWeight: 540 }}>
                {project ? `${project.name} test execution` : "Test execution"}
              </h1>
              <p className="mt-4 max-w-3xl text-base leading-6 text-white/80">
                A wider view for baseline and generated suite results, environment details, and captured logs without the run page constraints.
              </p>
            </div>
            <div className="grid gap-2 text-sm text-white/80">
              <div>
                <p className="m-0 uppercase tracking-[0.12em]">Project</p>
                <p className="mt-1 text-white">{project ? project.name : "Execution report"}</p>
              </div>
              <div>
                <p className="m-0 uppercase tracking-[0.12em]">Finished</p>
                <p className="mt-1 text-white">{formatDateTime(run.finished_at)}</p>
              </div>
              <div className="flex flex-wrap gap-2 pt-2">
                {executeStage ? <StatusBadge status={executeStage.status} /> : null}
                <Button variant="primary" onClick={() => navigate(`/app/runs/${run.id}`)}>
                  Back to run
                </Button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {errorMessage ? (
        <Card className="p-8">
          <h2 className="font-display text-[2rem] leading-[0.96] text-ink" style={{ fontWeight: 460 }}>
            Execution unavailable
          </h2>
          <p className="mt-3 text-base leading-6 text-muted">{errorMessage}</p>
        </Card>
      ) : null}

      <Card className="px-5 py-5 md:px-8 md:py-7">
        <div className="flex flex-col gap-4 border-b border-line/80 pb-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <p className="section-eyebrow">Overview</p>
            <h2 className="mt-3 font-display text-[2rem] leading-[0.96] tracking-[-0.55px] text-ink md:text-[48px]" style={{ fontWeight: 460 }}>
              Suite comparison
            </h2>
            <p className="mt-3 max-w-3xl text-base leading-6 text-muted">
              This page isolates the execute stage so the cards, environment metadata, and logs stay readable at full width.
            </p>
          </div>
          <div className="grid gap-2 text-sm text-muted">
            <div>
              <p className="m-0 uppercase tracking-[0.12em]">Run status</p>
              <p className="mt-1 text-ink">{run.status}</p>
            </div>
            <div>
              <p className="m-0 uppercase tracking-[0.12em]">Requested ref</p>
              <p className="mt-1 break-all text-ink">{run.ref_requested}</p>
            </div>
            <div>
              <p className="m-0 uppercase tracking-[0.12em]">Resolved commit</p>
              <p className="mt-1 break-all text-ink">{run.ref_resolved ?? "Awaiting ingest completion"}</p>
            </div>
          </div>
        </div>
      </Card>

      <ExecutionSummaryPanel token={session.access_token} run={run} showOpenPageButton={false} />
    </div>
  );
}
