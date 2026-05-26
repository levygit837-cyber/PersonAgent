import { FolderX, GitBranch, GitBranchIcon, Loader2 } from "lucide-react";

export function GitStatusSummary({
  hasWorkspace,
  isLoading,
  hasRepo,
  branch,
  modifiedCount,
  untrackedCount,
  hasAhead,
  hasBehind,
  status,
  isDirty,
}: {
  hasWorkspace: boolean;
  isLoading: boolean;
  hasRepo: boolean;
  branch: string;
  modifiedCount: number;
  untrackedCount: number;
  hasAhead: boolean;
  hasBehind: boolean;
  status?: { ahead: number; behind: number };
  isDirty: boolean;
}) {
  return (
    <div className="space-y-1.5 px-2 py-2 text-[11px] text-muted-foreground">
      {!hasWorkspace ? (
        <div className="flex items-center gap-2 text-muted-foreground/70">
          <FolderX className="h-3 w-3 shrink-0" />
          <span>No workspace selected</span>
        </div>
      ) : isLoading ? (
        <div className="flex items-center gap-2">
          <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
          <span>Loading status...</span>
        </div>
      ) : !hasRepo ? (
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <GitBranchIcon className="h-3 w-3 shrink-0 opacity-50" />
            <span className="font-medium text-foreground">No Git repository</span>
          </div>
          <p className="pl-5 text-[10px] leading-4 text-muted-foreground/70">
            This directory is not a Git repository. Run "git init" or select another workspace.
          </p>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <GitBranch className="h-3 w-3 shrink-0" />
            <span className="font-medium text-foreground">{branch}</span>
          </div>
          {(modifiedCount > 0 || untrackedCount > 0) && (
            <div className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
              <span>
                {modifiedCount} modified
                {untrackedCount > 0 ? `, ${untrackedCount} untracked` : ""}
              </span>
            </div>
          )}
          {hasAhead && status && (
            <div className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
              <span>{status.ahead} commit(s) ahead of remote</span>
            </div>
          )}
          {hasBehind && status && (
            <div className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground" />
              <span>{status.behind} commit(s) behind remote</span>
            </div>
          )}
          {!isDirty && !hasAhead && !hasBehind && (
            <div className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/70" />
              <span>Working tree clean</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
