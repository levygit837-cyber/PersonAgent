import { requestJson } from "./http";
import { createActionApproval } from "./chat-api";

export interface WorkspaceMentionSuggestion {
  type: "file" | "directory";
  name: string;
  path: string;
  display_path: string;
  is_directory: boolean;
  score: number;
}

export interface BrowserTabMentionSuggestion {
  type: "browser_tab";
  id: string;
  label: string;
  token: string;
  browser_id: string;
  tab_id: string;
  page_id: string;
  window_id?: string;
  url?: string;
  title?: string;
  runtime?: string;
  active?: boolean;
  is_active?: boolean;
  display_path: string;
  domain?: string;
  state?: Record<string, unknown>;
  updated_at?: string;
  score: number;
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

export async function createWorkspaceGrant(baseUrl: string, workspaceRoot: string) {
  return requestJson<{ workspace_id: string; root: string; source: string; created_at: string; last_used_at: string }>(baseUrl, "/workspace/grants", {
    method: "POST",
    body: JSON.stringify({ root: workspaceRoot, source: "desktop-electron" }),
  });
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

export function listWorkspaceMentions(
  baseUrl: string,
  query: string,
  workspaceRoot: string,
  limit = 40,
) {
  const params = new URLSearchParams({ q: query, workspace_root: workspaceRoot, limit: String(limit) });
  return requestJson<WorkspaceMentionSuggestion[]>(baseUrl, `/workspace/mentions?${params.toString()}`);
}

export function listBrowserTabMentions(
  baseUrl: string,
  conversationId: string,
  query: string,
  limit = 20,
) {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return requestJson<BrowserTabMentionSuggestion[]>(
    baseUrl,
    `/sessions/${encodeURIComponent(conversationId)}/browser/mentions?${params.toString()}`,
  );
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

export async function gitCommit(baseUrl: string, workspaceRoot: string, message: string, autoGenerateMessage = false) {
  const args = { workspace_root: workspaceRoot, message, auto_generate_message: autoGenerateMessage };
  const approval = await createActionApproval(baseUrl, "workspace.git_commit", args);
  return requestJson<{ success: boolean; output?: string; message?: string; sha?: string | null; short_sha?: string | null }>(baseUrl, "/workspace/git-commit", {
    method: "POST",
    body: JSON.stringify({
      ...args,
      approval_id: approval.approval_id,
      args_hash: approval.args_hash,
      approval_signature: approval.approval_signature,
      expires_at: approval.expires_at,
    }),
  });
}

export async function gitPush(baseUrl: string, workspaceRoot: string) {
  const args = { workspace_root: workspaceRoot };
  const approval = await createActionApproval(baseUrl, "workspace.git_push", args);
  return requestJson<{ success: boolean; output?: string; branch?: string; upstream?: string }>(baseUrl, "/workspace/git-push", {
    method: "POST",
    body: JSON.stringify({
      ...args,
      approval_id: approval.approval_id,
      args_hash: approval.args_hash,
      approval_signature: approval.approval_signature,
      expires_at: approval.expires_at,
    }),
  });
}

export async function gitOpenPr(baseUrl: string, workspaceRoot: string) {
  const args = { workspace_root: workspaceRoot };
  const approval = await createActionApproval(baseUrl, "workspace.git_pr", args);
  return requestJson<{ url: string | null; output?: string }>(baseUrl, "/workspace/git-pr", {
    method: "POST",
    body: JSON.stringify({
      ...args,
      approval_id: approval.approval_id,
      args_hash: approval.args_hash,
      approval_signature: approval.approval_signature,
      expires_at: approval.expires_at,
    }),
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
