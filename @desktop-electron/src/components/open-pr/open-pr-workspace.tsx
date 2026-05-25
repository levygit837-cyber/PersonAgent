import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  FileCode2,
  FolderOpen,
  GitBranch,
  GitPullRequest,
  RotateCw,
} from "lucide-react";
import { PullRequestCommentComposer } from "./comments/pull-request-comment-composer";
import { PullRequestComments } from "./comments/pull-request-comments";
import { DiffCard } from "./diff/diff-card";
import { DND_FILE_MIME, FileRailButton } from "./diff/file-rail-button";
import { PullRequestDetailPanel } from "./detail-panel";
import { FilterSelect } from "./queue/filter-select";
import { PullRequestCard } from "./queue/pull-request-card";
import { QueueFilterButton } from "./queue/queue-filter-button";
import { QueueState } from "./queue/queue-state";
import { ReviewAgentWindow } from "./review-agent-window";
import { PullRequestReviewView } from "./review-view";
import { StatusPill } from "./shared/status-pill";
import { prTotals, uniqueBranches, uniqueProjects } from "./shared/pr-utils";
import type {
  PullRequestCommentKind,
  PullRequestStatus,
  PullRequestSummary,
} from "../../api/client";
import { cn, workspaceName } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { useGitBranches, useGitCreatePullRequestComment, useGitPullRequests, useWorkspaceProjects } from "../../stores/git-store";
import { Button } from "../ui/button";

type ReviewMode = "queue" | "review";
type QueueFilter = "all" | "mine" | "flagged";

type PullRequestFile = PullRequestSummary["files"][number];

