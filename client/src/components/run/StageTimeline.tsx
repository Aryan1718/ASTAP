import { useNavigate } from "react-router-dom";

import type { Stage } from "../../types/api";
import { cn } from "../../lib/utils";
import { Button } from "../ui/Button";
import { StatusBadge } from "../ui/StatusBadge";

const orderedStages = ["ingest", "discover", "generate_tests", "execute_tests", "analyze"] as const;

function findStage(stages: Stage[], name: string) {
  return stages.find((stage) => stage.stage === name);
}

export function StageTimeline({ stages, runId }: { stages: Stage[]; runId: string }) {
  const navigate = useNavigate();

  return (
    <div className="surface p-6 md:p-8">
      <div className="border-b border-line/80 pb-6">
        <p className="section-eyebrow">Stages</p>
        <h2 className="mt-2 text-[2rem] leading-tight text-ink" style={{ fontWeight: 460 }}>
          Pipeline timeline
        </h2>
        <p className="mt-2 text-sm leading-6 text-muted">All pipeline stages reflect live API state, including the final analyze step that summarizes execution outcomes.</p>
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
                "rounded-2xl border p-5 transition",
                isLive ? "border-line bg-white" : "border-dashed border-line bg-transparent"
              )}
              title={isLive ? undefined : "Coming soon"}
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-4">
                  <div
                    className={cn(
                      "mt-1 flex h-11 w-11 items-center justify-center rounded-lg border text-sm font-display uppercase",
                      isComplete && "border-line bg-[#f7f3ee] text-ink",
                      isActive && "border-[#cbb7fb] bg-[#f4eefc] text-ink",
                      !isLive && "border-line text-muted",
                      isLive && !isComplete && !isActive && "border-line text-ink"
                    )}
                  >
                    0{index + 1}
                  </div>
                  <div>
                    <p className="m-0 text-sm font-semibold uppercase tracking-[0.2em] text-ink">{name.replace(/_/g, " ")}</p>
                    <p className="mt-1 text-sm leading-6 text-muted">
                      {isLive ? "Stage status is sourced from the API." : "Reserved placeholder for future pipeline phases."}
                    </p>
                  </div>
                </div>
                {isLive ? (
                  <div className="flex items-center gap-3">
                    {name === "generate_tests" && stage?.status === "succeeded" ? (
                      <Button
                        variant="secondary"
                        className="px-3 py-2 text-xs"
                        onClick={() => navigate(`/app/runs/${runId}/generated-tests`)}
                      >
                        View
                      </Button>
                    ) : null}
                    <StatusBadge status={stage?.status ?? "pending"} />
                  </div>
                ) : (
                  <span className="inline-flex rounded-lg border border-line px-3 py-1.5 font-display text-[11px] uppercase tracking-[0.12em] text-muted">
                    Coming soon
                  </span>
                )}
              </div>
              {stage?.error_message ? <p className="mt-3 text-sm text-muted">{stage.error_message}</p> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
