import type { ModelProvider, ReasoningPreset, PromptMode } from "./models";
import type { TeamTraceEventUi, TeamRunUi } from "./teams";
import type { ToolBlockStatus, ToolBlockUi } from "./tools";

export type PersistedMessageRole = "system" | "user" | "assistant" | "tool";

export interface PersistedMessage {
  id?: string;
  role: PersistedMessageRole;
  content: string;
  reasoning_content?: string;
  timestamp?: string;
  tool_call_id?: string;
  metadata?: Record<string, unknown>;
}

export interface GeneratedImage {
  mime_type: string;
  data?: string;
  alt?: string;
  artifact_id?: string;
  url?: string;
  size_bytes?: number;
  sha256?: string;
}

export type ConversationStatus = "idle" | "error" | "pending" | "running";

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  workspace_root?: string | null;
  status?: ConversationStatus | null;
}

export interface ConversationDetail {
  id: string;
  title: string;
  messages: PersistedMessage[];
  created_at: string;
  updated_at: string;
}

export interface ChatRequestPayload {
  conversation_id?: string;
  message: string;
  system_prompt?: string;
  stream: true;
  temperature: number;
  max_tokens: number;
  provider: ModelProvider;
  model: string;
  prompt_mode: PromptMode;
  reasoning_level: ReasoningPreset;
  reasoning_budget_tokens: number | null;
  max_tool_iterations?: number | null;
  workspace_root?: string;
  tool_context?: {
    workspace_root: string;
    cwd: string;
    allowed_roots: string[];
    permission_mode?: string;
  };
  context_attachments?: ContextAttachment[];
  plan_mode_requested?: boolean;
}

export type ContextAttachmentType =
  | "file_range"
  | "file"
  | "directory"
  | "skill"
  | "mcp_resource"
  | "terminal_output"
  | "browser_annotation"
  | "browser_tab"
  | "viewer_annotation"
  | "command_context";

export interface ContextAttachment {
  type: ContextAttachmentType;
  id?: string | number;
  label?: string;
  file_name?: string;
  file_path?: string;
  display_path?: string;
  start_line?: number;
  end_line?: number;
  language?: string;
  text?: string;
  shell?: string;
  content?: string;
  content_preview?: string;
  content_char_count?: number;
  url?: string;
  title?: string;
  node_id?: string;
  selector?: string;
  role?: string;
  quote?: string;
  browser_id?: string;
  tab_id?: string;
  page_id?: string;
  window_id?: string;
  active?: boolean;
  is_active?: boolean;
  runtime?: string;
  scroll?: Record<string, unknown>;
  viewport?: Record<string, unknown>;
  selected_element?: Record<string, unknown>;
  state?: Record<string, unknown>;
  directory_path?: string;
  entry_count?: number;
  name?: string;
  invocation_name?: string;
  slash_name?: string;
  description?: string;
  path?: string;
  source?: string;
  server?: string;
  uri?: string;
  command?: string;
  truncated?: boolean;
  [key: string]: unknown;
}

export interface ChatCommandInfo {
  name: string;
  slash_name: string;
  description: string;
  argument_hint?: string | null;
  source: "command" | "skill" | string;
  path: string;
  user_invocable: boolean;
  should_query?: boolean;
  ui_action?: string | null;
}

export interface SkillSummary {
  name: string;
  invocation_name: string;
  slash_name: string;
  description: string;
  source: string;
  path: string;
  enabled: boolean;
  user_invocable: boolean;
  model_invocable: boolean;
  allowed_tools: string[];
  argument_hint?: string | null;
  when_to_use?: string | null;
  context: string;
}

export interface SkillDetail extends SkillSummary {
  content: string;
  frontmatter: Record<string, unknown>;
}

export interface SkillMarketplaceItem {
  id: string;
  name: string;
  invocation_name: string;
  slash_name: string;
  description: string;
  allowed_tools: string[];
  argument_hint?: string | null;
  when_to_use?: string | null;
  installed: boolean;
}

export type MessageRoleUi = "user" | "agent" | "tool";
export type ChatMessagePartKind = "reasoning" | "content" | "tool" | "image";

export interface ChatTodoItemUi {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export interface TodoDockSnapshotUi {
  key: string;
  toolName: string;
  updateCount: number;
  status: ToolBlockStatus;
  todos: ChatTodoItemUi[];
}

export interface ChatMessagePartUi {
  kind: ChatMessagePartKind;
  id: string;
  content?: string;
  image?: GeneratedImage;
  reasoningBlockId?: string;
  toolBlockId?: string;
}

export interface ReasoningBlockUi {
  id: string;
  content: string;
  isStreaming: boolean;
  userExpanded?: boolean;
}

export interface ChatMessageUi {
  id: string;
  role: MessageRoleUi;
  label: string;
  content: string;
  reasoning: string;
  reasoningBlocks: ReasoningBlockUi[];
  toolBlocks: ToolBlockUi[];
  teamEvents: TeamTraceEventUi[];
  teamRun?: TeamRunUi;
  parts: ChatMessagePartUi[];
  isStreaming: boolean;
  isReasoningStreaming: boolean;
  metadata?: Record<string, unknown>;
}
