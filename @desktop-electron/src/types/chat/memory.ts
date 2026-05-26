export interface MemoryTraceClassicItem {
  path?: string;
  name?: string;
  header?: string;
  mtime_ms?: number;
  snippet?: string;
}

export interface MemoryTraceOperationalItem {
  type?: string;
  summary?: string;
  evidence?: string[];
  paths?: string[];
  source_ids?: string[];
  event_types?: string[];
  score?: number;
  status?: string;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface MemoryTraceSummary {
  total_used: number;
  classic_count: number;
  rag_count: number;
  omitted_count: number;
  budget_used: number;
  budget_tokens: number;
  latency_ms: number;
}

export interface MemoryTrace {
  classic: MemoryTraceClassicItem[];
  operational: MemoryTraceOperationalItem[];
  summary: MemoryTraceSummary;
  filters_applied?: Record<string, unknown>;
  prompt?: {
    formatted?: string;
    truncated?: boolean;
  };
}

export interface SessionMemoryTopItem {
  id: string;
  source: "classic" | "rag" | string;
  label: string;
  count: number;
  paths: string[];
  evidence: string[];
  messages: string[];
}

export interface SessionMemorySummary {
  total_recalls: number;
  rag_used: number;
  classic_used: number;
  omitted: number;
  avg_latency_ms: number;
  budget_used: number;
  budget_tokens: number;
  most_used: SessionMemoryTopItem[];
}
