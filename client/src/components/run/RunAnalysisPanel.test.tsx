import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RunAnalysisPanel } from "./RunAnalysisPanel";
import { apiClient } from "../../lib/apiClient";
import type { AnalysisReport, AnalysisSummary } from "../../types/api";

vi.mock("../../lib/apiClient", () => ({
  apiClient: {
    getAnalysisSummary: vi.fn(),
    getAnalysisReport: vi.fn(),
  },
}));

const mockApiClient = vi.mocked(apiClient);

function buildSummary(overrides: Partial<AnalysisSummary> = {}): AnalysisSummary {
  return {
    run_id: "run-123",
    stage_status: "succeeded",
    heuristics_version: 1,
    overall_assessment: "generated_tests_found_new_failures",
    baseline_repo_status: "passed",
    generated_tests_status: "failed",
    infrastructure_status: "ok",
    analysis_mode: "deterministic_plus_llm",
    llm_summary_available: true,
    counts: {
      existing_failed: 0,
      generated_failed: 1,
      high_signal_failures: 1,
      infrastructure_errors: 0,
      low_signal_failures: 0,
      unrunnable_failures: 0,
      flaky_suspects: 0,
    },
    highlights: [
      {
        kind: "generated_failure",
        priority: "high",
        headline: "Generated test for `parse_config` failed under `Path Traversal`.",
        severity: "high",
        confidence: "high",
        confidence_score: 0.96,
        failure_category: "product_failure",
        suite: "generated",
        test_name: "test_generated_path_traversal_signal",
        target_key: "abc123",
        symbol: "parse_config",
        source_file: "app/main.py",
        recipe_id: "path_traversal",
        recipe_name: "Path Traversal",
        generated_test_file: "generated_tests/security/test_parse_config_path_traversal_abc123.py",
        risk_tags: ["filesystem_access", "path_traversal_candidate"],
        heuristic_tags: ["baseline_suite_passed", "target_mapped"],
        evidence: ["AssertionError: expected sanitized path"],
      },
    ],
    artifacts: [],
    ...overrides,
  };
}

function buildReport(overrides: Partial<AnalysisReport> = {}): AnalysisReport {
  return {
    run_id: "run-123",
    path: "analyze/llm_summary.md",
    content: "# Run Analysis\n\n## Overall\nGenerated tests exposed a failure.\n",
    ...overrides,
  };
}

function renderPanel(stageStatus = "succeeded") {
  return render(
    <MemoryRouter initialEntries={["/app/runs/run-123"]}>
      <Routes>
        <Route path="/app/runs/:runId" element={<RunAnalysisPanel token="token" runId="run-123" stageStatus={stageStatus} />} />
        <Route path="/app/runs/:runId/generated-tests" element={<div>Generated tests route</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("RunAnalysisPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders the assessment, findings, and markdown narrative", async () => {
    mockApiClient.getAnalysisSummary.mockResolvedValue(buildSummary());
    mockApiClient.getAnalysisReport.mockResolvedValue(buildReport());

    renderPanel();

    expect(await screen.findByText("Generated tests found new failures")).toBeInTheDocument();
    expect(screen.getAllByText("Generated test for `parse_config` failed under `Path Traversal`.")).toHaveLength(2);
    expect(await screen.findByText("# Run Analysis", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("filesystem access")).toBeInTheDocument();
    expect(screen.getByText("confidence score 0.96", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Heuristics version")).toBeInTheDocument();
  });

  it("navigates to the generated tests page with the selected file path", async () => {
    mockApiClient.getAnalysisSummary.mockResolvedValue(buildSummary());
    mockApiClient.getAnalysisReport.mockResolvedValue(buildReport());

    renderPanel();

    await screen.findByText("Generated tests found new failures");
    await userEvent.click(screen.getByRole("button", { name: /view generated test/i }));

    await waitFor(() => {
      expect(screen.getByText("Generated tests route")).toBeInTheDocument();
    });
  });

  it("shows a pending state when analysis results are not ready yet", async () => {
    mockApiClient.getAnalysisSummary.mockRejectedValue(new Error("Analysis results not available"));

    renderPanel("running");

    expect(await screen.findByText("Analysis pending")).toBeInTheDocument();
    expect(screen.getByText(/analysis stage is still running/i)).toBeInTheDocument();
    expect(mockApiClient.getAnalysisReport).not.toHaveBeenCalled();
  });

  it("keeps deterministic analysis visible when the narrative request fails", async () => {
    mockApiClient.getAnalysisSummary.mockResolvedValue(buildSummary());
    mockApiClient.getAnalysisReport.mockRejectedValue(new Error("Analysis report not found"));

    renderPanel();

    expect(await screen.findByText("Generated tests found new failures")).toBeInTheDocument();
    expect(await screen.findByText("Analysis report not found")).toBeInTheDocument();
  });

  it("renders downgraded low-signal counters and heuristic tags", async () => {
    mockApiClient.getAnalysisSummary.mockResolvedValue(
      buildSummary({
        counts: {
          existing_failed: 0,
          generated_failed: 2,
          high_signal_failures: 0,
          infrastructure_errors: 0,
          low_signal_failures: 2,
          unrunnable_failures: 2,
          flaky_suspects: 1,
        },
        highlights: [
          {
            kind: "generated_failure",
            priority: "low",
            headline: "Generated test for `parse_config` likely failed because of setup or runnability issues under `Path Traversal`.",
            severity: "low",
            confidence: "low",
            confidence_score: 0.18,
            failure_category: "generated_test_issue",
            suite: "generated",
            test_name: "test_generated_path_traversal_signal",
            target_key: "abc123",
            symbol: "parse_config",
            source_file: "app/main.py",
            recipe_id: "path_traversal",
            recipe_name: "Path Traversal",
            generated_test_file: "generated_tests/security/test_parse_config_path_traversal_abc123.py",
            risk_tags: ["filesystem_access"],
            heuristic_tags: ["repeated_setup_error", "generated_suite_unrunnable"],
            evidence: ["ImportError: cannot import name TestClient"],
          },
        ],
      })
    );
    mockApiClient.getAnalysisReport.mockRejectedValue(new Error("Analysis report not found"));

    renderPanel();

    expect(await screen.findByText("Low-signal findings")).toBeInTheDocument();
    expect(screen.getByText("Unrunnable failures")).toBeInTheDocument();
    expect(screen.getByText("Flaky suspects")).toBeInTheDocument();
    expect(screen.getByText("generated suite unrunnable")).toBeInTheDocument();
  });
});
