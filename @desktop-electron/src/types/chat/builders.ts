import type { ChatRequestPayload, ContextAttachment } from "./messages";
import type { ModelProvider, ReasoningPreset, PromptMode } from "./models";
import { reasoningTokenBudget } from "./models";
import type { TeamConfig } from "./teams";

export function buildChatRequest(input: {
  conversationId?: string;
  message: string;
  provider: ModelProvider;
  model: string;
  reasoningPreset: ReasoningPreset;
  workspaceRoot?: string | null;
  systemPrompt?: string;
  promptMode?: PromptMode;
  contextAttachments?: ContextAttachment[];
  planModeRequested?: boolean;
  permissionMode?: string;
}): ChatRequestPayload {
  const trimmedWorkspace = input.workspaceRoot?.trim();
  const reasoningPreset =
    input.provider === "codex" && input.reasoningPreset === "max"
      ? "xhigh"
      : input.reasoningPreset;
  const payload: ChatRequestPayload = {
    message: input.message.trim(),
    stream: true,
    temperature: 0.7,
    max_tokens: -1,
    provider: input.provider,
    model: input.model,
    prompt_mode: input.promptMode ?? "auto",
    reasoning_level: reasoningPreset,
    reasoning_budget_tokens:
      reasoningPreset === "max" ? null : reasoningTokenBudget(reasoningPreset),
  };

  if (input.conversationId) payload.conversation_id = input.conversationId;
  if (input.systemPrompt) payload.system_prompt = input.systemPrompt;
  if (input.contextAttachments?.length) payload.context_attachments = input.contextAttachments;
  if (input.planModeRequested) payload.plan_mode_requested = input.planModeRequested;
  if (trimmedWorkspace) {
    payload.workspace_root = trimmedWorkspace;
    payload.tool_context = {
      workspace_root: trimmedWorkspace,
      cwd: trimmedWorkspace,
      allowed_roots: [trimmedWorkspace],
    };
    if (input.permissionMode) {
      payload.tool_context.permission_mode = input.permissionMode;
    }
  }

  return payload;
}

export function buildTeamRunStart(input: {
  conversationId?: string;
  message: string;
  provider: ModelProvider;
  model: string;
  reasoningPreset: ReasoningPreset;
  workspaceRoot?: string | null;
  systemPrompt?: string;
  contextAttachments?: ContextAttachment[];
  planModeRequested?: boolean;
  teamId?: string;
  teamConfig?: TeamConfig;
}) {
  return {
    type: "team.run.start",
    ...buildChatRequest(input),
    team_id: input.teamId ?? "default-4",
    team_config: input.teamConfig,
  };
}
