import { readSseStream } from "../sse";
import { PersonAgentApiError } from "../errors";
import { requestJson, personAgentAuthHeaders, webSocketBaseUrl } from "./http";
import type {
  ChatRequestPayload,
  ChatCommandInfo,
  CodexAuthStatus,
  LlmModel,
  ModelProvider,
  PlanDecisionResponse,
  StreamChunk,
  TeamConfig,
  TeamRunEvent,
  buildTeamRunStart,
} from "../../types/chat";

export interface ActionApprovalPayload {
  approval_id: string;
  action_kind: string;
  args_hash: string;
  expires_at: number;
  approval_signature: string;
}

export async function createActionApproval(_baseUrl: string, actionKind: string, args: Record<string, unknown>) {
  if (!window.personAgent?.security?.createActionApproval) {
    throw new PersonAgentApiError({
      message: "Desktop action approval is unavailable.",
      code: "desktop.action_approval_unavailable",
      category: "auth",
      status: 403,
      retryable: false,
    });
  }
  return window.personAgent.security.createActionApproval(actionKind, args) as Promise<ActionApprovalPayload>;
}

export async function listModels(baseUrl: string, provider: ModelProvider, capability?: string) {
  const params = new URLSearchParams({ provider, refresh: "false" });
  if (capability) params.set("capability", capability);
  const response = await requestJson<{ data?: unknown[] } | LlmModel[]>(baseUrl, `/chat/models?${params.toString()}`);
  const data = Array.isArray(response) ? response : response.data ?? [];
  return data.map((item) => normalizeModel(item, provider));
}

export function getCodexAuthStatus(baseUrl: string) {
  return requestJson<CodexAuthStatus>(baseUrl, "/chat/auth/codex/status");
}

export function logoutCodex(baseUrl: string) {
  return requestJson<CodexAuthStatus>(baseUrl, "/chat/auth/codex/logout", { method: "POST" });
}

export async function listChatCommands(baseUrl: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<ChatCommandInfo[]>(baseUrl, `/chat/commands${suffix}`);
}

function normalizeModel(item: unknown, provider: ModelProvider): LlmModel {
  if (!item || typeof item !== "object") return { id: "local-model", name: "Local model", provider };
  const record = item as Record<string, unknown>;
  const id = String(record.id ?? record.name ?? "local-model");
  return {
    id,
    name: String(record.name ?? id),
    provider,
    context_length: typeof record.context_length === "number" ? record.context_length : undefined,
    capabilities: Array.isArray(record.capabilities) ? record.capabilities.map(String) : undefined,
    metadata: record,
  };
}

export async function* streamChatCompletion(baseUrl: string, payload: ChatRequestPayload, signal?: AbortSignal) {
  const authHeaders = await personAgentAuthHeaders();
  const response = await fetch(`${baseUrl}/chat/completions/stream`, {
    method: "POST",
    headers: {
      ...authHeaders,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "Cache-Control": "no-cache",
    },
    body: JSON.stringify(payload),
    signal,
  });
  yield* readSseStream<StreamChunk>(response, signal);
}

export function approvePlan(
  baseUrl: string,
  input: { conversationId: string; approvalId: string; feedback?: string },
) {
  return requestJson<PlanDecisionResponse>(baseUrl, "/chat/plan/approve", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
      feedback: input.feedback,
    }),
  });
}

export function continuePlan(
  baseUrl: string,
  input: { conversationId: string; approvalId: string; feedback?: string },
) {
  return requestJson<PlanDecisionResponse>(baseUrl, "/chat/plan/continue", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
      feedback: input.feedback,
    }),
  });
}

export function cancelPlan(
  baseUrl: string,
  input: { conversationId: string; approvalId: string; feedback?: string },
) {
  return requestJson<PlanDecisionResponse>(baseUrl, "/chat/plan/cancel", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
      feedback: input.feedback,
    }),
  });
}

export function approveTool(baseUrl: string, input: { conversationId: string; approvalId: string; argsHash?: string }) {
  return requestJson<Record<string, unknown>>(baseUrl, "/chat/tools/approve", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
      args_hash: input.argsHash,
    }),
  });
}

export async function* streamApproveTool(baseUrl: string, input: { conversationId: string; approvalId: string; argsHash?: string }, signal?: AbortSignal) {
  const authHeaders = await personAgentAuthHeaders();
  const response = await fetch(`${baseUrl}/chat/tools/approve/stream`, {
    method: "POST",
    headers: {
      ...authHeaders,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "Cache-Control": "no-cache",
    },
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
      args_hash: input.argsHash,
    }),
    signal,
  });
  yield* readSseStream<StreamChunk>(response, signal);
}

export function rejectTool(baseUrl: string, input: { conversationId: string; approvalId: string }) {
  return requestJson<Record<string, unknown>>(baseUrl, "/chat/tools/reject", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
    }),
  });
}

export async function listTeams(baseUrl: string) {
  const response = await requestJson<{ data?: TeamConfig[] }>(baseUrl, "/chat/teams");
  return response.data ?? [];
}

export async function* streamTeamChat(
  baseUrl: string,
  payload: ReturnType<typeof buildTeamRunStart>,
  signal?: AbortSignal,
) {
  const socket = new WebSocket(`${webSocketBaseUrl(baseUrl)}/chat/team/ws`);
  const queue: TeamRunEvent[] = [];
  let done = false;
  let wake: (() => void) | undefined;

  const notify = () => {
    wake?.();
    wake = undefined;
  };

  const push = (event: TeamRunEvent) => {
    queue.push(event);
    notify();
  };

  const stop = () => {
    try {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "team.run.stop" }));
      }
    } catch {
      // Ignore best-effort stop delivery errors.
    }
    socket.close();
  };

  socket.onopen = () => socket.send(JSON.stringify(payload));
  socket.onmessage = (message) => {
    try {
      push(JSON.parse(String(message.data)) as TeamRunEvent);
    } catch (error) {
      push({ event: "error", error: error instanceof Error ? error.message : String(error) });
    }
  };
  socket.onerror = () => push({ event: "error", error: "Team Mode WebSocket failed." });
  socket.onclose = () => {
    done = true;
    notify();
  };
  signal?.addEventListener("abort", stop, { once: true });

  try {
    while (!done || queue.length > 0) {
      if (queue.length > 0) {
        const event = queue.shift();
        if (event) yield event;
        continue;
      }
      await new Promise<void>((resolve) => {
        wake = resolve;
      });
    }
  } finally {
    signal?.removeEventListener("abort", stop);
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      stop();
    }
  }
}
