import { localModel, type LlmModel, type ModelProvider } from "../../../types/chat";

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

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const DEEPSEEK_API_GROUP = "DeepSeek API";
export const DEEPSEEK_NVIDIA_GROUP = "DeepSeek NVIDIA";
export const ZENMUX_GROUP = "ZenMux";

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
