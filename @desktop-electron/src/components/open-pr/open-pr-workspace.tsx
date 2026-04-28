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
  Bot,
  Bug,
  Check,
  ChevronDown,
  FileCode2,
  Files,
  FolderOpen,
  GitBranch,
  MessageSquarePlus,
  RotateCw,
  Route,
  ScanSearch,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { cn, workspaceName } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { Button } from "../ui/button";

type PullRequestStatus = "ready" | "flagged" | "blocked";
type DiffLineKind = "context" | "add" | "delete";
type ReviewMode = "queue" | "review";

export interface DiffLine {
  number: string;
  kind: DiffLineKind;
  content: string;
}

export interface PullRequestFile {
  id: string;
  path: string;
  changeType: "modified" | "added" | "renamed";
  additions: number;
  deletions: number;
  summary: string;
  aiNote: string;
  lines: DiffLine[];
}

export interface PullRequestSummary {
  id: string;
  project: string;
  projectPath: string;
  number: number;
  title: string;
  author: string;
  branch: string;
  updated: string;
  status: PullRequestStatus;
  statusLabel: string;
  risk: "Low" | "Medium" | "High";
  tests: string;
  description: string;
  brief: string;
  focus: string;
  labels: string[];
  comments: number;
  files: PullRequestFile[];
}

interface ReviewAgentMessage {
  id: string;
  role: "agent" | "user";
  content: string;
}

const DND_FILE_MIME = "application/personagent-pr-file";

