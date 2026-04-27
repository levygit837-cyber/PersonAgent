import { useCallback, useMemo } from "react";
import type { ReactNode } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { Plus, Save, Square, Trash2, Play, X } from "lucide-react";
import { useLabStore } from "../../stores/lab-store";
import { labNodeTypes, nodeTypeLabel, type LabNode, type LabNodeType } from "../../types/lab";
import { jsonPreview } from "../../lib/utils";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

const nodeTypes = {
  labNode: LabNodeCard,
};

type LabFlowData = LabNode & Record<string, unknown>;
type LabFlowNode = Node<LabFlowData>;

export function LabWorkspace() {
  return (
    <ReactFlowProvider>
      <LabWorkspaceInner />
    </ReactFlowProvider>
  );
}

function LabWorkspaceInner() {
  const workflow = useLabStore((state) => state.workflow);
  const isRunning = useLabStore((state) => state.isRunning);
  const error = useLabStore((state) => state.error);
  const selectNode = useLabStore((state) => state.selectNode);
  const moveNode = useLabStore((state) => state.moveNode);
  const startConnection = useLabStore((state) => state.startConnection);
  const finishConnection = useLabStore((state) => state.finishConnection);

  const nodes: LabFlowNode[] = useMemo(
    () =>
      workflow.workflow.nodes.map((node) => ({
        id: node.id,
        type: "labNode",
        position: { x: node.x, y: node.y },
        data: node as LabFlowData,
        selected: workflow.workflow.selected_node_id === node.id,
        style: { width: node.width, height: node.height },
      })),
    [workflow.workflow.nodes, workflow.workflow.selected_node_id],
  );

  const edges: Edge[] = useMemo(
    () =>
      workflow.workflow.edges.map((edge) => ({
        id: edge.id,
        source: edge.from_node_id,
        target: edge.to_node_id,
        sourceHandle: edge.from_handle,
        targetHandle: edge.to_handle,
        label: edge.label,
        animated: edge.status === "running",
        style: {
          stroke:
            edge.status === "completed"
              ? "hsl(var(--success))"
              : edge.status === "error"
                ? "hsl(var(--destructive))"
                : "hsl(var(--border))",
        },
      })),
    [workflow.workflow.edges],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      startConnection(connection.source);
      finishConnection(connection.target);
    },
    [finishConnection, startConnection],
  );

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-background">
      <LabToolbar />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="relative min-w-0 flex-1">
          <ReactFlow<LabFlowNode, Edge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            minZoom={0.35}
            maxZoom={1.45}
            fitView
            onNodeClick={(_, node) => selectNode(node.id)}
            onNodeDragStop={(_, node) => moveNode(node.id, node.position.x, node.position.y)}
            onConnect={onConnect}
            className="app-grid"
          >
            <Background color="hsl(var(--glass-border) / 0.55)" gap={32} />
            <Controls className="rounded-xl border border-glass-border/35 bg-card/90 text-foreground shadow-soft" />
            <MiniMap
              pannable
              zoomable
              maskColor="rgba(0, 0, 0, 0.6)"
              nodeColor={(node) => {
                const data = node.data as unknown as LabNode;
                if (data.status === "completed") return "hsl(142, 53%, 55%)";
                if (data.status === "running") return "hsl(250, 60%, 65%)";
                if (data.status === "error") return "hsl(0, 72%, 60%)";
                return "hsl(220, 8%, 46%)";
              }}
              className="rounded-xl border border-glass-border/35 bg-card/90 shadow-soft"
            />
          </ReactFlow>
          <ExecutionTrace />
          {error ? (
            <div className="absolute left-5 right-5 top-5 rounded-xl border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive shadow-soft">
              {error}
            </div>
          ) : null}
          {isRunning ? (
            <div className="absolute right-5 top-5 rounded-xl border border-primary/25 bg-primary/10 px-3 py-1.5 font-mono text-[10px] uppercase text-primary shadow-soft">
              Engine running
            </div>
          ) : null}
        </div>
        <NodeInspector />
      </div>
    </section>
  );
}

