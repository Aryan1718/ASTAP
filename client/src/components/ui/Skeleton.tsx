export function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-[#f0ebe6] ${className ?? ""}`} />;
}
