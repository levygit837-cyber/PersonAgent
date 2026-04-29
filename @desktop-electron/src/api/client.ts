import { readSseStream } from "./sse";
import { PersonAgentApiError, extractApiErrorEnvelope } from "./errors";
import type {
  ChatRequestPayload,
  ChatCommandInfo,
  CodexAuthStatus,
  ConversationDetail,
  ConversationSummary,
  LlmModel,
  ModelProvider,
  PlanDecisionResponse,
  ProjectDetail,
  SessionPanelSnapshot,
  SkillDetail,
  SkillMarketplaceItem,
  SkillSummary,
  StreamChunk,
  TeamConfig,
  TeamRunEvent,
  buildTeamRunStart,
} from "../types/chat";

const fallbackBaseUrls = ["http://localhost:8000", "http://localhost:8001"];

export interface ConversationForkMessagePayload {
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  metadata?: Record<string, unknown>;
  tool_calls?: Array<Record<string, unknown>> | null;
  tool_call_id?: string | null;
}

export interface SessionBrowserViewport {
  width: number;
  height: number;
}

export interface SessionBrowserElement {
  node_id: string;
  tab_id?: string;
  frame_id?: string;
  frame_url?: string;
  role?: string;
  tag?: string;
  text?: string;
  selector?: string;
  selector_chain?: string[];
  shadow_path?: string[];
  stable_key?: string;
  interactable?: boolean;
  computed_summary?: Record<string, unknown>;
  href?: string;
  name?: string;
  input_type?: string;
  form_method?: string;
  form_action?: string;
  bounds?: { x: number; y: number; width: number; height: number };
  visible?: boolean;
}

export interface SessionBrowserAnnotation {
  id: string;
  browser_id: string;
  tab_id?: string;
  node_id: string;
  body: string;
  quote?: string;
  url?: string;
  title?: string;
  selector?: string;
  frame_id?: string;
  selector_chain?: string[];
  shadow_path?: string[];
  created_at: string;
  updated_at?: string;
}

export interface SessionBrowserTimelineEvent {
  id: string;
  browser_id: string;
  tab_id?: string;
  source: "user" | "agent" | "system";
  event_type: string;
  label: string;
  payload?: Record<string, unknown>;
  sequence?: number;
  automation_run_id?: string;
  created_at: string;
}

export interface SessionBrowserTab {
  tab_id: string;
  id?: string;
  url?: string;
  title?: string;
  runtime?: "lightpanda" | "chrome_cdp" | string;
  active?: boolean;
  is_active?: boolean;
  history?: string[];
  state?: Record<string, unknown>;
}

export interface SessionBrowserWorkspaceState {
  active_browser_id?: string;
  active_tab_id?: string;
  current_url?: string;
  current_title?: string;
  runtime?: "lightpanda" | "chrome_cdp" | string;
  last_element_map?: SessionBrowserElement[];
}

export interface SessionBrowserSnapshot {
  document_html: string;
  url: string;
  title: string;
  render_mode?: "screenshot" | "html_mirror" | "computed_html" | "pixel";
  runtime?: "lightpanda" | "chrome_cdp" | string;
  css_fidelity?: "pixel" | "original" | "embedded" | "computed" | "fallback_html" | string;
  fallback_reason?: string;
  tabs?: SessionBrowserTab[];
  active_tab_id?: string;
  frame_tree?: Array<Record<string, unknown>>;
  element_map?: SessionBrowserElement[];
  annotations?: SessionBrowserAnnotation[];
  timeline_events?: SessionBrowserTimelineEvent[];
}

