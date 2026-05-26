import { requestJson, webSocketBaseUrl } from "../http";
import type {
  SessionBrowserAnnotation,
  SessionBrowserCooperationEvent,
  SessionBrowserCooperationMode,
  SessionBrowserCooperationState,
  SessionBrowserCooperationWsEvent,
  SessionBrowserTimelineEvent,
  SessionBrowserView,
  SessionBrowserViewport,
} from "./types";

function sessionBrowserPath(browserId: string, suffix: string, conversationId?: string | null) {
  const encodedBrowserId = encodeURIComponent(browserId);
  if (conversationId?.trim()) {
    return `/sessions/${encodeURIComponent(conversationId.trim())}/browser/${encodedBrowserId}${suffix}`;
  }
  return `/sessions/browser/${encodedBrowserId}${suffix}`;
}

export function getSessionBrowserView(
  baseUrl: string,
  browserId: string,
  viewport: SessionBrowserViewport,
  conversationId?: string | null,
) {
  const params = new URLSearchParams({
    width: String(Math.round(viewport.width)),
    height: String(Math.round(viewport.height)),
  });
  if (viewport.cache_mode) params.set("cache_mode", viewport.cache_mode);
  if (viewport.wait_for_styles !== undefined) params.set("wait_for_styles", String(viewport.wait_for_styles));
  return requestJson<SessionBrowserView>(
    baseUrl,
    `${sessionBrowserPath(browserId, "/view", conversationId)}?${params.toString()}`,
  );
}

export function navigateSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { url: string },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/navigate", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function moveSessionBrowserHistory(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { direction: -1 | 1 },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/history", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function reloadSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport,
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/reload", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function clickSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { x: number; y: number; button?: "left" | "middle" | "right" },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/click", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function keySessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { text?: string; key?: string },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/key", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function scrollSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & { delta_x: number; delta_y: number },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/scroll", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function actSessionBrowser(
  baseUrl: string,
  browserId: string,
  input: SessionBrowserViewport & {
    node_id: string;
    action:
      | "click"
      | "fill"
      | "submit"
      | "select"
      | "press"
      | "hover"
      | "wait"
      | "drag"
      | "drop"
      | "upload"
      | "select_text"
      | "scroll_to"
      | "screenshot";
    value?: string;
    key?: string;
    target_node_id?: string;
    timeout_ms?: number;
    files?: string[];
    text?: string;
    x?: number;
    y?: number;
    source?: "user" | "agent" | "system";
  },
  conversationId?: string | null,
) {
  return requestJson<SessionBrowserView>(baseUrl, sessionBrowserPath(browserId, "/action", conversationId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function setSessionBrowserCooperation(
  baseUrl: string,
  conversationId: string,
  browserId: string,
  input: { enabled: boolean; mode?: SessionBrowserCooperationMode },
) {
  return requestJson<{
    cooperation: SessionBrowserCooperationState;
    state_patch: { cooperation?: SessionBrowserCooperationState };
    agent_context?: Record<string, unknown>;
  }>(baseUrl, sessionBrowserPath(browserId, "/cooperation", conversationId), {
    method: "POST",
    body: JSON.stringify({ enabled: input.enabled, mode: input.mode ?? "observe_only" }),
  });
}

export function ingestSessionBrowserEvents(
  baseUrl: string,
  conversationId: string,
  browserId: string,
  events: SessionBrowserCooperationEvent[],
) {
  return requestJson<{
    accepted_count: number;
    dropped_count: number;
    state_patch: { cooperation?: SessionBrowserCooperationState };
    notifications: Array<Record<string, unknown>>;
  }>(baseUrl, sessionBrowserPath(browserId, "/events", conversationId), {
    method: "POST",
    body: JSON.stringify({ events }),
  });
}

export function connectSessionBrowserCooperation(
  baseUrl: string,
  conversationId: string,
  browserId: string,
  handlers: {
    onMessage?: (event: SessionBrowserCooperationWsEvent) => void;
    onOpen?: (socket: WebSocket) => void;
    onClose?: () => void;
    onError?: (error: Event) => void;
  } = {},
) {
  const socket = new WebSocket(
    `${webSocketBaseUrl(baseUrl)}${sessionBrowserPath(browserId, "/cooperation/ws", conversationId)}`,
  );
  socket.onopen = () => handlers.onOpen?.(socket);
  socket.onmessage = (message) => {
    try {
      handlers.onMessage?.(JSON.parse(String(message.data)) as SessionBrowserCooperationWsEvent);
    } catch (error) {
      handlers.onMessage?.({
        type: "error",
        error: error instanceof Error ? error.message : String(error),
      });
    }
  };
  socket.onerror = (event) => handlers.onError?.(event);
  socket.onclose = () => handlers.onClose?.();
  return socket;
}

export function createSessionBrowserAnnotation(
  baseUrl: string,
  conversationId: string,
  browserId: string,
  input: {
    node_id: string;
    body: string;
    quote?: string;
    url?: string;
    title?: string;
    selector?: string;
    frame_id?: string;
    selector_chain?: string[];
    shadow_path?: string[];
    tab_id?: string;
  },
) {
  return requestJson<{ annotation: SessionBrowserAnnotation; annotations: SessionBrowserAnnotation[]; timeline_events: SessionBrowserTimelineEvent[] }>(
    baseUrl,
    sessionBrowserPath(browserId, "/annotations", conversationId),
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function deleteSessionBrowserAnnotation(
  baseUrl: string,
  conversationId: string,
  browserId: string,
  annotationId: string,
) {
  return requestJson<{ annotations: SessionBrowserAnnotation[]; timeline_events: SessionBrowserTimelineEvent[] }>(
    baseUrl,
    `${sessionBrowserPath(browserId, "/annotations", conversationId)}/${encodeURIComponent(annotationId)}`,
    { method: "DELETE" },
  );
}
