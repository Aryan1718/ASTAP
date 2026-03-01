import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { CreateProjectForm } from "../components/project/CreateProjectForm";
import { ProjectsTable } from "../components/project/ProjectsTable";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { SectionHeader } from "../components/ui/SectionHeader";
import { StatusBadge } from "../components/ui/StatusBadge";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import { apiClient } from "../lib/apiClient";
import { formatDateTime } from "../lib/utils";
import type { Project, RunListItem } from "../types/api";

function shouldPoll(runs: RunListItem[]) {
  return runs.some((run) => run.status === "queued" || run.status === "running" || run.progress_percent < 100);
}

export function ProjectsPage() {
  const { session } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [startingRunId, setStartingRunId] = useState<string | null>(null);

  useEffect(() => {
    async function loadProjects() {
      if (!session) {
        return;
      }

      setProjectsLoading(true);
      try {
        const [projectData, runData] = await Promise.all([
          apiClient.listProjects(session.access_token),
          apiClient.listRuns(session.access_token),
        ]);
        setProjects(projectData);
        setRuns(runData);
      } catch (err) {
        notify({
          title: "Unable to load projects",
          description: err instanceof Error ? err.message : "Request failed",
          tone: "error",
        });
      } finally {
        setProjectsLoading(false);
      }
    }

    void loadProjects();
  }, [notify, session]);

  useEffect(() => {
    if (!session || !shouldPoll(runs)) {
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        const runData = await apiClient.listRuns(session.access_token);
        setRuns(runData);
      } catch {
        return;
      }
    }, 2500);

    return () => window.clearInterval(timer);
  }, [runs, session]);

  async function handleCreateProject(payload: { name: string; repo_url: string; default_branch: string }) {
    if (!session) {
      return;
    }

    setCreating(true);
    try {
      const project = await apiClient.createProject(session.access_token, payload);
      setProjects((current) => [project, ...current]);
      notify({ title: "Project created", description: `${project.name} is ready for pipeline runs.`, tone: "success" });
    } catch (err) {
      notify({
        title: "Project creation failed",
        description: err instanceof Error ? err.message : "Request failed",
        tone: "error",
      });
      throw err;
    } finally {
      setCreating(false);
    }
  }

  async function handleStartRun(project: Project) {
    if (!session) {
      return;
    }

    setStartingRunId(project.id);
    try {
      const run = await apiClient.startRun(session.access_token, project.id, project.default_branch);
      const newRun: RunListItem = {
        id: run.run_id,
        project_id: run.project_id,
        project_name: project.name,
        status: run.status,
        ref_requested: run.ref_requested,
        created_at: run.created_at,
        progress_percent: 10,
      };
      setRuns((current) => [newRun, ...current]);
      notify({ title: "Run queued", description: `${project.name} pipeline run has been created.`, tone: "success" });
      navigate(`/app/runs/${run.run_id}`);
    } catch (err) {
      notify({
        title: "Unable to start run",
        description: err instanceof Error ? err.message : "Request failed",
        tone: "error",
      });
    } finally {
      setStartingRunId(null);
    }
  }

  const lastRuns = runs.reduce<Record<string, RunListItem | undefined>>((accumulator, run) => {
    if (!accumulator[run.project_id]) {
      accumulator[run.project_id] = run;
    }
    return accumulator;
  }, {});

  const recentRuns = runs.slice(0, 5);

  return (
    <div className="mx-auto grid w-full max-w-[1180px] gap-8">
      <SectionHeader
        eyebrow="GitHub Projects"
        title="Add a GitHub project and run the pipeline"
        description="Register repositories once, then launch and reopen pipeline executions from a much larger project workspace."
        actions={
          runs.length ? (
            <Button variant="ghost" onClick={() => navigate("/app/runs")}>
              View all runs
            </Button>
          ) : null
        }
      />
      <CreateProjectForm onSubmit={handleCreateProject} loading={creating} />
      <Card className="p-6 md:p-8">
        <div className="border-b border-line/80 pb-5">
          <p className="m-0 text-xs font-semibold uppercase tracking-[0.24em] text-accent">Project Library</p>
          <h2 className="mt-2 text-2xl font-semibold text-ink">Registered GitHub repositories</h2>
          <p className="mt-2 text-sm leading-6 text-muted">Start a new run or reopen the latest execution for each repository.</p>
        </div>
        <div className="mt-5">
          <ProjectsTable
            projects={projects}
            lastRuns={lastRuns}
            loading={projectsLoading}
            onOpenRun={(runId) => navigate(`/app/runs/${runId}`)}
            onStartRun={handleStartRun}
            startingRunId={startingRunId}
          />
        </div>
      </Card>
      <Card className="p-6 md:p-8">
        <div className="flex flex-col gap-3 border-b border-line/80 pb-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="m-0 text-xs font-semibold uppercase tracking-[0.24em] text-accent">Recent runs</p>
            <h2 className="mt-2 text-2xl font-semibold text-ink">Previously generated work stays visible</h2>
            <p className="mt-2 text-sm leading-6 text-muted">Open the latest executions directly from here without starting a new run.</p>
          </div>
          {runs.length ? (
            <Button variant="secondary" onClick={() => navigate("/app/runs")}>
              Open runs page
            </Button>
          ) : null}
        </div>
        {!recentRuns.length ? (
          <div className="py-10 text-center">
            <p className="m-0 text-sm text-muted">No runs have been created yet.</p>
          </div>
        ) : (
          <div className="mt-5 grid gap-3">
            {recentRuns.map((run) => (
              <button
                key={run.id}
                type="button"
                className="flex w-full flex-col gap-3 rounded-3xl border border-line bg-white px-5 py-4 text-left transition hover:border-accent/30 hover:bg-accent-50/40 md:flex-row md:items-center md:justify-between"
                onClick={() => navigate(`/app/runs/${run.id}`)}
              >
                <div>
                  <p className="m-0 text-base font-semibold text-ink">{run.project_name}</p>
                  <p className="mt-1 text-sm text-muted">
                    {run.ref_requested}
                    {run.ref_resolved ? ` • ${run.ref_resolved.slice(0, 12)}` : ""}
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <p className="m-0 text-sm text-muted">{formatDateTime(run.created_at)}</p>
                  <StatusBadge status={run.status} />
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
