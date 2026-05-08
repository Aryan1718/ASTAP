import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiClient } from "../../lib/apiClient";
import { cn } from "../../lib/utils";
import type { ExecutionLog, ExecutionSuite, ExecutionSummary, RunDetail } from "../../types/api";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Skeleton } from "../ui/Skeleton";
import { StatusBadge } from "../ui/StatusBadge";

type ExecutionSummaryPanelProps = {
  token: string;
  run: RunDetail;
  showOpenPageButton?: boolean;
};

const suiteOrder = ["existing", "generated", "combined"] as const;

function findStage(run: RunDetail, stageName: string) {
  return run.stages.find((stage) => stage.stage === stageName);
}

function formatDuration(value?: number | null) {
  if (value == null) {
    return "Not available";
  }
  return `${value.toFixed(value >= 10 ? 0 : 2)}s`;
}

function suiteLabel(suiteKey: string) {
  return suiteKey.replace(/_/g, " ");
}

export function ExecutionSummaryPanel({ token, run, showOpenPageButton = true }: ExecutionSummaryPanelProps) {
  const navigate = useNavigate();
  const executeStage = useMemo(() => findStage(run, "execute_tests"), [run]);
  const [summary, setSummary] = useState<ExecutionSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [selectedSuite, setSelectedSuite] = useState<string>("existing");
  const [activeLog, setActiveLog] = useState<ExecutionLog | null>(null);
  const [logLoading, setLogLoading] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);

  async function loadLog(suiteKey: string) {
    setLogLoading(true);
    setLogError(null);
    try {
      const payload = await apiClient.getExecutionLog(token, run.id, suiteKey);
      setActiveLog(payload);
    } catch (error) {
      setActiveLog(null);
      setLogError(error instanceof Error ? error.message : "Unable to load execution log");
    } finally {
      setLogLoading(false);
    }
  }

  useEffect(() => {
    if (executeStage?.status !== "succeeded") {
      setSummary(null);
      setSummaryError(null);
      return;
    }

    let active = true;
    setSummaryLoading(true);
    setSummaryError(null);
    void apiClient
      .getExecutionSummary(token, run.id)
      .then((payload) => {
        if (!active) {
          return;
        }
        setSummary(payload);
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setSummary(null);
        setSummaryError(error instanceof Error ? error.message : "Unable to load execution summary");
      })
      .finally(() => {
        if (active) {
          setSummaryLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [executeStage?.status, run.id, token]);

  const suites = useMemo(() => {
    if (!summary) {
      return [];
    }
    const items: ExecutionSuite[] = [];
    for (const suiteKey of suiteOrder) {
      const suite =
        suiteKey === "existing"
          ? summary.existing_tests
          : suiteKey === "generated"
            ? summary.generated_tests
            : summary.combined_tests;
      if (suite) {
        items.push(suite);
      }
    }
    return items;
  }, [summary]);

  useEffect(() => {
    if (!suites.length) {
      setSelectedSuite("existing");
      return;
    }
    if (!suites.some((suite) => suite.suite_key === selectedSuite)) {
      setSelectedSuite(suites[0].suite_key);
    }
  }, [selectedSuite, suites]);

  useEffect(() => {
    if (!summary || !selectedSuite) {
      setActiveLog(null);
      setLogError(null);
      return;
    }

    const selectedSummary = suites.find((suite) => suite.suite_key === selectedSuite);
    if (!selectedSummary?.log_path) {
      setActiveLog(null);
      setLogError(null);
      return;
    }

    let active = true;
    setLogLoading(true);
    setLogError(null);
    void apiClient
      .getExecutionLog(token, run.id, selectedSuite)
      .then((payload) => {
        if (!active) {
          return;
        }
        setActiveLog(payload);
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        setActiveLog(null);
        setLogError(error instanceof Error ? error.message : "Unable to load execution log");
      })
      .finally(() => {
        if (active) {
          setLogLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [run.id, selectedSuite, suites, summary, token]);

  return (
    <Card className="p-6 md:p-8">
      <div className="border-b border-line/80 pb-6">
        <p className="section-eyebrow">Execution</p>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 flex-1">
            <h2 className="mt-2 text-[2rem] leading-tight text-ink" style={{ fontWeight: 460 }}>
              Test execution summary
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted">
              Compare baseline repository tests against ASTAP generated tests and inspect the captured logs.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {showOpenPageButton ? (
              <Button variant="ghost" className="px-4 py-2 text-sm" onClick={() => navigate(`/app/runs/${run.id}/execution`)}>
                Open execution page
              </Button>
            ) : null}
            {summary?.overall_result ? <StatusBadge status={summary.overall_result} className="text-[11px]" /> : null}
          </div>
        </div>
      </div>

      {executeStage?.status === "pending" || executeStage?.status === "running" ? (
        <div className="mt-6 border border-dashed border-line px-5 py-6 text-sm text-muted">
          `execute_tests` is still running. Suite results and logs will appear here when execution finishes.
        </div>
      ) : null}

      {executeStage?.status === "failed" ? (
        <div className="mt-6 rounded-2xl border border-line bg-[#f7efee] px-5 py-6 text-sm text-ink">
          The `execute_tests` stage failed before a complete summary could be published.
        </div>
      ) : null}

      {summaryLoading ? (
        <div className="mt-6 grid gap-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}

      {!summaryLoading && summaryError ? (
        <div className="mt-6 rounded-2xl border border-line bg-[#f7efee] px-5 py-6 text-sm text-ink">{summaryError}</div>
      ) : null}

      {!summaryLoading && !summaryError && summary ? (
        <div className="mt-6 grid gap-6 min-w-0">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            {suites.map((suite) => {
              const isSelected = selectedSuite === suite.suite_key;
              return (
                <button
                  key={suite.suite_key}
                  type="button"
                  className={cn(
                    "min-w-0 border p-5 text-left transition",
                    isSelected ? "border-[#cbb7fb] bg-[#f4eefc]" : "border-line bg-transparent hover:bg-[#fbf8f5]"
                  )}
                  onClick={() => setSelectedSuite(suite.suite_key)}
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="m-0 text-xs font-semibold uppercase tracking-[0.18em] text-muted">{suiteLabel(suite.suite_key)}</p>
                    <StatusBadge status={suite.status} className="text-[10px]" />
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-ink">
                    <div>
                      <p className="m-0 text-muted">Passed</p>
                      <p className="mt-1 font-medium">{suite.passed}</p>
                    </div>
                    <div>
                      <p className="m-0 text-muted">Failed</p>
                      <p className="mt-1 font-medium">{suite.failed}</p>
                    </div>
                    <div>
                      <p className="m-0 text-muted">Errors</p>
                      <p className="mt-1 font-medium">{suite.errors}</p>
                    </div>
                    <div>
                      <p className="m-0 text-muted">Skipped</p>
                      <p className="mt-1 font-medium">{suite.skipped}</p>
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-5 text-sm text-muted">
                    <span>Collected {suite.collected}</span>
                    <span>Exit code {suite.exit_code ?? "n/a"}</span>
                    <span>{formatDuration(suite.duration_seconds)}</span>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <div className="min-w-0 border border-line px-5 py-5">
              <p className="m-0 text-xs font-semibold uppercase tracking-[0.18em] text-muted">Environment</p>
              <div className="mt-4 grid gap-4 text-sm">
                <div>
                  <p className="m-0 text-muted">Framework</p>
                  <p className="mt-1 text-ink">{summary.framework}</p>
                </div>
                <div>
                  <p className="m-0 text-muted">Python version</p>
                  <p className="mt-1 text-ink">{summary.environment?.python_version ?? "Not available"}</p>
                </div>
                <div>
                  <p className="m-0 text-muted">Execution image</p>
                  <p className="mt-1 break-all text-ink">{summary.environment?.execution_image ?? "Not available"}</p>
                </div>
                <div>
                  <p className="m-0 text-muted">Generated tests root</p>
                  <p className="mt-1 text-ink">{summary.environment?.generated_tests_root ?? "Not available"}</p>
                </div>
              </div>
            </div>

            <div className="min-w-0 border border-line px-5 py-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="m-0 text-xs font-semibold uppercase tracking-[0.18em] text-muted">Logs</p>
                  <p className="mt-2 text-sm text-muted">
                    {selectedSuite ? `Showing ${suiteLabel(selectedSuite)} suite output.` : "Select a suite to inspect execution output."}
                  </p>
                </div>
                {selectedSuite ? (
                  <Button variant="ghost" className="px-3 py-2 text-xs" onClick={() => void loadLog(selectedSuite)}>
                    Refresh log
                  </Button>
                ) : null}
              </div>
              {logLoading ? <Skeleton className="mt-4 h-64 w-full" /> : null}
              {!logLoading && logError ? (
                <div className="mt-4 rounded-2xl border border-line bg-[#f7efee] px-4 py-4 text-sm text-ink">{logError}</div>
              ) : null}
              {!logLoading && !logError ? (
                <pre className="mt-4 min-w-0 max-h-[28rem] overflow-auto rounded-2xl border border-line bg-[#fbf8f5] p-4 text-xs leading-6 text-ink">
                  {activeLog?.content ?? "No log available for the selected suite."}
                </pre>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </Card>
  );
}
