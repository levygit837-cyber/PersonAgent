export * from "./chat/messages";
export * from "./chat/tools";

import type { ChatRequestPayload, ContextAttachment } from "./chat/messages";

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

export interface TeamAgent {
  id: string;
  name: string;
  role: string;
  system_prompt: string;
  temperature: number;
  max_tokens: number;
  tools_enabled: boolean;
}

export interface TeamConfig {
  id: string;
  name: string;
  agents: TeamAgent[];
  execution_order: string[];
  coordinator?: TeamAgent;
  max_rounds: number | null;
  vote_every_rounds: number;
  consensus_threshold: number;
  force_final_vote?: boolean;
  blackboard_mode?: string;
  tool_policy?: string;
}

export interface TeamVote {
  agent_id: string;
  agent_name: string;
  approve: boolean;
  confidence: number;
  blocker?: string;
  critical_blocker?: boolean;
  final_points?: string;
}

export interface TeamConsensus {
  approvals: number;
  required: number;
  threshold: number;
  critical_blocker?: boolean;
  round?: number;
}

export interface TeamRunEvent {
  event:
    | "team_run_started"
    | "round_started"
    | "agent_turn_started"
    | "agent_delta"
    | "agent_turn_completed"
    | "execution_contract"
    | "blackboard_event"
    | "blackboard_snapshot"
    | "claim_graph_delta"
    | "coverage_matrix"
    | "coherency_score"
    | "tool_phase"
    | "debate_started"
    | "debate_skipped"
    | "adaptive_vote"
    | "vote_started"
    | "agent_vote"
    | "consensus_reached"
    | "coordinator_planning_started"
    | "coordinator_planning_completed"
    | "coordinator_redirect"
    | "coordinator_started"
    | "coordinator_completed"
    | "final_delta"
    | "team_run_completed"
    | "team_consensus_failed"
    | "team_run_cancelled"
    | "error";
  run_id?: string;
  conversation_id?: string;
  title?: string;
  team?: TeamConfig;
  round?: number;
  phase?: string;
  agent_id?: string;
  agent_name?: string;
  agent_role?: string;
  sequence?: number;
  event_type?: string;
  payload?: Record<string, unknown>;
  snapshot?: Record<string, unknown>;
  delta?: Record<string, unknown>;
  contract?: Record<string, unknown>;
  coverage_matrix?: Array<Record<string, unknown>>;
  coverage_complete?: number;
  coverage_total?: number;
  coherency_score?: number;
  coherency?: Record<string, unknown>;
  tool_phase?: string;
  calls?: Array<Record<string, unknown>>;
  results?: Array<Record<string, unknown>>;
  proposals?: Array<Record<string, unknown>>;
  triggers?: string[];
  redirect?: string;
  team_memory_snapshot?: Record<string, unknown>;
  blackboard_snapshot?: Record<string, unknown>;
  content?: string;
  reasoning_content?: string;
  digest?: string;
  approve?: boolean;
  confidence?: number;
  blocker?: string;
  critical_blocker?: boolean;
  final_points?: string;
  consensus?: TeamConsensus;
  guidance?: Record<string, unknown>;
  final_output?: string;
  reason?: string;
  error?: string;
  error_detail?: ApiErrorEnvelope;
  status?: number | string;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  first_token_ms?: number;
}

export interface TeamTraceEventUi {
  id: string;
  kind:
    | "run"
    | "round"
    | "turn"
    | "tool"
    | "vote"
    | "consensus"
    | "blackboard"
    | "debate"
    | "coordinator"
    | "failed"
    | "cancelled";
  title: string;
  detail?: string;
  round?: number;
  agentId?: string;
  agentName?: string;
  status?: "running" | "completed" | "approved" | "rejected" | "failed" | "cancelled";
  content?: string;
}

export type TeamCompactStatus = "idle" | "running" | "completed" | "failed" | "cancelled" | "blocked";

export interface TeamClaimTraceUi {
  id: string;
  type: string;
  text: string;
  agentId?: string;
  agentName?: string;
  status?: string;
  confidence?: number;
  coherencyScore?: number;
  noveltyScore?: number;
}

export interface TeamCoverageTraceUi {
  id: string;
  title: string;
  detail?: string;
  ownerAgentId?: string;
  status?: string;
}

export interface TeamToolTraceUi {
  id: string;
  phase?: string;
  title: string;
  status: TeamCompactStatus;
  summary?: string;
  calls: Array<Record<string, unknown>>;
  results: Array<Record<string, unknown>>;
  proposals: Array<Record<string, unknown>>;
  createdAt?: string;
}

export type TeamAgentLogKind = "status" | "thinking" | "response" | "tool" | "claim" | "error";

export interface TeamAgentLogUi {
  id: string;
  kind: TeamAgentLogKind;
  title: string;
  content?: string;
  status?: TeamCompactStatus;
  round?: number;
  phase?: string;
  createdAt?: string;
  toolId?: string;
}

export interface TeamAgentTraceUi {
  agentId: string;
  agentName: string;
  agentRole?: string;
  status: TeamCompactStatus;
  phase?: string;
  round?: number;
  focus?: string;
  thinking: string;
  output: string;
  digest?: string;
  logs: TeamAgentLogUi[];
  claims: TeamClaimTraceUi[];
  tools: TeamToolTraceUi[];
  durationMs?: number;
  firstTokenMs?: number;
  coherencyScore?: number;
  error?: string;
  isCoordinator?: boolean;
}