export interface SessionBrowserView {
  type: "browser_view";
  browser_id: string;
  url: string;
  title: string;
  html?: string;
  document_html?: string;
  render_mode?: "screenshot" | "html_mirror" | "computed_html" | "pixel";
  runtime?: "lightpanda" | "chrome_cdp" | string;
  css_fidelity?: "pixel" | "original" | "embedded" | "computed" | "fallback_html" | string;
  fallback_reason?: string;
  tabs?: SessionBrowserTab[];
  active_tab_id?: string;
  frame_tree?: Array<Record<string, unknown>>;
  element_map?: SessionBrowserElement[];
  annotations?: SessionBrowserAnnotation[];
  timeline_events?: SessionBrowserTimelineEvent[];
  browser_snapshot?: SessionBrowserSnapshot;
  workspace_state?: SessionBrowserWorkspaceState;
  last_action?: Record<string, unknown>;
  user_agent?: string;
  image_data: string;
  image_mime_type: string;
  screenshot_method: string;
  screenshot_error?: string;
  viewport_width: number;
  viewport_height: number;
  can_capture: boolean;
}

export async function resolveBackendUrl(current?: string | null) {
  const candidates = Array.from(new Set([current, ...fallbackBaseUrls].filter(Boolean))) as string[];
  for (const candidate of candidates) {
    try {
      const response = await fetch(`${candidate}/health`, { signal: AbortSignal.timeout(3000) });
      if (response.ok) return candidate;
    } catch {
      continue;
    }
  }
  throw new Error("No PersonAgent backend answered on the configured ports.");
}

async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const method = init?.method?.toUpperCase() ?? "GET";
  const hasBody = init?.body !== undefined && init.body !== null;
  const shouldSendJsonContentType =
    hasBody && (typeof FormData === "undefined" || !(init?.body instanceof FormData));
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      ...(shouldSendJsonContentType && method !== "GET" && method !== "HEAD" ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      // Non-JSON error bodies keep status text.
    }
    throw new PersonAgentApiError(
      extractApiErrorEnvelope(body, response.status, response.statusText),
    );
  }
  return (await response.json()) as T;
}

export function listConversations(baseUrl: string) {
  return requestJson<ConversationSummary[]>(baseUrl, "/conversations");
}

export function getConversation(baseUrl: string, id: string) {
  return requestJson<ConversationDetail>(baseUrl, `/conversations/${id}`);
}

export function forkConversation(
  baseUrl: string,
  id: string,
  input: {
    title?: string | null;
    workspaceRoot?: string | null;
    messages: ConversationForkMessagePayload[];
  },
) {
  return requestJson<ConversationDetail>(baseUrl, `/conversations/${id}/fork`, {
    method: "POST",
    body: JSON.stringify({
      title: input.title,
      workspace_root: input.workspaceRoot,
      messages: input.messages,
    }),
  });
}

export function deleteConversation(baseUrl: string, id: string) {
  return requestJson<{ deleted: boolean }>(baseUrl, `/conversations/${id}`, { method: "DELETE" });
}

export function getSessionPanel(baseUrl: string, conversationId: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<SessionPanelSnapshot>(baseUrl, `/sessions/${conversationId}/panel${suffix}`);
}

export function listWorkspaceFiles(baseUrl: string, dirPath: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams({ path: dirPath });
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  return requestJson<Array<{ name: string; isDirectory: boolean; path: string }>>(baseUrl, `/workspace/files?${params.toString()}`);
}

export function readWorkspaceFile(baseUrl: string, filePath: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams({ path: filePath });
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  return requestJson<{ path: string; name: string; content: string }>(baseUrl, `/workspace/file?${params.toString()}`);
}

export interface WorkspaceMentionSuggestion {
  type: "file" | "directory";
  name: string;
  path: string;
  display_path: string;
  is_directory: boolean;
  score: number;
}

export function listWorkspaceMentions(
  baseUrl: string,
  query: string,
  workspaceRoot: string,
  limit = 40,
) {
  const params = new URLSearchParams({ q: query, workspace_root: workspaceRoot, limit: String(limit) });
  return requestJson<WorkspaceMentionSuggestion[]>(baseUrl, `/workspace/mentions?${params.toString()}`);
}

