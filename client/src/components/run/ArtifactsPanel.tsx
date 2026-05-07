import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { formatBytes } from "../../lib/utils";
import type { Snapshot } from "../../types/api";

type ArtifactsPanelProps = {
  snapshot?: Snapshot | null;
  onCopy: (label: string, value: string) => void;
};

const items = [
  { label: "Bucket", key: "bucket" as const },
  { label: "Object key", key: "key" as const },
  { label: "SHA256", key: "sha256" as const },
];

export function ArtifactsPanel({ snapshot, onCopy }: ArtifactsPanelProps) {
  return (
    <Card className="p-6 md:p-8">
      <div className="border-b border-line/80 pb-6">
        <p className="section-eyebrow">Artifacts</p>
        <h2 className="mt-2 text-[2rem] leading-tight text-ink" style={{ fontWeight: 460 }}>
          Snapshot metadata
        </h2>
      </div>
      {!snapshot ? (
        <div className="mt-6 border border-dashed border-line px-5 py-6 text-sm text-muted">
          Snapshot metadata will appear after ingest resolves a commit and uploads the immutable archive used by discover.
        </div>
      ) : (
        <div className="mt-6 grid gap-4">
          {items.map((item) => {
            const value = snapshot[item.key];
            return (
              <div key={item.label} className="flex flex-col gap-3 border border-line bg-transparent px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">{item.label}</p>
                  <p className="mt-2 break-all text-sm text-ink">{value ?? "Not available"}</p>
                </div>
                <Button variant="ghost" disabled={!value} onClick={() => value && onCopy(item.label, value)}>
                  Copy
                </Button>
              </div>
            );
          })}
          <div className="border border-line bg-transparent px-4 py-4">
            <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-muted">Size</p>
            <p className="mt-2 text-sm text-ink">{formatBytes(snapshot.size_bytes)}</p>
          </div>
        </div>
      )}
    </Card>
  );
}
