import { requestJson, webSocketBaseUrl } from "./http";
import type { ConversationDetail, ConversationSummary, ProjectDetail, SessionPanelSnapshot } from "../../types/chat";

export interface ConversationForkMessagePayload {
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  metadata?: Record<string, unknown>;
  tool_calls?: Array<Record<string, unknown>> | null;
  tool_call_id?: string | null;
}

export interface SessionBrowserViewport {
  width: number;
  height: number;
  cache_mode?: "prefer_live" | "prefer_cached";
  wait_for_styles?: boolean;
}

export interface SessionBrowserElement {
  node_id: string;
  tab_id?: string;
  frame_id?: string;
  frame_url?: string;
  role?: string;
  tag?: string;
  text?: string;
  selector?: string;
  selector_chain?: string[];
  shadow_path?: string[];
  stable_key?: string;
  interactable?: boolean;
  computed_summary?: Record<string, unknown>;
  href?: string;
  name?: string;
  input_type?: string;
  form_method?: string;
  form_action?: string;
  bounds?: { x: number; y: number; width: number; height: number };
  visible?: boolean;
}

export interface SessionBrowserAnnotation {
  id: string;
  browser_id: string;
  tab_id?: string;
  node_id: string;
  body: string;
  quote?: string;
  url?: string;
  title?: string;
  selector?: string;
  frame_id?: string;
  selector_chain?: string[];
  shadow_path?: string[];
  created_at: string;
  updated_at?: string;
}

export interface SessionBrowserTimelineEvent {
  id: string;
  browser_id: string;
  tab_id?: string;
  source: "user" | "agent" | "system";
  event_type: string;
  label: string;
  payload?: Record<string, unknown>;
  sequence?: number;
  automation_run_id?: string;
  created_at: string;
}

export interface SessionBrowserTab {
  tab_id: string;
  id?: string;
  url?: string;
  title?: string;
  runtime?: "lightpanda" | "chrome_cdp" | string;
  active?: boolean;
  is_active?: boolean;
  history?: string[];
  state?: Record<string, unknown>;
}

export interface SessionBrowserWorkspaceState {
  active_browser_id?: string;
  active_tab_id?: string;
  current_url?: string;
  current_title?: string;
  runtime?: "lightpanda" | "chrome_cdp" | string;
  last_element_map?: SessionBrowserElement[];
  cooperation?: SessionBrowserCooperationState;
}

export type SessionBrowserCooperationMode = "observe_only" | "suggest_before_action" | "agent_control";

export interface SessionBrowserCooperationState {
  enabled?: boolean;
  mode?: SessionBrowserCooperationMode;
  agent_control?: SessionBrowserCooperationMode;
  browser_id?: string;
  url?: string;
  title?: string;
  page_state?: Record<string, unknown>;
  recent_actions?: string[];
  useful_timeline?: Array<Record<string, unknown>>;
  recent_user_events?: Array<Record<string, unknown>>;
  recent_agent_events?: Array<Record<string, unknown>>;
  raw_events?: Array<Record<string, unknown>>;
  notifications?: Array<Record<string, unknown>>;
  pending_action_proposals?: Array<Record<string, unknown>>;
  policy?: Record<string, unknown>;
  last_user_activity_at?: string;
  updated_at?: string;
}

export interface SessionBrowserCooperationEvent {
  event_id?: string;
  kind: string;
  source?: "user" | "agent" | "system" | "browser";
  channel?: "event" | "action" | "proposal" | "trace";
  trace_role?: "user" | "agent" | "system" | "browser";
  visibility?: "raw" | "useful" | "debug";
  raw_kind?: string;
  timestamp?: string;
  tab_id?: string;
  page_id?: string;
  url?: string;
  target?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  coordinates?: Record<string, unknown>;
  duration_ms?: number;
  trace_effect?: "click" | "type" | "scroll" | "extract" | "highlight" | string;
  correlation_id?: string;
  importance?: "low" | "medium" | "high";
  semantic_label?: string;
}

export type SessionBrowserCooperationWsEvent =
  | {
      type: "snapshot";
      cooperation?: SessionBrowserCooperationState;
      state_patch?: { cooperation?: SessionBrowserCooperationState };
      raw_events?: Array<Record<string, unknown>>;
      useful_timeline?: Array<Record<string, unknown>>;
      recent_user_events?: Array<Record<string, unknown>>;
      recent_agent_events?: Array<Record<string, unknown>>;
      pending_action_proposals?: Array<Record<string, unknown>>;
      page_state?: Record<string, unknown>;
    }
  | {
      type: "event_batch.accepted" | "timeline.patch" | "mode.changed" | "proposal.resolved";
      cooperation?: SessionBrowserCooperationState;
      state_patch?: { cooperation?: SessionBrowserCooperationState };
      raw_events?: Array<Record<string, unknown>>;
      useful_timeline?: Array<Record<string, unknown>>;
      recent_user_events?: Array<Record<string, unknown>>;
      recent_agent_events?: Array<Record<string, unknown>>;
      proposal?: Record<string, unknown>;
      accepted_count?: number;
      dropped_count?: number;
      notifications?: Array<Record<string, unknown>>;
    }
  | { type: "proposal.created"; proposal: Record<string, unknown>; state_patch?: { cooperation?: SessionBrowserCooperationState } }
  | { type: "mode.changed"; cooperation?: SessionBrowserCooperationState; state_patch?: { cooperation?: SessionBrowserCooperationState } }
  | { type: "pong"; timestamp?: string }
  | { type: "error"; error: string };

