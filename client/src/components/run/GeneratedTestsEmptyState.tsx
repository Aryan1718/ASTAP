import { Card } from "../ui/Card";

type GeneratedTestsEmptyStateProps = {
  title: string;
  description: string;
  tone?: "default" | "error";
};

export function GeneratedTestsEmptyState({
  title,
  description,
  tone = "default",
}: GeneratedTestsEmptyStateProps) {
  const borderClass = tone === "error" ? "border-red-200 bg-red-50/60" : "border-dashed border-line bg-canvas";
  const eyebrowClass = tone === "error" ? "text-red-700" : "text-accent";
  const textClass = tone === "error" ? "text-red-800" : "text-muted";

  return (
    <Card className={`p-6 md:p-8 ${borderClass}`}>
      <p className={`m-0 text-xs font-semibold uppercase tracking-[0.24em] ${eyebrowClass}`}>Generated Tests</p>
      <h2 className="mt-2 text-2xl font-semibold text-ink">{title}</h2>
      <p className={`mt-3 max-w-2xl text-sm leading-6 ${textClass}`}>{description}</p>
    </Card>
  );
}
