export type ModelProvider = "llama" | "nvidia" | "deepseek" | "zenmux" | "vertex" | "kimi" | "codex";

export type ReasoningPreset = "low" | "medium" | "high" | "xhigh" | "max";
export type PromptMode = "auto" | "writing" | "exploring" | "research";

export const reasoningPresets: Array<{
  value: ReasoningPreset;
  label: string;
  tokenBudget: number;
}> = [
  { value: "low", label: "Low", tokenBudget: 2048 },
  { value: "medium", label: "Medium", tokenBudget: 4082 },
  { value: "high", label: "High", tokenBudget: 8192 },
  { value: "xhigh", label: "xHigh", tokenBudget: 16382 },
  { value: "max", label: "Max", tokenBudget: 32768 },
];

export function reasoningTokenBudget(preset: ReasoningPreset) {
  return reasoningPresets.find((item) => item.value === preset)?.tokenBudget ?? 2048;
}

export interface LlmModel {
  id: string;
  name: string;
  provider: ModelProvider;
  context_length?: number;
  capabilities?: string[];
  metadata?: Record<string, unknown>;
}

export interface CodexAuthStatus {
  authenticated: boolean;
  auth_mode?: string | null;
  account_id?: string | null;
  email?: string | null;
  plan_type?: string | null;
  last_refresh?: string | null;
  auth_path?: string | null;
  error?: string | null;
  logout_started?: boolean;
}

export interface ApiErrorEnvelope {
  code: string;
  category: string;
  severity?: string;
  message: string;
  status: number;
  retryable: boolean;
  correlation_id?: string;
  safe_for_model?: boolean;
  safe_for_telemetry?: boolean;
  metadata?: Record<string, unknown>;
}

export const localModel: LlmModel = {
  id: "local-model",
  name: "Local model",
  provider: "llama",
};
