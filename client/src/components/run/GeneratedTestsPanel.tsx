import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";

import { apiClient } from "../../lib/apiClient";
import type {
  GeneratedTestCases,
  GeneratedTestFileContent,
  GeneratedTestManifest,
  GeneratedTestManifestEntry,
  RunDetail,
  Stage,
} from "../../types/api";
import { Card } from "../ui/Card";
import { Skeleton } from "../ui/Skeleton";
import { GeneratedTestsCodeViewer } from "./GeneratedTestsCodeViewer";
import { GeneratedTestsEmptyState } from "./GeneratedTestsEmptyState";
import { GeneratedTestsFileTree } from "./GeneratedTestsFileTree";
import { GeneratedTestsHeader } from "./GeneratedTestsHeader";

type GeneratedTestsPanelProps = {
  token: string;
  run: RunDetail;
  minimal?: boolean;
  initialSelectedPath?: string | null;
};

const DEFAULT_EXPLORER_WIDTH = 288;
const MIN_EXPLORER_WIDTH = 220;
const MAX_EXPLORER_WIDTH = 520;

function findStage(stages: Stage[], stageName: string) {
  return stages.find((stage) => stage.stage === stageName);
}

function generatedEntries(manifest: GeneratedTestManifest | null) {
  if (!manifest) {
    return [];
  }

  return manifest.files.filter(
    (entry): entry is GeneratedTestManifestEntry & { generated_test_file: string } =>
      entry.status === "generated" && Boolean(entry.generated_test_file)
  );
}

function ManifestLoadingState({ minimal }: { minimal: boolean }) {
  return (
    <Card className="h-[calc(100vh-8.5rem)] overflow-hidden">
      {minimal ? null : (
        <div className="border-b border-line/80 px-6 py-5 md:px-8">
          <p className="m-0 font-display text-xs uppercase tracking-[0.12em] text-muted">Generated Tests</p>
          <h2 className="mt-2 text-2xl font-normal text-ink">Read-only code explorer</h2>
        </div>
      )}
      <div className="grid h-full gap-0 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <div className="border-r border-line p-4">
          <p className="m-0 font-display text-xs uppercase tracking-[0.12em] text-muted">Explorer</p>
          <Skeleton className="h-5 w-24" />
          <Skeleton className="mt-4 h-10 w-full" />
          <Skeleton className="mt-3 h-10 w-full" />
          <Skeleton className="mt-3 h-10 w-full" />
        </div>
        <div className="p-5">
          <Skeleton className="h-6 w-80" />
          <Skeleton className="mt-3 h-12 w-full" />
          <Skeleton className="mt-4 h-[28rem] w-full" />
        </div>
      </div>
    </Card>
  );
}