export function getSessionProjectDetail(
  baseUrl: string,
  conversationId: string,
  input: { type: string; id: string; workspaceRoot?: string | null },
) {
  const params = new URLSearchParams({ type: input.type, id: input.id });
  if (input.workspaceRoot?.trim()) params.set("workspace_root", input.workspaceRoot.trim());
  return requestJson<ProjectDetail>(baseUrl, `/sessions/${conversationId}/project/details?${params.toString()}`);
}

function sessionBrowserPath(browserId: string, suffix: string, conversationId?: string | null) {
  const encodedBrowserId = encodeURIComponent(browserId);
  if (conversationId?.trim()) {
    return `/sessions/${encodeURIComponent(conversationId.trim())}/browser/${encodedBrowserId}${suffix}`;
  }
  return `/sessions/browser/${encodedBrowserId}${suffix}`;
}

export function getSessionBrowserView(
  baseUrl: string,
  browserId: string,
  viewport: SessionBrowserViewport,
  conversationId?: string | null,
) {
  const params = new URLSearchParams({
    width: String(Math.round(viewport.width)),
    height: String(Math.round(viewport.height)),
  });
  return requestJson<SessionBrowserView>(
    baseUrl,
    `${sessionBrowserPath(browserId, "/view", conversationId)}?${params.toString()}`,
  );
}

