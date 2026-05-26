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
