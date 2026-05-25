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
  ArrowLeft,
  ArrowUp,
  AlertCircle,
  Bot,
  Bug,
  Check,
  ChevronDown,
  ExternalLink,
  FileCode2,
  Files,
  FolderOpen,
  GitBranch,
  GitPullRequest,
  MessageSquare,
  MessageSquarePlus,
  RotateCw,
  Route,
  ScanSearch,
  Send,
  ShieldAlert,
  UserRound,
} from "lucide-react";
import { DiffCard } from "./diff/diff-card";
import { DND_FILE_MIME, FileRailButton } from "./diff/file-rail-button";
import { FilterSelect } from "./queue/filter-select";
import { PullRequestCard } from "./queue/pull-request-card";
import { QueueFilterButton } from "./queue/queue-filter-button";
import { QueueState } from "./queue/queue-state";
import { StatusPill } from "./shared/status-pill";
import { clampValue, formatDateTime, prTotals, shortPath, statusText, uniqueBranches, uniqueProjects } from "./shared/pr-utils";
import type {
  PullRequestComment,
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

interface ReviewAgentMessage {
  id: string;
  role: "agent" | "user";
  content: string;
}

const COMMENT_OPTIONS: Array<{
  id: string;
  label: string;
  kind: PullRequestCommentKind;
  status?: PullRequestStatus;
}> = [
  { id: "human_review", label: "Human analysis", kind: "human_review" },
  { id: "ai_review", label: "AI analysis", kind: "ai_review" },
  { id: "needs_review", label: "Needs review", kind: "status", status: "needs_review" },
  { id: "merged", label: "Merged", kind: "status", status: "merged" },
  { id: "refused", label: "Refused", kind: "status", status: "refused" },
];

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

function PullRequestDetailPanel({
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

function PullRequestComments({ comments }: { comments: PullRequestComment[] }) {
  if (comments.length === 0) {
    return <p className="mt-2 text-xs leading-5 text-muted-foreground">No PR comments yet.</p>;
  }

  return (
    <div className="mt-3 space-y-2">
      {comments.slice(0, 5).map((comment) => (
        <article key={comment.id} className="rounded-xl border border-glass-border/25 bg-background/35 p-3">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1 font-medium text-foreground">
              {comment.source === "ai" ? <Bot className="h-3.5 w-3.5 text-primary" /> : <UserRound className="h-3.5 w-3.5" />}
              {comment.author}
            </span>
            <CommentKindPill comment={comment} />
            {comment.createdAt ? <span>{formatDateTime(comment.createdAt)}</span> : null}
          </div>
          <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">{comment.body}</p>
        </article>
      ))}
    </div>
  );
}

function PullRequestCommentComposer({
  pullRequest,
  onCreateComment,
  disabled,
}: {
  pullRequest: PullRequestSummary;
  onCreateComment: (input: { number: number; body: string; kind: PullRequestCommentKind; status?: PullRequestStatus | null }) => Promise<unknown>;
  disabled: boolean;
}) {
  const [optionId, setOptionId] = useState(COMMENT_OPTIONS[0].id);
  const [body, setBody] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const selectedOption = COMMENT_OPTIONS.find((option) => option.id === optionId) ?? COMMENT_OPTIONS[0];

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const value = body.trim();
    if (!value) return;
    setFeedback(null);
    try {
      await onCreateComment({ number: pullRequest.number, body: value, kind: selectedOption.kind, status: selectedOption.status ?? null });
      setBody("");
      setFeedback("Comment sent");
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Comment failed");
    }
  };

  return (
    <form className="mt-3 rounded-xl border border-glass-border/25 bg-background/30 p-3" onSubmit={submit}>
      <div className="flex flex-wrap gap-1.5">
        {COMMENT_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={cn(
              "rounded-full border px-2.5 py-1 text-[11px] transition-[background,border-color,color] duration-150",
              option.id === optionId
                ? "border-primary/35 bg-primary/10 text-foreground"
                : "border-glass-border/30 text-muted-foreground hover:bg-glass/80 hover:text-foreground",
            )}
            onClick={() => setOptionId(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <textarea
        value={body}
        rows={3}
        onChange={(event) => setBody(event.currentTarget.value)}
        placeholder="Write a PR comment..."
        className="mt-3 min-h-20 w-full resize-none rounded-xl border border-glass-border/35 bg-background/55 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/70 focus:border-primary/35 focus:ring-1 focus:ring-primary/20"
      />
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="min-w-0 text-[11px] text-muted-foreground">{feedback}</span>
        <Button type="submit" size="xs" className="rounded-xl" disabled={disabled || !body.trim()}>
          <Send className="h-3.5 w-3.5" />
          Send comment
        </Button>
      </div>
    </form>
  );
}

function ContextValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-glass-border/20 bg-background/30 px-3 py-2">
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className="mt-1 break-words text-foreground">{value}</div>
    </div>
  );
}

function CommentKindPill({ comment }: { comment: PullRequestComment }) {
  const label = comment.kind === "status" && comment.status
    ? statusText(comment.status)
    : comment.kind === "ai_review"
      ? "AI analysis"
      : "Human analysis";

  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 font-medium",
        comment.kind === "ai_review" && "border-primary/25 bg-primary/10 text-primary",
        comment.kind === "human_review" && "border-glass-border/30 bg-muted text-muted-foreground",
        comment.kind === "status" && "border-warning/25 bg-warning/10 text-warning",
      )}
    >
      {label}
    </span>
  );
}