export function navigateSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { url: string },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/navigate", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function moveSessionBrowserHistory(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { direction: -1 | 1 },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/history", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function reloadSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport,
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/reload", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function clickSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { x: number; y: number; button?: "left" | "middle" | "right" },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/click", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function keySessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { text?: string; key?: string },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/key", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function scrollSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { delta_x: number; delta_y: number },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/scroll", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function actSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & {
    node_id: string;
    action:
      | "click"
      | "fill"
      | "submit"
      | "select"
      | "press"
      | "hover"
      | "wait"
      | "drag"
      | "drop"
      | "upload"
      | "select_text"
      | "scroll_to"
      | "screenshot";
    value?: string;
    key?: string;
    target_node_id?: string;
    timeout_ms?: number;
    files?: string[];
    text?: string;
    x?: number;
    y?: number;
    source?: "user" | "agent" | "system";
  },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/action", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createSessionBrowserAnnotation(
  baseUrl: string,
  conversationId: string,
  browserId: string,
  input: {
    node_id: string;
    body: string;
    quote?: string;
    url?: string;
    title?: string;
    selector?: string;
    frame_id?: string;
    selector_chain?: string[];
    shadow_path?: string[];
    tab_id?: string;
  },
) {
  return requestJson<{ annotation: SessionBrowserAnnotation; annotations: SessionBrowserAnnotation[]; timeline_events: SessionBrowserTimelineEvent[] }>(
    baseUrl,
    sessionBrowserPath(browserId, "/annotations", conversationId),
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function deleteSessionBrowserAnnotation(
  baseUrl: string,
  conversationId: string,
  browserId: string,
  annotationId: string,
) {
  return requestJson<{ annotations: SessionBrowserAnnotation[]; timeline_events: SessionBrowserTimelineEvent[] }>(
    baseUrl,
    `${sessionBrowserPath(browserId, "/annotations", conversationId)}/${encodeURIComponent(annotationId)}`,
    { method: "DELETE" },
  );
}

export async function listModels(baseUrl: string, provider: ModelProvider, capability?: string) {
  const params = new URLSearchParams({ provider, refresh: "false" });
  if (capability) params.set("capability", capability);
  const response = await requestJson<{ data?: unknown[] } | LlmModel[]>(baseUrl, `/chat/models?${params.toString()}`);
  const data = Array.isArray(response) ? response : response.data ?? [];
  return data.map((item) => normalizeModel(item, provider));
}

export function getCodexAuthStatus(baseUrl: string) {
  return requestJson<CodexAuthStatus>(baseUrl, "/chat/auth/codex/status");
}

export function logoutCodex(baseUrl: string) {
  return requestJson<CodexAuthStatus>(baseUrl, "/chat/auth/codex/logout", { method: "POST" });
}

export async function listChatCommands(baseUrl: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<ChatCommandInfo[]>(baseUrl, `/chat/commands${suffix}`);
}

export function listSkills(baseUrl: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<SkillSummary[]>(baseUrl, `/skills${suffix}`);
}

export function getSkillDetail(baseUrl: string, invocationName: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<SkillDetail>(baseUrl, `/skills/${encodeURIComponent(invocationName)}${suffix}`);
}

export function setSkillActivation(
  baseUrl: string,
  invocationName: string,
  enabled: boolean,
  workspaceRoot?: string | null,
) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<{ invocation_name: string; enabled: boolean }>(
    baseUrl,
    `/skills/${encodeURIComponent(invocationName)}/activation${suffix}`,
    {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    },
  );
}

export function listMarketplaceSkills(baseUrl: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<SkillMarketplaceItem[]>(baseUrl, `/skills/marketplace${suffix}`);
}

export function installMarketplaceSkill(baseUrl: string, itemId: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<{ item: SkillMarketplaceItem; installed_path: string }>(
    baseUrl,
    `/skills/marketplace/${encodeURIComponent(itemId)}/install${suffix}`,
    { method: "POST" },
  );
}

export interface GitStatus {
  branch: string;
  ahead: number;
  behind: number;
  modified_count: number;
  untracked_count: number;
  is_dirty: boolean;
  remote_url?: string | null;
}

export interface GitBranchInfo {
  name: string;
  kind: "local" | "remote";
  current: boolean;
  upstream?: string | null;
  last_commit_iso?: string | null;
  last_commit_subject?: string | null;
  worktree_path?: string | null;
  checked_out_elsewhere?: boolean;
}

export interface GitBranchesResponse {
  is_repo: boolean;
  current: string;
  branches: GitBranchInfo[];
}

export interface GitWorktreeCreateResponse {
  success: boolean;
  branch: string;
  path: string;
  output?: string;
}

export interface GitRecentAction {
  id: string;
  type: "commit" | "push" | "pr" | "action" | string;
  title: string;
  subtitle?: string | null;
  timestamp?: string | null;
  url?: string | null;
}

export interface GitRecentActionsResponse {
  is_repo: boolean;
  actions: GitRecentAction[];
  errors: string[];
}

export interface WorkspaceProject {
  name: string;
  path: string;
  is_repo: boolean;
}

export type PullRequestStatus = "needs_review" | "approved" | "merged" | "refused";
export type PullRequestCommentKind = "human_review" | "ai_review" | "status";
export type PullRequestCommentSource = "human" | "ai" | "system";

export interface PullRequestComment {
  id: string;
  kind: PullRequestCommentKind;
  source: PullRequestCommentSource;
  author: string;
  body: string;
  createdAt?: string | null;
  url?: string | null;
  status?: PullRequestStatus | null;
}

export interface PullRequestFileChange {
  id: string;
  path: string;
  changeType: "modified" | "added" | "renamed" | "deleted";
  additions: number;
  deletions: number;
  summary: string;
  lines: Array<{ number: string; kind: "context" | "add" | "delete"; content: string }>;
}

export interface PullRequestSummary {
  id: string;
  project: string;
  projectPath: string;
  number: number;
  title: string;
  author: string;
  branch: string;
  baseBranch: string;
  updated: string;
  updatedAt?: string | null;
  url?: string | null;
  status: PullRequestStatus;
  statusLabel: string;
  risk: "Low" | "Medium" | "High";
  checkSummary: string;
  description: string;
  labels: string[];
  commentsCount: number;
  comments: PullRequestComment[];
  files: PullRequestFileChange[];
  isMine: boolean;
  isFlagged: boolean;
  reviewDecision?: string | null;
  mergeState?: string | null;
}

export interface GitPullRequestsResponse {
  is_repo: boolean;
  viewerLogin?: string | null;
  pullRequests: PullRequestSummary[];
  errors: string[];
}

export function getGitStatus(baseUrl: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<GitStatus>(baseUrl, `/workspace/git-status${suffix}`);
}

export function listGitBranches(baseUrl: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<GitBranchesResponse>(baseUrl, `/workspace/git-branches${suffix}`);
}

export function getGitRecentActions(baseUrl: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<GitRecentActionsResponse>(baseUrl, `/workspace/git-recent-actions${suffix}`);
}

export function listWorkspaceProjects(baseUrl: string) {
  return requestJson<{ projects: WorkspaceProject[] }>(baseUrl, "/workspace/projects");
}

export function listGitPullRequests(baseUrl: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<GitPullRequestsResponse>(baseUrl, `/workspace/git-pull-requests${suffix}`);
}

export function generateGitCommitMessage(baseUrl: string, workspaceRoot: string) {
  const params = new URLSearchParams({ workspace_root: workspaceRoot });
  return requestJson<{ message: string }>(baseUrl, `/workspace/git-commit-message?${params.toString()}`);
}

export function gitCreateBranch(baseUrl: string, workspaceRoot: string, name: string) {
  return requestJson<{ success: boolean; branch: string; output?: string }>(baseUrl, "/workspace/git-branches", {
    method: "POST",
    body: JSON.stringify({ workspace_root: workspaceRoot, name }),
  });
}

export function gitCreateWorktree(
  baseUrl: string,
  workspaceRoot: string,
  input: { name?: string; branch?: string; sourceMessageId?: string },
) {
  return requestJson<GitWorktreeCreateResponse>(baseUrl, "/workspace/git-worktrees", {
    method: "POST",
    body: JSON.stringify({
      workspace_root: workspaceRoot,
      name: input.name,
      branch: input.branch,
      source_message_id: input.sourceMessageId,
    }),
  });
}

export function gitCheckoutBranch(baseUrl: string, workspaceRoot: string, name: string, kind: "local" | "remote") {
  return requestJson<{ success: boolean; branch: string; output?: string }>(baseUrl, "/workspace/git-checkout", {
    method: "POST",
    body: JSON.stringify({ workspace_root: workspaceRoot, name, kind }),
  });
}

export function gitCommit(baseUrl: string, workspaceRoot: string, message: string, autoGenerateMessage = false) {
  return requestJson<{ success: boolean; output?: string; message?: string; sha?: string | null; short_sha?: string | null }>(baseUrl, "/workspace/git-commit", {
    method: "POST",
    body: JSON.stringify({ workspace_root: workspaceRoot, message, auto_generate_message: autoGenerateMessage }),
  });
}

export function gitPush(baseUrl: string, workspaceRoot: string) {
  return requestJson<{ success: boolean; output?: string; branch?: string; upstream?: string }>(baseUrl, "/workspace/git-push", {
    method: "POST",
    body: JSON.stringify({ workspace_root: workspaceRoot }),
  });
}

export function gitOpenPr(baseUrl: string, workspaceRoot: string) {
  return requestJson<{ url: string | null; output?: string }>(baseUrl, "/workspace/git-pr", {
    method: "POST",
    body: JSON.stringify({ workspace_root: workspaceRoot }),
  });
}

export function gitCreatePullRequestComment(
  baseUrl: string,
  input: {
    workspaceRoot: string;
    number: number;
    body: string;
    kind: PullRequestCommentKind;
    status?: PullRequestStatus | null;
  },
) {
  return requestJson<{ success: boolean; output?: string; url?: string | null }>(
    baseUrl,
    `/workspace/git-pull-requests/${input.number}/comments`,
    {
      method: "POST",
      body: JSON.stringify({
        workspace_root: input.workspaceRoot,
        body: input.body,
        kind: input.kind,
        status: input.status ?? null,
      }),
    },
  );
}

function normalizeModel(item: unknown, provider: ModelProvider): LlmModel {
  if (!item || typeof item !== "object") return { id: "local-model", name: "Local model", provider };
  const record = item as Record<string, unknown>;
  const id = String(record.id ?? record.name ?? "local-model");
  return {
    id,
    name: String(record.name ?? id),
    provider,
    context_length: typeof record.context_length === "number" ? record.context_length : undefined,
    capabilities: Array.isArray(record.capabilities) ? record.capabilities.map(String) : undefined,
    metadata: record,
  };
}

export async function* streamChatCompletion(baseUrl: string, payload: ChatRequestPayload, signal?: AbortSignal) {
  const response = await fetch(`${baseUrl}/chat/completions/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "Cache-Control": "no-cache",
    },
    body: JSON.stringify(payload),
    signal,
  });
  yield* readSseStream<StreamChunk>(response, signal);
}

export function approvePlan(
  baseUrl: string,
  input: { conversationId: string; approvalId: string; feedback?: string },
) {
  return requestJson<PlanDecisionResponse>(baseUrl, "/chat/plan/approve", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
      feedback: input.feedback,
    }),
  });
}

export function continuePlan(
  baseUrl: string,
  input: { conversationId: string; approvalId: string; feedback?: string },
) {
  return requestJson<PlanDecisionResponse>(baseUrl, "/chat/plan/continue", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
      feedback: input.feedback,
    }),
  });
}

export function cancelPlan(
  baseUrl: string,
  input: { conversationId: string; approvalId: string; feedback?: string },
) {
  return requestJson<PlanDecisionResponse>(baseUrl, "/chat/plan/cancel", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
      feedback: input.feedback,
    }),
  });
}

export function approveTool(baseUrl: string, input: { conversationId: string; approvalId: string }) {
  return requestJson<Record<string, unknown>>(baseUrl, "/chat/tools/approve", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
    }),
  });
}

export async function* streamApproveTool(baseUrl: string, input: { conversationId: string; approvalId: string }, signal?: AbortSignal) {
  const response = await fetch(`${baseUrl}/chat/tools/approve/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "Cache-Control": "no-cache",
    },
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
    }),
    signal,
  });
  yield* readSseStream<StreamChunk>(response, signal);
}

