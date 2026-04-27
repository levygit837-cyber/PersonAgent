export type LabNodeType =
  | "trigger"
  | "agent"
  | "if_else"
  | "output"
  | "browser"
  | "tool"
  | "schema_validator"
  | "memory"
  | "human_approval"
  | "queue_delay"
  | "subworkflow"
  | "artifact_transform";

export type LabNodeStatus = "queued" | "running" | "completed" | "error" | "warning";
export type LabRunMode = "idle" | "running";

export const labNodeTypes: Array<{ value: LabNodeType; label: string }> = [
  { value: "trigger", label: "Trigger" },
  { value: "agent", label: "Agent Node" },
  { value: "if_else", label: "If/Else Node" },
  { value: "output", label: "Output Node" },
  { value: "browser", label: "Browser Node" },
  { value: "tool", label: "Tool Node" },
  { value: "schema_validator", label: "Schema Validator" },
  { value: "memory", label: "Memory Node" },
  { value: "human_approval", label: "Human Approval" },
  { value: "queue_delay", label: "Queue Delay" },
  { value: "subworkflow", label: "Subworkflow" },
  { value: "artifact_transform", label: "Artifact Transform" },
];

export function nodeTypeLabel(type: LabNodeType) {
  return labNodeTypes.find((item) => item.value === type)?.label ?? "Node";
}

export interface LabViewport {
  x: number;
  y: number;
  zoom: number;
}

export interface LabExecutionState {
  mode: LabRunMode;
  current_node_id?: string;
}

export interface LabNode {
  id: string;
  type: LabNodeType;
  title: string;
  description: string;
  x: number;
  y: number;
  width: number;
  height: number;
  status: LabNodeStatus;
  progress: number;
  output_kind: string;
  output_preview: string;
  last_output: string;
  config: Record<string, unknown>;
  input_contract: Record<string, unknown>;
  output_contract: Record<string, unknown>;
  tools: string[];
  perks: Record<string, unknown>;
}

export interface LabEdge {
  id: string;
  from_node_id: string;
  to_node_id: string;
  from_handle: string;
  to_handle: string;
  status: LabNodeStatus;
  label: string;
}

export interface LabTraceEvent {
  id: string;
  event: string;
  message: string;
  node_id?: string;
  timestamp: string;
  status: LabNodeStatus;
}

export interface LabGraphDocument {
  schema_version: string;
  viewport: LabViewport;
  selected_node_id: string;
  execution_state: LabExecutionState;
  nodes: LabNode[];
  edges: LabEdge[];
  trace_events: LabTraceEvent[];
}

export interface WorkflowRecord {
  id: string;
  title: string;
  workflow: LabGraphDocument;
  created_at: string;
  updated_at: string;
}

export interface NodeCatalog {
  schema_version?: string;
  supported_perks?: string[];
  unsupported_perks?: string[];
  tools?: Array<Record<string, unknown>>;
  node_types?: Array<{
    type: LabNodeType;
    label: string;
    description?: string;
    executable?: boolean;
    future?: boolean;
    outputs?: string[];
    perks?: string[];
    config_schema?: Record<string, unknown>;
  }>;
}

export interface WorkflowRunEvent {
  event?: string;
  node_id?: string;
  node_title?: string;
  edge_id?: string;
  output_preview?: string;
  output?: unknown;
  error?: string;
  tool_message?: string;
  status?: number;
  [key: string]: unknown;
}

export function emptyWorkflow(): WorkflowRecord {
  return {
    id: "local_empty",
    title: "No workflow selected",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    workflow: {
      schema_version: "1.0",
      viewport: { x: 0, y: 0, zoom: 0.72 },
      selected_node_id: "",
      execution_state: { mode: "idle" },
      nodes: [],
      edges: [],
      trace_events: [],
    },
  };
}

export function newWorkflowDraft(): LabGraphDocument {
  return {
    schema_version: "1.0",
    viewport: { x: 0, y: 0, zoom: 0.72 },
    selected_node_id: "trigger",
    execution_state: { mode: "idle" },
    trace_events: [],
    nodes: [
      {
        id: "trigger",
        type: "trigger",
        title: "Trigger",
        description: "Starts the workflow from a run payload or on a schedule.",
        x: 80,
        y: 260,
        width: 240,
        height: 126,
        status: "queued",
        progress: 0,
        output_kind: "payload",
        output_preview: "Awaiting run payload.",
        last_output: "",
        config: {},
        input_contract: { kind: "any" },
        output_contract: { kind: "payload" },
        tools: [],
        perks: {},
      },
      {
        id: "output",
        type: "output",
        title: "Final Output",
        description: "Collects the final workflow output.",
        x: 390,
        y: 260,
        width: 260,
        height: 126,
        status: "queued",
        progress: 0,
        output_kind: "artifact_bundle",
        output_preview: "Awaiting upstream output.",
        last_output: "",
        config: {},
        input_contract: { kind: "any" },
        output_contract: { kind: "artifact_bundle" },
        tools: [],
        perks: {},
      },
    ],
    edges: [
      {
        id: "edge_trigger_output",
        from_node_id: "trigger",
        to_node_id: "output",
        from_handle: "out",
        to_handle: "in",
        status: "queued",
        label: "",
      },
    ],
  };
}
