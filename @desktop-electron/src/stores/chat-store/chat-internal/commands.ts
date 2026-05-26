import type { ChatMessageUi, ModelProvider, ReasoningPreset, SessionUsage } from "../../../types/chat";
import { useAppStore } from "../../app-store";
import type { ChatSet, ChatState } from "../internal";
import { getEffectiveWorkspaceRoot } from "../internal";

export const localSlashCommands = new Set([
  "clear",
  "model",
  "effort",
  "skills",
  "permissions",
  "usage",
  "status",
  "help",
]);

export const modelProviders: ModelProvider[] = ["llama", "nvidia", "deepseek", "zenmux", "vertex", "kimi", "codex"];
export const reasoningPresetValues: ReasoningPreset[] = ["low", "medium", "high", "xhigh", "max"];

export function handleLocalSlashCommand(
  message: string,
  set: ChatSet,
  get: () => ChatState,
) {
  const parsed = parseLocalSlashCommand(message);
  if (!parsed || !localSlashCommands.has(parsed.name)) return false;

  if (parsed.name === "clear") {
    get().startNewConversation();
    return true;
  }

  const app = useAppStore.getState();
  let response = "";
  if (parsed.name === "help") {
    response = commandHelpText();
  } else if (parsed.name === "skills") {
    app.setSection("skills");
    response = "Opened the Skills workspace. Use `/skill-name` in chat to invoke an enabled user skill.";
  } else if (parsed.name === "model") {
    response = applyModelCommand(parsed.args, app);
  } else if (parsed.name === "effort") {
    response = applyEffortCommand(parsed.args, app);
  } else if (parsed.name === "permissions") {
    response = permissionsCommandText();
  } else if (parsed.name === "usage") {
    response = usageCommandText(get().liveSessionUsage);
  } else if (parsed.name === "status") {
    response = statusCommandText(get(), app);
  }

  appendLocalCommandResult(set, response || `Command /${parsed.name} completed.`);
  return true;
}

export function parseLocalSlashCommand(message: string) {
  const trimmed = message.trim();
  if (!trimmed.startsWith("/") || trimmed === "/") return null;
  const [head, ...rest] = trimmed.slice(1).split(/\s+/);
  if (!head) return null;
  return { name: head.toLowerCase(), args: rest };
}

export function appendLocalCommandResult(set: ChatSet, content: string) {
  const now = Date.now();
  const agentId = `${now}_command_result`;
  const agentMessage: ChatMessageUi = {
    id: agentId,
    role: "agent",
    label: "PersonAgent",
    content,
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [{ kind: "content", id: `content-${agentId}`, content }],
    isStreaming: false,
    isReasoningStreaming: false,
    metadata: {
      local_command_result: true,
    },
  };
  set((state) => ({
    messages: [...state.messages, agentMessage],
    error: undefined,
    pendingPlanApproval: undefined,
    pendingToolApproval: undefined,
  }));
}

export function applyModelCommand(args: string[], app: ReturnType<typeof useAppStore.getState>) {
  if (args.length === 0) {
    return [
      `Current model: ${app.provider}/${app.selectedModelId}`,
      "Usage: `/model <model-id>`, `/model <provider> <model-id>`, or `/model <provider>:<model-id>`.",
    ].join("\n");
  }

  const raw = args.join(" ").trim();
  const colonMatch = raw.match(/^([a-z]+):(.+)$/i);
  let provider: ModelProvider | undefined;
  let modelId = raw;
  if (colonMatch) {
    const candidate = normalizeProvider(colonMatch[1]);
    if (candidate) {
      provider = candidate;
      modelId = colonMatch[2].trim();
    }
  } else {
    const first = normalizeProvider(args[0]);
    if (first) {
      provider = first;
      modelId = args.slice(1).join(" ").trim();
    }
  }

  if (!modelId) {
    if (!provider) return "No model or provider was provided.";
    app.setProvider(provider);
    return `Provider changed to ${provider}. Current model: ${useAppStore.getState().selectedModelId}`;
  }

  const nextProvider = provider ?? inferProviderForModel(modelId) ?? app.provider;
  app.setProvider(nextProvider);
  useAppStore.getState().setSelectedModelId(modelId);
  return `Model changed to ${nextProvider}/${modelId}.`;
}

