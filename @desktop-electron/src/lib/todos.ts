import type { ToolBlockUi } from "../types/chat";

export type TodoItem = {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "completed";
};

export function todoItems(block: ToolBlockUi): TodoItem[] {
  const rawTodos =
    arrayValue(block.data?.todos) ??
    arrayValue(block.data?.items) ??
    arrayValue(block.data?.todo_list) ??
    singleTodoValue(block.data?.todo) ??
    todoArrayFromContent(block.content);

  return rawTodos
    .map((item, index) => normalizeTodoItem(item, index))
    .filter((item): item is TodoItem => Boolean(item));
}

function normalizeTodoItem(value: unknown, index: number): TodoItem | undefined {
  if (!isRecord(value)) return undefined;
  const content =
    stringValue(value.content) ??
    stringValue(value.title) ??
    stringValue(value.text) ??
    stringValue(value.description);
  if (!content) return undefined;
  const id = stringValue(value.id) ?? `${content}-${index}`;
  return {
    id,
    content,
    status: todoStatusValue(value.status),
  };
}

function todoStatusValue(value: unknown): TodoItem["status"] {
  if (typeof value !== "string") return "pending";
  const normalized = value.trim().toLowerCase().replace(/-/g, "_");
  if (normalized === "completed" || normalized === "complete" || normalized === "done") return "completed";
  if (normalized === "in_progress" || normalized === "running" || normalized === "active") return "in_progress";
  return "pending";
}

function todoArrayFromContent(content: string): unknown[] {
  if (!content.trim()) return [];
  try {
    const parsed: unknown = JSON.parse(content);
    if (!isRecord(parsed)) return [];
    return (
      arrayValue(parsed.todos) ??
      arrayValue(parsed.items) ??
      arrayValue(parsed.todo_list) ??
      singleTodoValue(parsed.todo) ??
      []
    );
  } catch {
    return [];
  }
}

function arrayValue(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined;
}

function singleTodoValue(value: unknown): unknown[] | undefined {
  return isRecord(value) ? [value] : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function stringValue(value: unknown) {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length ? trimmed : undefined;
}
