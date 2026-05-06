import { Skeleton } from "../ui/Skeleton";

type GeneratedTestsCodeViewerProps = {
  path: string;
  content?: string | null;
  isLoading: boolean;
  errorMessage?: string | null;
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

export function GeneratedTestsCodeViewer({ path, content, isLoading, errorMessage }: GeneratedTestsCodeViewerProps) {
  const lines = content?.split("\n") ?? [];

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-transparent">
      <div className="border-b border-line bg-transparent px-5 py-3">
        <p className="m-0 truncate font-mono text-sm text-ink">{path}</p>
      </div>

      {isLoading ? <LoadingState /> : null}
      {!isLoading && errorMessage ? <ErrorState message={errorMessage} /> : null}
      {!isLoading && !errorMessage ? (
        <div className="min-h-0 flex-1 overflow-auto bg-transparent">
          <div className="min-h-full min-w-max font-mono text-[13px] leading-6 text-ink">
            {lines.map((line, index) => (
              <div key={`${path}-${index + 1}`} className="grid grid-cols-[4rem_minmax(0,1fr)]">
                <div className="select-none border-r border-line bg-[#fbf8f5] px-4 py-0.5 text-right text-xs text-muted">
                  {index + 1}
                </div>
                <pre className="m-0 px-4 py-0.5 whitespace-pre">{line || " "}</pre>
              </div>
            ))}
            {lines.length === 0 ? <div className="px-4 py-8 text-sm text-muted">No content returned for this generated file.</div> : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