export function applyEffortCommand(args: string[], app: ReturnType<typeof useAppStore.getState>) {
  const requested = (args[0] || "").toLowerCase();
  if (!requested) {
    return `Current reasoning effort: ${app.reasoningPreset}\nUsage: /effort low|medium|high|xhigh|max`;
  }
  if (!reasoningPresetValues.includes(requested as ReasoningPreset)) {
    return `Unknown reasoning effort: ${requested}. Use low, medium, high, xhigh, or max.`;
  }
  app.setReasoningPreset(requested as ReasoningPreset);
  return `Reasoning effort changed to ${requested}.`;
}

export function normalizeProvider(value?: string): ModelProvider | undefined {
  const normalized = (value || "").toLowerCase();
  return modelProviders.find((provider) => provider === normalized);
}

export function inferProviderForModel(modelId: string): ModelProvider | undefined {
  const normalized = modelId.toLowerCase();
  if (normalized === "local-model") return "llama";
  if (normalized.startsWith("deepseek/deepseek-v4-")) return "zenmux";
  if (normalized.startsWith("deepseek-v4-")) return "deepseek";
  if (normalized.startsWith("gpt-") || normalized.startsWith("o")) return "codex";
  if (normalized.includes("gemini")) return "vertex";
  if (normalized.includes("kimi")) return "kimi";
  if (normalized.includes("nvidia") || normalized.includes("nemotron")) return "nvidia";
  return undefined;
}

export function commandHelpText() {
  return [
    "Local commands:",
    "/clear - clear the current chat UI state.",
    "/model [provider:]<model-id> - show or change the selected model.",
    "/effort <low|medium|high|xhigh|max> - show or change reasoning effort.",
    "/skills - open the Skills workspace.",
    "/permissions - show the current tool permission behavior.",
    "/usage - show live session usage counters.",
    "/status - show local chat/workspace/model status.",
    "",
    "Model-visible commands:",
    "/plan, /memory, /mcp, /context, /compact, /diff, /files, /branch, /doctor, Markdown commands, and enabled skills are sent to the model with hidden command context.",
  ].join("\n");
}

export function permissionsCommandText() {
  return [
    "Tool permissions are enforced by the runtime.",
    "Read-only tools can run directly when allowed. Risky tools pause on a permission_required event and resume only after approval.",
    "Command frontmatter can still narrow allowed tools for that turn.",
  ].join("\n");
}

export function usageCommandText(usage: SessionUsage) {
  return [
    "Live session usage:",
    `Context tokens: ${usageLabel(usage.context_tokens)}`,
    `Agent output tokens: ${usageLabel(usage.agent_output_tokens)}`,
    `Thinking tokens: ${usageLabel(usage.thinking_output_tokens)}`,
    `Tool calls: ${usageLabel(usage.tool_calls)}`,
    `Skills used: ${usageLabel(usage.skills_used_count)}`,
    `MCP calls: ${usageLabel(usage.mcp_calls_count)}`,
    `Plans created: ${usageLabel(usage.plans_created)}`,
    `Todos created: ${usageLabel(usage.todos_created)}`,
    `Subagents used: ${usageLabel(usage.subagents_used)}`,
  ].join("\n");
}

export function statusCommandText(state: ChatState, app: ReturnType<typeof useAppStore.getState>) {
  return [
    "Local status:",
    `Workspace: ${getEffectiveWorkspaceRoot(state) || "(none)"}`,
    `Model: ${app.provider}/${app.selectedModelId}`,
    `Reasoning effort: ${app.reasoningPreset}`,
    `Conversation: ${state.conversationId || "(new)"}`,
    `Team Mode: ${app.teamMode ? "on" : "off"}`,
    `Messages loaded: ${state.messages.length}`,
    `Composer attachments: ${state.composerAnnotations.length}`,
  ].join("\n");
}

export function usageLabel(metric: SessionUsage[keyof SessionUsage]) {
  return `${metric.value}${metric.estimated ? " estimated" : ""}`;
}

// ---------------------------------------------------------------------------
// Generation / streaming helpers
// ---------------------------------------------------------------------------

