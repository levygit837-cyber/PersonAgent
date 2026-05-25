import { requestJson } from "./client/http";
export { resolveBackendUrl, fetchBackendText } from "./client/http";
import { createActionApproval } from "./client/chat-api";
export type { ActionApprovalPayload } from "./client/chat-api";
export {
  createActionApproval,
  listModels,
  getCodexAuthStatus,
  logoutCodex,
  listChatCommands,
  streamChatCompletion,
  approvePlan,
  continuePlan,
  cancelPlan,
  approveTool,
  streamApproveTool,
  rejectTool,
  listTeams,
  streamTeamChat,
} from "./client/chat-api";
export {
  createWorkspaceGrant,
  listWorkspaceFiles,
  readWorkspaceFile,
  listWorkspaceMentions,
  listBrowserTabMentions,
  getGitStatus,
  listGitBranches,
  getGitRecentActions,
  listWorkspaceProjects,
  listGitPullRequests,
  generateGitCommitMessage,
  gitCreateBranch,
  gitCreateWorktree,
  gitCheckoutBranch,
  gitCommit,
  gitPush,
  gitOpenPr,
  gitCreatePullRequestComment,
} from "./client/workspace-api";
export type {
  WorkspaceMentionSuggestion,
  BrowserTabMentionSuggestion,
  GitStatus,
  GitBranchInfo,
  GitBranchesResponse,
  GitWorktreeCreateResponse,
  GitRecentAction,
  GitRecentActionsResponse,
  WorkspaceProject,
  PullRequestStatus,
  PullRequestCommentKind,
  PullRequestCommentSource,
  PullRequestComment,
  PullRequestFileChange,
  PullRequestSummary,
  GitPullRequestsResponse,
} from "./client/workspace-api";
export {
  listConversations,
  getConversation,
  forkConversation,
  deleteConversation,
  getSessionPanel,
  getSessionProjectDetail,
  getSessionBrowserView,
  navigateSessionBrowser,
  moveSessionBrowserHistory,
  reloadSessionBrowser,
  clickSessionBrowser,
  keySessionBrowser,
  scrollSessionBrowser,
  actSessionBrowser,
  setSessionBrowserCooperation,
  ingestSessionBrowserEvents,
  connectSessionBrowserCooperation,
  createSessionBrowserAnnotation,
  deleteSessionBrowserAnnotation,
} from "./client/session-api";
export type {
  ConversationForkMessagePayload,
  SessionBrowserViewport,
  SessionBrowserElement,
  SessionBrowserAnnotation,
  SessionBrowserTimelineEvent,
  SessionBrowserTab,
  SessionBrowserWorkspaceState,
  SessionBrowserCooperationMode,
  SessionBrowserCooperationState,
  SessionBrowserCooperationEvent,
  SessionBrowserCooperationWsEvent,
  SessionBrowserSnapshot,
  SessionBrowserView,
} from "./client/session-api";
import type {
  SkillDetail,
  SkillMarketplaceItem,
  SkillSummary,
} from "../types/chat";

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
