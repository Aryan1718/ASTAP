import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiClient } from "../../lib/apiClient";
import type { AnalysisSummary } from "../../types/api";
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

function AnalysisLoadingState({ runId }: { runId: string }) {
  const navigate = useNavigate();

  return (
    <Card className="p-6 md:p-8">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="section-eyebrow">Analysis</p>
          <Skeleton className="mt-3 h-8 w-56" />
          <Skeleton className="mt-3 h-5 w-full" />
          <Skeleton className="mt-2 h-5 w-5/6" />
        </div>
        <Button variant="ghost" className="px-4 py-2 text-sm" onClick={() => navigate(`/app/runs/${runId}/analysis`)}>
          Open analysis page
        </Button>
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

  const counts = useMemo(
    () =>
      summary
        ? [
            { label: "Baseline failures", value: summary.counts.existing_failed },
            { label: "Generated failures", value: summary.counts.generated_failed },
            { label: "High-signal findings", value: summary.counts.high_signal_failures },
            { label: "Low-signal findings", value: summary.counts.low_signal_failures },
          ]
        : [],
    [summary]
  );

  if (loadingSummary) {
    return <AnalysisLoadingState runId={runId} />;
  }

  if (summaryError) {
    return (
      <Card className="p-6 md:p-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <p className="section-eyebrow">Analysis</p>
            <h2 className="mt-2 text-[2rem] leading-tight text-ink" style={{ fontWeight: 460 }}>
              Analysis unavailable
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted">{summaryError}</p>
          </div>
          <Button variant="ghost" className="px-4 py-2 text-sm" onClick={() => navigate(`/app/runs/${runId}/analysis`)}>
            Open analysis page
          </Button>
        </div>
      </Card>
    );
  }

  if (!summary) {
    return (
      <Card className="p-6 md:p-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <p className="section-eyebrow">Analysis</p>
            <h2 className="mt-2 text-[2rem] leading-tight text-ink" style={{ fontWeight: 460 }}>
              Analysis pending
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted">{narrativeUnavailableMessage(stageStatus)}</p>
          </div>
          <Button variant="ghost" className="px-4 py-2 text-sm" onClick={() => navigate(`/app/runs/${runId}/analysis`)}>
            Open analysis page
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-6 md:p-8">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
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
        <div className="grid gap-3 text-sm text-muted">
          <Button variant="ghost" className="px-4 py-2 text-sm" onClick={() => navigate(`/app/runs/${runId}/analysis`)}>
            Open analysis page
          </Button>
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

      <div className="mt-8 rounded-2xl border border-line bg-white px-5 py-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="max-w-3xl">
            <p className="m-0 text-xs font-semibold uppercase tracking-[0.18em] text-muted">Open analysis</p>
            <p className="mt-2 text-sm leading-6 text-muted">
              View the full narrative, deterministic findings, and run-to-run history on the dedicated analysis page instead of rendering it inline here.
            </p>
          </div>
          <Button variant="ghost" className="px-4 py-2 text-sm" onClick={() => navigate(`/app/runs/${runId}/analysis`)}>
            Go to analysis page
          </Button>
        </div>
      </div>
    </Card>
  );
}
