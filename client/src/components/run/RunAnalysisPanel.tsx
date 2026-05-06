import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiClient } from "../../lib/apiClient";
import { cn } from "../../lib/utils";
import type { AnalysisReport, AnalysisSummary } from "../../types/api";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Skeleton } from "../ui/Skeleton";
import { StatusBadge } from "../ui/StatusBadge";

type RunAnalysisPanelProps = {
  token: string;
  runId: string;
  stageStatus?: string | null;
};

function isPendingStatus(status?: string | null) {
  return status === "pending" || status === "running" || status === "retrying";
}

function assessmentLabel(value: string) {
  return {
    all_passed: "All passed",
    baseline_repo_failed: "Baseline repo failed",
    generated_tests_found_new_failures: "Generated tests found new failures",
    generated_tests_unrunnable: "Generated tests unrunnable",
    infrastructure_error: "Infrastructure error",
    mixed_results: "Mixed results",
  }[value] ?? value.replace(/_/g, " ");
}

function assessmentSummary(summary: AnalysisSummary) {
  const firstHighlight = summary.highlights[0]?.headline;
  if (firstHighlight) {
    return firstHighlight;
  }

  return {
    all_passed: "Existing and generated suites completed without any notable failures.",
    baseline_repo_failed: "The repository's own tests were already failing before generated findings were considered.",
    generated_tests_found_new_failures: "Generated tests found failures while the baseline suite still passed.",
    generated_tests_unrunnable: "Generated tests could not run cleanly, so findings may be incomplete.",
    infrastructure_error: "Environment setup failed before test execution completed.",
    mixed_results: "The run completed with a mix of baseline, generated, or setup signals.",
  }[summary.overall_assessment];
}

function narrativeUnavailableMessage(stageStatus?: string | null) {
  if (isPendingStatus(stageStatus)) {
    return "The analysis stage is still running. The narrative will appear after analysis artifacts are published.";
  }
  return "No LLM-written narrative was produced for this run.";
}

function findingTone(highlight: AnalysisSummary["highlights"][number]) {
  if (highlight.failure_category === "generated_test_issue" || highlight.confidence === "low") {
    return "border-line bg-[#fbf8f5]";
  }
  if (highlight.failure_category === "flaky_suspect") {
    return "border-line bg-[#f7f3ee]";
  }
  return "border-line bg-white";
}

function AnalysisLoadingState() {
  return (
    <Card className="p-6 md:p-8">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="section-eyebrow">Analysis</p>
          <Skeleton className="mt-3 h-8 w-56" />
          <Skeleton className="mt-3 h-5 w-full" />
          <Skeleton className="mt-2 h-5 w-5/6" />
        </div>
        <Skeleton className="h-8 w-24" />
      </div>
      <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    </Card>
  );
}