export function OpenPrWorkspace() {
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const recentWorkspaces = useAppStore((state) => state.recentWorkspaces);
  const selectWorkspace = useAppStore((state) => state.selectWorkspace);
  const workspaceProject = selectedWorkspace ? workspaceName(selectedWorkspace) : undefined;
  const pullRequestsQuery = useGitPullRequests(true);
  const workspaceProjectsQuery = useWorkspaceProjects(true);
  const branchesQuery = useGitBranches(Boolean(selectedWorkspace));
  const createCommentMutation = useGitCreatePullRequestComment();
  const pullRequests = pullRequestsQuery.data?.pullRequests ?? [];
  const backendProjects = workspaceProjectsQuery.data?.projects ?? [];
  const projects = useMemo(
    () => uniqueProjects(pullRequests, workspaceProject, selectedWorkspace, recentWorkspaces, backendProjects),
    [backendProjects, pullRequests, recentWorkspaces, selectedWorkspace, workspaceProject],
  );
  const selectedProjectPath = selectedWorkspace ?? projects[0]?.path ?? "";
  const [mode, setMode] = useState<ReviewMode>("queue");
  const [selectedBranch, setSelectedBranch] = useState("all");
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");
  const [selectedPrId, setSelectedPrId] = useState("");
  const [detailPr, setDetailPr] = useState<PullRequestSummary | null>(null);
  const filteredPullRequests = useMemo(
    () =>
      pullRequests.filter((pullRequest) => {
        if (selectedProjectPath && pullRequest.projectPath !== selectedProjectPath) return false;
        if (selectedBranch !== "all" && pullRequest.branch !== selectedBranch) return false;
        if (queueFilter === "mine") return pullRequest.isMine;
        if (queueFilter === "flagged") return pullRequest.isFlagged;
        return true;
      }),
    [pullRequests, queueFilter, selectedBranch, selectedProjectPath],
  );
  const branchOptions = useMemo(
    () => uniqueBranches(pullRequests, selectedProjectPath, branchesQuery.data?.branches ?? []),
    [branchesQuery.data?.branches, pullRequests, selectedProjectPath],
  );
  const selectedPr = useMemo(
    () => filteredPullRequests.find((pullRequest) => pullRequest.id === selectedPrId) ?? null,
    [filteredPullRequests, selectedPrId],
  );
  const activePr = selectedPr ?? detailPr;
  const firstFileId = activePr?.files[0]?.id ?? "";
  const [openFileIds, setOpenFileIds] = useState<string[]>(() => (firstFileId ? [firstFileId] : []));
  const [activeFileId, setActiveFileId] = useState(firstFileId);

  useEffect(() => {
    const firstProjectPath = projects[0]?.path;
    if (!selectedWorkspace && firstProjectPath) {
      void selectWorkspace(firstProjectPath);
    }
  }, [projects, selectWorkspace, selectedWorkspace]);

  useEffect(() => {
    if (branchOptions.length > 0 && selectedBranch !== "all" && !branchOptions.includes(selectedBranch)) {
      setSelectedBranch("all");
    }
  }, [branchOptions, selectedBranch]);

  useEffect(() => {
    if (selectedPrId && !filteredPullRequests.some((pullRequest) => pullRequest.id === selectedPrId)) {
      setSelectedPrId("");
      setMode("queue");
    }
  }, [filteredPullRequests, selectedPrId]);

  useEffect(() => {
    if (selectedPr) {
      setDetailPr(selectedPr);
    }
  }, [selectedPr]);

  useEffect(() => {
    const nextFirstFileId = activePr?.files[0]?.id ?? "";
    setOpenFileIds(nextFirstFileId ? [nextFirstFileId] : []);
    setActiveFileId(nextFirstFileId);
  }, [activePr?.id, activePr?.files]);

  const replaceVisibleFile = (fileId: string) => {
    if (!activePr?.files.some((file) => file.id === fileId)) return;
    setOpenFileIds([fileId]);
    setActiveFileId(fileId);
  };

  const addVisibleFile = (fileId: string) => {
    if (!activePr?.files.some((file) => file.id === fileId)) return;
    setOpenFileIds((current) => (current.includes(fileId) ? current : [...current, fileId]));
    setActiveFileId(fileId);
  };

  const focusVisibleFile = (fileId: string) => {
    if (openFileIds.includes(fileId)) {
      setActiveFileId(fileId);
    }
  };

  const closeFile = (fileId: string) => {
    if (openFileIds.length <= 1) return;
    const nextFileIds = openFileIds.filter((id) => id !== fileId);
    setOpenFileIds(nextFileIds);
    if (activeFileId === fileId) {
      setActiveFileId(nextFileIds[0] ?? "");
    }
  };

  const startReview = () => {
    if (!activePr) return;
    setMode("review");
    if (!openFileIds.length && firstFileId) {
      setOpenFileIds([firstFileId]);
      setActiveFileId(firstFileId);
    }
  };

  const openFiles = activePr?.files.filter((file) => openFileIds.includes(file.id)) ?? [];
  const activeFile = activePr?.files.find((file) => file.id === activeFileId) ?? openFiles[0] ?? activePr?.files[0];
  const totals = activePr ? prTotals(activePr) : { additions: 0, deletions: 0 };
  const handleSelectPr = (pullRequest: PullRequestSummary) => {
    setMode("queue");
    setSelectedPrId((current) => (current === pullRequest.id ? "" : pullRequest.id));
    setDetailPr(pullRequest);
  };
  const handleCreateComment = (input: { number: number; body: string; kind: PullRequestCommentKind; status?: PullRequestStatus | null }) =>
    createCommentMutation.mutateAsync(input);

  return (
    <section className="relative flex h-full min-w-0 flex-col overflow-hidden bg-background" data-testid="open-pr-workspace">
      {mode === "queue" || !activePr ? (
        <PullRequestQueueView
          pullRequests={filteredPullRequests}
          allPullRequests={pullRequests}
          projects={projects}
          branchOptions={branchOptions}
          selectedPr={selectedPr}
          detailPr={detailPr}
          selectedProjectPath={selectedProjectPath}
          selectedBranch={selectedBranch}
          queueFilter={queueFilter}
          selectedWorkspace={selectedWorkspace}
          viewerLogin={pullRequestsQuery.data?.viewerLogin ?? null}
          loading={pullRequestsQuery.isLoading || pullRequestsQuery.isFetching}
          errors={pullRequestsQuery.data?.errors ?? (pullRequestsQuery.error ? [pullRequestsQuery.error.message] : [])}
          onSelectProject={(projectPath) => {
            void selectWorkspace(projectPath);
            setSelectedBranch("all");
            setSelectedPrId("");
          }}
          onSelectBranch={setSelectedBranch}
          onSelectFilter={(filter) => {
            setQueueFilter(filter);
            setSelectedPrId("");
          }}
          onSelectPr={handleSelectPr}
          onStartReview={startReview}
          onRefresh={() => void pullRequestsQuery.refetch()}
          onCreateComment={handleCreateComment}
          creatingComment={createCommentMutation.isPending}
        />
      ) : (
        <PullRequestReviewView
          pullRequest={activePr}
          totals={totals}
          activeFileId={activeFileId}
          activeFile={activeFile}
          openFiles={openFiles}
          onBack={() => setMode("queue")}
          onSelectFile={replaceVisibleFile}
          onAddFile={addVisibleFile}
          onFocusFile={focusVisibleFile}
          onCloseFile={closeFile}
        />
      )}
    </section>
  );
}