export interface TeamBlackboardTraceUi {
  status: TeamCompactStatus;
  actualPhase?: string;
  nextAction?: string;
  entryCount?: number;
  latestSequence?: number;
  claims: TeamClaimTraceUi[];
  evidence: string[];
  decisions: string[];
  blockers: string[];
  coverage: TeamCoverageTraceUi[];
  coverageComplete?: number;
  coverageTotal?: number;
  coherencyScore?: number;
  lowCoherencyCount?: number;
  tools: TeamToolTraceUi[];
  snapshot?: Record<string, unknown>;
  updatedAt?: string;
}

export interface TeamRunUi {
  runId?: string;
  title: string;
  status: TeamCompactStatus;
  round?: number;
  actualPhase?: string;
  agents: TeamAgentTraceUi[];
  blackboard: TeamBlackboardTraceUi;
  votes: TeamTraceEventUi[];
  startedAt?: string;
  completedAt?: string;
}

export interface MemoryTraceClassicItem {
  path?: string;
  name?: string;
  header?: string;
  mtime_ms?: number;
  snippet?: string;
}

export interface MemoryTraceOperationalItem {
  type?: string;
  summary?: string;
  evidence?: string[];
  paths?: string[];
  source_ids?: string[];
  event_types?: string[];
  score?: number;
  status?: string;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface MemoryTraceSummary {
  total_used: number;
  classic_count: number;
  rag_count: number;
  omitted_count: number;
  budget_used: number;
  budget_tokens: number;
  latency_ms: number;
}

export interface MemoryTrace {
  classic: MemoryTraceClassicItem[];
  operational: MemoryTraceOperationalItem[];
  summary: MemoryTraceSummary;
  filters_applied?: Record<string, unknown>;
  prompt?: {
    formatted?: string;
    truncated?: boolean;
  };
}

export interface SessionMemoryTopItem {
  id: string;
  source: "classic" | "rag" | string;
  label: string;
  count: number;
  paths: string[];
  evidence: string[];
  messages: string[];
}

export interface SessionMemorySummary {
  total_recalls: number;
  rag_used: number;
  classic_used: number;
  omitted: number;
  avg_latency_ms: number;
  budget_used: number;
  budget_tokens: number;
  most_used: SessionMemoryTopItem[];
}

export interface SessionUsageMetric {
  value: number;
  estimated: boolean;
}

export interface SessionUsage {
  context_tokens: SessionUsageMetric;
  agent_output_tokens: SessionUsageMetric;
  thinking_output_tokens: SessionUsageMetric;
  tool_calls: SessionUsageMetric;
  skills_used_count: SessionUsageMetric;
  mcp_calls_count: SessionUsageMetric;
  plans_created: SessionUsageMetric;
  todos_created: SessionUsageMetric;
  subagents_used: SessionUsageMetric;
}

export interface ChangedFile {
  id: string;
  path: string;
  display_path: string;
  added_lines: number;
  removed_lines: number;
  source: string;
  status: string;
  diff?: string;
  content?: string;
}

export interface SessionSource {
  id: string;
  title: string;
  description: string;
  url: string;
  domain: string;
  favicon_url: string;
  tool_name: string;
}

export interface ProjectItem {
  id: string;
  type: "commit" | "push" | "pr" | "branch" | string;
  title: string;
  subtitle?: string;
  timestamp?: string | null;
  url?: string | null;
  active?: boolean;
  metadata?: Record<string, unknown>;
}

export interface SessionProjectSnapshot {
  repo?: {
    name_with_owner?: string | null;
    url?: string | null;
    default_branch?: string | null;
    pushed_at?: string | null;
    source?: string;
  } | null;
  prs: ProjectItem[];
  branches: ProjectItem[];
  pushes: ProjectItem[];
  commits: ProjectItem[];
  errors: string[];
}

export interface ProjectDetail {
  type: string;
  id: string;
  title: string;
  url?: string | null;
  metadata?: Record<string, unknown>;
  files?: Array<Record<string, unknown>>;
  commits?: Array<Record<string, unknown>>;
  patch?: string;
  source?: string;
  error?: string | null;
}

export interface SessionPanelSnapshot {
  conversation_id: string;
  title: string;
  updated_at: string;
  changed_files: ChangedFile[];
  sources: SessionSource[];
  usage: SessionUsage;
  memory?: SessionMemorySummary;
  project: SessionProjectSnapshot;
}

export function emptySessionUsage(): SessionUsage {
  return {
    context_tokens: { value: 0, estimated: false },
    agent_output_tokens: { value: 0, estimated: false },
    thinking_output_tokens: { value: 0, estimated: false },
    tool_calls: { value: 0, estimated: false },
    skills_used_count: { value: 0, estimated: false },
    mcp_calls_count: { value: 0, estimated: false },
    plans_created: { value: 0, estimated: false },
    todos_created: { value: 0, estimated: false },
    subagents_used: { value: 0, estimated: false },
  };
}

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
