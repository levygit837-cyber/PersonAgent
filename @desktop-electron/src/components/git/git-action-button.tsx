import { type ChangeEvent, useState } from "react";
import {
  FolderX,
  GitBranch,
  GitBranchIcon,
  GitCommit,
  GitPullRequest,
  Loader2,
  Sparkles,
  Upload,
} from "lucide-react";
import { errorMessage } from "../../api/errors";
import {
  useGitCommit,
  useGitGenerateCommitMessage,
  useGitOpenPr,
  useGitPush,
  useGitRecentActions,
  useGitStatus,
} from "../../stores/git-store";
import { useAppStore } from "../../stores/app-store";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import type { OperationFeedback } from "./git-action-button/types";
import { GitStatusSummary } from "./git-action-button/git-status-summary";
import { MenuFeedback, CommitFeedback } from "./git-action-button/feedback";
import { RecentActionsSection } from "./git-action-button/recent-actions";

export function GitActionButton({
  workspaceRoot: workspaceRootOverride,
  compact = false,
}: {
  workspaceRoot?: string | null;
  compact?: boolean;
}) {
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceRoot = workspaceRootOverride || selectedWorkspace;
  const [open, setOpen] = useState(false);
  const [commitDialogOpen, setCommitDialogOpen] = useState(false);
  const [commitMessage, setCommitMessage] = useState("");
  const [autoGenerateComment, setAutoGenerateComment] = useState(false);
  const [commitFeedback, setCommitFeedback] = useState<OperationFeedback | null>(null);
  const [menuFeedback, setMenuFeedback] = useState<OperationFeedback | null>(null);
  const [pendingCommitMode, setPendingCommitMode] = useState<"commit" | "commitAndPush" | null>(null);

  const { data: status, isLoading, isFetching } = useGitStatus(true, workspaceRoot);
  const commitMutation = useGitCommit(workspaceRoot);
  const pushMutation = useGitPush(workspaceRoot);
  const prMutation = useGitOpenPr(workspaceRoot);
  const generateMessageMutation = useGitGenerateCommitMessage(workspaceRoot);

  const hasWorkspace = Boolean(workspaceRoot);
  const hasRepo = hasWorkspace && Boolean(status?.branch);
  const recentActionsQuery = useGitRecentActions(open && hasRepo, workspaceRoot);
  const isDirty = status?.is_dirty ?? false;
  const hasAhead = (status?.ahead ?? 0) > 0;
  const hasBehind = (status?.behind ?? 0) > 0;
  const modifiedCount = status?.modified_count ?? 0;
  const untrackedCount = status?.untracked_count ?? 0;
  const changedCount = modifiedCount + untrackedCount;
  const branch = status?.branch || "";
  const isCommitActionPending = commitMutation.isPending || pushMutation.isPending;
  const canCommit = Boolean(commitMessage.trim() || autoGenerateComment);
  const commitSucceeded = commitFeedback?.kind === "success";
  const hasPendingWork = isDirty || hasAhead;

  const baseButtonClass =
    compact
      ? "relative inline-flex h-7 max-w-[132px] items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium transition-all duration-200"
      : "relative inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-[11px] font-medium transition-all duration-200";

  let buttonClass = baseButtonClass;
  let showPulse = false;

  if (!hasWorkspace) {
    buttonClass += " border-glass-border/25 bg-transparent text-muted-foreground/50 cursor-not-allowed";
  } else if (isLoading) {
    buttonClass += " border-glass-border/35 bg-background/80 text-muted-foreground";
  } else if (!hasRepo) {
    buttonClass += " border-glass-border/25 bg-transparent text-muted-foreground/60";
  } else if (hasPendingWork) {
    buttonClass += " border-glass-border/35 bg-background/80 text-muted-foreground hover:border-glass-border/55 hover:bg-glass/70 hover:text-foreground";
    showPulse = true;
  } else if (hasBehind) {
    buttonClass += " border-glass-border/35 bg-background/80 text-muted-foreground";
  } else {
    buttonClass += " border-glass-border/35 bg-background/80 text-muted-foreground hover:border-glass-border/55 hover:bg-glass/70 hover:text-foreground";
  }

  const openCommitDialog = () => {
    setOpen(false);
    setCommitDialogOpen(true);
    setCommitMessage("");
    setAutoGenerateComment(false);
    setCommitFeedback(null);
    setPendingCommitMode(null);
    setMenuFeedback(null);
  };

  const closeCommitDialog = () => {
    if (isCommitActionPending) return;
    setCommitDialogOpen(false);
    setCommitMessage("");
    setAutoGenerateComment(false);
    setCommitFeedback(null);
    setPendingCommitMode(null);
  };

  const handleAutoGenerateCommentChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const enabled = event.currentTarget.checked;
    setAutoGenerateComment(enabled);
    setCommitFeedback(null);
    if (!enabled) return;
    try {
      const result = await generateMessageMutation.mutateAsync();
      setCommitMessage(result.message);
    } catch (error) {
      setCommitFeedback({
        kind: "error",
        title: "Auto generate comment failed",
        detail: errorMessage(error),
      });
    }
  };

  const handleCommit = async (pushAfterCommit: boolean) => {
    if (!canCommit || isCommitActionPending || commitSucceeded) return;
    setCommitFeedback(null);
    setPendingCommitMode(pushAfterCommit ? "commitAndPush" : "commit");
    let committed = false;
    let committedLabel = commitMessage.trim();
    try {
      const commitResult = await commitMutation.mutateAsync({
        message: committedLabel,
        autoGenerateMessage: autoGenerateComment,
      });
      committed = true;
      committedLabel = commitResult.message || committedLabel;
      setCommitMessage(committedLabel);

      let detail = commitResult.short_sha ? `${commitResult.short_sha} · ${committedLabel}` : committedLabel;
      if (pushAfterCommit) {
        const pushResult = await pushMutation.mutateAsync();
        const destination = pushResult.upstream || pushResult.branch;
        if (destination) detail = `${detail} · pushed to ${destination}`;
      }
      setAutoGenerateComment(false);
      setCommitFeedback({
        kind: "success",
        title: pushAfterCommit ? "Commit and Push completed" : "Commit completed",
        detail,
      });
    } catch (error) {
      setCommitFeedback({
        kind: "error",
        title: committed ? "Commit created, push failed" : pushAfterCommit ? "Commit and Push failed" : "Commit failed",
        detail: errorMessage(error),
      });
    } finally {
      setPendingCommitMode(null);
    }
  };

  const handlePush = async () => {
    if (!hasRepo || pushMutation.isPending) return;
    setMenuFeedback(null);
    try {
      const result = await pushMutation.mutateAsync();
      setMenuFeedback({
        kind: "success",
        title: "Push completed",
        detail: result.output || `Pushed ${result.branch || branch}`,
      });
    } catch (error) {
      setMenuFeedback({ kind: "error", title: "Push failed", detail: errorMessage(error) });
    }
  };

  const handleOpenPr = async () => {
    if (!hasRepo || prMutation.isPending) return;
    setMenuFeedback(null);
    try {
      const result = await prMutation.mutateAsync();
      setMenuFeedback({
        kind: "success",
        title: "Pull request ready",
        detail: result.url || result.output || "Pull request action completed.",
      });
    } catch (error) {
      setMenuFeedback({ kind: "error", title: "Open PR failed", detail: errorMessage(error) });
    }
  };

  const buttonContent = (
    <>
      {!hasWorkspace ? (
        <FolderX className="h-3 w-3 shrink-0" />
      ) : !hasRepo && !isLoading ? (
        <GitBranchIcon className="h-3 w-3 shrink-0 opacity-50" />
      ) : (
        <GitBranch className="h-3 w-3 shrink-0" />
      )}

      {!hasWorkspace ? (
        <span>No workspace</span>
      ) : isLoading ? (
        <span className="flex items-center gap-1">
          <Loader2 className="h-2.5 w-2.5 animate-spin" />
          <span className="text-muted-foreground">Git</span>
        </span>
      ) : !hasRepo ? (
        <span>No repository</span>
      ) : (
        <span className="truncate">{branch}</span>
      )}

      {hasRepo && isFetching && !isLoading && (
        <Loader2 className="h-2.5 w-2.5 animate-spin text-muted-foreground/60" />
      )}

      {hasRepo && isDirty && (
        <span className="relative flex h-3.5 items-center justify-center">
          <span
            className={[
              "absolute inline-flex h-2 w-2 rounded-full bg-warning",
              showPulse ? "personagent-git-pulse" : "",
            ].join(" ")}
          />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-warning" />
        </span>
      )}

      {hasRepo && hasAhead && !isDirty && status && (
        <span className="relative flex h-3.5 items-center justify-center" aria-label={`${status.ahead} pending commit(s)`}>
          <span
            className={[
              "absolute inline-flex h-2 w-2 rounded-full bg-warning",
              showPulse ? "personagent-git-pulse" : "",
            ].join(" ")}
          />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-warning" />
        </span>
      )}

      {hasRepo && hasAhead && !isDirty && status && (
        <span className="rounded-full bg-warning/20 px-1 text-[10px] font-semibold text-warning">
          ↑{status.ahead}
        </span>
      )}

      {hasRepo && isDirty && modifiedCount > 0 && (
        <span className="rounded-full bg-warning/20 px-1 text-[10px] font-semibold text-warning">
          {modifiedCount}
        </span>
      )}
    </>
  );

  return (
    <>
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className={buttonClass}
            disabled={!hasWorkspace}
            title={
              !hasWorkspace
                ? "Select a workspace"
                : !hasRepo
                  ? "No Git repository detected"
                  : `${branch} - click for actions`
            }
          >
            {buttonContent}
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuContent side="bottom" align="end" className="personagent-dropdown-fade w-72">
          <DropdownMenuLabel className="text-xs font-semibold">Git Actions</DropdownMenuLabel>

          <GitStatusSummary
            hasWorkspace={hasWorkspace}
            isLoading={isLoading}
            hasRepo={hasRepo}
            branch={branch}
            modifiedCount={modifiedCount}
            untrackedCount={untrackedCount}
            hasAhead={hasAhead}
            hasBehind={hasBehind}
            status={status}
            isDirty={isDirty}
          />

          <DropdownMenuSeparator />

          <DropdownMenuItem
            onSelect={(event) => {
              event.preventDefault();
              if (!hasRepo) return;
              openCommitDialog();
            }}
            disabled={!hasRepo || !isDirty || isCommitActionPending}
            className="gap-2 text-xs"
          >
            <GitCommit className="h-3.5 w-3.5" />
            Commit changes...
            {commitMutation.isPending && <Loader2 className="ml-auto h-3 w-3 animate-spin" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onSelect={(event) => {
              event.preventDefault();
              void handlePush();
            }}
            disabled={!hasRepo || pushMutation.isPending}
            className="gap-2 text-xs"
          >
            <Upload className="h-3.5 w-3.5" />
            Push
            {pushMutation.isPending && <Loader2 className="ml-auto h-3 w-3 animate-spin" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onSelect={(event) => {
              event.preventDefault();
              void handleOpenPr();
            }}
            disabled={!hasRepo || !hasAhead || prMutation.isPending}
            className="gap-2 text-xs"
          >
            <GitPullRequest className="h-3.5 w-3.5" />
            Open PR
            {prMutation.isPending && <Loader2 className="ml-auto h-3 w-3 animate-spin" />}
          </DropdownMenuItem>

          {menuFeedback ? <MenuFeedback feedback={menuFeedback} /> : null}

          <DropdownMenuSeparator />

          <RecentActionsSection query={recentActionsQuery} />
        </DropdownMenuContent>
      </DropdownMenu>

      {commitDialogOpen && hasRepo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-glass-border/35 bg-card/95 p-4 shadow-floating backdrop-blur-xl">
            <h3 className="text-sm font-semibold text-foreground">Commit changes</h3>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {changedCount} changed file(s) will be committed on {branch}.
            </p>

            <label className="mt-3 flex items-center gap-2 rounded-xl border border-glass-border/30 bg-background/45 px-3 py-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={autoGenerateComment}
                disabled={generateMessageMutation.isPending || isCommitActionPending || commitSucceeded}
                onChange={(event) => void handleAutoGenerateCommentChange(event)}
                className="h-3.5 w-3.5 accent-primary"
              />
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              <span className="font-medium text-foreground">Auto generate comment</span>
              {generateMessageMutation.isPending ? <Loader2 className="ml-auto h-3 w-3 animate-spin" /> : null}
            </label>

            <textarea
              value={commitMessage}
              onChange={(event) => {
                setCommitMessage(event.target.value);
                setCommitFeedback(null);
              }}
              placeholder="Commit message..."
              disabled={isCommitActionPending || commitSucceeded}
              className="mt-3 min-h-[88px] w-full resize-none rounded-xl border border-glass-border/35 bg-background/60 px-3 py-2 text-xs text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/30 focus:ring-1 focus:ring-primary/20 disabled:opacity-60"
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  void handleCommit(false);
                }
              }}
            />

            {commitFeedback ? <CommitFeedback feedback={commitFeedback} /> : null}

            <div className="mt-3 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={closeCommitDialog}
                disabled={isCommitActionPending}
                className="rounded-lg px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-glass/60 hover:text-foreground disabled:opacity-50"
              >
                {commitSucceeded ? "Done" : "Cancel"}
              </button>
              <button
                type="button"
                disabled={!canCommit || isCommitActionPending || commitSucceeded}
                onClick={() => void handleCommit(false)}
                className="rounded-lg border border-glass-border/35 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-glass/70 disabled:opacity-40"
              >
                {pendingCommitMode === "commit" ? "Committing..." : "Commit"}
              </button>
              <button
                type="button"
                disabled={!canCommit || isCommitActionPending || commitSucceeded}
                onClick={() => void handleCommit(true)}
                className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-40"
              >
                {pendingCommitMode === "commitAndPush" ? "Committing and pushing..." : "Commit and Push"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
