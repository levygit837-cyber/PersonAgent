import { Check, GitBranch, GitBranchPlus, Loader2, Plus, Search, X } from "lucide-react";
import { createPortal } from "react-dom";
import { type CSSProperties, type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { errorMessage } from "../../api/errors";
import { cn, compactPath } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { useGitBranches, useGitCheckoutBranch, useGitCreateBranch, useGitStatus } from "../../stores/git-store";
import type { GitBranchInfo } from "../../api/client";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../ui/tooltip";

const BRANCH_PANEL_WIDTH = 360;
const BRANCH_PANEL_EXIT_MS = 140;

type BranchSwitcherButtonProps = {
  enabled: boolean;
};

export function BranchSwitcherButton({ enabled }: BranchSwitcherButtonProps) {
  const workspaceRoot = useAppStore((state) => state.selectedWorkspace);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const [mounted, setMounted] = useState(false);
  const [exiting, setExiting] = useState(false);
  const [position, setPosition] = useState<CSSProperties>({ left: 20, bottom: 88 });
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");
  const [operationError, setOperationError] = useState<string | null>(null);
  const [pendingBranch, setPendingBranch] = useState<string | null>(null);
  const statusQuery = useGitStatus(enabled);
  const branchesQuery = useGitBranches(mounted && !exiting && enabled);
  const createMutation = useGitCreateBranch();
  const checkoutMutation = useGitCheckoutBranch();
  const open = mounted && !exiting;
  const status = statusQuery.data;
  const hasWorkspace = Boolean(workspaceRoot);
  const isPending = createMutation.isPending || checkoutMutation.isPending;

  const branches = useMemo(() => dedupeBranchOptions(branchesQuery.data?.branches ?? []), [branchesQuery.data?.branches]);
  const currentBranch = useMemo(() => {
    return (
      branches.find((branch) => branch.current) ??
      (branchesQuery.data?.current || status?.branch
        ? {
            name: branchesQuery.data?.current || status?.branch || "",
            kind: "local" as const,
            current: true,
          }
        : undefined)
    );
  }, [branches, branchesQuery.data?.current, status?.branch]);

  const filteredBranches = useMemo(() => {
    const token = query.trim().toLowerCase();
    return branches.filter((branch) => {
      if (branch.current) return false;
      return !token || branch.name.toLowerCase().includes(token);
    });
  }, [branches, query]);

  const localBranches = filteredBranches.filter((branch) => branch.kind === "local");
  const remoteBranches = filteredBranches.filter((branch) => branch.kind === "remote");

  const clearCloseTimer = () => {
    if (closeTimerRef.current) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  };

  const updatePosition = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const margin = 20;
    const maxLeft = Math.max(margin, window.innerWidth - BRANCH_PANEL_WIDTH - margin);
    setPosition({
      left: Math.min(Math.max(rect.left, margin), maxLeft),
      bottom: Math.max(72, window.innerHeight - rect.top + 10),
    });
  };

  const openPanel = () => {
    if (!enabled) return;
    clearCloseTimer();
    setOperationError(null);
    setMounted(true);
    setExiting(false);
    window.requestAnimationFrame(updatePosition);
  };

  const closePanel = () => {
    if (!mounted || exiting) return;
    clearCloseTimer();
    setExiting(true);
    closeTimerRef.current = window.setTimeout(() => {
      setMounted(false);
      setExiting(false);
      setCreateOpen(false);
      setQuery("");
      setNewBranchName("");
      setOperationError(null);
      setPendingBranch(null);
    }, BRANCH_PANEL_EXIT_MS);
  };

  useEffect(() => clearCloseTimer, []);

  useEffect(() => {
    if (!enabled && mounted) closePanel();
  }, [enabled, mounted]);

  useEffect(() => {
    if (!mounted) return undefined;
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [mounted]);

  useEffect(() => {
    if (!mounted) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      closePanel();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closePanel();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [mounted, exiting]);

  const checkoutBranch = async (branch: GitBranchInfo) => {
    if (branch.current || branch.checked_out_elsewhere || isPending) return;
    setOperationError(null);
    setPendingBranch(`${branch.kind}:${branch.name}`);
    try {
      await checkoutMutation.mutateAsync({ name: branch.name, kind: branch.kind });
      closePanel();
    } catch (error) {
      setOperationError(errorMessage(error));
      setPendingBranch(null);
    }
  };

  const createBranch = async (event: FormEvent) => {
    event.preventDefault();
    const branchName = newBranchName.trim();
    if (!branchName || isPending) return;
    setOperationError(null);
    setPendingBranch(`new:${branchName}`);
    try {
      await createMutation.mutateAsync(branchName);
      closePanel();
    } catch (error) {
      setOperationError(errorMessage(error));
      setPendingBranch(null);
    }
  };

  const branchNeedsAttention = branchHasPendingWork({
    hasWorkspace,
    loading: statusQuery.isLoading || branchesQuery.isLoading,
    hasRepo: Boolean(branchesQuery.data?.is_repo ?? status?.branch),
    dirty: status?.is_dirty ?? false,
    ahead: status?.ahead ?? 0,
  });

  return (
    <>
      <TooltipProvider delayDuration={150}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              ref={triggerRef}
              type="button"
              variant="ghost"
              size="icon"
              disabled={!enabled}
              aria-label="Branches"
              aria-expanded={open}
              title="Branches"
              onClick={() => {
                if (open) closePanel();
                else openPanel();
              }}
              className={cn(
                "relative h-10 w-10 shrink-0 rounded-xl text-muted-foreground hover:text-foreground",
                open && "bg-glass/80 text-foreground",
              )}
            >
              <GitBranch className="h-4 w-4" />
              {branchNeedsAttention ? (
                <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-warning ring-2 ring-card" />
              ) : null}
            </Button>
          </TooltipTrigger>
          <TooltipContent>Branches</TooltipContent>
        </Tooltip>
      </TooltipProvider>

      {mounted
        ? createPortal(
            <div
              ref={panelRef}
              role="dialog"
              aria-label="Branches"
              data-testid="branch-switcher-panel"
              style={position}
              className={cn(
                "personagent-branch-panel fixed z-50 w-[min(360px,calc(100vw-32px))] overflow-hidden rounded-2xl border border-glass-border/35 bg-popover/95 text-popover-foreground shadow-floating backdrop-blur-xl",
                exiting && "is-exiting",
              )}
            >
              <div className="flex items-center gap-2 border-b border-glass-border/25 px-3 py-2.5">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <GitBranch className="h-3.5 w-3.5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-semibold text-foreground">Branches</div>
                  <div className="truncate text-[10px] text-muted-foreground">
                    {currentBranch?.name || (hasWorkspace ? "No active branch" : "No workspace selected")}
                  </div>
                </div>
                <Button
                  type="button"
                  variant={createOpen ? "secondary" : "ghost"}
                  size="iconSm"
                  aria-label="Create branch"
                  disabled={!hasWorkspace || branchesQuery.isLoading || branchesQuery.data?.is_repo === false || isPending}
                  onClick={() => {
                    setCreateOpen((value) => !value);
                    setOperationError(null);
                  }}
                  className="h-7 w-7 rounded-lg"
                >
                  <GitBranchPlus className="h-3.5 w-3.5" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="iconSm"
                  aria-label="Close branches"
                  onClick={closePanel}
                  className="h-7 w-7 rounded-lg"
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>

              <div className="space-y-2 p-2.5">
                {createOpen && (
                  <form className="personagent-branch-create flex items-center gap-2" onSubmit={createBranch}>
                    <input
                      value={newBranchName}
                      onChange={(event) => setNewBranchName(event.currentTarget.value)}
                      placeholder="new-branch-name"
                      autoFocus
                      className="min-w-0 flex-1 rounded-lg border border-glass-border/35 bg-background/60 px-2.5 py-2 text-xs text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/35 focus:ring-1 focus:ring-primary/20"
                    />
                    <Button
                      type="submit"
                      variant="secondary"
                      size="iconSm"
                      aria-label="Create branch"
                      disabled={!newBranchName.trim() || createMutation.isPending}
                      className="h-8 w-8 rounded-lg"
                    >
                      {createMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                    </Button>
                  </form>
                )}

                {status?.is_dirty && (
                  <div className="rounded-lg border border-warning/25 bg-warning/10 px-2.5 py-2 text-[11px] text-warning">
                    Working tree has local changes. Checkout may fail if Git cannot preserve them.
                  </div>
                )}

                {operationError && (
                  <div role="alert" className="rounded-lg border border-destructive/25 bg-destructive/10 px-2.5 py-2 text-[11px] text-destructive">
                    {operationError}
                  </div>
                )}

                {!hasWorkspace ? (
                  <EmptyBranchState title="No workspace selected" description="Select a workspace before switching branches." />
                ) : branchesQuery.isLoading || statusQuery.isLoading ? (
                  <div className="flex items-center gap-2 px-2 py-6 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Loading branches...
                  </div>
                ) : branchesQuery.data?.is_repo === false ? (
                  <EmptyBranchState title="No Git repository" description="The selected workspace is not a Git repository." />
                ) : (
                  <>
                    {currentBranch && (
                      <div className="rounded-xl border border-primary/20 bg-primary/10 p-1.5">
                        <BranchRow branch={currentBranch} pending={false} onSelect={() => undefined} />
                      </div>
                    )}

                    <div className="relative">
                      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                      <input
                        value={query}
                        onChange={(event) => setQuery(event.currentTarget.value)}
                        placeholder="Search branches..."
                        className="h-8 w-full rounded-lg border border-glass-border/30 bg-background/45 pl-8 pr-2 text-xs text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/35 focus:ring-1 focus:ring-primary/20"
                      />
                    </div>

                    <BranchSection title="Local" branches={localBranches} pendingBranch={pendingBranch} onSelect={checkoutBranch} />
                    <BranchSection title="Remote" branches={remoteBranches} pendingBranch={pendingBranch} onSelect={checkoutBranch} />
                    {localBranches.length === 0 && remoteBranches.length === 0 && !currentBranch && (
                      <EmptyBranchState
                        title={query.trim() ? "No matches" : "No branches yet"}
                        description={query.trim() ? "No branches match this search." : "Create the first branch from the current repository state."}
                        compact
                      />
                    )}
                    {localBranches.length === 0 && remoteBranches.length === 0 && currentBranch && query.trim() && (
                      <EmptyBranchState title="No matches" description="No branches match this search." compact />
                    )}
                  </>
                )}
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

function BranchSection({
  title,
  branches,
  pendingBranch,
  onSelect,
}: {
  title: string;
  branches: GitBranchInfo[];
  pendingBranch: string | null;
  onSelect: (branch: GitBranchInfo) => void;
}) {
  if (branches.length === 0) return null;
  return (
    <section>
      <div className="px-1 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {title}
      </div>
      <div className="max-h-36 space-y-1 overflow-y-auto overscroll-contain pr-1">
        {branches.map((branch) => (
          <BranchRow
            key={`${branch.kind}:${branch.name}`}
            branch={branch}
            pending={pendingBranch === `${branch.kind}:${branch.name}`}
            onSelect={() => onSelect(branch)}
          />
        ))}
      </div>
    </section>
  );
}

function BranchRow({
  branch,
  pending,
  onSelect,
}: {
  branch: GitBranchInfo;
  pending: boolean;
  onSelect: () => void;
}) {
  const disabled = branch.current || branch.checked_out_elsewhere || pending;
  const description = branch.checked_out_elsewhere && branch.worktree_path
    ? `In use: ${compactPath(branch.worktree_path)}`
    : branch.last_commit_subject || branch.upstream || (branch.kind === "remote" ? "Remote branch" : "Local branch");
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onSelect}
      title={branch.checked_out_elsewhere && branch.worktree_path ? `Already checked out in ${branch.worktree_path}` : undefined}
      className={cn(
        "flex w-full min-w-0 items-center gap-2 rounded-lg px-2 py-2 text-left text-xs transition-colors",
        branch.current ? "cursor-default text-foreground" : "text-muted-foreground hover:bg-glass/80 hover:text-foreground",
        branch.checked_out_elsewhere && "cursor-not-allowed opacity-60 hover:bg-transparent hover:text-muted-foreground",
        pending && "opacity-70",
      )}
    >
      <span className="flex h-4 w-4 shrink-0 items-center justify-center">
        {pending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : branch.current ? (
          <Check className="h-3.5 w-3.5 text-primary" />
        ) : (
          <GitBranch className="h-3.5 w-3.5" />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{branch.name}</span>
        <span className="block truncate text-[10px] text-muted-foreground/75">
          {description}
        </span>
      </span>
    </button>
  );
}

function EmptyBranchState({
  title,
  description,
  compact = false,
}: {
  title: string;
  description: string;
  compact?: boolean;
}) {
  return (
    <div className={cn("rounded-xl border border-glass-border/30 bg-background/35 px-3 text-center", compact ? "py-3" : "py-6")}>
      <div className="text-xs font-medium text-foreground">{title}</div>
      <div className="mt-1 text-[11px] leading-4 text-muted-foreground">{description}</div>
    </div>
  );
}

function branchHasPendingWork(input: {
  hasWorkspace: boolean;
  loading: boolean;
  hasRepo: boolean;
  dirty: boolean;
  ahead: number;
}) {
  return input.hasWorkspace && !input.loading && input.hasRepo && (input.dirty || input.ahead > 0);
}

function dedupeBranchOptions(branches: GitBranchInfo[]) {
  const localNames = new Set(
    branches
      .filter((branch) => branch.kind === "local")
      .map((branch) => branch.name),
  );
  const localUpstreams = new Set(
    branches
      .filter((branch) => branch.kind === "local" && branch.upstream)
      .map((branch) => branch.upstream as string),
  );
  return branches.filter((branch) => {
    if (branch.kind !== "remote") return true;
    if (localUpstreams.has(branch.name)) return false;
    return !localNames.has(remoteTrackingBranchName(branch.name));
  });
}

function remoteTrackingBranchName(remoteName: string) {
  const slashIndex = remoteName.indexOf("/");
  return slashIndex === -1 ? remoteName : remoteName.slice(slashIndex + 1);
}
