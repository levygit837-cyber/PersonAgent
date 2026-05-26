import type { TeamCompactStatus } from "../../../types/chat";

function TracePill({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded-full border border-glass-border/35 px-2 py-0.5">
      {label} <strong className="font-semibold text-foreground">{value}</strong>
    </span>
  );
}

function StatusDot({ status }: { status: TeamCompactStatus }) {
  if (status === "running" || status === "blocked") {
    return (
      <span className="relative inline-flex h-2 w-2 shrink-0" aria-label={status}>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/45" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
      </span>
    );
  }
  const color =
    status === "completed" ? "bg-success" : status === "failed" ? "bg-destructive" : status === "cancelled" ? "bg-muted-foreground" : "bg-muted-foreground/70";
  return <span className={`inline-flex h-2 w-2 shrink-0 rounded-full ${color}`} aria-label={status} />;
}

export { TracePill, StatusDot };