export interface SessionBrowserSnapshot {
  document_html?: string;
  document_ref?: string;
  document_url?: string;
  preview_image_ref?: string;
  preview_image_url?: string;
  url: string;
  title: string;
  render_mode?: "screenshot" | "html_mirror" | "computed_html" | "pixel";
  runtime?: "lightpanda" | "chrome_cdp" | string;
  css_fidelity?: "pixel" | "original" | "embedded" | "computed" | "fallback_html" | string;
  fallback_reason?: string;
  render_cache_key?: string;
  render_cache_status?: "hit" | "miss" | "stored" | "stale" | string;
  style_ready?: boolean;
  stylesheet_count?: number;
  stylesheet_loaded_count?: number;
  stylesheet_cached_count?: number;
  visual_events?: Array<Record<string, unknown>>;
  tabs?: SessionBrowserTab[];
  active_tab_id?: string;
  frame_tree?: Array<Record<string, unknown>>;
  element_map?: SessionBrowserElement[];
  annotations?: SessionBrowserAnnotation[];
  timeline_events?: SessionBrowserTimelineEvent[];
  cooperation?: SessionBrowserCooperationState;
  scroll_x?: number;
  scroll_y?: number;
}

export interface SessionBrowserView {
  type: "browser_view";
  browser_id: string;
  url: string;
  title: string;
  html?: string;
  document_html?: string;
  document_ref?: string;
  document_url?: string;
  render_mode?: "screenshot" | "html_mirror" | "computed_html" | "pixel";
  runtime?: "lightpanda" | "chrome_cdp" | string;
  css_fidelity?: "pixel" | "original" | "embedded" | "computed" | "fallback_html" | string;
  fallback_reason?: string;
  render_cache_key?: string;
  render_cache_status?: "hit" | "miss" | "stored" | "stale" | string;
  style_ready?: boolean;
  stylesheet_count?: number;
  stylesheet_loaded_count?: number;
  stylesheet_cached_count?: number;
  visual_events?: Array<Record<string, unknown>>;
  tabs?: SessionBrowserTab[];
  active_tab_id?: string;
  frame_tree?: Array<Record<string, unknown>>;
  element_map?: SessionBrowserElement[];
  annotations?: SessionBrowserAnnotation[];
  timeline_events?: SessionBrowserTimelineEvent[];
  cooperation?: SessionBrowserCooperationState;
  browser_snapshot?: SessionBrowserSnapshot;
  workspace_state?: SessionBrowserWorkspaceState;
  last_action?: Record<string, unknown>;
  user_agent?: string;
  preview_image_ref?: string;
  preview_image_url?: string;
  image_data?: string;
  image_mime_type?: string;
  screenshot_method: string;
  screenshot_error?: string;
  viewport_width: number;
  viewport_height: number;
  scroll_x?: number;
  scroll_y?: number;
  can_capture: boolean;
}

export function listConversations(baseUrl: string) {
  return requestJson<ConversationSummary[]>(baseUrl, "/conversations");
}

export function getConversation(baseUrl: string, id: string) {
  return requestJson<ConversationDetail>(baseUrl, `/conversations/${id}`);
}

export function forkConversation(
  baseUrl: string,
  id: string,
  input: {
    title?: string | null;
    workspaceRoot?: string | null;
    messages: ConversationForkMessagePayload[];
  },
) {
  return requestJson<ConversationDetail>(baseUrl, `/conversations/${id}/fork`, {
    method: "POST",
    body: JSON.stringify({
      title: input.title,
      workspace_root: input.workspaceRoot,
      messages: input.messages,
    }),
  });
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

export function getSessionProjectDetail(
  baseUrl: string,
  conversationId: string,
  input: { type: string; id: string; workspaceRoot?: string | null },
) {
  const params = new URLSearchParams({ type: input.type, id: input.id });
  if (input.workspaceRoot?.trim()) params.set("workspace_root", input.workspaceRoot.trim());
  return requestJson<ProjectDetail>(baseUrl, `/sessions/${conversationId}/project/details?${params.toString()}`);
}

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
