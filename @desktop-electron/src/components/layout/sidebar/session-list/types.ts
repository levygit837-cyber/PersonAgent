import type { ConversationSummary } from "../../../../types/chat";

export const MAX_VISIBLE_CONVERSATIONS = 4;

export function getConversationTimestamp(conversation: ConversationSummary) {
  for (const value of [conversation.updated_at, conversation.created_at]) {
    const timestamp = Date.parse(value);
    if (Number.isFinite(timestamp)) return timestamp;
  }
  return 0;
}

export function compareConversationsByRecency(
  left: ConversationSummary,
  right: ConversationSummary,
) {
  return getConversationTimestamp(right) - getConversationTimestamp(left);
}

export interface WorkspaceGroup {
  workspace: string;
  name: string;
  conversations: ConversationSummary[];
}

export function getWorkspaceGroupTimestamp(group: WorkspaceGroup) {
  return group.conversations.reduce(
    (latest, conversation) => Math.max(latest, getConversationTimestamp(conversation)),
    0,
  );
}

export function compareWorkspaceGroupsByRecency(left: WorkspaceGroup, right: WorkspaceGroup) {
  return getWorkspaceGroupTimestamp(right) - getWorkspaceGroupTimestamp(left);
}

export function workspaceForConversation(
  conversation: ConversationSummary,
  convWorkspaceMap: Record<string, string>,
  selectedWorkspace?: string,
) {
  const mapped = convWorkspaceMap[conversation.id]?.trim();
  if (mapped) return mapped;
  const fromBackend = conversation.workspace_root?.trim();
  if (fromBackend) return fromBackend;
  return selectedWorkspace?.trim();
}