export function GeneratedTestsPanel({ token, run, minimal = false, initialSelectedPath = null }: GeneratedTestsPanelProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [manifest, setManifest] = useState<GeneratedTestManifest | null>(null);
  const [loadingManifest, setLoadingManifest] = useState(true);
  const [manifestError, setManifestError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [fileContents, setFileContents] = useState<Record<string, GeneratedTestFileContent>>({});
  const [loadingPath, setLoadingPath] = useState<string | null>(null);
  const [contentError, setContentError] = useState<string | null>(null);
  const [testCasesPayload, setTestCasesPayload] = useState<GeneratedTestCases | null>(null);
  const [explorerWidth, setExplorerWidth] = useState(DEFAULT_EXPLORER_WIDTH);
  const [isResizing, setIsResizing] = useState(false);

  const generateTestsStage = useMemo(() => findStage(run.stages, "generate_tests"), [run.stages]);
  const files = useMemo(() => generatedEntries(manifest), [manifest]);
  const testCases = useMemo(() => testCasesPayload?.cases ?? [], [testCasesPayload]);
  const selectedCase = useMemo(
    () => testCases.find((entry) => entry.case_id === selectedCaseId) ?? null,
    [selectedCaseId, testCases]
  );
  const selectedEntry = useMemo(() => files.find((entry) => entry.generated_test_file === selectedPath) ?? files[0] ?? null, [files, selectedPath]);

  useEffect(() => {
    let active = true;

    async function loadManifest() {
      setLoadingManifest(true);
      setManifestError(null);
      try {
        const payload = await apiClient.getGeneratedTestsManifest(token, run.id);
        if (!active) {
          return;
        }
        setManifest(payload);
      } catch (error) {
        if (!active) {
          return;
        }
        setManifest(null);
        setManifestError(error instanceof Error ? error.message : "Unable to load generated tests");
      } finally {
        if (active) {
          setLoadingManifest(false);
        }
      }
    }

    void loadManifest();

    return () => {
      active = false;
    };
  }, [generateTestsStage?.status, run.id, token]);

  useEffect(() => {
    let active = true;

    async function loadCases() {
      try {
        const payload = await apiClient.getGeneratedTestCases(token, run.id);
        if (!active) {
          return;
        }
        setTestCasesPayload(payload);
      } catch {
        if (!active) {
          return;
        }
        setTestCasesPayload(null);
      }
    }

    void loadCases();

    return () => {
      active = false;
    };
  }, [generateTestsStage?.status, run.id, token]);

  useEffect(() => {
    if (!files.length) {
      setSelectedPath(null);
      setSelectedCaseId(null);
      return;
    }

    if (selectedPath && files.some((entry) => entry.generated_test_file === selectedPath)) {
      return;
    }

    if (initialSelectedPath && files.some((entry) => entry.generated_test_file === initialSelectedPath)) {
      setSelectedPath(initialSelectedPath);
      return;
    }

    setSelectedPath(files[0].generated_test_file);
  }, [files, initialSelectedPath, selectedPath]);

  useEffect(() => {
    if (!selectedCaseId) {
      return;
    }
    if (!selectedCase) {
      setSelectedCaseId(null);
      return;
    }
    if (selectedCase.generated_test_file && selectedCase.generated_test_file !== selectedPath) {
      setSelectedPath(selectedCase.generated_test_file);
    }
  }, [selectedCase, selectedCaseId, selectedPath]);

  useEffect(() => {
    if (!selectedEntry?.generated_test_file || fileContents[selectedEntry.generated_test_file]) {
      return;
    }

    let active = true;

    async function loadContent() {
      const path = selectedEntry.generated_test_file;
      setLoadingPath(path);
      setContentError(null);
      try {
        const payload = await apiClient.getGeneratedTestContent(token, run.id, path);
        if (!active) {
          return;
        }
        const resolvedPath = payload.path || path;
        setFileContents((current) => ({ ...current, [resolvedPath]: { ...payload, path: resolvedPath } }));
      } catch (error) {
        if (!active) {
          return;
        }
        setContentError(error instanceof Error ? error.message : "Unable to load generated test content");
      } finally {
        if (active) {
          setLoadingPath((current) => (current === path ? null : current));
        }
      }
    }

    void loadContent();

    return () => {
      active = false;
    };
  }, [fileContents, run.id, selectedEntry, token]);

  useEffect(() => {
    if (!isResizing) {
      return;
    }

    function handleMouseMove(event: MouseEvent) {
      const panelBounds = panelRef.current?.getBoundingClientRect();
      if (!panelBounds) {
        return;
      }

      const nextWidth = event.clientX - panelBounds.left;
      const maxWidth = Math.min(MAX_EXPLORER_WIDTH, Math.max(MIN_EXPLORER_WIDTH, panelBounds.width - 320));
      const clampedWidth = Math.min(Math.max(nextWidth, MIN_EXPLORER_WIDTH), maxWidth);
      setExplorerWidth(clampedWidth);
    }

    function handleMouseUp() {
      setIsResizing(false);
    }

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  function handleResizeStart(event: ReactMouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    setIsResizing(true);
  }

  function handleSelectFile(path: string) {
    setSelectedPath(path);
    setSelectedCaseId(null);
  }

  function handleSelectCase(caseId: string, path: string) {
    setSelectedCaseId(caseId);
    setSelectedPath(path);
  }

  if (loadingManifest) {
    return <ManifestLoadingState minimal={minimal} />;
  }

  if (manifest && files.length === 0) {
    return (
      <GeneratedTestsEmptyState
        title="No generated tests found"
        description="This run completed without any generated test files. Once generated artifacts are available, they will appear in this explorer."
      />
    );
  }

  if (!manifest) {
    if (generateTestsStage?.status === "pending" || generateTestsStage?.status === "running" || run.status === "queued" || run.status === "running") {
      return (
        <GeneratedTestsEmptyState
          title="Generated tests are still processing"
          description="The generate_tests stage has not published a manifest yet. Check back once the run finishes and generated files will appear here."
        />
      );
    }

    if (generateTestsStage?.status === "failed") {
      return (
        <GeneratedTestsEmptyState
          title="Generated tests unavailable"
          description={generateTestsStage.error_message ?? manifestError ?? "The backend did not return generated test artifacts for this run."}
          tone="error"
        />
      );
    }

    return (
      <GeneratedTestsEmptyState
        title="No generated tests found for this run"
        description={manifestError ?? "The backend did not return a generated test manifest for this run."}
      />
    );
  }

  if (!selectedEntry?.generated_test_file) {
    return null;
  }

  const currentContent = fileContents[selectedEntry.generated_test_file] ?? null;
  const panelStyle = {
    "--explorer-width": `${explorerWidth}px`,
  } as CSSProperties;

  return (
    <Card className="h-[calc(100vh-8.5rem)] overflow-hidden">
      {minimal ? null : (
        <GeneratedTestsHeader
          manifest={manifest}
          runStatus={run.status}
          generatedCount={files.length}
          testCaseCount={testCases.length}
        />
      )}
      <div
        ref={panelRef}
        style={panelStyle}
        className="grid h-full min-h-0 grid-cols-1 gap-0 lg:[grid-template-columns:var(--explorer-width)_12px_minmax(0,1fr)]"
      >
        <GeneratedTestsFileTree
          files={files}
          testCases={testCases}
          selectedPath={selectedEntry.generated_test_file}
          selectedCaseId={selectedCaseId}
          onSelect={handleSelectFile}
          onSelectCase={handleSelectCase}
        />
        <button
          type="button"
          aria-label="Resize explorer"
          aria-orientation="vertical"
          onMouseDown={handleResizeStart}
          className="group hidden cursor-col-resize border-x border-line bg-transparent transition hover:bg-[#fbf8f5] lg:flex lg:min-h-0 lg:items-center lg:justify-center"
        >
          <span className="h-12 w-1 bg-line transition group-hover:bg-[#cbb7fb]" />
        </button>
        <GeneratedTestsCodeViewer
          path={selectedEntry.generated_test_file}
          content={currentContent?.content ?? null}
          isLoading={loadingPath === selectedEntry.generated_test_file && !currentContent}
          errorMessage={loadingPath === null && !currentContent ? contentError : null}
          highlightedTestName={selectedCase?.generated_test_file === selectedEntry.generated_test_file ? selectedCase.name : null}
        />
      </div>
    </Card>
  );
}
