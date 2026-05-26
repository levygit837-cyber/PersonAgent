import type { ApiErrorEnvelope } from "./models";

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
