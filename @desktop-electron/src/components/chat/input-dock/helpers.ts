import type {
  BrowserTabMentionSuggestion,
  WorkspaceMentionSuggestion,
} from "../../../api/client";
import type { ComposerAnnotation } from "../../../stores/chat-store";
import type { TerminalSnippet } from "../../../stores/terminal-store";
import {
  localModel,
  type ChatCommandInfo,
  type ContextAttachment,
  type LlmModel,
  type ModelProvider,
  type SkillSummary,
  type TodoDockSnapshotUi,
} from "../../../types/chat";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ModelOption = {
  id: string;
  provider: ModelProvider;
  label: string;
  group: string;
  contextLength?: number;
};

export type ComposerMentionKind = "file" | "directory" | "skill" | "browser_tab";

export type ComposerMention = {
  id: string;
  type: ComposerMentionKind;
  label: string;
  token: string;
  displayPath: string;
  fileName?: string;
  filePath?: string;
  directoryPath?: string;
  name?: string;
  invocationName?: string;
  slashName?: string;
  description?: string;
  path?: string;
  source?: string;
  browserId?: string;
  tabId?: string;
  pageId?: string;
  windowId?: string;
  url?: string;
  title?: string;
  runtime?: string;
  active?: boolean;
  state?: Record<string, unknown>;
  updatedAt?: string;
};

export type MentionTrigger = {
  start: number;
  end: number;
  query: string;
};

