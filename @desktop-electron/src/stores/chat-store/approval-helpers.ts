import {
  type ChatMessageUi,
  type PlanApprovalUi,
  type StreamChunk,
  type ToolApprovalUi,
} from "../../types/chat";

export function planApprovalFromChunk(chunk: StreamChunk): PlanApprovalUi {
  return {
    conversationId: String(chunk.conversation_id ?? ""),
    approvalId: String(chunk.approval_id ?? ""),
    planId: String(chunk.plan_id ?? ""),
    planContent: String(chunk.plan_content ?? ""),
    planStatus: String(chunk.plan_status ?? "awaiting_approval"),
    feedback: chunk.feedback,
  };
}

export function attachPlanApprovalArtifact(message: ChatMessageUi, approval: PlanApprovalUi): ChatMessageUi {
  return {
    ...message,
    metadata: {
      ...(message.metadata ?? {}),
      plan_approval: approval,
    },
  };
}

export function updatePlanApprovalArtifact(
  messages: ChatMessageUi[],
  approvalId: string,
  planStatus: string,
  feedback?: string,
): ChatMessageUi[] {
  return messages.map((message) => {
    const raw = message.metadata?.plan_approval;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return message;
    const approval = raw as Partial<PlanApprovalUi>;
    if (approval.approvalId !== approvalId) return message;
    return {
      ...message,
      metadata: {
        ...(message.metadata ?? {}),
        plan_approval: {
          ...approval,
          planStatus,
          feedback: feedback?.trim() || approval.feedback,
        },
      },
    };
  });
}

export function toolApprovalFromChunk(chunk: StreamChunk): ToolApprovalUi {
  return {
    conversationId: String(chunk.conversation_id ?? ""),
    approvalId: String(chunk.approval_id ?? ""),
    argsHash:
      typeof chunk.args_hash === "string"
        ? chunk.args_hash
        : typeof chunk.tool_approval?.args_hash === "string"
          ? chunk.tool_approval.args_hash
          : undefined,
    toolCallId: String(chunk.tool_call_id ?? chunk.tool_approval?.tool_call_id ?? ""),
    toolName: String(chunk.tool_name ?? chunk.tool_approval?.tool_name ?? "tool"),
    toolInput: chunk.tool_input ?? chunk.tool_approval?.arguments,
    message: chunk.tool_error ?? chunk.tool_result ?? chunk.tool_approval?.message,
  };
}
