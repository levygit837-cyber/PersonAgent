import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAppStore } from "../../stores/app-store";

type StateEventResource =
  | "git-status"
  | "git-branches"
  | "git-recent-actions"
  | "git-pull-requests"
  | "session-panel"
  | "models"
  | "codex-auth"
  | "conversations";

interface StateChangedEvent {
  event: "state.changed";
  resource: StateEventResource | string;
  scope?: {
    workspace_root?: string | null;
    conversation_id?: string | null;
    provider?: string | null;
  };
  version?: string;
  changed_at?: string;
}

const TERMINAL_STATE_CHECK_DELAYS_MS = [1_500, 5_000];

export function StateEventBridge() {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const apiStatus = useAppStore((state) => state.apiStatus);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);

  useEffect(() => {
    if (!baseUrl || apiStatus !== "online") return;
    const controller = new AbortController();
    const params = new URLSearchParams();
    if (selectedWorkspace) params.set("workspace_root", selectedWorkspace);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    void streamStateEvents(`${baseUrl}/events/state${suffix}`, controller.signal, (event) => {
      invalidateStateResource(queryClient, baseUrl, event.resource, event.scope);
    });

    return () => controller.abort();
  }, [apiStatus, baseUrl, queryClient, selectedWorkspace]);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ command?: string; workspaceRoot?: string | null }>).detail;
      const command = detail?.command ?? "";
      const workspaceRoot = detail?.workspaceRoot || selectedWorkspace;
      for (const delay of TERMINAL_STATE_CHECK_DELAYS_MS) {
        window.setTimeout(() => {
          if (/\bgit\b/.test(command) && workspaceRoot) {
            invalidateGitState(queryClient, baseUrl, workspaceRoot);
          }
          if (/\bcodex\b/.test(command)) {
            invalidateStateResource(queryClient, baseUrl, "codex-auth", { provider: "codex" });
            invalidateStateResource(queryClient, baseUrl, "models", { provider: "codex" });
          }
        }, delay);
      }
    };
    window.addEventListener("personagent:terminal-state-command", handler);
    return () => window.removeEventListener("personagent:terminal-state-command", handler);
  }, [baseUrl, queryClient, selectedWorkspace]);

  return null;
}

function parseStateEvent(raw: string) {
  try {
    const event = JSON.parse(raw) as StateChangedEvent;
    return event.event === "state.changed" && typeof event.resource === "string" ? event : null;
  } catch {
    return null;
  }
}

async function streamStateEvents(url: string, signal: AbortSignal, onEvent: (event: StateChangedEvent) => void) {
  const headers = window.personAgent?.auth?.getHeaders ? await window.personAgent.auth.getHeaders() : {};
  const response = await fetch(url, {
    headers: {
      ...headers,
      Accept: "text/event-stream",
      "Cache-Control": "no-cache",
    },
    signal,
  });
  if (!response.ok || !response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseStateSseBlocks(buffer);
      buffer = parsed.rest;
      for (const raw of parsed.events) {
        const event = parseStateEvent(raw);
        if (event) onEvent(event);
      }
    }
  } catch {
    // Fallback polling paths still refresh critical state.
  } finally {
    reader.releaseLock();
  }
}

function parseStateSseBlocks(buffer: string) {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: string[] = [];
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n")
      .trim();
    if (data) events.push(data);
  }
  return { events, rest };
}

function invalidateGitState(queryClient: ReturnType<typeof useQueryClient>, baseUrl: string, workspaceRoot: string) {
  invalidateStateResource(queryClient, baseUrl, "git-status", { workspace_root: workspaceRoot });
  invalidateStateResource(queryClient, baseUrl, "git-branches", { workspace_root: workspaceRoot });
  invalidateStateResource(queryClient, baseUrl, "git-recent-actions", { workspace_root: workspaceRoot });
  invalidateStateResource(queryClient, baseUrl, "git-pull-requests", { workspace_root: workspaceRoot });
}

function invalidateStateResource(
  queryClient: ReturnType<typeof useQueryClient>,
  baseUrl: string,
  resource: string,
  scope?: StateChangedEvent["scope"],
) {
  const workspaceRoot = scope?.workspace_root || undefined;
  const conversationId = scope?.conversation_id || undefined;
  const provider = scope?.provider || undefined;

  if (resource === "git-status") {
    void queryClient.invalidateQueries({ queryKey: workspaceRoot ? ["git-status", baseUrl, workspaceRoot] : ["git-status"] });
    return;
  }
  if (resource === "git-branches") {
    void queryClient.invalidateQueries({ queryKey: workspaceRoot ? ["git-branches", baseUrl, workspaceRoot] : ["git-branches"] });
    return;
  }
  if (resource === "git-recent-actions") {
    void queryClient.invalidateQueries({ queryKey: workspaceRoot ? ["git-recent-actions", baseUrl, workspaceRoot] : ["git-recent-actions"] });
    return;
  }
  if (resource === "git-pull-requests") {
    void queryClient.invalidateQueries({ queryKey: workspaceRoot ? ["git-pull-requests", baseUrl, workspaceRoot] : ["git-pull-requests"] });
    return;
  }
  if (resource === "session-panel") {
    void queryClient.invalidateQueries({
      queryKey: conversationId ? ["session-panel", baseUrl, conversationId, workspaceRoot] : ["session-panel"],
    });
    return;
  }
  if (resource === "models") {
    void queryClient.invalidateQueries({ queryKey: provider ? ["models", baseUrl, provider] : ["models", baseUrl] });
    return;
  }
  if (resource === "codex-auth") {
    void queryClient.invalidateQueries({ queryKey: ["codex-auth", baseUrl] });
    return;
  }
  if (resource === "conversations") {
    void queryClient.invalidateQueries({ queryKey: ["conversations", baseUrl] });
  }
}
