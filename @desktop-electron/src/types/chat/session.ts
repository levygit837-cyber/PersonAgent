import type { SessionMemorySummary } from "./memory";

export interface SessionUsageMetric {
  value: number;
  estimated: boolean;
}

export interface SessionUsage {
  context_tokens: SessionUsageMetric;
  agent_output_tokens: SessionUsageMetric;
  thinking_output_tokens: SessionUsageMetric;
  tool_calls: SessionUsageMetric;
  skills_used_count: SessionUsageMetric;
  mcp_calls_count: SessionUsageMetric;
  plans_created: SessionUsageMetric;
  todos_created: SessionUsageMetric;
  subagents_used: SessionUsageMetric;
}

export interface ChangedFile {
  id: string;
  path: string;
  display_path: string;
  added_lines: number;
  removed_lines: number;
  source: string;
  status: string;
  diff?: string;
  content?: string;
}

export interface SessionSource {
  id: string;
  title: string;
  description: string;
  url: string;
  domain: string;
  favicon_url: string;
  tool_name: string;
}

export interface ProjectItem {
  id: string;
  type: "commit" | "push" | "pr" | "branch" | string;
  title: string;
  subtitle?: string;
  timestamp?: string | null;
  url?: string | null;
  active?: boolean;
  metadata?: Record<string, unknown>;
}

export interface SessionProjectSnapshot {
  repo?: {
    name_with_owner?: string | null;
    url?: string | null;
    default_branch?: string | null;
    pushed_at?: string | null;
    source?: string;
  } | null;
  prs: ProjectItem[];
  branches: ProjectItem[];
  pushes: ProjectItem[];
  commits: ProjectItem[];
  errors: string[];
}

export interface ProjectDetail {
  type: string;
  id: string;
  title: string;
  url?: string | null;
  metadata?: Record<string, unknown>;
  files?: Array<Record<string, unknown>>;
  commits?: Array<Record<string, unknown>>;
  patch?: string;
  source?: string;
  error?: string | null;
}

export interface SessionPanelSnapshot {
  conversation_id: string;
  title: string;
  updated_at: string;
  changed_files: ChangedFile[];
  sources: SessionSource[];
  usage: SessionUsage;
  memory?: SessionMemorySummary;
  project: SessionProjectSnapshot;
}

export function emptySessionUsage(): SessionUsage {
  return {
    context_tokens: { value: 0, estimated: false },
    agent_output_tokens: { value: 0, estimated: false },
    thinking_output_tokens: { value: 0, estimated: false },
    tool_calls: { value: 0, estimated: false },
    skills_used_count: { value: 0, estimated: false },
    mcp_calls_count: { value: 0, estimated: false },
    plans_created: { value: 0, estimated: false },
    todos_created: { value: 0, estimated: false },
    subagents_used: { value: 0, estimated: false },
  };
}
