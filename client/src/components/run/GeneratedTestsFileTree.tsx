import { useMemo, useState } from "react";

import { cn } from "../../lib/utils";
import type { GeneratedTestManifestEntry } from "../../types/api";

type GeneratedTestsFileTreeProps = {
  files: GeneratedTestManifestEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
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

export function GeneratedTestsFileTree({ files, selectedPath, onSelect }: GeneratedTestsFileTreeProps) {
  const groups = useMemo(() => groupFiles(files), [files]);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(groupFiles(files).map((group) => [group.key, true]))
  );

  return (
    <aside className="flex min-h-0 flex-col border-r border-line bg-white">
      <div className="border-b border-line/80 px-4 py-4">
        <p className="m-0 text-xs font-semibold uppercase tracking-[0.18em] text-muted">Explorer</p>
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
                className="focus-ring flex w-full items-center justify-between rounded-xl px-2 py-2 text-left text-sm font-semibold text-ink hover:bg-canvas"
                onClick={() => setOpenGroups((current) => ({ ...current, [group.key]: !isOpen }))}
                aria-expanded={isOpen}
              >
                <span className="flex items-center gap-2">
                  <span className="text-muted">{isOpen ? "▾" : "▸"}</span>
                  <span>{group.label}</span>
                </span>
                <span className="rounded-full bg-canvas px-2 py-0.5 text-xs font-medium text-muted">{group.files.length}</span>
              </button>

              {isOpen ? (
                <div className="mt-1 grid gap-1 px-1">
                  {group.files.map((file) => {
                    const path = file.generated_test_file ?? "";
                    const isSelected = path === selectedPath;

                    return (
                      <button
                        key={path}
                        type="button"
                        className={cn(
                          "focus-ring group flex w-full items-start gap-3 rounded-2xl border px-3 py-2.5 text-left transition",
                          isSelected
                            ? "border-accent/25 bg-accent-50/70 shadow-soft"
                            : "border-transparent bg-white hover:border-line hover:bg-canvas"
                        )}
                        onClick={() => onSelect(path)}
                        aria-current={isSelected ? "true" : undefined}
                      >
                        <span
                          className={cn(
                            "mt-1 h-2.5 w-2.5 flex-none rounded-full",
                            isSelected ? "bg-accent" : "bg-slate-300 group-hover:bg-accent/45"
                          )}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-ink">{filenameFromPath(path)}</span>
                          <span className="mt-1 block truncate text-xs text-muted">{targetLabel(file)}</span>
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
    </aside>
  );
}