const mockPullRequests: PullRequestSummary[] = [
  {
    id: "pr-84",
    project: "PersonAgent",
    projectPath: "/home/levybonito/Projetos/PersonAgent",
    number: 84,
    title: "Add context attachments to chat completion",
    author: "LB",
    branch: "feature/context-attachments",
    updated: "18m ago",
    status: "flagged",
    statusLabel: "Needs review",
    risk: "Medium",
    tests: "8 passing",
    description:
      "Carries selected file, terminal snippet and workspace metadata into the backend prompt builder without changing visible chat content.",
    brief:
      "The implementation is coherent, but request DTOs and prompt-surface tests need close review because attachment content can silently alter the model context.",
    focus:
      "Inspect DTO serialization, backend prompt assembly and whether visible message content remains separated from hidden context attachments.",
    labels: ["backend", "prompt", "frontend"],
    comments: 3,
    files: [
      {
        id: "chat-dto",
        path: "@backend/src/personagent/application/dto/chat_dto.py",
        changeType: "modified",
        additions: 42,
        deletions: 8,
        summary: "Attachment schema enters the request boundary.",
        aiNote: "Validate that hidden attachments never get echoed as user-visible assistant content.",
        lines: [
          { number: "44", kind: "context", content: "class ChatCompletionRequest(BaseModel):" },
          { number: "45", kind: "context", content: "    messages: list[ChatMessageDto]" },
          {
            number: "46",
            kind: "add",
            content: "    context_attachments: list[ContextAttachmentDto] = Field(default_factory=list)",
          },
          {
            number: "47",
            kind: "add",
            content: "    display_attachments: list[DisplayAttachmentDto] = Field(default_factory=list)",
          },
          { number: "48", kind: "context", content: "    model: str | None = None" },
          { number: "49", kind: "context", content: "    provider: str | None = None" },
          { number: "50", kind: "add", content: "    def attachment_count(self) -> int:" },
          { number: "51", kind: "add", content: "        return len(self.context_attachments)" },
        ],
      },
      {
        id: "chat-completion",
        path: "@backend/src/personagent/application/use_cases/chat_completion.py",
        changeType: "modified",
        additions: 64,
        deletions: 22,
        summary: "Prompt builder receives extra contextual surfaces.",
        aiNote: "Check token accounting and prompt-surface tracking for every attachment path.",
        lines: [
          { number: "118", kind: "context", content: "prompt_context = await self._build_prompt_context(request)" },
          { number: "119", kind: "delete", content: "messages = self.prompt_builder.build(messages=request.messages)" },
          { number: "120", kind: "add", content: "messages = self.prompt_builder.build(" },
          { number: "121", kind: "add", content: "    messages=request.messages," },
          { number: "122", kind: "add", content: "    context_attachments=request.context_attachments," },
          { number: "123", kind: "add", content: ")" },
          { number: "124", kind: "context", content: "return await self.llm_backend.chat_completion(messages)" },
        ],
      },
      {
        id: "input-dock",
        path: "@desktop-electron/src/components/chat/input-dock.tsx",
        changeType: "modified",
        additions: 71,
        deletions: 18,
        summary: "Composer chips attach file and terminal context.",
        aiNote: "Confirm the composer still clears state after failed and successful sends.",
        lines: [
          { number: "198", kind: "context", content: "const canSend = Boolean(text.trim()) || composerAnnotations.length > 0;" },
          { number: "199", kind: "add", content: "const requestAttachments = buildContextAttachments(composerAnnotations);" },
          { number: "200", kind: "add", content: "const displayAttachments = buildDisplayAttachments(composerAnnotations);" },
          { number: "201", kind: "context", content: "void sendMessage(visibleMessage, undefined, {" },
          { number: "202", kind: "add", content: "  contextAttachments: requestAttachments," },
          { number: "203", kind: "add", content: "  displayAttachments," },
          { number: "204", kind: "context", content: "});" },
        ],
      },
    ],
  },
  {
    id: "pr-79",
    project: "PersonAgent",
    projectPath: "/home/levybonito/Projetos/PersonAgent",
    number: 79,
    title: "Stabilize Git action menu feedback",
    author: "MA",
    branch: "fix/git-feedback",
    updated: "41m ago",
    status: "ready",
    statusLabel: "CI passing",
    risk: "Low",
    tests: "12 passing",
    description:
      "Keeps commit, push and open PR feedback visible inside the git menu while operations refresh repository status.",
    brief:
      "Low-risk UI patch. The main check is whether the popover preserves operation feedback while git status refreshes.",
    focus: "Review disabled states, pending transitions and error display for partial commit-and-push failures.",
    labels: ["git", "ui"],
    comments: 0,
    files: [
      {
        id: "git-action-button",
        path: "@desktop-electron/src/components/git/git-action-button.tsx",
        changeType: "modified",
        additions: 92,
        deletions: 28,
        summary: "Operation feedback persists inside dropdown.",
        aiNote: "Make sure successful PR output is not hidden when the dropdown closes.",
        lines: [
          { number: "76", kind: "add", content: "const [menuFeedback, setMenuFeedback] = useState<OperationFeedback | null>(null);" },
          { number: "77", kind: "context", content: "const pushMutation = useGitPush();" },
          { number: "78", kind: "add", content: "const prMutation = useGitOpenPr();" },
          { number: "80", kind: "add", content: "const handleOpenPr = async () => {" },
          { number: "81", kind: "add", content: "  const result = await prMutation.mutateAsync();" },
          { number: "82", kind: "add", content: "  setMenuFeedback({ kind: 'success', title: 'Pull request ready', detail: result.url });" },
          { number: "83", kind: "add", content: "};" },
        ],
      },
      {
        id: "git-store",
        path: "@desktop-electron/src/stores/git-store.ts",
        changeType: "modified",
        additions: 34,
        deletions: 6,
        summary: "Adds open PR mutation wiring.",
        aiNote: "Invalidate status only after the mutation settles to reduce flicker.",
        lines: [
          { number: "158", kind: "add", content: "export function useGitOpenPr() {" },
          { number: "159", kind: "add", content: "  const queryClient = useQueryClient();" },
          { number: "160", kind: "add", content: "  return useMutation({ mutationFn: openPullRequest });" },
          { number: "161", kind: "add", content: "}" },
        ],
      },
    ],
  },
  {
    id: "pr-72",
    project: "PersonAgent",
    projectPath: "/home/levybonito/Projetos/PersonAgent",
    number: 72,
    title: "Backfill unique conversation titles",
    author: "CA",
    branch: "feature/title-backfill",
    updated: "1h ago",
    status: "blocked",
    statusLabel: "AI flagged",
    risk: "High",
    tests: "5 passing",
    description:
      "Adds batch title generation using full transcript summaries and collision repair for duplicated session names.",
    brief:
      "The batch flow is useful, but title uniqueness must be deterministic when several sessions summarize to the same phrase.",
    focus: "Check database transaction boundaries, collision repair order and title backfill retry behavior.",
    labels: ["sessions", "backend", "migration"],
    comments: 7,
    files: [
      {
        id: "conversation-model",
        path: "@backend/src/personagent/domain/models/conversation.py",
        changeType: "modified",
        additions: 31,
        deletions: 9,
        summary: "Conversation title metadata expanded.",
        aiNote: "Check if nullable fields stay backward compatible for old rows.",
        lines: [
          { number: "22", kind: "context", content: "class ConversationSummary(BaseModel):" },
          { number: "23", kind: "context", content: "    id: str" },
          { number: "24", kind: "add", content: "    generated_title: str | None = None" },
          { number: "25", kind: "add", content: "    title_confidence: float | None = None" },
          { number: "26", kind: "context", content: "    workspace_root: str | None = None" },
        ],
      },
    ],
  },
  {
    id: "pr-118",
    project: "WebPilot",
    projectPath: "/home/levybonito/Projetos/WebPilot",
    number: 118,
    title: "Review browser execution flow split",
    author: "WP",
    branch: "feature/browser-execution-flow",
    updated: "24m ago",
    status: "ready",
    statusLabel: "Ready",
    risk: "Medium",
    tests: "7 passing",
    description:
      "Separates browser session orchestration from file upload/download actions so review traces can show each execution boundary.",
    brief:
      "The split is visually clear, but the execution state names need a pass because similar browser events can now appear in multiple panels.",
    focus: "Review naming, file-action grouping and whether the browser trace remains readable after long runs.",
    labels: ["browser", "workspace", "review"],
    comments: 2,
    files: [
      {
        id: "webpilot-chat",
        path: "webpilot/runtime/chat.py",
        changeType: "modified",
        additions: 58,
        deletions: 17,
        summary: "Chat execution now emits separate browser and file events.",
        aiNote: "Check that long browser traces still preserve chronological order.",
        lines: [
          { number: "88", kind: "context", content: "async def run_chat_turn(request: ChatRequest) -> ChatResult:" },
          { number: "89", kind: "add", content: "    browser_events = await browser_executor.collect_events(request.session_id)" },
          { number: "90", kind: "add", content: "    file_events = await file_executor.collect_events(request.session_id)" },
          { number: "91", kind: "context", content: "    return ChatResult(events=[*browser_events, *file_events])" },
        ],
      },
      {
        id: "webpilot-engine",
        path: "webpilot/runtime/execution_engine.py",
        changeType: "modified",
        additions: 43,
        deletions: 12,
        summary: "Execution engine exposes smaller reviewable phases.",
        aiNote: "Verify that state transitions cannot skip cleanup after failed browser commands.",
        lines: [
          { number: "151", kind: "delete", content: "await self._run_all_steps(context)" },
          { number: "152", kind: "add", content: "await self._run_browser_steps(context)" },
          { number: "153", kind: "add", content: "await self._run_file_steps(context)" },
          { number: "154", kind: "add", content: "await self._finalize_review_trace(context)" },
        ],
      },
    ],
  },
  {
    id: "pr-31",
    project: "WebPilot",
    projectPath: "/home/levybonito/Projetos/WebPilot",
    number: 31,
    title: "Fix upload artifact previews",
    author: "WP",
    branch: "fix/upload-preview",
    updated: "2h ago",
    status: "flagged",
    statusLabel: "Needs review",
    risk: "Low",
    tests: "4 passing",
    description: "Normalizes uploaded artifact names before rendering them in the review surface.",
    brief: "Small UI/data cleanup. The main thing to verify is that names stay stable after refresh.",
    focus: "Check filename normalization, duplicate artifact handling and empty upload states.",
    labels: ["files", "ui"],
    comments: 1,
    files: [
      {
        id: "webpilot-upload",
        path: "webpilot/files/upload_file.py",
        changeType: "modified",
        additions: 22,
        deletions: 8,
        summary: "Upload previews normalize display names.",
        aiNote: "Look for collisions when two artifacts share the same basename.",
        lines: [
          { number: "40", kind: "context", content: "def display_name(path: str) -> str:" },
          { number: "41", kind: "delete", content: "    return path.split('/')[-1]" },
          { number: "42", kind: "add", content: "    return normalize_artifact_name(path)" },
        ],
      },
    ],
  },
  {
    id: "pr-46",
    project: "MindFlow",
    projectPath: "/home/levybonito/Projetos/MindFlow",
    number: 46,
    title: "Unify workflow route decisions",
    author: "MF",
    branch: "feature/workflow-route-decisions",
    updated: "3h ago",
    status: "ready",
    statusLabel: "CI passing",
    risk: "High",
    tests: "10 passing",
    description: "Moves route decisions into one runtime contract before tool invocation.",
    brief: "High-impact runtime change. Review the contract boundaries before approving.",
    focus: "Check route decision serialization, hook ordering and plugin compatibility.",
    labels: ["runtime", "workflow", "tools"],
    comments: 5,
    files: [
      {
        id: "mindflow-route",
        path: "mindflow/runtime/routes.py",
        changeType: "modified",
        additions: 87,
        deletions: 29,
        summary: "Route decisions now share one typed object.",
        aiNote: "Confirm old plugin payloads are still accepted by compatibility shims.",
        lines: [
          { number: "67", kind: "add", content: "class WorkflowRouteDecision(BaseModel):" },
          { number: "68", kind: "add", content: "    agent_id: str" },
          { number: "69", kind: "add", content: "    tool_policy: ToolPolicy" },
          { number: "70", kind: "context", content: "    metadata: dict[str, Any] = Field(default_factory=dict)" },
        ],
      },
    ],
  },
];

