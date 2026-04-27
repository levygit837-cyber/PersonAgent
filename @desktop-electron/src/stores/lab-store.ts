import { create } from "zustand";
import {
  createWorkflow as createWorkflowApi,
  deleteWorkflow as deleteWorkflowApi,
  getNodeCatalog,
  getWorkflow,
  listWorkflows,
  runWorkflowStream,
  updateWorkflow,
} from "../api/client";
import { useAppStore } from "./app-store";
import {
  emptyWorkflow,
  labNodeTypes,
  newWorkflowDraft,
  nodeTypeLabel,
  type LabEdge,
  type LabGraphDocument,
  type LabNode,
  type LabNodeStatus,
  type LabNodeType,
  type NodeCatalog,
  type WorkflowRecord,
  type WorkflowRunEvent,
} from "../types/lab";
import { jsonPreview } from "../lib/utils";

interface LabState {
  workflow: WorkflowRecord;
  workflows: WorkflowRecord[];
  catalog: NodeCatalog;
  isLoading: boolean;
  isSaving: boolean;
  isRunning: boolean;
  error?: string;
  connectingFromNodeId?: string;
  runController?: AbortController;
  initialize: () => Promise<void>;
  refresh: () => Promise<void>;
  createWorkflow: () => Promise<void>;
  loadWorkflow: (id: string) => Promise<void>;
  deleteWorkflow: (id: string) => Promise<void>;
  saveGraph: () => Promise<void>;
  runWorkflow: () => Promise<void>;
  stopWorkflow: () => void;
  selectNode: (id: string) => void;
  addNode: (type: LabNodeType) => void;
  moveNode: (id: string, x: number, y: number) => void;
  deleteSelectedNode: () => void;
  updateSelectedNode: (patch: Partial<Pick<LabNode, "title" | "description" | "output_kind" | "config" | "tools" | "perks">>) => void;
  startConnection: (nodeId: string) => void;
  finishConnection: (nodeId: string) => void;
}

