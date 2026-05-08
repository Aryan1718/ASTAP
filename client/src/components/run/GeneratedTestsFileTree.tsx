import { useMemo, useState } from "react";

import { cn } from "../../lib/utils";
import type { GeneratedTestCase, GeneratedTestManifestEntry } from "../../types/api";

type GeneratedTestsFileTreeProps = {
  files: GeneratedTestManifestEntry[];
  testCases: GeneratedTestCase[];
  selectedPath: string | null;
  selectedCaseId: string | null;
  onSelect: (path: string) => void;
  onSelectCase: (caseId: string, path: string) => void;
};

type FileGroup = {
  key: string;
  label: string;
  files: GeneratedTestManifestEntry[];
};

const orderedGroups = [
  { key: "services", label: "Services" },
  { key: "api", label: "API" },
] as const;

function groupFiles(files: GeneratedTestManifestEntry[]): FileGroup[] {
  const grouped = new Map<string, GeneratedTestManifestEntry[]>();

  for (const file of files) {
    const path = file.generated_test_file;
    if (!path) {
      continue;
    }

    const segments = path.split("/");
    const groupKey = segments[1] ?? "other";
    grouped.set(groupKey, [...(grouped.get(groupKey) ?? []), file]);
  }

  const preferredGroups = orderedGroups
    .filter((group) => grouped.has(group.key))
    .map((group) => ({ key: group.key, label: group.label, files: grouped.get(group.key) ?? [] }));

  const additionalGroups = [...grouped.entries()]
    .filter(([key]) => !orderedGroups.some((group) => group.key === key))
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, entries]) => ({
      key,
      label: key.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()),
      files: entries,
    }));

  return [...preferredGroups, ...additionalGroups];
}

function filenameFromPath(path: string) {
  return path.split("/").at(-1) ?? path;
}

function targetLabel(file: GeneratedTestManifestEntry) {
  return `${file.symbol} · ${file.test_kind ?? "generated"}`;
}

function groupedCases(testCases: GeneratedTestCase[]) {
  return testCases.reduce<Record<string, GeneratedTestCase[]>>((accumulator, testCase) => {
    if (!testCase.generated_test_file) {
      return accumulator;
    }
    accumulator[testCase.generated_test_file] = [...(accumulator[testCase.generated_test_file] ?? []), testCase];
    return accumulator;
  }, {});
}

function statusTone(status: string) {
  switch (status) {
    case "failed":
    case "error":
      return "bg-[#d05b3f]";
    case "passed":
      return "bg-[#2f7d4a]";
    case "skipped":
      return "bg-[#d3a14a]";
    default:
      return "bg-[#b6aea3]";
  }
}

export function GeneratedTestsFileTree({
  files,
  testCases,
  selectedPath,
  selectedCaseId,
  onSelect,
  onSelectCase,
}: GeneratedTestsFileTreeProps) {
  const groups = useMemo(() => groupFiles(files), [files]);
  const casesByPath = useMemo(() => groupedCases(testCases), [testCases]);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(groupFiles(files).map((group) => [group.key, true]))
  );

  return (
    <aside className="flex min-h-0 flex-col border-r border-line bg-transparent">
      <div className="border-b border-line/80 px-4 py-4">
        <p className="m-0 font-display text-xs uppercase tracking-[0.12em] text-muted">Explorer</p>
        <p className="mt-1 text-sm text-ink">
          {files.length} file{files.length === 1 ? "" : "s"}
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
        {groups.map((group) => {
          const isOpen = openGroups[group.key] ?? true;

          return (
            <div key={group.key} className="mb-3">
              <button
                type="button"
                className="focus-ring flex w-full items-center justify-between rounded-lg px-2 py-2 text-left text-sm text-ink hover:bg-[#fbf8f5]"
                onClick={() => setOpenGroups((current) => ({ ...current, [group.key]: !isOpen }))}
                aria-expanded={isOpen}
              >
                <span className="flex items-center gap-2">
                  <span className="text-muted">{isOpen ? "▾" : "▸"}</span>
                  <span>{group.label}</span>
                </span>
                <span className="rounded-lg border border-line px-2 py-0.5 font-display text-xs uppercase text-muted">{group.files.length}</span>
              </button>

              {isOpen ? (
                <div className="mt-1 grid gap-1 px-1">
                  {group.files.map((file) => {
                    const path = file.generated_test_file ?? "";
                    const isSelected = path === selectedPath;
                    const cases = casesByPath[path] ?? [];

                    return (
                      <div key={path}>
                        <button
                          type="button"
                          className={cn(
                            "focus-ring group flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition",
                            isSelected
                              ? "border-[#cbb7fb] bg-[#f4eefc]"
                              : "border-transparent bg-transparent hover:border-line hover:bg-[#fbf8f5]"
                          )}
                          onClick={() => onSelect(path)}
                          aria-current={isSelected ? "true" : undefined}
                        >
                          <span
                            className={cn(
                              "mt-1 h-2.5 w-2.5 flex-none",
                              isSelected ? "bg-[#714cb6]" : "bg-[#d5d0ca] group-hover:bg-[#cbb7fb]"
                            )}
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium text-ink">{filenameFromPath(path)}</span>
                            <span className="mt-1 block truncate text-xs text-muted">{targetLabel(file)}</span>
                          </span>
                        </button>
                        {cases.length ? (
                          <div className="mt-1 grid gap-1 pl-8">
                            {cases.map((testCase) => {
                              const isCaseSelected = testCase.case_id === selectedCaseId;
                              return (
                                <button
                                  key={testCase.case_id}
                                  type="button"
                                  className={cn(
                                    "focus-ring flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left text-xs transition",
                                    isCaseSelected ? "bg-[#efe8fa]" : "hover:bg-[#fbf8f5]"
                                  )}
                                  onClick={() => onSelectCase(testCase.case_id, path)}
                                  aria-current={isCaseSelected ? "true" : undefined}
                                >
                                  <span className={cn("mt-1 h-2 w-2 flex-none rounded-full", statusTone(testCase.status))} />
                                  <span className="min-w-0 flex-1">
                                    <span className="block truncate text-ink">{testCase.name}</span>
                                    <span className="mt-0.5 block truncate uppercase tracking-[0.08em] text-muted">
                                      {testCase.status}
                                    </span>
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