export function rejectTool(baseUrl: string, input: { conversationId: string; approvalId: string }) {
  return requestJson<Record<string, unknown>>(baseUrl, "/chat/tools/reject", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
    }),
  });
}

export async function listTeams(baseUrl: string) {
  const response = await requestJson<{ data?: TeamConfig[] }>(baseUrl, "/chat/teams");
  return response.data ?? [];
}

export async function* streamTeamChat(
  baseUrl: string,
  payload: ReturnType<typeof buildTeamRunStart>,
  signal?: AbortSignal,
) {
  const socket = new WebSocket(`${webSocketBaseUrl(baseUrl)}/chat/team/ws`);
  const queue: TeamRunEvent[] = [];
  let done = false;
  let wake: (() => void) | undefined;

  const notify = () => {
    wake?.();
    wake = undefined;
  };

  const push = (event: TeamRunEvent) => {
    queue.push(event);
    notify();
  };

  const stop = () => {
    try {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "team.run.stop" }));
      }
    } catch {
      // Ignore best-effort stop delivery errors.
    }
    socket.close();
  };

  socket.onopen = () => socket.send(JSON.stringify(payload));
  socket.onmessage = (message) => {
    try {
      push(JSON.parse(String(message.data)) as TeamRunEvent);
    } catch (error) {
      push({ event: "error", error: error instanceof Error ? error.message : String(error) });
    }
  };
  socket.onerror = () => push({ event: "error", error: "Team Mode WebSocket failed." });
  socket.onclose = () => {
    done = true;
    notify();
  };
  signal?.addEventListener("abort", stop, { once: true });

  try {
    while (!done || queue.length > 0) {
      if (queue.length > 0) {
        const event = queue.shift();
        if (event) yield event;
        continue;
      }
      await new Promise<void>((resolve) => {
        wake = resolve;
      });
    }
  } finally {
    signal?.removeEventListener("abort", stop);
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      stop();
    }
  }
}

function webSocketBaseUrl(baseUrl: string) {
  const url = new URL(baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString().replace(/\/$/, "");
}
