import type { Stage } from "../../types/api";
import { cn } from "../../lib/utils";
import { StatusBadge } from "../ui/StatusBadge";

const orderedStages = ["ingest", "discover", "generate_tests", "execute_tests", "analyze"] as const;

function findStage(stages: Stage[], name: string) {
  return stages.find((stage) => stage.stage === name);
}

export function StageTimeline({ stages }: { stages: Stage[] }) {
  return (
    <div className="surface p-6 md:p-8">
      <div className="border-b border-line/80 pb-6">
        <p className="m-0 text-xs font-semibold uppercase tracking-[0.24em] text-accent">Stages</p>
        <h2 className="mt-2 text-2xl font-semibold text-ink">Pipeline timeline</h2>
        <p className="mt-2 text-sm leading-6 text-muted">Ingest and discover reflect live API state. Later stages stay visible as placeholders.</p>
      </div>
      <div className="mt-6 grid gap-4">
        {orderedStages.map((name, index) => {
          const stage = findStage(stages, name);
          const isLive = Boolean(stage);
          const isComplete = stage?.status === "succeeded";
          const isActive = stage?.status === "running" || stage?.status === "retrying";

          return (
            <div
              key={name}
              className={cn(
                "rounded-2xl border p-4 transition",
                isLive ? "border-line bg-white" : "border-dashed border-line bg-slate-50/70"
              )}
              title={isLive ? undefined : "Coming soon"}
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-4">
                  <div
                    className={cn(
                      "mt-1 flex h-10 w-10 items-center justify-center rounded-2xl text-sm font-semibold",
                      isComplete && "bg-emerald-50 text-emerald-700",
                      isActive && "bg-accent-50 text-accent-700",
                      !isLive && "bg-slate-100 text-slate-500",
                      isLive && !isComplete && !isActive && "bg-slate-100 text-slate-700"
                    )}
                  >
                    0{index + 1}
                  </div>
                  <div>
                    <p className="m-0 text-sm font-semibold uppercase tracking-[0.18em] text-ink">{name.replace(/_/g, " ")}</p>
                    <p className="mt-1 text-sm leading-6 text-muted">
                      {isLive ? "Stage status is sourced from the API." : "Reserved placeholder for future pipeline phases."}
                    </p>
                  </div>
                </div>
                {isLive ? (
                  <StatusBadge status={stage?.status ?? "pending"} />
                ) : (
                  <span className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                    Coming soon
                  </span>
                )}
              </div>
              {stage?.error_message ? <p className="mt-3 text-sm text-red-600">{stage.error_message}</p> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
