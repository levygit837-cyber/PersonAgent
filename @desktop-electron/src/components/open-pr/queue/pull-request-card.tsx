import type { PullRequestSummary } from "../../../api/client";
import { cn } from "../../../lib/utils";
import { StatusPill } from "../shared/status-pill";
import { prTotals } from "../shared/pr-utils";

export function PullRequestCard({
  pullRequest,
  active,
  onClick,
}: {
  pullRequest: PullRequestSummary;
  active: boolean;
  onClick: () => void;
}) {
  const totals = prTotals(pullRequest);
  return (
    <button
      type="button"
      className={cn(
        "group w-full rounded-2xl border p-3 text-left transition-[background,border-color,box-shadow,transform] duration-200",
        active
          ? "border-primary/30 bg-accent/70 text-foreground shadow-soft"
          : "border-transparent text-muted-foreground hover:border-glass-border/30 hover:bg-glass/70 hover:text-foreground",
      )}
      onClick={onClick}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-[11px] font-semibold text-primary">#{pullRequest.number}</span>
        <StatusPill status={pullRequest.status}>{pullRequest.statusLabel}</StatusPill>
      </div>
      <div className="mt-2 line-clamp-2 text-sm font-semibold leading-5 text-foreground">{pullRequest.title}</div>
      <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">{pullRequest.description}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <span className="grid h-5 w-5 place-items-center rounded-full border border-glass-border/35 bg-background/60 text-[10px] font-bold text-foreground">
          {pullRequest.author}
        </span>
        <span>{pullRequest.updated}</span>
        <span>{pullRequest.files.length} files</span>
        <span className="font-mono text-success">+{totals.additions}</span>
        <span className="font-mono text-destructive">-{totals.deletions}</span>
      </div>
    </button>
  );
}
