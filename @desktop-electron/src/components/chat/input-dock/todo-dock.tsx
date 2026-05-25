import { ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useState } from "react";
import { useChatStore } from "../../../stores/chat-store";
import type { TodoDockSnapshotUi, ToolBlockStatus } from "../../../types/chat";
import { TODO_DOCK_EXIT_MS, todoStatusLabel } from "./helpers";

function TodoDockStatusDot({ status }: { status: ToolBlockStatus }) {
  if (status === "running" || status === "queued") {
    return <span className="personagent-spinner h-1.5 w-1.5 shrink-0 text-primary/80" aria-hidden="true" />;
  }
  const color = status === "error" || status === "permission_required" ? "bg-destructive" : "bg-success";
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${color}`} aria-hidden="true" />;
}

function TodoDockPanel({
  snapshot,
  exiting,
  minimized,
  restoring,
  onToggleMinimized,
  onExitComplete,
}: {
  snapshot: TodoDockSnapshotUi;
  exiting: boolean;
  minimized: boolean;
  restoring: boolean;
  onToggleMinimized: () => void;
  onExitComplete: () => void;
}) {
  const completed = snapshot.todos.filter((todo) => todo.status === "completed").length;
  const active = snapshot.todos.find((todo) => todo.status === "in_progress");
  const progressLabel = `${completed}/${snapshot.todos.length}`;
  return (
    <section
      className={`${exiting ? "personagent-todo-exit" : "personagent-todo-rise"} ${minimized ? "is-minimized" : restoring ? "is-restoring" : ""} personagent-input-todo-dock personagent-todo-panel pointer-events-auto overflow-hidden rounded-t-2xl rounded-b-none border border-b-0 border-glass-border/35 bg-card/90 shadow-dock ring-1 ring-primary/10 backdrop-blur-2xl`}
      aria-label="Todo tracker"
      data-testid="input-todo-tracker"
      data-state={exiting ? "exiting" : minimized ? "minimized" : "visible"}
      onAnimationEnd={() => {
        if (exiting) onExitComplete();
      }}
    >
      <div className="flex min-w-0 items-center justify-between gap-2 border-b border-glass-border/20 px-2.5 py-1.5">
        <div className="flex min-w-0 items-center gap-1.5">
          <TodoDockStatusDot status={snapshot.status} />
          <div className="min-w-0">
            <div className="truncate font-mono text-[10px] font-semibold uppercase text-foreground">
              {minimized ? `Todos ${progressLabel}` : "Todos"}
            </div>
            <div className={`${minimized ? "hidden" : "block"} truncate font-mono text-[9px] text-muted-foreground`}>
              {snapshot.toolName}
              {snapshot.updateCount > 1 ? ` - ${snapshot.updateCount} updates` : ""}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <div className="rounded-full border border-glass-border/30 bg-background/40 px-1.5 py-0 font-mono text-[9px] leading-4 text-muted-foreground">
            {minimized ? progressLabel : snapshot.status === "running" || snapshot.status === "queued" ? "updating" : `${progressLabel} done`}
          </div>
          <button
            type="button"
            className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-glass/80 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/60"
            aria-label={minimized ? "Restore Todo tracker" : "Minimize Todo tracker"}
            onClick={onToggleMinimized}
          >
            {minimized ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
        </div>
      </div>
      <ul className={`${minimized ? "max-h-0 py-0 opacity-0" : "max-h-24 py-0.5 opacity-100"} personagent-input-todo-scroll overflow-y-auto overscroll-contain transition-[max-height,opacity,padding] duration-200 ease-out`} data-testid="input-todo-scroll">
        {snapshot.todos.map((todo, index) => (
          <li
            key={todo.id || `${todo.content}-${index}`}
            className="personagent-todo-item grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-1.5 border-b border-glass-border/15 px-2.5 py-1 last:border-0"
            style={{ animationDelay: `${Math.min(index * 24, 144)}ms` }}
          >
            <span className="pt-[5px]">
              <span
                className={`personagent-todo-dot inline-flex h-2 w-2 shrink-0 rounded-full ${todo.status === "completed" ? "bg-success" : "bg-warning"}`}
                data-status={todo.status}
                aria-label={todoStatusLabel(todo.status)}
              />
            </span>
            <span
              className={
                todo.status === "completed"
                  ? "min-w-0 break-words text-[11px] leading-4 text-muted-foreground/70 line-through decoration-success/50"
                  : "min-w-0 break-words text-[11px] leading-4 text-foreground/90"
              }
            >
              {todo.content}
            </span>
            {active?.id === todo.id ? (
              <span className="mt-px rounded-full border border-warning/25 px-1 py-0 font-mono text-[9px] leading-4 text-warning">active</span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function InputTodoDock() {
  const liveSnapshot = useChatStore((state) => state.latestTodoSnapshot);
  const isExecuting = useChatStore(
    (state) => state.isStreaming || state.isFinalizing || !!state.pendingToolApproval || !!state.pendingPlanApproval
  );
  const liveKey = liveSnapshot?.key;
  const [displaySnapshot, setDisplaySnapshot] = useState<TodoDockSnapshotUi | undefined>();
  const [exiting, setExiting] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [restoring, setRestoring] = useState(false);

  useEffect(() => {
    if (isExecuting && liveSnapshot && liveKey !== displaySnapshot?.key) {
      setDisplaySnapshot(liveSnapshot);
      setExiting(false);
    }
  }, [isExecuting, liveKey]);

  useEffect(() => {
    if (isExecuting || !displaySnapshot || exiting) return;
    setExiting(true);
  }, [displaySnapshot, exiting, isExecuting]);

  useEffect(() => {
    if (!exiting) return undefined;
    const timer = window.setTimeout(() => {
      setDisplaySnapshot(undefined);
      setExiting(false);
    }, TODO_DOCK_EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [exiting]);

  useEffect(() => {
    if (!restoring) return undefined;
    const timer = window.setTimeout(() => setRestoring(false), 240);
    return () => window.clearTimeout(timer);
  }, [restoring]);

  if (!displaySnapshot) return null;

  return (
    <TodoDockPanel
      snapshot={displaySnapshot}
      exiting={exiting}
      minimized={minimized}
      restoring={restoring}
      onToggleMinimized={() => {
        setMinimized((value) => {
          if (value) setRestoring(true);
          return !value;
        });
      }}
      onExitComplete={() => {
        if (!exiting) return;
        setDisplaySnapshot(undefined);
        setExiting(false);
      }}
    />
  );
}
