import { Card } from "../components/ui/Card";

export function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return (
    <Card className="p-8">
      <p className="m-0 font-display text-xs uppercase tracking-[0.12em] text-muted">Placeholder</p>
      <h1 className="mt-3 text-3xl font-normal text-ink">{title}</h1>
      <p className="mt-4 max-w-2xl text-sm leading-7 text-muted">{description}</p>
    </Card>
  );
}
