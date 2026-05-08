import { useEffect, useMemo, useRef } from "react";

import { Skeleton } from "../ui/Skeleton";

type GeneratedTestsCodeViewerProps = {
  path: string;
  content?: string | null;
  isLoading: boolean;
  errorMessage?: string | null;
  highlightedTestName?: string | null;
};

function LoadingState() {
  return (
    <div className="grid gap-3 p-5">
      <Skeleton className="h-5 w-72" />
      <Skeleton className="h-[32rem] w-full" />
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="p-6">
      <div className="rounded-2xl border border-line bg-[#f7efee] px-4 py-4 text-sm text-ink">{message}</div>
    </div>
  );
}

export function GeneratedTestsCodeViewer({
  path,
  content,
  isLoading,
  errorMessage,
  highlightedTestName = null,
}: GeneratedTestsCodeViewerProps) {
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const lines = content?.split("\n") ?? [];
  const highlightedLineIndex = useMemo(() => {
    if (!highlightedTestName || !lines.length) {
      return null;
    }
    const pattern = `def ${highlightedTestName}(`;
    const asyncPattern = `async def ${highlightedTestName}(`;
    const index = lines.findIndex((line) => line.includes(pattern) || line.includes(asyncPattern));
    return index >= 0 ? index : null;
  }, [highlightedTestName, lines]);

  useEffect(() => {
    if (highlightedLineIndex === null) {
      return;
    }
    lineRefs.current[highlightedLineIndex]?.scrollIntoView({
      block: "center",
      behavior: "smooth",
    });
  }, [highlightedLineIndex, path]);

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-transparent">
      <div className="border-b border-line bg-transparent px-5 py-3">
        <p className="m-0 truncate font-mono text-sm text-ink">{path}</p>
        {highlightedTestName ? <p className="mt-1 truncate text-xs uppercase tracking-[0.08em] text-muted">{highlightedTestName}</p> : null}
      </div>

      {isLoading ? <LoadingState /> : null}
      {!isLoading && errorMessage ? <ErrorState message={errorMessage} /> : null}
      {!isLoading && !errorMessage ? (
        <div className="min-h-0 flex-1 overflow-auto bg-transparent">
          <div className="min-h-full min-w-max font-mono text-[13px] leading-6 text-ink">
            {lines.map((line, index) => (
              <div
                key={`${path}-${index + 1}`}
                ref={(element) => {
                  lineRefs.current[index] = element;
                }}
                className="grid grid-cols-[4rem_minmax(0,1fr)]"
              >
                <div
                  className={`select-none border-r border-line px-4 py-0.5 text-right text-xs text-muted ${
                    highlightedLineIndex === index ? "bg-[#efe8fa] text-ink" : "bg-[#fbf8f5]"
                  }`}
                >
                  {index + 1}
                </div>
                <pre className={`m-0 px-4 py-0.5 whitespace-pre ${highlightedLineIndex === index ? "bg-[#f6f1fd]" : ""}`}>{line || " "}</pre>
              </div>
            ))}
            {lines.length === 0 ? <div className="px-4 py-8 text-sm text-muted">No content returned for this generated file.</div> : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
