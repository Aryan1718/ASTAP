import { Card } from "../components/ui/Card";

export function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return (
    <Card className="p-8">
      <p className="m-0 text-xs font-semibold uppercase tracking-[0.24em] text-accent">Placeholder</p>
      <h1 className="mt-3 text-3xl font-semibold text-ink">{title}</h1>
      <p className="mt-4 max-w-2xl text-sm leading-7 text-muted">{description}</p>
    </Card>
  );
}