function PullRequestQueueView({
  pullRequests,
  allPullRequests,
  projects,
  branchOptions,
  selectedPr,
  detailPr,
  selectedProjectPath,
  selectedBranch,
  queueFilter,
  selectedWorkspace,
  viewerLogin,
  loading,
  errors,
  onSelectProject,
  onSelectBranch,
  onSelectFilter,
  onSelectPr,
  onStartReview,
  onRefresh,
  onCreateComment,
  creatingComment,
}: {
  pullRequests: PullRequestSummary[];
  allPullRequests: PullRequestSummary[];
  projects: Array<{ name: string; path: string }>;
  branchOptions: string[];
  selectedPr: PullRequestSummary | null;
  detailPr: PullRequestSummary | null;
  selectedProjectPath: string;
  selectedBranch: string;
  queueFilter: QueueFilter;
  selectedWorkspace?: string;
  viewerLogin?: string | null;
  loading: boolean;
  errors: string[];
  onSelectProject: (project: string) => void;
  onSelectBranch: (branch: string) => void;
  onSelectFilter: (filter: QueueFilter) => void;
  onSelectPr: (pullRequest: PullRequestSummary) => void;
  onStartReview: () => void;
  onRefresh: () => void;
  onCreateComment: (input: { number: number; body: string; kind: PullRequestCommentKind; status?: PullRequestStatus | null }) => Promise<unknown>;
  creatingComment: boolean;
}) {
  const displayedPr = selectedPr ?? detailPr;
  const detailOpen = Boolean(selectedPr);
  const totals = displayedPr ? prTotals(displayedPr) : { additions: 0, deletions: 0 };
  const workspaceLabel = selectedWorkspace ? workspaceName(selectedWorkspace) : "Workspace";
  const flaggedCount = allPullRequests.filter((pullRequest) => pullRequest.projectPath === selectedProjectPath && pullRequest.isFlagged).length;

  return (
    <>
      <header className="flex h-auto shrink-0 items-start gap-4 border-b border-glass-border/25 bg-background/95 px-5 py-4 max-[760px]:flex-col">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">Repository Review</div>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-foreground">Open Pull Requests</h1>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {workspaceLabel} review queue with live PR comments, changed files and merge signals.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 max-[760px]:w-full max-[760px]:justify-start">
          <FilterSelect
            label="Project"
            icon={<FolderOpen className="h-3.5 w-3.5" />}
            value={selectedProjectPath}
            onChange={onSelectProject}
            options={projects.map((project) => ({ value: project.path, label: project.name }))}
          />
          <FilterSelect
            label="Branch"
            icon={<GitBranch className="h-3.5 w-3.5" />}
            value={selectedBranch}
            onChange={onSelectBranch}
            options={[
              { value: "all", label: "All branches" },
              ...branchOptions.map((branch) => ({ value: branch, label: branch })),
            ]}
          />
          <div className="hidden overflow-hidden rounded-xl border border-glass-border/35 bg-card/70 text-xs text-muted-foreground shadow-soft min-[980px]:flex">
            <QueueFilterButton active={queueFilter === "all"} onClick={() => onSelectFilter("all")}>All</QueueFilterButton>
            <QueueFilterButton active={queueFilter === "mine"} onClick={() => onSelectFilter("mine")} bordered>
              Mine
            </QueueFilterButton>
            <QueueFilterButton active={queueFilter === "flagged"} onClick={() => onSelectFilter("flagged")} bordered>
              Flagged
            </QueueFilterButton>
          </div>
          <Button variant="subtle" size="iconSm" aria-label="Refresh pull requests" className="rounded-xl" onClick={onRefresh} disabled={loading}>
            <RotateCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          </Button>
        </div>
      </header>

      <div
        className={cn(
          "grid min-h-0 flex-1 overflow-hidden p-5 transition-[grid-template-columns,gap,max-width] duration-300 ease-out max-[1040px]:overflow-auto",
          detailOpen
            ? "grid-cols-[minmax(320px,420px)_minmax(0,1fr)] gap-4 max-[1040px]:grid-cols-1"
            : "mx-auto w-full max-w-[540px] grid-cols-[minmax(0,1fr)_minmax(0,0fr)] gap-0 max-[1040px]:grid-cols-1",
        )}
      >
        <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-card/75 shadow-soft backdrop-blur-xl">
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-glass-border/25 px-4 py-3">
            <div>
              <div className="text-sm font-semibold text-foreground">Queue</div>
              <div className="text-[11px] text-muted-foreground">Ordered by GitHub update time</div>
            </div>
            <span className="rounded-full border border-warning/30 bg-warning/10 px-2 py-1 text-[10px] font-semibold text-warning">
              {flaggedCount} flagged
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loading ? (
              <QueueState icon={<RotateCw className="h-4 w-4 animate-spin" />} title="Loading pull requests" detail="" />
            ) : errors.length > 0 ? (
              <QueueState icon={<AlertCircle className="h-4 w-4" />} title="Pull requests unavailable" detail={errors[0] ?? "GitHub CLI did not return PR data."} />
            ) : pullRequests.length > 0 ? (
              pullRequests.map((pullRequest) => (
                <PullRequestCard
                  key={pullRequest.id}
                  pullRequest={pullRequest}
                  active={pullRequest.id === selectedPr?.id}
                  onClick={() => onSelectPr(pullRequest)}
                />
              ))
            ) : (
              <QueueState
                icon={<GitPullRequest className="h-4 w-4" />}
                title={queueFilter === "mine" && viewerLogin ? "No pull requests assigned to you" : "No pull requests"}
                detail={queueFilter === "mine" && !viewerLogin ? "GitHub did not return the current user." : "No PRs match the current project, branch and queue filter."}
              />
            )}
          </div>
        </section>

        {displayedPr ? (
          <PullRequestDetailPanel
            pullRequest={displayedPr}
            totals={totals}
            open={detailOpen}
            onStartReview={onStartReview}
            onCreateComment={onCreateComment}
            creatingComment={creatingComment}
          />
        ) : null}
      </div>
    </>
  );
}