export const useLabStore = create<LabState>((set, get) => ({
  workflow: emptyWorkflow(),
  workflows: [],
  catalog: {},
  isLoading: false,
  isSaving: false,
  isRunning: false,

  initialize: async () => {
    if (get().workflows.length > 0 || get().isLoading) return;
    await get().refresh();
  },

  refresh: async () => {
    set({ isLoading: true, error: undefined });
    try {
      const baseUrl = useAppStore.getState().baseUrl;
      const [workflows, catalog] = await Promise.all([listWorkflows(baseUrl), getNodeCatalog(baseUrl)]);
      set({
        workflows,
        catalog,
        workflow: workflows[0] ?? emptyWorkflow(),
        isLoading: false,
      });
    } catch (error) {
      set({ isLoading: false, error: error instanceof Error ? error.message : String(error) });
    }
  },

  createWorkflow: async () => {
    set({ isSaving: true, error: undefined });
    try {
      const created = await createWorkflowApi(useAppStore.getState().baseUrl, "Untitled Workflow", newWorkflowDraft());
      set((state) => ({
        workflow: created,
        workflows: [created, ...state.workflows.filter((item) => item.id !== created.id)],
        isSaving: false,
      }));
    } catch (error) {
      set({ isSaving: false, error: error instanceof Error ? error.message : String(error) });
    }
  },

  loadWorkflow: async (id) => {
    set({ isLoading: true, error: undefined });
    try {
      const workflow = await getWorkflow(useAppStore.getState().baseUrl, id);
      set({ workflow, isLoading: false });
    } catch (error) {
      set({ isLoading: false, error: error instanceof Error ? error.message : String(error) });
    }
  },

  deleteWorkflow: async (id) => {
    if (get().isRunning) return;
    try {
      await deleteWorkflowApi(useAppStore.getState().baseUrl, id);
      set((state) => {
        const workflows = state.workflows.filter((item) => item.id !== id);
        return {
          workflows,
          workflow: state.workflow.id === id ? workflows[0] ?? emptyWorkflow() : state.workflow,
        };
      });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },

  saveGraph: async () => {
    const current = get().workflow;
    if (current.id.startsWith("local_")) {
      set({ isSaving: true, error: undefined });
      try {
        const created = await createWorkflowApi(useAppStore.getState().baseUrl, current.title || "Untitled Workflow", current.workflow);
        set((state) => ({
          workflow: created,
          workflows: [created, ...state.workflows],
          isSaving: false,
        }));
      } catch (error) {
        set({ isSaving: false, error: error instanceof Error ? error.message : String(error) });
      }
      return;
    }

    set({ isSaving: true, error: undefined });
    try {
      const saved = await updateWorkflow(useAppStore.getState().baseUrl, current.id, current.title, current.workflow);
      set((state) => ({
        workflow: saved,
        workflows: [saved, ...state.workflows.filter((item) => item.id !== saved.id)],
        isSaving: false,
      }));
    } catch (error) {
      set({ isSaving: false, error: error instanceof Error ? error.message : String(error) });
    }
  },

  runWorkflow: async () => {
    if (get().isRunning) return;
    if (get().workflow.id.startsWith("local_")) {
      await get().saveGraph();
    } else {
      await get().saveGraph();
    }
    const workflow = get().workflow;
    if (workflow.id.startsWith("local_")) return;

    const controller = new AbortController();
    set((state) => ({
      isRunning: true,
      runController: controller,
      workflow: {
        ...state.workflow,
        workflow: {
          ...state.workflow.workflow,
          execution_state: { mode: "running" },
          trace_events: [trace("workflow_run_started", "Workflow run started.")],
          nodes: state.workflow.workflow.nodes.map((node) => ({ ...node, status: "queued", progress: 0 })),
          edges: state.workflow.workflow.edges.map((edge) => ({ ...edge, status: "queued" })),
        },
      },
    }));

    try {
      const selectedWorkspace = useAppStore.getState().selectedWorkspace;
      const toolContext = selectedWorkspace
        ? {
            workspace_root: selectedWorkspace,
            cwd: selectedWorkspace,
            allowed_roots: [selectedWorkspace],
          }
        : {};
      for await (const event of runWorkflowStream(
        useAppStore.getState().baseUrl,
        workflow.id,
        "",
        toolContext,
        controller.signal,
      )) {
        applyRunEvent(event, set);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        set({ error: error instanceof Error ? error.message : String(error) });
      }
    } finally {
      set((state) => ({
        isRunning: false,
        runController: undefined,
        workflow: {
          ...state.workflow,
          workflow: {
            ...state.workflow.workflow,
            execution_state: { mode: "idle" },
          },
        },
      }));
    }
  },

  stopWorkflow: () => {
    get().runController?.abort();
    set((state) => ({
      isRunning: false,
      runController: undefined,
      workflow: {
        ...state.workflow,
        workflow: { ...state.workflow.workflow, execution_state: { mode: "idle" } },
      },
    }));
  },

  selectNode: (id) => {
    set((state) => ({
      workflow: {
        ...state.workflow,
        workflow: { ...state.workflow.workflow, selected_node_id: id },
      },
    }));
  },

  addNode: (type) => {
    if (get().isRunning) return;
    set((state) => {
      const node = nodeForType(type, state.workflow.workflow.nodes.length + 1, state.workflow.workflow.viewport);
      return {
        workflow: {
          ...state.workflow,
          workflow: {
            ...state.workflow.workflow,
            nodes: [...state.workflow.workflow.nodes, node],
            selected_node_id: node.id,
          },
        },
      };
    });
  },

  moveNode: (id, x, y) => {
    if (get().isRunning) return;
    set((state) => ({
      workflow: {
        ...state.workflow,
        workflow: {
          ...state.workflow.workflow,
          nodes: state.workflow.workflow.nodes.map((node) => (node.id === id ? { ...node, x, y } : node)),
        },
      },
    }));
  },

  deleteSelectedNode: () => {
    const selectedId = get().workflow.workflow.selected_node_id;
    if (!selectedId || get().isRunning) return;
    set((state) => {
      const nodes = state.workflow.workflow.nodes.filter((node) => node.id !== selectedId);
      const edges = state.workflow.workflow.edges.filter(
        (edge) => edge.from_node_id !== selectedId && edge.to_node_id !== selectedId,
      );
      return {
        workflow: {
          ...state.workflow,
          workflow: {
            ...state.workflow.workflow,
            nodes,
            edges,
            selected_node_id: nodes[0]?.id ?? "",
          },
        },
      };
    });
  },

  updateSelectedNode: (patch) => {
    const selectedId = get().workflow.workflow.selected_node_id;
    if (!selectedId || get().isRunning) return;
    set((state) => ({
      workflow: {
        ...state.workflow,
        workflow: {
          ...state.workflow.workflow,
          nodes: state.workflow.workflow.nodes.map((node) =>
            node.id === selectedId
              ? {
                  ...node,
                  ...patch,
                  output_contract: patch.output_kind
                    ? { ...node.output_contract, kind: patch.output_kind }
                    : node.output_contract,
                }
              : node,
          ),
        },
      },
    }));
  },

  startConnection: (nodeId) => {
    if (get().isRunning) return;
    set((state) => ({
      connectingFromNodeId: nodeId,
      workflow: {
        ...state.workflow,
        workflow: { ...state.workflow.workflow, selected_node_id: nodeId },
      },
    }));
  },

  finishConnection: (nodeId) => {
    const fromNodeId = get().connectingFromNodeId;
    if (!fromNodeId || fromNodeId === nodeId || get().isRunning) {
      set({ connectingFromNodeId: undefined });
      return;
    }
    set((state) => {
      const fromNode = state.workflow.workflow.nodes.find((node) => node.id === fromNodeId);
      if (!fromNode) return { connectingFromNodeId: undefined };
      const fromHandle = nextHandleForConnection(fromNode, state.workflow.workflow.edges);
      const retainedEdges = state.workflow.workflow.edges.filter((edge) => {
        if (edge.from_node_id !== fromNodeId) return true;
        if (fromNode.type === "if_else") return edge.from_handle !== fromHandle;
        return false;
      });
      const edge: LabEdge = {
        id: `edge_${fromNodeId}_${fromHandle}_${nodeId}`,
        from_node_id: fromNodeId,
        to_node_id: nodeId,
        from_handle: fromHandle,
        to_handle: "in",
        status: "queued",
        label: fromHandle === "out" ? "manual" : fromHandle,
      };
      return {
        connectingFromNodeId: undefined,
        workflow: {
          ...state.workflow,
          workflow: {
            ...state.workflow.workflow,
            edges: [...retainedEdges, edge],
            selected_node_id: nodeId,
          },
        },
      };
    });
  },
}));

function applyRunEvent(
  event: WorkflowRunEvent,
  set: (partial: LabState | Partial<LabState> | ((state: LabState) => LabState | Partial<LabState>)) => void,
) {
  const eventName = event.event ?? "event";
  const nodeId = typeof event.node_id === "string" ? event.node_id : undefined;
  const message =
    stringValue(event.error) ??
    stringValue(event.tool_message) ??
    stringValue(event.output_preview) ??
    stringValue(event.node_title) ??
    eventName;

  if (eventName === "edge_selected") {
    const edgeId = stringValue(event.edge_id);
    set((state) => ({
      workflow: {
        ...state.workflow,
        workflow: {
          ...state.workflow.workflow,
          edges: state.workflow.workflow.edges.map((edge) =>
            edge.id === edgeId ? { ...edge, status: "completed" } : edge,
          ),
          trace_events: [...state.workflow.workflow.trace_events, trace(eventName, `Selected edge ${edgeId ?? ""}.`)],
        },
      },
    }));
    return;
  }

  const status = statusFromRunEvent(eventName);
  set((state) => ({
    error: eventName === "node_error" ? message : state.error,
    workflow: {
      ...state.workflow,
      workflow: {
        ...state.workflow.workflow,
        selected_node_id: nodeId ?? state.workflow.workflow.selected_node_id,
        nodes: state.workflow.workflow.nodes.map((node) =>
          node.id === nodeId
            ? {
                ...node,
                status,
                progress: status === "completed" ? 1 : 0.58,
                output_preview: stringValue(event.output_preview) ?? node.output_preview,
                last_output: Object.prototype.hasOwnProperty.call(event, "output")
                  ? jsonPreview(event.output)
                  : node.last_output,
              }
            : node,
        ),
        trace_events: [
          ...state.workflow.workflow.trace_events,
          trace(eventName, message, nodeId, status),
        ],
      },
    },
  }));
}

function statusFromRunEvent(eventName: string): LabNodeStatus {
  if (eventName === "node_started" || eventName === "tool_call_started" || eventName === "tool_progress") {
    return "running";
  }
  if (eventName === "node_error" || eventName === "tool_error" || eventName === "permission_required") {
    return "error";
  }
  if (eventName === "node_completed" || eventName === "workflow_run_completed" || eventName === "tool_result") {
    return "completed";
  }
  return "queued";
}

function trace(event: string, message: string, nodeId?: string, status: LabNodeStatus = "queued") {
  const now = new Date();
  return {
    id: `${now.getTime()}_${event}_${Math.random().toString(16).slice(2)}`,
    event,
    message,
    node_id: nodeId,
    timestamp: now.toISOString(),
    status,
  };
}

function nodeForType(type: LabNodeType, index: number, viewport: { x: number; y: number }) {
  const centerX = viewport.x || 760;
  const centerY = viewport.y || 360;
  const lane = index % 4;
  const x = centerX - 120 + (lane - 1.5) * 58;
  const y = centerY - 63 + (((Math.floor(index / 4) % 3) - 1) * 52);
  const outputKind = outputKindForType(type);
  const node: LabNode = {
    id: `node_${Date.now()}`,
    type,
    title: nodeTypeLabel(type),
    description: descriptionForType(type),
    x,
    y,
    width: type === "output" ? 260 : 240,
    height: 126,
    status: "queued",
    progress: 0,
    output_kind: outputKind,
    output_preview: "No run output yet.",
    last_output: "",
    config: configForType(type),
    input_contract: { kind: "any" },
    output_contract: { kind: outputKind },
    tools: [],
    perks: {},
  };
  return node;
}

function configForType(type: LabNodeType): Record<string, unknown> {
  if (type === "agent") return { instructions: "Describe what this agent should do." };
  if (type === "if_else") {
    return {
      condition: "Choose whether the previous output should use then or else.",
      then_goal: "The objective matches the expected route.",
      else_goal: "The objective does not match the expected route.",
    };
  }
  if (type === "tool") {
    return {
      tool_name: "",
      arguments: {},
      use_previous_output_as_arguments: true,
    };
  }
  if (type === "schema_validator") {
    return {
      schema: { type: "object", properties: {}, required: [] },
    };
  }
  if (type === "artifact_transform") return { format: "markdown", title: "Workflow Artifact" };
  return {};
}

function descriptionForType(type: LabNodeType) {
  return labNodeTypes.find((item) => item.value === type)?.label ?? "Workflow node";
}

function outputKindForType(type: LabNodeType) {
  const map: Record<LabNodeType, string> = {
    trigger: "payload",
    agent: "text",
    if_else: "route",
    output: "artifact_bundle",
    browser: "browser_state",
    tool: "tool_result",
    schema_validator: "json_schema",
    memory: "memory_record",
    human_approval: "approval",
    queue_delay: "queue_receipt",
    subworkflow: "workflow_output",
    artifact_transform: "artifact",
  };
  return map[type];
}

function nextHandleForConnection(fromNode: LabNode, edges: LabEdge[]) {
  if (fromNode.type !== "if_else") return "out";
  const existing = new Set(edges.filter((edge) => edge.from_node_id === fromNode.id).map((edge) => edge.from_handle));
  if (!existing.has("then")) return "then";
  if (!existing.has("else")) return "else";
  return "then";
}

function stringValue(value: unknown) {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length ? trimmed : undefined;
}
