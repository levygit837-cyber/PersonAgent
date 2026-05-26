import { requestJson } from "../http";
import type { ConversationDetail, ConversationSummary, ProjectDetail, SessionPanelSnapshot } from "../../../types/chat";
import type { ConversationForkMessagePayload } from "./types";

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

export function getSessionProjectDetail(
  baseUrl: string,
  conversationId: string,
  input: { type: string; id: string; workspaceRoot?: string | null },
) {
  const params = new URLSearchParams({ type: input.type, id: input.id });
  if (input.workspaceRoot?.trim()) params.set("workspace_root", input.workspaceRoot.trim());
  return requestJson<ProjectDetail>(baseUrl, `/sessions/${conversationId}/project/details?${params.toString()}`);
}
