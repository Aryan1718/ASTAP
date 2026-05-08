import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GeneratedTestsPanel } from "./GeneratedTestsPanel";
import { apiClient } from "../../lib/apiClient";
import type { GeneratedTestFileContent, GeneratedTestManifest, RunDetail } from "../../types/api";

vi.mock("../../lib/apiClient", () => ({
  apiClient: {
    getGeneratedTestsManifest: vi.fn(),
    getGeneratedTestContent: vi.fn(),
  },
}));

const mockApiClient = vi.mocked(apiClient);

function buildRun(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "run-123",
    project_id: "project-123",
    status: "succeeded",
    ref_requested: "main",
    ref_resolved: "abc123",
    created_at: "2026-03-19T16:00:00Z",
    started_at: "2026-03-19T16:01:00Z",
    finished_at: "2026-03-19T16:02:00Z",
    progress_percent: 100,
    snapshot: null,
    stages: [
      { stage: "ingest", status: "succeeded" },
      { stage: "discover", status: "succeeded" },
      { stage: "generate_tests", status: "succeeded" },
    ],
    ...overrides,
  };
}

function buildManifest(overrides: Partial<GeneratedTestManifest> = {}): GeneratedTestManifest {
  return {
    version: 1,
    run_id: "run-123",
    generated_at: "2026-03-19T16:02:30Z",
    files: [
      {
        target_key: "a1b2c3",
        target_type: "SERVICE_FUNCTION",
        symbol: "parse_config",
        source_file: "app/utils.py",
        generated_test_file: "generated_tests/services/test_parse_config_a1b2c3.py",
        test_kind: "unit",
        status: "generated",
      },
      {
        target_key: "f9e8d7",
        target_type: "API_ENDPOINT",
        symbol: "get_user",
        source_file: "app/api.py",
        generated_test_file: "generated_tests/api/test_get_user_f9e8d7.py",
        test_kind: "api",
        status: "generated",
      },
    ],
    ...overrides,
  };
}

function buildContent(path: string, content: string): GeneratedTestFileContent {
  return {
    path,
    content,
    language: "python",
  };
}

describe("GeneratedTestsPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders a loading state while the manifest request is pending", () => {
    mockApiClient.getGeneratedTestsManifest.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(() => resolve(buildManifest()), 50);
        })
    );

    render(<GeneratedTestsPanel token="token" run={buildRun()} />);

    expect(screen.getByText("Explorer")).toBeInTheDocument();
  });

  it("renders the manifest into grouped file tree entries", async () => {
    mockApiClient.getGeneratedTestsManifest.mockResolvedValue(buildManifest());
    mockApiClient.getGeneratedTestContent.mockResolvedValue(
      buildContent("generated_tests/services/test_parse_config_a1b2c3.py", "def test_parse_config():\n    assert True\n")
    );

    render(<GeneratedTestsPanel token="token" run={buildRun()} />);

    expect(await screen.findByText("Services")).toBeInTheDocument();
    expect(screen.getByText("API")).toBeInTheDocument();
    expect(screen.getByText("test_parse_config_a1b2c3.py")).toBeInTheDocument();
    expect(screen.getByText("test_get_user_f9e8d7.py")).toBeInTheDocument();
  });

  it("clicking a file loads and shows its code content", async () => {
    mockApiClient.getGeneratedTestsManifest.mockResolvedValue(buildManifest());
    mockApiClient.getGeneratedTestContent.mockImplementation(async (_token, _runId, path) => {
      if (path.includes("parse_config")) {
        return buildContent(path, "def test_parse_config():\n    assert True\n");
      }

      return buildContent(path, "def test_get_user():\n    assert response.status_code == 200\n");
    });

    render(<GeneratedTestsPanel token="token" run={buildRun()} />);

    await screen.findByText("test_parse_config_a1b2c3.py");

    await userEvent.click(screen.getByRole("button", { name: /test_get_user_f9e8d7.py/i }));

    await waitFor(() => {
      expect(screen.getByText("def test_get_user():")).toBeInTheDocument();
      expect(screen.getByText((content) => content.includes("response.status_code"))).toBeInTheDocument();
    });
  });

  it("renders an empty state when the manifest has no generated files", async () => {
    mockApiClient.getGeneratedTestsManifest.mockResolvedValue(buildManifest({ files: [] }));

    render(<GeneratedTestsPanel token="token" run={buildRun()} />);

    expect(await screen.findByText("No generated tests found")).toBeInTheDocument();
  });

  it("renders a specific empty state when the manifest explains why nothing was generated", async () => {
    mockApiClient.getGeneratedTestsManifest.mockResolvedValue(
      buildManifest({ files: [], empty_reason: "no_eligible_targets_after_runnability_filtering" })
    );

    render(<GeneratedTestsPanel token="token" run={buildRun()} />);

    expect(await screen.findByText("No eligible targets after filtering")).toBeInTheDocument();
  });

  it("keeps the selected file visually highlighted", async () => {
    mockApiClient.getGeneratedTestsManifest.mockResolvedValue(buildManifest());
    mockApiClient.getGeneratedTestContent.mockImplementation(async (_token, _runId, path) =>
      buildContent(path, `def ${path.includes("parse_config") ? "test_parse_config" : "test_get_user"}():\n    pass\n`)
    );

    render(<GeneratedTestsPanel token="token" run={buildRun()} />);

    const apiFileButton = await screen.findByRole("button", { name: /test_get_user_f9e8d7.py/i });
    await userEvent.click(apiFileButton);

    expect(apiFileButton).toHaveClass("border-[#cbb7fb]");
    expect(apiFileButton).toHaveAttribute("aria-current", "true");
  });

  it("honors an initial selected path when it matches a generated file", async () => {
    mockApiClient.getGeneratedTestsManifest.mockResolvedValue(buildManifest());
    mockApiClient.getGeneratedTestContent.mockImplementation(async (_token, _runId, path) =>
      buildContent(path, `def ${path.includes("get_user") ? "test_get_user" : "test_parse_config"}():\n    pass\n`)
    );

    render(
      <GeneratedTestsPanel
        token="token"
        run={buildRun()}
        initialSelectedPath="generated_tests/api/test_get_user_f9e8d7.py"
      />
    );

    await waitFor(() => {
      expect(screen.getByText("def test_get_user():")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /test_get_user_f9e8d7.py/i })).toHaveAttribute("aria-current", "true");
  });
});
