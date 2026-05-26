import { GitCommit, GitPullRequest, History, Loader2, Upload } from "lucide-react";
import type { GitRecentAction } from "../../../api/client";

export function RecentActionsSection({
  query,
}: {
  query: {
    data?: { actions: GitRecentAction[]; errors?: string[] };
    isLoading: boolean;
    isFetching: boolean;
  };
}) {
  const actions = query.data?.actions ?? [];
  return (
    <div className="px-2 py-2">
      <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        <History className="h-3 w-3" />
        <span>Recent Actions</span>
        {query.isFetching ? <Loader2 className="ml-auto h-3 w-3 animate-spin" /> : null}
      </div>
      {query.isLoading ? (
        <div className="flex items-center gap-2 rounded-lg px-2 py-2 text-[11px] text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          <span>Loading recent actions...</span>
        </div>
      ) : actions.length === 0 ? (
        <div className="rounded-lg px-2 py-2 text-[11px] text-muted-foreground/75">
          No recent Git actions found.
        </div>
      ) : (
        <div className="max-h-48 space-y-1 overflow-y-auto pr-1">
          {actions.slice(0, 8).map((action) => (
            <RecentActionItem key={`${action.type}:${action.id}`} action={action} />
          ))}
        </div>
      )}
    </div>
  );
}

function RecentActionItem({ action }: { action: GitRecentAction }) {
  const content = (
    <>
      <RecentActionIcon type={action.type} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[11px] font-medium text-foreground">{action.title}</div>
        <div className="truncate text-[10px] text-muted-foreground">
          {[action.subtitle, formatTimestamp(action.timestamp)].filter(Boolean).join(" · ")}
        </div>
      </div>
    </>
  );
  const className =
    "flex w-full min-w-0 items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-glass/60";
  if (action.url) {
    return (
      <a href={action.url} target="_blank" rel="noreferrer" className={className}>
        {content}
      </a>
    );
  }
  return <div className={className}>{content}</div>;
}

function RecentActionIcon({ type }: { type: string }) {
  if (type === "push") return <Upload className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  if (type === "pr") return <GitPullRequest className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  return <GitCommit className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
}

function formatTimestamp(value?: string | null) {
  if (!value) return "";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}
