import { ExternalLink, FileCode2, Files, GitPullRequest, MessageSquare, ScanSearch } from "lucide-react";
import type { PullRequestCommentKind, PullRequestStatus, PullRequestSummary } from "../../api/client";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";
import { PullRequestCommentComposer } from "./comments/pull-request-comment-composer";
import { PullRequestComments } from "./comments/pull-request-comments";
import { ContextValue } from "./shared/context-value";
import { StatusPill } from "./shared/status-pill";
import { prTotals, shortPath } from "./shared/pr-utils";

export function PullRequestDetailPanel({
  pullRequest,
  totals,
  open,
  onStartReview,
  onCreateComment,
  creatingComment,
}: {
  pullRequest: PullRequestSummary;
  totals: { additions: number; deletions: number };
  open: boolean;
  onStartReview: () => void;
  onCreateComment: (input: { number: number; body: string; kind: PullRequestCommentKind; status?: PullRequestStatus | null }) => Promise<unknown>;
  creatingComment: boolean;
}) {
  return (
    <section
      key={pullRequest.id}
      aria-hidden={!open}
      data-testid="pr-detail-panel"
      data-open={open ? "true" : "false"}
      className={cn(
        "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-card/75 shadow-soft backdrop-blur-xl transition-[opacity,transform,max-width] duration-300 ease-out",
        open ? "max-w-none translate-x-0 opacity-100" : "pointer-events-none max-w-0 translate-x-8 opacity-0",
      )}
    >
      <div className="shrink-0 border-b border-glass-border/25 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="break-words font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
              PR #{pullRequest.number} / {pullRequest.branch || "unknown branch"}
            </div>
            <h2 className="mt-2 text-xl font-semibold leading-7 text-foreground">{pullRequest.title}</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{pullRequest.description}</p>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            {pullRequest.url ? (
              <Button asChild variant="subtle" size="iconSm" aria-label="Open pull request in browser" className="rounded-xl">
                <a href={pullRequest.url} target="_blank" rel="noreferrer">
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </Button>
            ) : null}
            <Button className="rounded-xl" onClick={onStartReview}>
              <ScanSearch className="h-4 w-4" />
              Start Review
            </Button>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <StatusPill status={pullRequest.status}>{pullRequest.statusLabel}</StatusPill>
          <RiskPill risk={pullRequest.risk} />
          <span className="rounded-full border border-glass-border/35 bg-background/45 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
            {pullRequest.checkSummary}
          </span>
          {pullRequest.labels.map((label) => (
            <span key={label} className="rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
              {label}
            </span>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-4 gap-2 max-[760px]:grid-cols-2">
          <MetricTile label="Files" value={pullRequest.files.length} />
          <MetricTile label="Comments" value={pullRequest.commentsCount} />
          <MetricTile label="Additions" value={"+" + totals.additions} tone="success" />
          <MetricTile label="Deletions" value={"-" + totals.deletions} tone="destructive" />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-5" data-testid="pr-preview-scroll">
        <DetailCard icon={<GitPullRequest className="h-4 w-4" />} title="PR context">
          <div className="mt-3 grid gap-2 text-xs leading-5 text-muted-foreground sm:grid-cols-2">
            <ContextValue label="Author" value={pullRequest.author} />
            <ContextValue label="Updated" value={pullRequest.updated} />
            <ContextValue label="Base" value={pullRequest.baseBranch || "unknown"} />
            <ContextValue label="Merge" value={pullRequest.mergeState || "unknown"} />
          </div>
        </DetailCard>
        <DetailCard icon={<MessageSquare className="h-4 w-4" />} title="Comments">
          <PullRequestComments comments={pullRequest.comments} />
          <PullRequestCommentComposer pullRequest={pullRequest} onCreateComment={onCreateComment} disabled={creatingComment} />
        </DetailCard>
        <DetailCard icon={<Files className="h-4 w-4" />} title="Changed files">
          <div className="mt-3 flex flex-wrap gap-2">
            {pullRequest.files.length > 0 ? (
              pullRequest.files.map((file) => (
                <span key={file.id} className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground">
                  <FileCode2 className="h-3.5 w-3.5" />
                  {shortPath(file.path)}
                  <span className="font-mono text-success">+{file.additions}</span>
                  <span className="font-mono text-destructive">-{file.deletions}</span>
                </span>
              ))
            ) : (
              <p className="text-xs leading-5 text-muted-foreground">GitHub did not return changed-file metadata for this PR.</p>
            )}
          </div>
        </DetailCard>
      </div>
    </section>
  );
}

export function DetailCard({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <article className="mb-3 rounded-2xl border border-glass-border/30 bg-background/35 p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <span className="text-primary">{icon}</span>
        {title}
      </div>
      {typeof children === "string" ? <p className="mt-2 text-sm leading-6 text-muted-foreground">{children}</p> : children}
    </article>
  );
}

export function MetricTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: "success" | "destructive";
}) {
  return (
    <div className="rounded-2xl border border-glass-border/25 bg-background/35 p-3">
      <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 text-xl font-semibold text-foreground",
          tone === "success" && "text-success",
          tone === "destructive" && "text-destructive",
        )}
      >
        {value}
      </div>
    </div>
  );
}

export function RiskPill({ risk }: { risk: PullRequestSummary["risk"] }) {
  return (
    <span
      className={cn(
        "rounded-full border px-2.5 py-1 text-[11px] font-medium",
        risk === "Low" && "border-success/25 bg-success/10 text-success",
        risk === "Medium" && "border-warning/25 bg-warning/10 text-warning",
        risk === "High" && "border-destructive/25 bg-destructive/10 text-destructive",
      )}
    >
      {risk} risk
    </span>
  );
}