export type MentionSuggestion = {
  id: string;
  type: ComposerMentionKind;
  primary: string;
  secondary: string;
  token: string;
  mention: ComposerMention;
  score: number;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const DEEPSEEK_API_GROUP = "DeepSeek API";
export const DEEPSEEK_NVIDIA_GROUP = "DeepSeek NVIDIA";
export const ZENMUX_GROUP = "ZenMux";
export const MODEL_CATALOG_STALE_MS = 10 * 60_000;
export const PLAN_MODE_SYSTEM_PROMPT = [
  "The user enabled Plan Mode from the composer UI for this turn.",
  "Enter PlanMode before doing workspace-changing work.",
  "Research and inspect what is needed, then write a concrete plan and request approval instead of making changes.",
].join("\n");
export const CODEX_AUTH_STALE_MS = 2 * 60_000;
export const TODO_DOCK_EXIT_MS = 280;
export const BROWSER_MENTION_RE = /(^|\s)(@Browser(?::([^\s"]+))?)/gi;

export const ICONIFY_BASE = "https://api.iconify.design/simple-icons";

export const GROUP_ICON_SLUG: Record<string, string> = {
  Local: "ollama",
  "Kimi Code": "moonshotai",
  "ChatGPT Subscription": "openai",
  OpenAI: "openai",
  Qwen: "qwen",
  Minimax: "minimax",
  Moonshot: "moonshotai",
  "Zhipu AI": "zhipu",
  ByteDance: "bytedance",
  [DEEPSEEK_API_GROUP]: "deepseek",
  [ZENMUX_GROUP]: "deepseek",
  [DEEPSEEK_NVIDIA_GROUP]: "nvidia",
  "Google Vertex": "google",
  NVIDIA: "nvidia",
  Mistral: "mistralai",
  Meta: "meta",
  Google: "google",
  Microsoft: "microsoft",
  IBM: "ibm",
};

export const curatedHostedModels: ModelOption[] = [
  { id: "kimi-for-coding", provider: "kimi", label: "Kimi K2.6", group: "Kimi Code", contextLength: 262144 },
  { id: "gpt-5.5", provider: "codex", label: "GPT-5.5", group: "ChatGPT Subscription", contextLength: 272000 },
  { id: "gpt-5.4-mini", provider: "codex", label: "GPT-5.4-Mini", group: "ChatGPT Subscription", contextLength: 272000 },
  { id: "qwen/qwen3.5-397b-a17b", provider: "nvidia", label: "Qwen3.5-397B", group: "Qwen" },
  { id: "qwen/qwen3-coder-480b-a35b-instruct", provider: "nvidia", label: "Qwen3 Coder 480B", group: "Qwen" },
  { id: "minimaxai/minimax-m2.5", provider: "nvidia", label: "Minimax M2.5", group: "Minimax" },
  { id: "moonshotai/kimi-k2.6", provider: "nvidia", label: "Kimi K2.6", group: "Moonshot" },
  { id: "z-ai/glm-5.1", provider: "nvidia", label: "GLM 5.1", group: "Zhipu AI" },
  { id: "meta/llama-4-maverick-17b-128e-instruct", provider: "nvidia", label: "Llama 4 Maverick", group: "Meta" },
  { id: "bytedance/seed-oss-36b-instruct", provider: "nvidia", label: "Seed OSS 36B", group: "ByteDance" },
  { id: "mistralai/mistral-small-4-119b-2603", provider: "nvidia", label: "Mistral Small 4 119B", group: "Mistral" },
  { id: "deepseek-v4-flash", provider: "deepseek", label: "DeepSeek V4 Flash", group: DEEPSEEK_API_GROUP },
  { id: "deepseek-v4-pro", provider: "deepseek", label: "DeepSeek V4 Pro", group: DEEPSEEK_API_GROUP },
  { id: "deepseek/deepseek-v4-flash-free", provider: "zenmux", label: "DeepSeek V4 Flash Free", group: ZENMUX_GROUP, contextLength: 1000000 },
  { id: "deepseek/deepseek-v4-pro-free", provider: "zenmux", label: "DeepSeek V4 Pro Free", group: ZENMUX_GROUP, contextLength: 1000000 },
  { id: "deepseek-ai/deepseek-v4-flash", provider: "nvidia", label: "DeepSeek V4 Flash", group: DEEPSEEK_NVIDIA_GROUP },
  { id: "deepseek-ai/deepseek-v4-pro", provider: "nvidia", label: "DeepSeek V4 Pro", group: DEEPSEEK_NVIDIA_GROUP },
  { id: "mistralai/mistral-medium-3.5-128b", provider: "nvidia", label: "Mistral Medium 3.5 128B", group: "Mistral" },
  { id: "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", provider: "nvidia", label: "Nemotron 3 Nano Omni 30B", group: "NVIDIA" },
  { id: "gemini-3.1-pro-preview", provider: "vertex", label: "Gemini 3.1 Pro", group: "Google Vertex" },
  { id: "gemini-3.1-pro-preview-customtools", provider: "vertex", label: "Gemini 3.1 Pro Custom Tools", group: "Google Vertex" },
  { id: "gemini-3.1-flash-lite-preview", provider: "vertex", label: "Gemini 3.1 Flash-Lite", group: "Google Vertex" },
  { id: "gemini-3.1-flash-image-preview", provider: "vertex", label: "Gemini 3.1 Flash Image", group: "Google Vertex" },
  { id: "gemini-3-flash-preview", provider: "vertex", label: "Gemini 3 Flash", group: "Google Vertex" },
  { id: "gemini-3-pro-image-preview", provider: "vertex", label: "Gemini 3 Pro Image", group: "Google Vertex" },
];

export const modelGroupOrder = [
  "Local",
  "Kimi Code",
  "ChatGPT Subscription",
  "OpenAI",
  "Qwen",
  "Minimax",
  "Moonshot",
  "Zhipu AI",
  "ByteDance",
  DEEPSEEK_API_GROUP,
  ZENMUX_GROUP,
  DEEPSEEK_NVIDIA_GROUP,
  "Google Vertex",
  "NVIDIA",
  "Mistral",
  "Meta",
  "Google",
  "Microsoft",
  "IBM",
  "Writer",
  "Other",
];

// ---------------------------------------------------------------------------
// Pure helper functions
// ---------------------------------------------------------------------------

export function providerIconUrl(group: string): string | null {
  const slug = GROUP_ICON_SLUG[group];
  if (!slug) return null;
  return `${ICONIFY_BASE}/${slug}.svg?color=white`;
}

export function formatModelLabel(value: string) {
  const normalized = value.trim();
  if (!normalized || normalized === "local-model" || normalized.toLowerCase() === "local model") return "Local";
  const exact: Record<string, string> = {
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4-mini": "GPT-5.4-Mini",
    "kimi-for-coding": "Kimi K2.6",
    "qwen/qwen3.5-397b-a17b": "Qwen3.5-397B",
    "qwen/qwen3-coder-480b-a35b-instruct": "Qwen3 Coder 480B",
    "minimaxai/minimax-m2.5": "Minimax M2.5",
    "moonshotai/kimi-k2.6": "Kimi K2.6",
    "z-ai/glm-5.1": "GLM 5.1",
    "z-ai/glm5": "GLM5",
    "meta/llama-4-maverick-17b-128e-instruct": "Llama 4 Maverick",
    "bytedance/seed-oss-36b-instruct": "Seed OSS 36B",
    "mistralai/mistral-small-4-119b-2603": "Mistral Small 4 119B",
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "deepseek/deepseek-v4-flash-free": "DeepSeek V4 Flash Free",
    "deepseek/deepseek-v4-pro-free": "DeepSeek V4 Pro Free",
    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro",
    "deepseek-ai/deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-ai/deepseek-v4-pro": "DeepSeek V4 Pro",
    "nvidia/nemotron-3-nano-30b-a3b": "Nemotron 3 Nano 30B",
    "mistralai/mistral-medium-3.5-128b": "Mistral Medium 3.5 128B",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": "Nemotron 3 Nano Omni 30B",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
    "gemini-3.1-pro-preview-customtools": "Gemini 3.1 Pro Custom Tools",
    "gemini-3.1-flash-lite-preview": "Gemini 3.1 Flash-Lite",
    "gemini-3.1-flash-image-preview": "Gemini 3.1 Flash Image",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "gemini-3-pro-image-preview": "Gemini 3 Pro Image",
  };
  if (exact[normalized]) return exact[normalized];

  const leaf = normalized.includes("/") ? normalized.split("/").at(-1) || normalized : normalized;
  const brandNames: Record<string, string> = {
    ai: "AI",
    deepseek: "DeepSeek",
    gpt: "GPT",
    gemini: "Gemini",
    kimi: "Kimi",
    llama: "Llama",
    minimax: "Minimax",
    mistral: "Mistral",
    nemotron: "Nemotron",
    oss: "OSS",
    qwen: "Qwen",
  };
  return leaf
    .replace(/[-_]+/g, " ")
    .replace(/\b(gpt|oss|qwen|kimi|mistral|llama|nemotron|deepseek|minimax|gemini|ai)\b/gi, (part) => brandNames[part.toLowerCase()])
    .replace(/\b(qwen|gpt|kimi|llama)(?=\d)/gi, (part) => brandNames[part.toLowerCase()])
    .replace(/\b([0-9]+)b\b/gi, "$1B")
    .replace(/\b([0-9]+)k\b/gi, "$1K")
    .replace(/\s+/g, " ")
    .trim();
}

export function modelGroup(id: string, provider: ModelProvider) {
  const normalized = id.toLowerCase();
  if (provider === "llama") return "Local";
  if (provider === "kimi") return "Kimi Code";
  if (provider === "codex") return "ChatGPT Subscription";
  if (provider === "vertex") return "Google Vertex";
  if (provider === "zenmux") return ZENMUX_GROUP;
  if (provider === "deepseek") return DEEPSEEK_API_GROUP;
  if (normalized.startsWith("openai/") || normalized.startsWith("gpt-")) return "OpenAI";
  if (normalized.startsWith("qwen/")) return "Qwen";
  if (normalized.startsWith("minimax") || normalized.startsWith("minimaxai/")) return "Minimax";
  if (normalized.startsWith("moonshotai/")) return "Moonshot";
  if (normalized.startsWith("deepseek-ai/")) return DEEPSEEK_NVIDIA_GROUP;
  if (normalized.startsWith("nvidia/")) return "NVIDIA";
  if (normalized.startsWith("mistralai/") || normalized.startsWith("nv-mistralai/")) return "Mistral";
  if (normalized.startsWith("meta/")) return "Meta";
  if (normalized.startsWith("google/")) return "Google";
  if (normalized.startsWith("microsoft/")) return "Microsoft";
  if (normalized.startsWith("ibm/")) return "IBM";
  if (normalized.startsWith("writer/")) return "Writer";
  if (normalized.includes("/")) return formatVendorLabel(normalized.split("/", 1)[0]);
  return "Other";
}

export function groupRank(group: string) {
  const index = modelGroupOrder.indexOf(group);
  return index === -1 ? modelGroupOrder.length : index;
}

export function toModelOption(model: LlmModel, fallbackProvider: ModelProvider): ModelOption {
  const provider = model.provider || fallbackProvider;
  const id = model.id || localModel.id;
  return {
    id,
    provider,
    label: formatModelLabel(model.name || id),
    group: modelGroup(id, provider),
    contextLength: model.context_length,
  };
}

export function buildModelOptions(
  localModels?: LlmModel[],
  hostedModels?: LlmModel[],
  deepSeekModels?: LlmModel[],
  zenMuxModels?: LlmModel[],
  vertexModels?: LlmModel[],
  kimiModels?: LlmModel[],
  codexModels?: LlmModel[],
) {
  const byKey = new Map<string, ModelOption>();
  const add = (option: ModelOption) => {
    byKey.set(`${option.provider}:${option.id}`, option);
  };

  if (localModels && localModels.length > 0) {
    for (const model of localModels) {
      add(toModelOption(model, "llama"));
    }
  }
  for (const model of curatedHostedModels) {
    add(model);
  }
  for (const model of hostedModels ?? []) {
    add(toModelOption(model, "nvidia"));
  }
  for (const model of deepSeekModels ?? []) {
    add(toModelOption(model, "deepseek"));
  }
  for (const model of zenMuxModels ?? []) {
    add(toModelOption(model, "zenmux"));
  }
  for (const model of vertexModels ?? []) {
    add(toModelOption(model, "vertex"));
  }
  for (const model of kimiModels ?? []) {
    add(toModelOption(model, "kimi"));
  }
  for (const model of codexModels ?? []) {
    add(toModelOption(model, "codex"));
  }

  return [...byKey.values()];
}

export function groupModelOptions(options: ModelOption[]) {
  const groups = new Map<string, ModelOption[]>();
  for (const option of options) {
    const group = groups.get(option.group) ?? [];
    group.push(option);
    groups.set(option.group, group);
  }

  return [...groups.entries()]
    .sort(([left], [right]) => groupRank(left) - groupRank(right) || left.localeCompare(right))
    .map(([name, items]) => ({ name, items: items.sort((left, right) => left.label.localeCompare(right.label)) }));
}

export function formatVendorLabel(value: string) {
  const exact: Record<string, string> = {
    "01-ai": "01.AI",
    ai21labs: "AI21 Labs",
    baai: "BAAI",
    bigcode: "BigCode",
    bytedance: "ByteDance",
    sarvamai: "SarvamAI",
    "stepfun-ai": "StepFun",
    "z-ai": "Z.ai",
  };
  if (exact[value]) return exact[value];

  return value
    .replace(/[-_]+/g, " ")
    .replace(/\b(ai|ibm|baai)\b/gi, (part) => part.toUpperCase())
    .replace(/\b\w/g, (part) => part.toUpperCase())
    .trim();
}

export function slashTokenFromText(value: string) {
  const trimmed = value.trimStart();
  if (!trimmed.startsWith("/") || trimmed.includes("\n")) return null;
  const token = trimmed.split(/\s+/, 1)[0];
  return token;
}

export function parseComposerSlashInvocation(value: string) {
  const trimmed = value.trim();
  if (!trimmed.startsWith("/") || trimmed === "/") return null;
  const head = trimmed.slice(1).split(/\s+/, 1)[0];
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:/-]*$/.test(head)) return null;
  return { name: head.toLowerCase() };
}

export function filterSlashCommands(commands: ChatCommandInfo[], slashToken: string | null) {
  if (slashToken === null) return [];
  const normalized = slashToken.toLowerCase();
  return commands
    .filter((command) => command.user_invocable && command.slash_name.toLowerCase().startsWith(normalized))
    .sort((left, right) => left.slash_name.localeCompare(right.slash_name));
}

export function mentionTriggerFromText(value: string, cursor: number): MentionTrigger | null {
  const beforeCursor = value.slice(0, cursor);
  const quoted = beforeCursor.match(/(^|\s)@"([^"]*)$/);
  if (quoted && quoted.index !== undefined) {
    return {
      start: quoted.index + (quoted[1]?.length ?? 0),
      end: cursor,
      query: quoted[2] ?? "",
    };
  }
  const regular = beforeCursor.match(/(^|\s)@([^\s"]*)$/);
  if (!regular || regular.index === undefined) return null;
  return {
    start: regular.index + (regular[1]?.length ?? 0),
    end: cursor,
    query: regular[2] ?? "",
  };
}

export function buildMentionSuggestions(
  workspaceSuggestions: WorkspaceMentionSuggestion[],
  skills: SkillSummary[],
  browserTabs: BrowserTabMentionSuggestion[],
  query: string,
  conversationId?: string,
): MentionSuggestion[] {
  const normalizedQuery = query.trim().toLowerCase();
  const skillQuery = normalizedQuery.startsWith("skill:")
    ? normalizedQuery.slice("skill:".length)
    : normalizedQuery;
  const browserQuery = browserMentionQueryFromText(query);
  const includeBrowser = browserQuery !== null;
  const includeWorkspace = !normalizedQuery.startsWith("skill:") && !includeBrowser;
  const includeSkills = !includeBrowser && (
    normalizedQuery.startsWith("skill:")
    || normalizedQuery === ""
    || "skill".startsWith(normalizedQuery)
    || skills.some((skill) => skill.invocation_name.toLowerCase().includes(normalizedQuery))
  );

  const fileItems = includeWorkspace
    ? workspaceSuggestions.map((item) => mentionSuggestionFromWorkspace(item))
    : [];
  const skillItems = includeSkills
    ? skills
      .filter((skill) => skill.enabled)
      .filter((skill) => {
        if (!skillQuery) return true;
        const haystack = `${skill.invocation_name} ${skill.name} ${skill.description}`.toLowerCase();
        return haystack.includes(skillQuery);
      })
      .slice(0, 20)
      .map((skill, index) => mentionSuggestionFromSkill(skill, index))
    : [];
  const browserItems = includeBrowser
    ? [
        ...browserTabs.map((tab) => mentionSuggestionFromBrowserTab(tab)),
        browserTargetMentionSuggestion(query, conversationId),
      ].filter((item): item is MentionSuggestion => Boolean(item))
    : [];

  return [...browserItems, ...fileItems, ...skillItems]
    .sort((left, right) => left.score - right.score || left.primary.localeCompare(right.primary))
    .slice(0, 12);
}

export function browserMentionQueryFromText(query: string): string | null {
  const normalized = query.trim();
  const lower = normalized.toLowerCase();
  if (lower.startsWith("browser:")) return normalized.slice("browser:".length);
  if (lower === "browser") return "";
  if (normalized && "browser".startsWith(lower)) return "";
  return null;
}

export function mentionSuggestionFromBrowserTab(tab: BrowserTabMentionSuggestion, tokenOverride?: string): MentionSuggestion {
  const domain = tab.domain || domainFromUrl(tab.url || "") || "tab";
  const token = tokenOverride || tab.token || `@Browser:${domain}`;
  const mention: ComposerMention = {
    id: tab.id || `browser_tab:${tab.browser_id}:${tab.page_id || tab.tab_id}`,
    type: "browser_tab",
    label: "@Browser",
    token,
    displayPath: tab.display_path || tab.title || tab.url || domain,
    browserId: tab.browser_id,
    tabId: tab.tab_id,
    pageId: tab.page_id || tab.tab_id,
    windowId: tab.window_id || tab.page_id || tab.tab_id,
    url: tab.url,
    title: tab.title,
    runtime: tab.runtime,
    active: Boolean(tab.active || tab.is_active),
    state: tab.state,
    updatedAt: tab.updated_at,
  };
  return {
    id: mention.id,
    type: mention.type,
    primary: tab.title || domain,
    secondary: `${tab.active || tab.is_active ? "Active browser tab" : "Browser tab"} - ${tab.url || tab.page_id}`,
    token,
    mention,
    score: tab.score,
  };
}

export function browserTargetMentionSuggestion(query: string, conversationId?: string): MentionSuggestion | null {
  const target = browserMentionQueryFromText(query);
  if (target === null) return null;
  const token = target ? `@Browser:${target}` : "@Browser";
  const mention = mentionFromBrowserTarget(target, token, conversationId);
  return {
    id: mention.id,
    type: mention.type,
    primary: target ? `Browser: ${target}` : "Browser",
    secondary: target ? "Open or target this URL in the shared Browser window" : "Shared Browser window",
    token,
    mention,
    score: target ? 1.25 : 0.25,
  };
}

export function mentionFromBrowserTarget(target: string, token: string, conversationId?: string): ComposerMention {
  const normalizedTarget = target.trim();
  const url = normalizeBrowserMentionUrl(normalizedTarget);
  const displayPath = normalizedTarget ? url || normalizedTarget : "Shared Browser window";
  const targetId = normalizedTarget
    ? normalizedTarget.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || "target"
    : "active";
  return {
    id: `browser_tab:${conversationId || "pending"}:${targetId}`,
    type: "browser_tab",
    label: "@Browser",
    token,
    displayPath,
    browserId: conversationId,
    url,
    title: normalizedTarget ? `Browser target: ${normalizedTarget}` : "Shared Browser window",
    active: !normalizedTarget,
  };
}

export function mentionSuggestionFromWorkspace(item: WorkspaceMentionSuggestion): MentionSuggestion {
  const token = mentionTokenForPath(item.display_path);
  const label = item.is_directory ? "@Directory" : "@File";
  const mention: ComposerMention = {
    id: `${item.type}:${item.path}`,
    type: item.is_directory ? "directory" : "file",
    label,
    token,
    displayPath: item.display_path,
    fileName: item.is_directory ? undefined : item.name,
    filePath: item.is_directory ? undefined : item.path,
    directoryPath: item.is_directory ? item.path : undefined,
  };
  return {
    id: mention.id,
    type: mention.type,
    primary: item.display_path,
    secondary: item.is_directory ? "Directory" : "File",
    token,
    mention,
    score: item.score,
  };
}

export function mentionSuggestionFromSkill(skill: SkillSummary, index: number): MentionSuggestion {
  const token = `@skill:${skill.invocation_name}`;
  const mention: ComposerMention = {
    id: `skill:${skill.invocation_name}`,
    type: "skill",
    label: token,
    token,
    displayPath: skill.path,
    name: skill.name,
    invocationName: skill.invocation_name,
    slashName: skill.slash_name,
    description: skill.description,
    path: skill.path,
    source: skill.source,
  };
  return {
    id: mention.id,
    type: "skill",
    primary: token,
    secondary: skill.description || skill.name,
    token,
    mention,
    score: 2.5 + index * 0.01,
  };
}

export function autoResolveBrowserMentions(
  value: string,
  mentions: ComposerMention[],
  browserTabs: BrowserTabMentionSuggestion[],
  conversationId?: string,
): ComposerMention[] {
  const selectedBrowserMentions = mentions.filter((mention) => mention.type === "browser_tab");
  const parsedBrowserMentions = browserMentionsFromText(
    value,
    browserTabs,
    selectedBrowserMentions,
    conversationId,
  );
  if (parsedBrowserMentions.length > 0) {
    return dedupeMentions([
      ...mentions.filter((mention) => mention.type !== "browser_tab"),
      ...parsedBrowserMentions,
    ]);
  }
  return mentions;
}

export function domainFromUrl(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

export function browserMentionsFromText(
  value: string,
  browserTabs: BrowserTabMentionSuggestion[],
  selectedBrowserMentions: ComposerMention[],
  conversationId?: string,
): ComposerMention[] {
  const mentions: ComposerMention[] = [];
  const seen = new Set<string>();
  for (const match of value.matchAll(BROWSER_MENTION_RE)) {
    const token = match[2] || "";
    if (!token || seen.has(token.toLowerCase())) continue;
    seen.add(token.toLowerCase());
    const target = (match[3] || "").trim();
    const selectedMention = findSelectedBrowserMention(token, target, selectedBrowserMentions);
    if (selectedMention) {
      mentions.push(selectedMention);
      continue;
    }
    const matchedTab = target
      ? findBrowserTabMention(target, browserTabs)
      : browserTabs.find((tab) => tab.active || tab.is_active) || browserTabs[0];
    mentions.push(
      matchedTab
        ? mentionSuggestionFromBrowserTab(matchedTab, token).mention
        : mentionFromBrowserTarget(target, token, conversationId),
    );
  }
  return mentions;
}

export function findSelectedBrowserMention(
  token: string,
  target: string,
  selectedBrowserMentions: ComposerMention[],
) {
  const normalizedToken = token.toLowerCase();
  const normalizedTarget = target.trim().toLowerCase();
  return selectedBrowserMentions.find((mention) => {
    if (mention.token.toLowerCase() === normalizedToken) return true;
    if (!normalizedTarget) return false;
    const domain = domainFromUrl(mention.url || "").toLowerCase();
    const haystack = [domain, mention.url, mention.title, mention.displayPath, mention.pageId, mention.tabId, mention.windowId]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return domain === normalizedTarget || domain.startsWith(normalizedTarget) || haystack.includes(normalizedTarget);
  });
}

export function findBrowserTabMention(target: string, browserTabs: BrowserTabMentionSuggestion[]) {
  const normalized = target.trim().toLowerCase();
  if (!normalized) return undefined;
  return browserTabs.find((tab) => {
    const domain = (tab.domain || domainFromUrl(tab.url || "")).toLowerCase();
    const haystack = [domain, tab.url, tab.title, tab.page_id, tab.tab_id, tab.window_id]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return domain === normalized || domain.startsWith(normalized) || haystack.includes(normalized);
  });
}

export function normalizeBrowserMentionUrl(target: string) {
  const trimmed = target.trim();
  if (!trimmed) return undefined;
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(withScheme);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return undefined;
    if (!parsed.hostname || (!parsed.hostname.includes(".") && parsed.hostname !== "localhost")) return undefined;
    return parsed.toString();
  } catch {
    return undefined;
  }
}

export function dedupeMentions(mentions: ComposerMention[]) {
  const seen = new Set<string>();
  return mentions.filter((mention) => {
    const key = `${mention.type}:${mention.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function mentionTokenForPath(displayPath: string) {
  const normalized = displayPath.replace(/"/g, '\\"');
  return /\s/.test(displayPath) ? `@"${normalized}"` : `@${normalized}`;
}

export function buildComposerContextAttachments(
  annotations: ComposerAnnotation[],
  terminalSnippet: TerminalSnippet | null,
  mentions: ComposerMention[] = [],
) {
  const mentionAttachments: ContextAttachment[] = mentions.map((mention) => contextAttachmentFromMention(mention));
  const annotationAttachments: ContextAttachment[] = annotations.map((annotation) => {
    if (annotation.source === "browser") {
      return {
        type: "browser_annotation",
        id: annotation.id,
        label: `@Annotation#${annotation.id}`,
        display_path: annotation.displayPath,
        url: annotation.browserUrl || annotation.filePath,
        title: annotation.browserTitle || annotation.fileName,
        node_id: annotation.browserNodeId,
        selector: annotation.browserSelector,
        role: annotation.browserRole,
        text: annotation.text,
        quote: annotation.browserQuote || annotation.selectedLines,
      };
    }
    return {
      type: "viewer_annotation",
      id: annotation.id,
      label: `@Annotation#${annotation.id}`,
      file_name: annotation.fileName,
      file_path: annotation.filePath,
      display_path: annotation.displayPath,
      start_line: annotation.startLine,
      end_line: annotation.endLine,
      language: annotation.language,
      text: annotation.text,
    };
  });
  const requestAttachments: ContextAttachment[] = [...mentionAttachments, ...annotationAttachments];
  const displayAttachments: ContextAttachment[] = [...requestAttachments];

  if (terminalSnippet?.content) {
    requestAttachments.push({
      type: "terminal_output",
      id: terminalSnippet.id,
      label: "@terminal:bash",
      shell: "bash",
      content: terminalSnippet.content,
    });
    displayAttachments.push({
      type: "terminal_output",
      id: terminalSnippet.id,
      label: "@terminal:bash",
      shell: "bash",
      content_preview: terminalSnippet.content.slice(0, 160).replace(/\s+/g, " ").trim(),
      content_char_count: terminalSnippet.content.length,
    });
  }

  return { requestAttachments, displayAttachments };
}

export function contextAttachmentFromMention(mention: ComposerMention): ContextAttachment {
  if (mention.type === "browser_tab") {
    return {
      type: "browser_tab",
      id: mention.id,
      label: mention.label,
      browser_id: mention.browserId,
      tab_id: mention.tabId,
      page_id: mention.pageId || mention.tabId,
      window_id: mention.windowId || mention.pageId || mention.tabId,
      url: mention.url,
      title: mention.title,
      runtime: mention.runtime,
      active: mention.active,
      is_active: mention.active,
      display_path: mention.displayPath,
      state: mention.state,
      updated_at: mention.updatedAt,
    };
  }
  if (mention.type === "directory") {
    return {
      type: "directory",
      id: mention.id,
      label: mention.label,
      directory_path: mention.directoryPath,
      display_path: mention.displayPath,
    };
  }
  if (mention.type === "skill") {
    return {
      type: "skill",
      id: mention.id,
      label: mention.label,
      name: mention.name,
      invocation_name: mention.invocationName,
      slash_name: mention.slashName,
      description: mention.description,
      path: mention.path,
      display_path: mention.displayPath,
      source: mention.source,
    };
  }
  return {
    type: "file",
    id: mention.id,
    label: mention.label,
    file_name: mention.fileName,
    file_path: mention.filePath,
    display_path: mention.displayPath,
  };
}

export function attachmentOnlyMessage(
  annotations: ComposerAnnotation[],
  terminalSnippet: TerminalSnippet | null,
  mentions: ComposerMention[] = [],
) {
  const annotationText = annotations
    .map((annotation) => annotation.text.trim())
    .filter(Boolean)
    .join("\n\n");
  if (annotationText) return annotationText;
  if (terminalSnippet) return "Use the attached terminal output.";
  if (mentions.length > 0) return "Use the selected @ references.";
  return "Use the attached context.";
}

export function formatLineRange(start: number, end: number) {
  return start === end ? String(start) : `${start}-${end}`;
}

export function todoStatusLabel(status: TodoDockSnapshotUi["todos"][number]["status"]) {
  if (status === "completed") return "completed";
  if (status === "in_progress") return "in progress";
  return "pending";
}
