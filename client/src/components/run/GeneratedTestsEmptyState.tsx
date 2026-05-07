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
  const borderClass = tone === "error" ? "border-line bg-[#f7efee]" : "border-dashed border-line bg-transparent";
  const eyebrowClass = "text-muted";
  const textClass = "text-muted";

  return (
    <Card className={`p-6 md:p-8 ${borderClass}`}>
      <p className={`m-0 font-display text-xs uppercase tracking-[0.12em] ${eyebrowClass}`}>Generated Tests</p>
      <h2 className="mt-2 text-2xl font-normal text-ink">{title}</h2>
      <p className={`mt-3 max-w-2xl text-sm leading-6 ${textClass}`}>{description}</p>
    </Card>
  );
}