function PullRequestReviewView({
  pullRequest,
  totals,
  activeFileId,
  activeFile,
  openFiles,
  onBack,
  onSelectFile,
  onAddFile,
  onFocusFile,
  onCloseFile,
}: {
  pullRequest: PullRequestSummary;
  totals: { additions: number; deletions: number };
  activeFileId: string;
  activeFile?: PullRequestFile;
  openFiles: PullRequestFile[];
  onBack: () => void;
  onSelectFile: (fileId: string) => void;
  onAddFile: (fileId: string) => void;
  onFocusFile: (fileId: string) => void;
  onCloseFile: (fileId: string) => void;
}) {
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const fileId = event.dataTransfer.getData(DND_FILE_MIME) || event.dataTransfer.getData("text/plain");
    if (fileId) onAddFile(fileId);
  };

  return (
    <>
      <header className="flex h-auto shrink-0 items-start gap-4 border-b border-glass-border/25 bg-background/95 px-5 py-4 max-[760px]:flex-col">
        <div className="min-w-0 flex-1">
          <div className="break-words font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
            PR #{pullRequest.number} / {pullRequest.branch}
          </div>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-foreground">{pullRequest.title}</h1>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {pullRequest.files.length} files changed, {pullRequest.commentsCount} review comments, {pullRequest.risk.toLowerCase()} risk.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 max-[760px]:w-full max-[760px]:justify-start">
          <Button variant="subtle" className="rounded-xl" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
            Queue
          </Button>
          <Button variant="subtle" className="rounded-xl">
            <MessageSquarePlus className="h-4 w-4" />
            Draft comment
          </Button>
          <Button className="rounded-xl">
            <Check className="h-4 w-4" />
            Approve
          </Button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(260px,330px)_minmax(0,1fr)] gap-4 overflow-hidden p-5 max-[940px]:grid-cols-1 max-[940px]:overflow-auto">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-card/75 shadow-soft backdrop-blur-xl">
          <div className="shrink-0 border-b border-glass-border/25 px-4 py-3">
            <div className="text-sm font-semibold text-foreground">Files changed</div>
            <div className="mt-1 text-[11px] text-muted-foreground">{totals.additions} additions, {totals.deletions} deletions</div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {pullRequest.files.map((file) => (
              <FileRailButton
                key={file.id}
                file={file}
                active={file.id === activeFileId}
                onOpen={() => onSelectFile(file.id)}
              />
            ))}
          </div>
        </section>

        <section
          className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-card/75 shadow-soft backdrop-blur-xl"
          onDragOver={(event) => event.preventDefault()}
          onDrop={handleDrop}
          data-testid="pr-diff-dropzone"
        >
          <div className="flex shrink-0 items-start justify-between gap-3 border-b border-glass-border/25 px-4 py-3 max-[760px]:flex-col">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-foreground">{activeFile?.path ?? "Diff viewer"}</div>
              <div className="mt-1 text-[11px] text-muted-foreground">Drop files here to compare more than one diff.</div>
            </div>
            <div className="flex shrink-0 flex-wrap justify-end gap-2 max-[760px]:justify-start">
              <Button variant="subtle" size="xs" className="rounded-xl">
                <Bug className="h-3.5 w-3.5" />
                Find errors
              </Button>
              <Button variant="subtle" size="xs" className="rounded-xl">
                <Route className="h-3.5 w-3.5" />
                Trace function
              </Button>
              <Button variant="subtle" size="xs" className="rounded-xl">
                <ShieldAlert className="h-3.5 w-3.5" />
                Risk
              </Button>
            </div>
          </div>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
            {openFiles.map((file) => (
              <DiffCard
                key={file.id}
                file={file}
                active={file.id === activeFileId}
                canClose={openFiles.length > 1}
                onFocus={() => onFocusFile(file.id)}
                onClose={() => onCloseFile(file.id)}
              />
            ))}
          </div>
        </section>
      </div>

      <ReviewAgentWindow pullRequest={pullRequest} activeFile={activeFile} />
    </>
  );
}