export function RunAnalysisPanel({ token, runId, stageStatus }: RunAnalysisPanelProps) {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<AnalysisSummary | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [loadingReport, setLoadingReport] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadSummary() {
      setLoadingSummary(true);
      setSummaryError(null);
      try {
        const payload = await apiClient.getAnalysisSummary(token, runId);
        if (!active) {
          return;
        }
        setSummary(payload);
      } catch (error) {
        if (!active) {
          return;
        }
        const message = error instanceof Error ? error.message : "Unable to load analysis";
        if (message === "Analysis results not available" || message === "Run not found") {
          setSummary(null);
          setSummaryError(null);
        } else {
          setSummary(null);
          setSummaryError(message);
        }
      } finally {
        if (active) {
          setLoadingSummary(false);
        }
      }
    }

    void loadSummary();

    return () => {
      active = false;
    };
  }, [runId, stageStatus, token]);

  useEffect(() => {
    let active = true;

    async function loadReport() {
      if (!summary?.llm_summary_available) {
        setReport(null);
        setReportError(null);
        setLoadingReport(false);
        return;
      }

      setLoadingReport(true);
      setReportError(null);
      try {
        const payload = await apiClient.getAnalysisReport(token, runId);
        if (!active) {
          return;
        }
        setReport(payload);
      } catch (error) {
        if (!active) {
          return;
        }
        setReport(null);
        setReportError(error instanceof Error ? error.message : "Unable to load analysis report");
      } finally {
        if (active) {
          setLoadingReport(false);
        }
      }
    }

    void loadReport();

    return () => {
      active = false;
    };
  }, [runId, summary?.llm_summary_available, token]);

  const counts = useMemo(
    () =>
      summary
        ? [
            { label: "Baseline failures", value: summary.counts.existing_failed },
            { label: "Generated failures", value: summary.counts.generated_failed },
            { label: "High-signal findings", value: summary.counts.high_signal_failures },
            { label: "Infrastructure errors", value: summary.counts.infrastructure_errors },
            { label: "Low-signal findings", value: summary.counts.low_signal_failures },
            { label: "Unrunnable failures", value: summary.counts.unrunnable_failures },
            { label: "Flaky suspects", value: summary.counts.flaky_suspects },
          ]
        : [],
    [summary]
  );

  if (loadingSummary) {
    return <AnalysisLoadingState />;
  }

  if (summaryError) {
    return (
      <Card className="p-6 md:p-8">
        <p className="section-eyebrow">Analysis</p>
        <h2 className="mt-2 text-[2rem] leading-tight text-ink" style={{ fontWeight: 460 }}>
          Analysis unavailable
        </h2>
        <p className="mt-3 text-sm leading-6 text-muted">{summaryError}</p>
      </Card>
    );
  }

  if (!summary) {
    return (
      <Card className="p-6 md:p-8">
        <p className="section-eyebrow">Analysis</p>
        <h2 className="mt-2 text-[2rem] leading-tight text-ink" style={{ fontWeight: 460 }}>
          Analysis pending
        </h2>
        <p className="mt-3 text-sm leading-6 text-muted">
          {narrativeUnavailableMessage(stageStatus)}
        </p>
      </Card>
    );
  }

  return (
    <Card className="p-6 md:p-8">
      <div className="flex flex-col gap-4 border-b border-line/80 pb-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <p className="section-eyebrow">Analysis</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <h2 className="m-0 text-[2rem] leading-tight text-ink" style={{ fontWeight: 460 }}>
              {assessmentLabel(summary.overall_assessment)}
            </h2>
            <StatusBadge status={summary.overall_assessment} />
          </div>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-muted">{assessmentSummary(summary)}</p>
        </div>
        <div className="grid gap-2 text-sm text-muted">
          <div>
            <p className="m-0 uppercase tracking-[0.12em]">Analyze stage</p>
            <p className="mt-1 text-ink">{summary.stage_status}</p>
          </div>
          <div>
            <p className="m-0 uppercase tracking-[0.12em]">Analysis mode</p>
            <p className="mt-1 text-ink">{summary.analysis_mode.replace(/_/g, " ")}</p>
          </div>
          <div>
            <p className="m-0 uppercase tracking-[0.12em]">Heuristics version</p>
            <p className="mt-1 text-ink">{summary.heuristics_version}</p>
          </div>
        </div>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
        {counts.map((item) => (
          <div key={item.label} className="rounded-2xl border border-line bg-[#fbf8f5] px-4 py-4">
            <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">{item.label}</p>
            <p className="mt-3 text-3xl text-ink" style={{ fontWeight: 460 }}>
              {item.value}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-8 grid gap-8 xl:grid-cols-[1.1fr_0.9fr]">
        <div>
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="m-0 text-xs font-semibold uppercase tracking-[0.18em] text-muted">Top findings</p>
              <p className="mt-2 text-sm leading-6 text-muted">Deterministic findings derived from the analyze stage artifacts.</p>
            </div>
          </div>

          <div className="mt-4 grid gap-4">
            {summary.highlights.length ? (
              summary.highlights.map((highlight, index) => (
                <div
                  key={`${highlight.headline}-${index}`}
                  className={cn("rounded-2xl border px-5 py-5", findingTone(highlight))}
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={highlight.priority} />
                        {highlight.suite ? <StatusBadge status={highlight.suite} /> : null}
                        <StatusBadge status={highlight.severity} />
                        <StatusBadge status={highlight.confidence} />
                        <StatusBadge status={highlight.failure_category} />
                      </div>
                      <h3 className="mt-3 text-lg leading-7 text-ink" style={{ fontWeight: 460 }}>
                        {highlight.headline}
                      </h3>
                      <p className="mt-2 text-sm leading-6 text-muted">
                        Confidence score {highlight.confidence_score.toFixed(2)}
                      </p>
                    </div>
                    {highlight.generated_test_file ? (
                      <Button
                        variant="ghost"
                        className="px-4 py-2 text-sm"
                        onClick={() =>
                          navigate(
                            `/app/runs/${runId}/generated-tests?path=${encodeURIComponent(highlight.generated_test_file ?? "")}`
                          )
                        }
                      >
                        View generated test
                      </Button>
                    ) : null}
                  </div>

                  <div className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
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

                  {highlight.risk_tags.length ? (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {highlight.risk_tags.map((tag) => (
                        <span
                          key={tag}
                          className="inline-flex rounded-lg border border-line bg-[#f7f3ee] px-3 py-1.5 text-[11px] font-display uppercase tracking-[0.12em] text-ink"
                          style={{ fontWeight: 600 }}
                        >
                          {tag.replace(/_/g, " ")}
                        </span>
                      ))}
                    </div>
                  ) : null}

                  {highlight.heuristic_tags.length ? (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {highlight.heuristic_tags.map((tag) => (
                        <span
                          key={tag}
                          className="inline-flex rounded-lg border border-line bg-white px-3 py-1.5 text-[11px] font-display uppercase tracking-[0.12em] text-muted"
                          style={{ fontWeight: 600 }}
                        >
                          {tag.replace(/_/g, " ")}
                        </span>
                      ))}
                    </div>
                  ) : null}

                  {highlight.evidence.length ? (
                    <ul className="mt-4 grid gap-2 pl-5 text-sm leading-6 text-muted">
                      {highlight.evidence.map((line, evidenceIndex) => (
                        <li key={`${highlight.headline}-evidence-${evidenceIndex}`} className="break-words">
                          {line}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-line bg-white px-5 py-5 text-sm leading-6 text-muted">
                No high-signal findings were extracted from this run.
              </div>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-line bg-[#fbf8f5] px-5 py-5">
          <p className="m-0 text-xs font-semibold uppercase tracking-[0.18em] text-muted">Narrative</p>
          <p className="mt-2 text-sm leading-6 text-muted">
            Optional LLM-written explanation layered on top of the deterministic summary.
          </p>

          {loadingReport ? <Skeleton className="mt-4 h-48 w-full" /> : null}

          {!loadingReport && report?.content ? (
            <pre
              className={cn(
                "mt-4 max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-2xl border border-line bg-white p-4 text-sm leading-6 text-ink",
                "font-sans"
              )}
            >
              {report.content}
            </pre>
          ) : null}

          {!loadingReport && !report?.content ? (
            <div className="mt-4 rounded-2xl border border-line bg-white px-4 py-4 text-sm leading-6 text-muted">
              {reportError ?? narrativeUnavailableMessage(summary.stage_status)}
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