export function OpenPrWorkspace() {
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const workspaceProject = selectedWorkspace ? workspaceName(selectedWorkspace) : undefined;
  const projects = useMemo(() => uniqueProjects(mockPullRequests), []);
  const initialProject = projects.some((project) => project.name === workspaceProject) ? workspaceProject : projects[0]?.name;
  const [mode, setMode] = useState<ReviewMode>("queue");
  const [selectedProject, setSelectedProject] = useState(initialProject ?? "");
  const [selectedBranch, setSelectedBranch] = useState("all");
  const filteredPullRequests = useMemo(
    () =>
      mockPullRequests.filter((pullRequest) => {
        if (pullRequest.project !== selectedProject) return false;
        return selectedBranch === "all" || pullRequest.branch === selectedBranch;
      }),
    [selectedBranch, selectedProject],
  );
  const branchOptions = useMemo(() => uniqueBranches(mockPullRequests, selectedProject), [selectedProject]);
  const [selectedPrId, setSelectedPrId] = useState(filteredPullRequests[0]?.id ?? "");
  const selectedPr = useMemo(
    () => filteredPullRequests.find((pullRequest) => pullRequest.id === selectedPrId) ?? filteredPullRequests[0] ?? mockPullRequests[0],
    [filteredPullRequests, selectedPrId],
  );
  const firstFileId = selectedPr.files[0]?.id ?? "";
  const [openFileIds, setOpenFileIds] = useState<string[]>(() => (firstFileId ? [firstFileId] : []));
  const [activeFileId, setActiveFileId] = useState(firstFileId);

  useEffect(() => {
    if (branchOptions.length > 0 && selectedBranch !== "all" && !branchOptions.includes(selectedBranch)) {
      setSelectedBranch("all");
    }
  }, [branchOptions, selectedBranch]);

  useEffect(() => {
    if (!filteredPullRequests.some((pullRequest) => pullRequest.id === selectedPrId)) {
      setSelectedPrId(filteredPullRequests[0]?.id ?? "");
      setMode("queue");
    }
  }, [filteredPullRequests, selectedPrId]);

  useEffect(() => {
    const nextFirstFileId = selectedPr.files[0]?.id ?? "";
    setOpenFileIds(nextFirstFileId ? [nextFirstFileId] : []);
    setActiveFileId(nextFirstFileId);
  }, [selectedPr.id, selectedPr.files]);

  const replaceVisibleFile = (fileId: string) => {
    if (!selectedPr.files.some((file) => file.id === fileId)) return;
    setOpenFileIds([fileId]);
    setActiveFileId(fileId);
  };

  const addVisibleFile = (fileId: string) => {
    if (!selectedPr.files.some((file) => file.id === fileId)) return;
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
    setMode("review");
    if (!openFileIds.length && firstFileId) {
      setOpenFileIds([firstFileId]);
      setActiveFileId(firstFileId);
    }
  };

  const openFiles = selectedPr.files.filter((file) => openFileIds.includes(file.id));
  const activeFile = selectedPr.files.find((file) => file.id === activeFileId) ?? openFiles[0] ?? selectedPr.files[0];
  const totals = prTotals(selectedPr);

  return (
    <section className="relative flex h-full min-w-0 flex-col overflow-hidden bg-background" data-testid="open-pr-workspace">
      {mode === "queue" ? (
        <PullRequestQueueView
          pullRequests={filteredPullRequests}
          projects={projects}
          branchOptions={branchOptions}
          selectedPr={selectedPr}
          selectedProject={selectedProject}
          selectedBranch={selectedBranch}
          selectedWorkspace={selectedWorkspace}
          onSelectProject={(project) => {
            setSelectedProject(project);
            setSelectedBranch("all");
          }}
          onSelectBranch={setSelectedBranch}
          onSelectPr={(pullRequest) => setSelectedPrId(pullRequest.id)}
          onStartReview={startReview}
        />
      ) : (
        <PullRequestReviewView
          pullRequest={selectedPr}
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
  projects,
  branchOptions,
  selectedPr,
  selectedProject,
  selectedBranch,
  selectedWorkspace,
  onSelectProject,
  onSelectBranch,
  onSelectPr,
  onStartReview,
}: {
  pullRequests: PullRequestSummary[];
  projects: Array<{ name: string; path: string }>;
  branchOptions: string[];
  selectedPr: PullRequestSummary;
  selectedProject: string;
  selectedBranch: string;
  selectedWorkspace?: string;
  onSelectProject: (project: string) => void;
  onSelectBranch: (branch: string) => void;
  onSelectPr: (pullRequest: PullRequestSummary) => void;
  onStartReview: () => void;
}) {
  const totals = prTotals(selectedPr);
  const workspaceLabel = selectedWorkspace ? workspaceName(selectedWorkspace) : "Workspace";

  return (
    <>
      <header className="flex h-auto shrink-0 items-start gap-4 border-b border-glass-border/25 bg-background/95 px-5 py-4 max-[760px]:flex-col">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">Repository Review</div>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-foreground">Open Pull Requests</h1>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {workspaceLabel} review queue with AI briefings, changed-file signals and merge readiness.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 max-[760px]:w-full max-[760px]:justify-start">
          <FilterSelect
            label="Project"
            icon={<FolderOpen className="h-3.5 w-3.5" />}
            value={selectedProject}
            onChange={onSelectProject}
            options={projects.map((project) => ({ value: project.name, label: project.name }))}
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
            <button className="bg-primary/10 px-3 py-2 text-foreground" type="button">All</button>
            <button className="border-l border-glass-border/25 px-3 py-2 hover:bg-glass/80 hover:text-foreground" type="button">Mine</button>
            <button className="border-l border-glass-border/25 px-3 py-2 hover:bg-glass/80 hover:text-foreground" type="button">Flagged</button>
          </div>
          <Button variant="subtle" size="iconSm" aria-label="Refresh pull requests" className="rounded-xl">
            <RotateCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(320px,420px)_minmax(0,1fr)] gap-4 overflow-hidden p-5 max-[1040px]:grid-cols-1 max-[1040px]:overflow-auto">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-card/75 shadow-soft backdrop-blur-xl">
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-glass-border/25 px-4 py-3">
            <div>
              <div className="text-sm font-semibold text-foreground">Queue</div>
              <div className="text-[11px] text-muted-foreground">Ordered by review risk and recency</div>
            </div>
            <span className="rounded-full border border-warning/30 bg-warning/10 px-2 py-1 text-[10px] font-semibold text-warning">
              2 flagged
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {pullRequests.length > 0 ? pullRequests.map((pullRequest) => (
              <PullRequestCard
                key={pullRequest.id}
                pullRequest={pullRequest}
                active={pullRequest.id === selectedPr.id}
                onClick={() => onSelectPr(pullRequest)}
              />
            )) : (
              <div className="rounded-xl border border-glass-border/30 bg-background/35 p-3 text-xs leading-5 text-muted-foreground">
                No pull requests for this project and branch.
              </div>
            )}
          </div>
        </section>

        <section
          key={selectedPr.id}
          className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-card/75 shadow-soft backdrop-blur-xl transition-[opacity,transform] duration-200 ease-out"
        >
          <div className="shrink-0 border-b border-glass-border/25 p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
                  PR #{selectedPr.number} / {selectedPr.branch}
                </div>
                <h2 className="mt-2 text-xl font-semibold leading-7 text-foreground">{selectedPr.title}</h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{selectedPr.description}</p>
              </div>
              <Button className="shrink-0 rounded-xl" onClick={onStartReview}>
                <ScanSearch className="h-4 w-4" />
                Start Review
              </Button>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <StatusPill status={selectedPr.status}>{selectedPr.statusLabel}</StatusPill>
              <RiskPill risk={selectedPr.risk} />
              <span className="rounded-full border border-glass-border/35 bg-background/45 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
                {selectedPr.tests}
              </span>
              {selectedPr.labels.map((label) => (
                <span key={label} className="rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
                  {label}
                </span>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-4 gap-2 max-[760px]:grid-cols-2">
              <MetricTile label="Files" value={selectedPr.files.length} />
              <MetricTile label="Comments" value={selectedPr.comments} />
              <MetricTile label="Additions" value={`+${totals.additions}`} tone="success" />
              <MetricTile label="Deletions" value={`-${totals.deletions}`} tone="destructive" />
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-5" data-testid="pr-preview-scroll">
            <BriefCard icon={<Sparkles className="h-4 w-4" />} title="AI brief">
              {selectedPr.brief}
            </BriefCard>
            <BriefCard icon={<Files className="h-4 w-4" />} title="Changed files">
              <div className="mt-3 flex flex-wrap gap-2">
                {selectedPr.files.map((file) => (
                  <span key={file.id} className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground">
                    <FileCode2 className="h-3.5 w-3.5" />
                    {shortPath(file.path)}
                  </span>
                ))}
              </div>
            </BriefCard>
            <BriefCard icon={<ShieldAlert className="h-4 w-4" />} title="Review focus">
              {selectedPr.focus}
            </BriefCard>
          </div>
        </section>
      </div>
    </>
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
            {pullRequest.files.length} files changed, {pullRequest.comments} review comments, {pullRequest.risk.toLowerCase()} risk.
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

function PullRequestCard({
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

function FileRailButton({
  file,
  active,
  onOpen,
}: {
  file: PullRequestFile;
  active: boolean;
  onOpen: () => void;
}) {
  const onDragStart = (event: DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(DND_FILE_MIME, file.id);
    event.dataTransfer.setData("text/plain", file.id);
  };

  return (
    <button
      type="button"
      draggable
      onDragStart={onDragStart}
      onClick={onOpen}
      aria-label={`Open diff for ${file.path}`}
      className={cn(
        "mb-1.5 w-full rounded-xl border p-3 text-left transition-[background,border-color,box-shadow,transform] duration-150",
        active
          ? "border-primary/30 bg-accent/70 text-foreground shadow-soft"
          : "border-transparent text-muted-foreground hover:border-glass-border/30 hover:bg-glass/70 hover:text-foreground",
      )}
    >
      <div className="flex min-w-0 items-start gap-2">
        <FileCode2 className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="break-words text-xs font-semibold leading-5 text-foreground">{file.path}</div>
          <div className="mt-1 flex flex-wrap gap-2 text-[11px]">
            <span>{file.changeType}</span>
            <span className="font-mono text-success">+{file.additions}</span>
            <span className="font-mono text-destructive">-{file.deletions}</span>
          </div>
          <p className="mt-2 text-[11px] leading-4 text-muted-foreground">{file.summary}</p>
        </div>
      </div>
    </button>
  );
}

function DiffCard({
  file,
  active,
  canClose,
  onFocus,
  onClose,
}: {
  file: PullRequestFile;
  active: boolean;
  canClose: boolean;
  onFocus: () => void;
  onClose: () => void;
}) {
  return (
    <article
      className={cn(
        "overflow-hidden rounded-2xl border bg-background/45 transition-[border-color,box-shadow] duration-150",
        active ? "border-primary/30 shadow-soft" : "border-glass-border/30",
      )}
      data-testid={`open-diff-card-${file.id}`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-glass-border/25 px-3 py-2">
        <button type="button" className="min-w-0 text-left" onClick={onFocus}>
          <div className="truncate text-xs font-semibold text-foreground">{file.path}</div>
          <div className="mt-0.5 text-[10px] text-muted-foreground">
            {file.changeType} / +{file.additions} -{file.deletions}
          </div>
        </button>
        <Button variant="ghost" size="iconSm" aria-label={`Close diff for ${file.path}`} disabled={!canClose} onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full table-fixed border-collapse font-mono text-[12px] leading-6">
          <tbody>
            {file.lines.map((line, index) => (
              <tr key={`${file.id}-${line.number}-${index}`} className="border-b border-glass-border/10 last:border-b-0">
                <td className="w-14 select-none px-3 py-0.5 text-right text-muted-foreground/60">{line.number}</td>
                <td className={cn("whitespace-pre-wrap break-words px-3 py-0.5 text-foreground/85", diffLineClass(line.kind))}>
                  {linePrefix(line.kind)} {line.content}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="m-3 rounded-xl border border-warning/25 bg-warning/10 px-3 py-2 text-xs leading-5 text-muted-foreground">
        <span className="font-semibold text-warning">AI note:</span> {file.aiNote}
      </div>
    </article>
  );
}

function FilterSelect({
  label,
  icon,
  value,
  options,
  onChange,
}: {
  label: string;
  icon: ReactNode;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-glass-border/35 bg-card/70 px-2.5 text-xs text-muted-foreground shadow-soft">
      <span className="text-primary">{icon}</span>
      <span className="sr-only">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        className="max-w-[220px] bg-transparent text-foreground outline-none"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} className="bg-popover text-popover-foreground">
            {option.label}
          </option>
        ))}
      </select>
    </label>
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

function BriefCard({
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

function StatusPill({
  status,
  children,
}: {
  status: PullRequestStatus;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-1 text-[10px] font-semibold",
        status === "ready" && "border-success/30 bg-success/10 text-success",
        status === "flagged" && "border-warning/30 bg-warning/10 text-warning",
        status === "blocked" && "border-destructive/30 bg-destructive/10 text-destructive",
      )}
    >
      {children}
    </span>
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

function prTotals(pullRequest: PullRequestSummary) {
  return pullRequest.files.reduce(
    (totals, file) => ({
      additions: totals.additions + file.additions,
      deletions: totals.deletions + file.deletions,
    }),
    { additions: 0, deletions: 0 },
  );
}

function uniqueProjects(pullRequests: PullRequestSummary[]) {
  const projects = new Map<string, string>();
  for (const pullRequest of pullRequests) {
    if (!projects.has(pullRequest.project)) {
      projects.set(pullRequest.project, pullRequest.projectPath);
    }
  }
  return Array.from(projects, ([name, path]) => ({ name, path }));
}

function uniqueBranches(pullRequests: PullRequestSummary[], project: string) {
  const branches = new Set<string>();
  for (const pullRequest of pullRequests) {
    if (pullRequest.project === project) {
      branches.add(pullRequest.branch);
    }
  }
  return Array.from(branches).sort();
}

function shortPath(path: string) {
  const pieces = path.split("/");
  return pieces.slice(Math.max(0, pieces.length - 2)).join("/");
}

function diffLineClass(kind: DiffLineKind) {
  if (kind === "add") return "bg-success/10 text-success";
  if (kind === "delete") return "bg-destructive/10 text-destructive line-through decoration-destructive/50";
  return "";
}

function linePrefix(kind: DiffLineKind) {
  if (kind === "add") return "+";
  if (kind === "delete") return "-";
  return " ";
}

function clampValue(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
