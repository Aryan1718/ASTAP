import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RunAnalysisPanel } from "./RunAnalysisPanel";
import { apiClient } from "../../lib/apiClient";
import type { AnalysisSummary } from "../../types/api";

vi.mock("../../lib/apiClient", () => ({
  apiClient: {
    getAnalysisSummary: vi.fn(),
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
    trend: {
      status: "available",
      comparison_run: {
        run_id: "run-122",
        created_at: "2026-05-05T00:00:00Z",
        ref_requested: "main",
        ref_resolved: "abc123",
        overall_assessment: "all_passed",
      },
      counts: {
        new_findings: 1,
        recurring_findings: 0,
        fixed_findings: 1,
        recurring_noise: 0,
      },
      headline: "1 new finding appeared and 1 prior finding disappeared versus the previous analyzed run.",
      new_findings: [
        {
          fingerprint: "generated|abc123|path_traversal|product_failure|test_parse_config_path_traversal_abc123.py",
          suite: "generated",
          failure_category: "product_failure",
          headline: "Generated test for `parse_config` failed under `Path Traversal`.",
          target_key: "abc123",
          symbol: "parse_config",
          recipe_id: "path_traversal",
          recipe_name: "Path Traversal",
          generated_test_file: "generated_tests/security/test_parse_config_path_traversal_abc123.py",
          confidence: "high",
          severity: "high",
        },
      ],
      fixed_findings: [
        {
          fingerprint: "existing|tests/test_existing.py|tests.test_existing|test_existing_parse_config",
          suite: "existing",
          failure_category: "baseline_failure",
          headline: "Existing test `test_existing_parse_config` failed before generated tests were considered.",
          confidence: "high",
          severity: "high",
        },
      ],
    },
    artifacts: [],
    ...overrides,
  };
}

function renderPanel(stageStatus = "succeeded") {
  return render(
    <MemoryRouter initialEntries={["/app/runs/run-123"]}>
      <Routes>
        <Route path="/app/runs/:runId" element={<RunAnalysisPanel token="token" runId="run-123" stageStatus={stageStatus} />} />
        <Route path="/app/runs/:runId/generated-tests" element={<div>Generated tests route</div>} />
        <Route path="/app/runs/:runId/analysis" element={<div>Analysis route</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("RunAnalysisPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders the compact assessment and analysis-page navigation", async () => {
    mockApiClient.getAnalysisSummary.mockResolvedValue(buildSummary());

    renderPanel();

    expect(await screen.findByText("Generated tests found new failures")).toBeInTheDocument();
    expect(screen.getByText("Heuristics version")).toBeInTheDocument();
    expect(screen.getByText("Open analysis")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /go to analysis page/i })).toBeInTheDocument();
    expect(screen.queryByText("Run Analysis")).not.toBeInTheDocument();
  });

  it("navigates to the dedicated analysis page", async () => {
    mockApiClient.getAnalysisSummary.mockResolvedValue(buildSummary());

    renderPanel();

    await screen.findByText("Generated tests found new failures");
    await userEvent.click(screen.getByRole("button", { name: /go to analysis page/i }));

    await waitFor(() => {
      expect(screen.getByText("Analysis route")).toBeInTheDocument();
    });
  });

  it("shows a pending state when analysis results are not ready yet", async () => {
    mockApiClient.getAnalysisSummary.mockRejectedValue(new Error("Analysis results not available"));

    renderPanel("running");

    expect(await screen.findByText("Analysis pending")).toBeInTheDocument();
    expect(screen.getByText(/analysis stage is still running/i)).toBeInTheDocument();
  });

  it("renders compact counters for downgraded low-signal states", async () => {
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

    renderPanel();

    expect(await screen.findByText("Low-signal findings")).toBeInTheDocument();
    expect(screen.queryByText("Unrunnable failures")).not.toBeInTheDocument();
    expect(screen.queryByText("Flaky suspects")).not.toBeInTheDocument();
  });

  it("renders an unavailable trend empty state when no comparison run exists", async () => {
    mockApiClient.getAnalysisSummary.mockResolvedValue(
      buildSummary({
        trend: {
          status: "unavailable",
          comparison_run: null,
          counts: {
            new_findings: 0,
            recurring_findings: 0,
            fixed_findings: 0,
            recurring_noise: 0,
          },
          headline: "No earlier analyzed run is available for comparison.",
          new_findings: [],
          fixed_findings: [],
        },
      })
    );

    renderPanel();

    expect(await screen.findByText("Generated tests found new failures")).toBeInTheDocument();
    expect(screen.getByText("Open analysis")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /go to analysis page/i })).toBeInTheDocument();
  });
});
