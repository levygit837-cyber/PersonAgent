import type { GeneratedImage } from "./messages";
import type { ApiErrorEnvelope, MemoryTrace } from "../chat";

export type ToolBlockStatus = "queued" | "running" | "completed" | "error" | "permission_required";

export interface ToolBlockUi {
  id: string;
  name: string;
  status: ToolBlockStatus;
  title: string;
  message: string;
  content: string;
  path?: string;
  data?: Record<string, unknown>;
  isCollapsed: boolean;
}

export interface ToolApprovalPayload {
  approval_id: string;
  args_hash?: string;
  status: string;
  tool_call_id: string;
  tool_name: string;
  arguments?: Record<string, unknown>;
  message?: string;
}

export interface ToolApprovalUi {
  conversationId: string;
  approvalId: string;
  argsHash?: string;
  toolCallId: string;
  toolName: string;
  toolInput?: Record<string, unknown>;
  message?: string;
}

export interface PlanApprovalUi {
  conversationId: string;
  approvalId: string;
  planId: string;
  planContent: string;
  planStatus: string;
  feedback?: string | null;
}

export interface PlanDecisionResponse {
  event?: string;
  conversation_id: string;
  approval_id?: string | null;
  plan_id?: string | null;
  plan_content?: string;
  plan_status?: string;
  plan_active?: boolean;
  feedback?: string | null;
  cancelled?: boolean;
  injected_message?: string;
  suggested_message?: string;
}

export interface StreamChunk {
  event?: string;
  conversation_id?: string;
  title?: string;
  approval_id?: string;
  args_hash?: string;
  plan_id?: string;
  plan_content?: string;
  plan_status?: string;
  plan_active?: boolean;
  feedback?: string | null;
  cancelled?: boolean;
  content?: string;
  reasoning_content?: string;
  finish_reason?: string;
  model?: string;
  provider?: string;
  usage?: Record<string, unknown>;
  context_tokens_estimated?: number;
  context_tokens_after_turn_estimated?: number;
  context_window_tokens?: number;
  context_compacted?: boolean;
  prompt_tokens_estimated?: number;
  memory_trace?: MemoryTrace;
  images?: GeneratedImage[];
  is_thinking?: boolean;
  error?: string;
  error_detail?: ApiErrorEnvelope;
  status?: number;
  tool_call_id?: string;
  tool_name?: string;
  tool_status?: string;
  tool_message?: string;
  tool_result?: string;
  tool_error?: string;
  metadata?: Record<string, unknown>;
  tool_input?: Record<string, unknown>;
  tool_data?: Record<string, unknown>;
  tool_approval?: ToolApprovalPayload;
  tool_calls?: unknown;
  tool_iterations?: number;
  next_step_suggestion?: string | null;
}

export function isToolEvent(chunk: StreamChunk) {
  return (
    chunk.event === "tool_call_started" ||
    chunk.event === "tool_progress" ||
    chunk.event === "tool_result" ||
    chunk.event === "tool_error" ||
    chunk.event === "permission_required" ||
    chunk.event === "tool_group_started" ||
    chunk.event === "tool_group_finished"
  );
}

export function isToolGroupEvent(chunk: StreamChunk) {
  return chunk.event === "tool_group_started" || chunk.event === "tool_group_finished";
}

export function parseToolStatus(value?: string): ToolBlockStatus {
  if (value === "completed") return "completed";
  if (value === "error") return "error";
  if (value === "permission_required") return "permission_required";
  if (value === "running") return "running";
  return "queued";
}
