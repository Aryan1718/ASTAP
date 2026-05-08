import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { MarkdownArticle } from "../components/ui/MarkdownArticle";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";
import { useAuth } from "../hooks/useAuth";
import { apiClient } from "../lib/apiClient";
import { formatDateTime } from "../lib/utils";
import type { AnalysisReport, AnalysisSummary, Project, RunDetail } from "../types/api";

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

export function AnalysisReportPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const { session } = useAuth();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [summary, setSummary] = useState<AnalysisSummary | null>(null);
  const [report, setReport] = useState<AnalysisReport | null>(null);
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
        const [runData, projects, summaryData] = await Promise.all([
          apiClient.getRun(session.access_token, runId),
          apiClient.listProjects(session.access_token),
          apiClient.getAnalysisSummary(session.access_token, runId),
        ]);

        if (!active) {
          return;
        }

        setRun(runData);
        setProject(projects.find((entry) => entry.id === runData.project_id) ?? null);
        setSummary(summaryData);

        if (summaryData.llm_summary_available) {
          const reportData = await apiClient.getAnalysisReport(session.access_token, runId);
          if (!active) {
            return;
          }
          setReport(reportData);
        } else {
          setReport(null);
        }
      } catch (err) {
        if (!active) {
          return;
        }

        setErrorMessage(err instanceof Error ? err.message : "Unable to load analysis report");
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
          Analysis unavailable
        </h1>
        <p className="mt-3 text-base leading-6 text-muted">The requested run could not be loaded.</p>
      </Card>
    );
  }

  if (errorMessage) {
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
                <p className="m-0 text-xs uppercase tracking-[0.28em] text-white/80">Analysis report</p>
                <h1 className="mt-4 font-display text-[36px] leading-[0.96] text-white md:text-[48px]" style={{ fontWeight: 540 }}>
                  {project ? `${project.name} analysis report` : "Analysis report"}
                </h1>
              </div>
              <div className="pt-2">
                <Button variant="primary" onClick={() => navigate(`/app/runs/${run.id}`)}>
                  Back to run
                </Button>
              </div>
            </div>
          </div>
        </section>

        <Card className="p-8">
          <h2 className="font-display text-[2rem] leading-[0.96] text-ink" style={{ fontWeight: 460 }}>
            Analysis unavailable
          </h2>
          <p className="mt-3 text-base leading-6 text-muted">{errorMessage}</p>
        </Card>
      </div>
    );
  }

  const overviewCards = summary
    ? [
        { label: "Baseline failures", value: summary.counts.existing_failed },
        { label: "Generated failures", value: summary.counts.generated_failed },
        { label: "High-signal findings", value: summary.counts.high_signal_failures },
        { label: "Low-signal findings", value: summary.counts.low_signal_failures },
      ]
    : [];

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
              <p className="m-0 text-xs uppercase tracking-[0.28em] text-white/80">Analysis report</p>
              <h1 className="mt-4 max-w-4xl font-display text-[36px] leading-[0.96] text-white md:text-[48px]" style={{ fontWeight: 540 }}>
                {summary?.overall_assessment?.replace(/_/g, " ") ?? "Narrative summary"}
              </h1>
              <p className="mt-4 max-w-3xl text-base leading-6 text-white/80">
                A calmer reading surface for the analyze stage, with the narrative, strongest findings, and run-to-run changes in one place.
              </p>
            </div>
            <div className="grid gap-2 text-sm text-white/80">
              <div>
                <p className="m-0 uppercase tracking-[0.12em]">Project</p>
                <p className="mt-1 text-white">{project ? project.name : "Analysis report"}</p>
              </div>
              <div>
                <p className="m-0 uppercase tracking-[0.12em]">Finished</p>
                <p className="mt-1 text-white">{formatDateTime(run.finished_at)}</p>
              </div>
              <div className="pt-2">
                <Button variant="primary" onClick={() => navigate(`/app/runs/${run.id}`)}>
                  Back to run
                </Button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <Card className="px-5 py-5 md:px-8 md:py-7">
        <div className="flex flex-col gap-4 border-b border-line/80 pb-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <p className="section-eyebrow">Overview</p>
            <h2 className="mt-3 font-display text-[2rem] leading-[0.96] tracking-[-0.55px] text-ink md:text-[48px]" style={{ fontWeight: 460 }}>
              Narrative summary
            </h2>
            <p className="mt-3 max-w-3xl text-base leading-6 text-muted">
              This page takes the analysis out of the crowded run detail so the explanation and history are easier to navigate.
            </p>
          </div>
          <div className="grid gap-2 text-sm text-muted">
            <div>
              <p className="m-0 uppercase tracking-[0.12em]">Analyze stage</p>
              <p className="mt-1 text-ink">{summary?.stage_status ?? "unknown"}</p>
            </div>
            <div>
              <p className="m-0 uppercase tracking-[0.12em]">Analysis mode</p>
              <p className="mt-1 text-ink">{summary?.analysis_mode?.replace(/_/g, " ") ?? "unknown"}</p>
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              <StatusBadge status={summary?.overall_assessment ?? "unknown"} />
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {overviewCards.map((item) => (
            <div key={item.label} className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4">
              <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">{item.label}</p>
              <p className="mt-3 font-display text-4xl leading-none text-ink" style={{ fontWeight: 460 }}>
                {item.value}
              </p>
            </div>
          ))}
        </div>
      </Card>

      <Card className="px-5 py-5 md:px-8 md:py-8">
        <div className="border-b border-line/80 pb-6">
          <p className="section-eyebrow">Narrative</p>
          <p className="mt-3 max-w-3xl text-base leading-6 text-muted">
            Optional LLM-written explanation layered on top of the deterministic summary.
          </p>
        </div>

        {report?.content ? (
          <div className="mt-8 rounded-2xl border border-line bg-white px-5 py-6 md:px-8">
            <MarkdownArticle content={report.content} />
          </div>
        ) : (
          <div className="mt-8 rounded-2xl border border-line bg-[#fbf8f5] px-5 py-5 text-base leading-6 text-muted">
            No LLM-written narrative was produced for this run.
          </div>
        )}
      </Card>

      <Card className="px-5 py-5 md:px-8 md:py-8">
        <div className="border-b border-line/80 pb-6">
          <p className="section-eyebrow">Highest-signal findings</p>
          <p className="mt-3 max-w-3xl text-base leading-6 text-muted">
            Deterministic findings derived from the analyze stage artifacts, ordered for faster triage.
          </p>
        </div>

        <div className="mt-6 grid gap-4">
          {summary?.highlights.length ? (
            summary.highlights.map((highlight, index) => (
              <div key={`${highlight.headline}-${index}`} className="rounded-2xl border border-line bg-[#fbf8f5] px-5 py-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={highlight.priority} />
                      {highlight.suite ? <StatusBadge status={highlight.suite} /> : null}
                      <StatusBadge status={highlight.severity} />
                      <StatusBadge status={highlight.confidence} />
                      <StatusBadge status={highlight.failure_category} />
                    </div>
                    <h3 className="mt-4 font-display text-[26px] leading-[1.14] tracking-[-0.63px] text-ink" style={{ fontWeight: 540 }}>
                      {highlight.headline}
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-muted">Confidence score {highlight.confidence_score.toFixed(2)}</p>
                  </div>
                  {highlight.generated_test_file ? (
                    <Button
                      variant="ghost"
                      className="px-4 py-2 text-sm"
                      onClick={() =>
                        navigate(`/app/runs/${run.id}/generated-tests?path=${encodeURIComponent(highlight.generated_test_file ?? "")}`)
                      }
                    >
                      View generated test
                    </Button>
                  ) : null}
                </div>

                <div className="mt-5 grid gap-4 text-sm sm:grid-cols-2">
                  <div>
                    <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Target</p>
                    <p className="mt-2 text-ink">{highlight.symbol ?? "Unmapped target"}</p>
                    <p className="mt-1 break-all text-muted">{highlight.source_file ?? "No source file mapping available"}</p>
                  </div>
                  <div>
                    <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Recipe</p>
                    <p className="mt-2 text-ink">{highlight.recipe_name ?? highlight.recipe_id ?? "Not applicable"}</p>
                    <p className="mt-1 break-all text-muted">{highlight.generated_test_file ?? "No generated test file recorded"}</p>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="rounded-2xl border border-line bg-[#fbf8f5] px-5 py-5 text-base leading-6 text-muted">
              No high-signal findings were extracted from this run.
            </div>
          )}
        </div>
      </Card>

      <Card className="px-5 py-5 md:px-8 md:py-8">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="section-eyebrow">What Changed</p>
            <p className="mt-3 max-w-3xl text-base leading-6 text-muted">
              Compare this run against the most recent earlier analyzed run for the same project.
            </p>
          </div>
          {summary?.trend.comparison_run ? (
            <div className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4 text-sm text-muted">
              <p className="m-0 uppercase tracking-[0.12em]">Compared with</p>
              <p className="mt-1 text-ink">{formatDateTime(summary.trend.comparison_run.created_at)}</p>
              <p className="mt-1 break-all text-muted">
                {summary.trend.comparison_run.ref_resolved ??
                  summary.trend.comparison_run.ref_requested ??
                  summary.trend.comparison_run.run_id}
              </p>
            </div>
          ) : null}
        </div>

        {summary?.trend.status === "available" ? (
          <>
            <p className="mt-6 text-base leading-6 text-ink">{summary.trend.headline}</p>

            <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4">
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">New findings</p>
                <p className="mt-3 font-display text-4xl leading-none text-ink" style={{ fontWeight: 460 }}>
                  {summary.trend.counts.new_findings}
                </p>
              </div>
              <div className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4">
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Recurring findings</p>
                <p className="mt-3 font-display text-4xl leading-none text-ink" style={{ fontWeight: 460 }}>
                  {summary.trend.counts.recurring_findings}
                </p>
              </div>
              <div className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4">
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Fixed findings</p>
                <p className="mt-3 font-display text-4xl leading-none text-ink" style={{ fontWeight: 460 }}>
                  {summary.trend.counts.fixed_findings}
                </p>
              </div>
              <div className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4">
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Recurring noise</p>
                <p className="mt-3 font-display text-4xl leading-none text-ink" style={{ fontWeight: 460 }}>
                  {summary.trend.counts.recurring_noise}
                </p>
              </div>
            </div>

            <div className="mt-6 grid gap-6 xl:grid-cols-2">
              <div>
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">New findings</p>
                <div className="mt-3 grid gap-3">
                  {summary.trend.new_findings.length ? (
                    summary.trend.new_findings.map((finding) => (
                      <div key={finding.fingerprint} className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={finding.severity} />
                          <StatusBadge status={finding.confidence} />
                          <StatusBadge status={finding.failure_category} />
                        </div>
                        <p className="mt-3 text-base leading-6 text-ink">{finding.headline}</p>
                        {finding.generated_test_file ? (
                          <Button
                            variant="ghost"
                            className="mt-2 px-0 py-0 text-sm"
                            onClick={() =>
                              navigate(
                                `/app/runs/${run.id}/generated-tests?path=${encodeURIComponent(finding.generated_test_file ?? "")}`
                              )
                            }
                          >
                            Open generated test
                          </Button>
                        ) : null}
                      </div>
                    ))
                  ) : (
                    <div className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4 text-base leading-6 text-muted">
                      No new findings were detected compared with the previous analyzed run.
                    </div>
                  )}
                </div>
              </div>

              <div>
                <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Fixed findings</p>
                <div className="mt-3 grid gap-3">
                  {summary.trend.fixed_findings.length ? (
                    summary.trend.fixed_findings.map((finding) => (
                      <div key={finding.fingerprint} className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={finding.severity} />
                          <StatusBadge status={finding.confidence} />
                          <StatusBadge status={finding.failure_category} />
                        </div>
                        <p className="mt-3 text-base leading-6 text-ink">{finding.headline}</p>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4 text-base leading-6 text-muted">
                      No prior findings were cleared compared with the previous analyzed run.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="mt-6 rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4 text-base leading-6 text-muted">
            {summary?.trend.headline ?? "No earlier analyzed run was available for comparison."}
          </div>
        )}
      </Card>
    </div>
  );
}