function ReviewAgentWindow({
  pullRequest,
  activeFile,
}: {
  pullRequest: PullRequestSummary;
  activeFile?: PullRequestFile;
}) {
  const windowRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ dx: number; dy: number; width: number; height: number } | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const positionRef = useRef({
    x: Math.max(12, window.innerWidth - 420),
    y: Math.max(48, window.innerHeight - 330),
  });
  const messageNonceRef = useRef(1);
  const [expanded, setExpanded] = useState(false);
  const [input, setInput] = useState("");
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [dragging, setDragging] = useState(false);
  const [messages, setMessages] = useState<ReviewAgentMessage[]>([
    {
      id: "agent-initial",
      role: "agent",
      content: "Initial scan is ready. The highest-risk area is request context propagation across chat, workspace and git operations.",
    },
  ]);
  const [position, setPosition] = useState(() => ({
    x: Math.max(12, window.innerWidth - 420),
    y: Math.max(48, window.innerHeight - 330),
  }));

  useEffect(() => {
    positionRef.current = position;
  }, [position]);

  useEffect(() => {
    return () => {
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const clamp = () => {
      setViewportWidth(window.innerWidth);
      const rect = windowRef.current?.getBoundingClientRect();
      const width = rect?.width ?? 380;
      const height = rect?.height ?? 320;
      const nextPosition = {
        x: clampValue(positionRef.current.x, 8, Math.max(8, window.innerWidth - width - 8)),
        y: clampValue(positionRef.current.y, 44, Math.max(44, window.innerHeight - Math.min(height, window.innerHeight - 52))),
      };
      positionRef.current = nextPosition;
      setPosition(nextPosition);
    };
    clamp();
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
  }, [expanded]);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const rect = windowRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = { dx: event.clientX - rect.left, dy: event.clientY - rect.top, width: rect.width, height: rect.height };
    setDragging(true);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    positionRef.current = {
      x: clampValue(event.clientX - drag.dx, 8, Math.max(8, window.innerWidth - drag.width - 8)),
      y: clampValue(event.clientY - drag.dy, 44, Math.max(44, window.innerHeight - Math.min(drag.height, window.innerHeight - 52))),
    };
    if (animationFrameRef.current !== null) return;
    animationFrameRef.current = window.requestAnimationFrame(() => {
      animationFrameRef.current = null;
      setPosition(positionRef.current);
    });
  };

  const stopDrag = (event: PointerEvent<HTMLDivElement>) => {
    dragRef.current = null;
    setDragging(false);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  const submitPrompt = (event: FormEvent) => {
    event.preventDefault();
    const value = input.trim();
    if (!value) return;
    const nextId = messageNonceRef.current++;
    setMessages((current) => [
      ...current,
      { id: `user-${nextId}`, role: "user", content: value },
      {
        id: `agent-${nextId}`,
        role: "agent",
        content: `I will review ${shortPath(activeFile?.path ?? "the selected file")} in PR #${pullRequest.number}. Focus areas: contracts, regressions, missing tests and hidden context changes.`,
      },
    ]);
    setInput("");
  };

  const pickSuggestion = (value: string) => {
    setExpanded(true);
    setInput(value);
  };

  const narrowViewport = viewportWidth < 760;

  return (
    <aside
      ref={windowRef}
      role="dialog"
      aria-label="Review Agent"
      data-testid="review-agent-window"
      className={cn(
        "fixed left-0 top-0 z-50 flex max-h-[calc(100vh-56px)] flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-popover/98 shadow-floating will-change-transform",
        dragging ? "transition-none" : "transition-[width,border-color,box-shadow] duration-200",
        expanded ? "w-[min(390px,calc(100vw-24px))]" : "w-[min(300px,calc(100vw-24px))]",
      )}
      style={{ transform: `translate3d(${narrowViewport ? 12 : position.x}px, ${position.y}px, 0)` }}
    >
      <div
        className="flex items-center gap-2 border-b border-glass-border/25 bg-card/80 px-3 py-2"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={stopDrag}
        onPointerCancel={stopDrag}
      >
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-xl border border-primary/25 bg-primary/10 text-primary">
          <Bot className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-foreground">Review Agent</div>
          <div className="truncate text-[11px] text-muted-foreground">Watching {shortPath(activeFile?.path ?? "current PR")}</div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          aria-label={expanded ? "Compact Review Agent" : "Expand Review Agent"}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={() => setExpanded((current) => !current)}
        >
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform duration-150", expanded ? "rotate-180" : "")} />
        </Button>
      </div>

      {expanded ? (
        <>
          <div className="max-h-52 space-y-2 overflow-y-auto p-3">
            {messages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  "rounded-xl border px-3 py-2 text-xs leading-5",
                  message.role === "user"
                    ? "border-primary/25 bg-primary/10 text-foreground"
                    : "border-glass-border/25 bg-background/45 text-muted-foreground",
                )}
              >
                {message.content}
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 border-t border-glass-border/20 px-3 py-2">
            <AgentSuggestion onClick={() => pickSuggestion("Review only the selected file.")}>Selected file</AgentSuggestion>
            <AgentSuggestion onClick={() => pickSuggestion("Find regressions that could break existing tests.")}>Regressions</AgentSuggestion>
            <AgentSuggestion onClick={() => pickSuggestion("Search for the function usage across the repository.")}>Find usages</AgentSuggestion>
          </div>
          <form className="flex items-end gap-2 border-t border-glass-border/25 p-2.5" onSubmit={submitPrompt}>
            <textarea
              value={input}
              rows={1}
              onChange={(event) => setInput(event.currentTarget.value)}
              placeholder="Ask the PR agent..."
              className="min-h-10 min-w-0 flex-1 resize-none rounded-xl border border-glass-border/35 bg-background/55 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/70 focus:border-primary/35 focus:ring-1 focus:ring-primary/20"
            />
            <Button type="submit" size="icon" className="h-10 w-10 rounded-xl" aria-label="Send review agent message">
              <ArrowUp className="h-4 w-4" />
            </Button>
          </form>
        </>
      ) : null}
    </aside>
  );
}

function DetailCard({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
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

function MetricTile({
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

function RiskPill({ risk }: { risk: PullRequestSummary["risk"] }) {
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

function AgentSuggestion({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      className="rounded-full border border-glass-border/30 bg-background/40 px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-glass/80 hover:text-foreground"
      onClick={onClick}
    >
      {children}
    </button>
  );
}


