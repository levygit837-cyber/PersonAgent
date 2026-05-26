import type { ToolBlockStatus, ToolBlockUi } from "../../../types/chat";
import { todoItems, type TodoItem } from "./todo";
import { isError, isRunning } from "./shared";
import { StatusDot } from "./shared";
import { GenericToolEvent } from "./generic-tool";

export function TodoToolGroupBlock({ blocks }: { blocks: ToolBlockUi[] }) {
  return <TodoPanel blocks={blocks} />;
}

export function TodoToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  return <TodoPanel blocks={[block]} nested={nested} />;
}

function TodoPanel({ blocks, nested = false }: { blocks: ToolBlockUi[]; nested?: boolean }) {
  const latest = latestTodoBlock(blocks);
  const todos = todoItems(latest);
  const completed = todos.filter((todo) => todo.status === "completed").length;
  const active = todos.find((todo) => todo.status === "in_progress");
  const status = todoPanelStatus(blocks);
  const updateCount = blocks.length;

  if (todos.length === 0) {
    return <GenericToolEvent block={latest} nested={nested} />;
  }

  return (
    <section
      className={
        nested
          ? "personagent-todo-rise mb-2 overflow-hidden rounded-lg border border-glass-border/35 bg-card/45 shadow-soft"
          : "personagent-todo-rise mb-3 overflow-hidden rounded-lg border border-glass-border/40 bg-card/55 shadow-soft"
      }
      aria-label="Todo tracker"
      data-testid="todo-tracker"
    >
      <div className="flex min-w-0 items-center justify-between gap-3 border-b border-glass-border/25 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <StatusDot status={status} />
          <div className="min-w-0">
            <div className="truncate font-mono text-[11px] font-semibold uppercase text-foreground">Todos</div>
            <div className="truncate font-mono text-[10px] text-muted-foreground">
              {latest.name}
              {updateCount > 1 ? ` - ${updateCount} updates` : ""}
            </div>
          </div>
        </div>
        <div className="shrink-0 rounded-full border border-glass-border/35 bg-background/45 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
          {todoProgressLabel(status, completed, todos.length)}
        </div>
      </div>
      <ul className="max-h-56 overflow-y-auto py-1">
        {todos.map((todo, index) => (
          <TodoRow key={todo.id || `${todo.content}-${index}`} todo={todo} index={index} active={active?.id === todo.id} />
        ))}
      </ul>
    </section>
  );
}

function TodoRow({ todo, index, active }: { todo: TodoItem; index: number; active: boolean }) {
  const completed = todo.status === "completed";
  return (
    <li
      className="personagent-todo-item grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 border-b border-glass-border/20 px-3 py-1.5 last:border-0"
      style={{ animationDelay: `${Math.min(index * 24, 144)}ms` }}
    >
      <span className="pt-[7px]">
        <TodoStatusDot status={todo.status} />
      </span>
      <span
        className={
          completed
            ? "min-w-0 break-words text-[12px] leading-5 text-muted-foreground/70 line-through decoration-success/50"
            : "min-w-0 break-words text-[12px] leading-5 text-foreground/90"
        }
      >
        {todo.content}
      </span>
      {active ? (
        <span className="mt-0.5 rounded-full border border-warning/25 px-1.5 py-[1px] font-mono text-[10px] text-warning">active</span>
      ) : null}
    </li>
  );
}

function TodoStatusDot({ status }: { status: TodoItem["status"] }) {
  const completed = status === "completed";
  return (
    <span
      className={`personagent-todo-dot inline-flex h-2.5 w-2.5 shrink-0 rounded-full ${completed ? "bg-success" : "bg-warning"}`}
      data-status={status}
      aria-label={todoStatusLabel(status)}
    />
  );
}

function latestTodoBlock(blocks: ToolBlockUi[]) {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    if (todoItems(blocks[index]).length > 0) return blocks[index];
  }
  return blocks[blocks.length - 1];
}

function todoPanelStatus(blocks: ToolBlockUi[]): ToolBlockStatus {
  if (blocks.some(isError)) return "error";
  if (blocks.some(isRunning)) return "running";
  return "completed";
}

function todoProgressLabel(status: ToolBlockStatus, completed: number, total: number) {
  if (status === "running" || status === "queued") return "updating";
  if (status === "error" || status === "permission_required") return "failed";
  return `${completed}/${total} done`;
}

function todoStatusLabel(status: TodoItem["status"]) {
  if (status === "completed") return "completed";
  if (status === "in_progress") return "in progress";
  return "pending";
}