function LabToolbar() {
  const workflow = useLabStore((state) => state.workflow);
  const isSaving = useLabStore((state) => state.isSaving);
  const isRunning = useLabStore((state) => state.isRunning);
  const saveGraph = useLabStore((state) => state.saveGraph);
  const runWorkflow = useLabStore((state) => state.runWorkflow);
  const stopWorkflow = useLabStore((state) => state.stopWorkflow);
  const addNode = useLabStore((state) => state.addNode);

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-glass-border/25 bg-background px-5">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-foreground">Workflows</div>
        <div className="truncate font-mono text-[10px] uppercase text-primary">{workflow.title}</div>
      </div>
      <div className="rounded-xl border border-glass-border/35 bg-card/70 px-2.5 py-1.5 font-mono text-[10px] uppercase text-muted-foreground shadow-soft">
        {isRunning ? "Running" : "Idle"}
      </div>
      <Button variant="outline" size="sm" disabled={isSaving} onClick={() => void saveGraph()}>
        <Save className="h-4 w-4" />
        {isSaving ? "Saving" : "Save"}
      </Button>
      <Button variant={isRunning ? "destructive" : "default"} size="sm" onClick={() => (isRunning ? stopWorkflow() : void runWorkflow())}>
        {isRunning ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        {isRunning ? "Stop" : "Run Flow"}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" disabled={isRunning}>
            <Plus className="h-4 w-4" />
            Add Node
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {labNodeTypes.map((type) => (
            <DropdownMenuItem key={type.value} onClick={() => addNode(type.value)}>
              {type.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}

function LabNodeCard({ data, selected }: NodeProps<LabFlowNode>) {
  const selectNode = useLabStore((state) => state.selectNode);
  const statusColor =
    data.status === "completed"
      ? "bg-success"
      : data.status === "running"
        ? "bg-primary"
        : data.status === "error"
          ? "bg-destructive"
          : "bg-muted-foreground";

  return (
    <button
      type="button"
      onClick={() => selectNode(data.id)}
      className={
        selected
          ? "relative h-full w-full rounded-2xl border border-primary/50 bg-card/90 p-3 text-left shadow-[0_0_0_4px_hsl(var(--primary)_/_0.13),0_18px_36px_rgb(0_0_0_/_0.28)]"
          : "relative h-full w-full rounded-2xl border border-glass-border/35 bg-card/80 p-3 text-left shadow-soft hover:border-glass-border/50 hover:bg-glass/70"
      }
    >
      <Handle type="target" position={Position.Left} id="in" className="!h-2 !w-2 !border-primary !bg-background" />
      <Handle type="source" position={Position.Right} id="out" className="!h-2 !w-2 !border-primary !bg-background" />
      {data.type === "if_else" ? (
        <>
          <Handle type="source" position={Position.Bottom} id="then" className="!left-[35%] !h-2 !w-2 !border-success !bg-background" />
          <Handle type="source" position={Position.Bottom} id="else" className="!left-[65%] !h-2 !w-2 !border-warning !bg-background" />
        </>
      ) : null}
      <div className="mb-2 flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${statusColor}`} />
        <span className="truncate text-xs font-semibold text-foreground">{data.title}</span>
        <span className="ml-auto rounded-lg border border-glass-border/30 px-1.5 font-mono text-[9px] uppercase text-muted-foreground">
          {data.status}
        </span>
      </div>
      <div className="line-clamp-2 text-[11px] leading-5 text-muted-foreground">{data.description}</div>
      <div className="mt-2 truncate rounded-xl border border-glass-border/30 bg-background/70 px-2 py-1 font-mono text-[10px] text-muted-foreground">
        {data.output_preview || data.output_kind}
      </div>
    </button>
  );
}

function NodeInspector() {
  const workflow = useLabStore((state) => state.workflow);
  const selected = workflow.workflow.nodes.find((node) => node.id === workflow.workflow.selected_node_id);
  const updateSelectedNode = useLabStore((state) => state.updateSelectedNode);
  const deleteSelectedNode = useLabStore((state) => state.deleteSelectedNode);
  const selectNode = useLabStore((state) => state.selectNode);
  const isRunning = useLabStore((state) => state.isRunning);

  return (
    <aside className="hidden w-[340px] shrink-0 overflow-y-auto border-l border-glass-border/25 bg-card xl:block">
      <div className="flex items-center justify-between border-b border-glass-border/25 p-4">
        <div>
          <div className="text-sm font-semibold text-foreground">{selected ? selected.title : "Node Inspector"}</div>
          <div className="font-mono text-[10px] uppercase text-muted-foreground">
            {selected ? nodeTypeLabel(selected.type as LabNodeType) : "Select a node"}
          </div>
        </div>
        {selected && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              selectNode("");
            }}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl border border-glass-border/35 bg-card/80 text-muted-foreground transition-colors hover:border-glass-border/50 hover:bg-glass/80 hover:text-foreground"
            title="Close inspector"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      {selected ? (
        <div className="space-y-5 p-4">
          <Field label="Title">
            <input
              value={selected.title}
              disabled={isRunning}
              onChange={(event) => updateSelectedNode({ title: event.currentTarget.value })}
              className="h-9 w-full rounded-xl border border-glass-border/35 bg-card/80 px-3 text-sm text-foreground outline-none shadow-soft focus:ring-2 focus:ring-ring/25 disabled:opacity-50"
            />
          </Field>
          <Field label="Description / Instructions">
            <Textarea
              value={selected.description}
              disabled={isRunning}
              onChange={(event) =>
                updateSelectedNode({
                  description: event.currentTarget.value,
                  config:
                    selected.type === "agent"
                      ? { ...selected.config, instructions: event.currentTarget.value }
                      : selected.config,
                })
              }
              className="min-h-28"
            />
          </Field>
          <Field label="Config JSON">
            <Textarea
              value={jsonPreview(selected.config)}
              disabled={isRunning}
              onChange={(event) => {
                const next = parseJsonObject(event.currentTarget.value, selected.config);
                updateSelectedNode({ config: next });
              }}
              className="min-h-32 font-mono text-xs"
            />
          </Field>
          <Field label="Contracts">
            <pre className="max-h-40 overflow-auto rounded-xl border border-glass-border/35 bg-card/80 p-3 font-mono text-[11px] leading-5 text-muted-foreground shadow-soft">
              {jsonPreview({
                input: selected.input_contract,
                output: selected.output_contract,
                tools: selected.tools,
                perks: selected.perks,
              })}
            </pre>
          </Field>
          <Field label="Runtime Output">
            <pre className="max-h-48 overflow-auto rounded-xl border border-glass-border/35 bg-card/80 p-3 font-mono text-[11px] leading-5 text-muted-foreground shadow-soft">
              {selected.last_output || selected.output_preview || "No run output yet."}
            </pre>
          </Field>
          <Button variant="destructive" size="sm" disabled={isRunning} onClick={deleteSelectedNode}>
            <Trash2 className="h-4 w-4" />
            Delete Node
          </Button>
        </div>
      ) : (
        <div className="p-4 text-sm text-muted-foreground">Select a node on the canvas to edit its contract and runtime output.</div>
      )}
    </aside>
  );
}

function ExecutionTrace() {
  const trace = useLabStore((state) => state.workflow.workflow.trace_events);
  if (trace.length === 0) return null;
  return (
    <div className="absolute bottom-5 left-1/2 max-h-36 w-[min(660px,calc(100%-3rem))] -translate-x-1/2 overflow-hidden rounded-2xl border border-glass-border/35 bg-card/90 shadow-dock backdrop-blur-2xl">
      <div className="flex h-8 items-center justify-between border-b border-glass-border/25 px-3 font-mono text-[10px] uppercase text-muted-foreground">
        <span>Live Execution Trace</span>
        <span>{trace.length} events</span>
      </div>
      <div className="max-h-28 overflow-y-auto px-3 py-2 font-mono text-[11px] leading-5">
        {trace.slice(-8).map((event) => (
          <div key={event.id} className={event.status === "error" ? "text-destructive" : event.status === "completed" ? "text-success" : "text-muted-foreground"}>
            <span className="text-muted-foreground/60">{new Date(event.timestamp).toLocaleTimeString()}</span>{" "}
            <span>[{event.event}]</span> {event.message}
          </div>
        ))}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
      {children}
    </label>
  );
}

function parseJsonObject(text: string, fallback: Record<string, unknown>) {
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : fallback;
  } catch {
    return fallback;
  }
}
