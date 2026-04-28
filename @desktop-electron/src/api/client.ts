import { readSseStream } from "./sse";
import type {
  ChatRequestPayload,
  ChatCommandInfo,
  CodexAuthStatus,
  ConversationDetail,
  ConversationSummary,
  LlmModel,
  ModelProvider,
  PlanDecisionResponse,
  ProjectDetail,
  SessionPanelSnapshot,
  StreamChunk,
  TeamConfig,
  TeamRunEvent,
  buildTeamRunStart,
} from "../types/chat";

const fallbackBaseUrls = ["http://localhost:8000", "http://localhost:8001"];

export async function resolveBackendUrl(current?: string | null) {
  const candidates = Array.from(new Set([current, ...fallbackBaseUrls].filter(Boolean))) as string[];
  for (const candidate of candidates) {
    try {
      const response = await fetch(`${candidate}/health`, { signal: AbortSignal.timeout(3000) });
      if (response.ok) return candidate;
    } catch {
      continue;
    }
  }
  throw new Error("No PersonAgent backend answered on the configured ports.");
}

async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = String(body.detail ?? detail);
    } catch {
      // Non-JSON error bodies keep status text.
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function listConversations(baseUrl: string) {
  return requestJson<ConversationSummary[]>(baseUrl, "/conversations");
}

export function getConversation(baseUrl: string, id: string) {
  return requestJson<ConversationDetail>(baseUrl, `/conversations/${id}`);
}

export function deleteConversation(baseUrl: string, id: string) {
  return requestJson<{ deleted: boolean }>(baseUrl, `/conversations/${id}`, { method: "DELETE" });
}

export function getSessionPanel(baseUrl: string, conversationId: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<SessionPanelSnapshot>(baseUrl, `/sessions/${conversationId}/panel${suffix}`);
}

export function listWorkspaceFiles(baseUrl: string, dirPath: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams({ path: dirPath });
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  return requestJson<Array<{ name: string; isDirectory: boolean; path: string }>>(baseUrl, `/workspace/files?${params.toString()}`);
}

export function readWorkspaceFile(baseUrl: string, filePath: string, workspaceRoot?: string | null) {
  const params = new URLSearchParams({ path: filePath });
  if (workspaceRoot?.trim()) params.set("workspace_root", workspaceRoot.trim());
  return requestJson<{ path: string; name: string; content: string }>(baseUrl, `/workspace/file?${params.toString()}`);
}

export function getSessionProjectDetail(
  baseUrl: string,
  conversationId: string,
  input: { type: string; id: string; workspaceRoot?: string | null },
) {
  const params = new URLSearchParams({ type: input.type, id: input.id });
  if (input.workspaceRoot?.trim()) params.set("workspace_root", input.workspaceRoot.trim());
  return requestJson<ProjectDetail>(baseUrl, `/sessions/${conversationId}/project/details?${params.toString()}`);
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
  const response = await fetch(`${baseUrl}/chat/completions/stream`, {
    method: "POST",
    headers: {
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

export function approveTool(baseUrl: string, input: { conversationId: string; approvalId: string }) {
  return requestJson<Record<string, unknown>>(baseUrl, "/chat/tools/approve", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
    }),
  });
}

export async function* streamApproveTool(baseUrl: string, input: { conversationId: string; approvalId: string }, signal?: AbortSignal) {
  const response = await fetch(`${baseUrl}/chat/tools/approve/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "Cache-Control": "no-cache",
    },
    body: JSON.stringify({
      conversation_id: input.conversationId,
      approval_id: input.approvalId,
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

function webSocketBaseUrl(baseUrl: string) {
  const url = new URL(baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString().replace(/\/$/, "");
}
