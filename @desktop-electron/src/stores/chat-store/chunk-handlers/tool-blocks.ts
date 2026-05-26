import type { ChatMessageUi, StreamChunk, ToolBlockStatus, ToolBlockUi } from "../../../types/chat";
import { parseToolStatus } from "../../../types/chat";
import {
  isTodoToolName,
  latestTodoSnapshotFromMessage,
  isTodoToolBlock,
  isBrowserToolBlock,
  upsertBrowserToolBlock,
} from "../internal";
import { stringValue } from "./utils";
import { closeActiveReasoning } from "./reasoning";
import type { SetFn } from "./utils";

export function shouldCollapseToolBlock(name: string, status: ToolBlockStatus) {
  if (status !== "completed") return false;
  if (isTodoToolName(name)) return false;
  return new Set([
    "Read",
    "read_file",
    "shell",
    "Glob",
    "Grep",
    "search_files",
    "LSP",
    "WebFetch",
    "BrowserSearch",
    "BrowserOpen",
    "BrowserListTabs",
    "BrowserExtractContent",
    "BrowserReadContentChunk",
    "BrowserGetHtml",
    "BrowserGetElementMap",
    "BrowserClick",
    "BrowserType",
    "BrowserScreenshot",
    "BrowserCloseTab",
    "BrowserReadConsole",
    "BrowserScript",
    "BrowserScroll",
    "BrowserReload",
    "BrowserHistory",
    "BrowserSwitchTab",
    "BrowserWait",
    "BrowserAct",
    "Task",
    "TaskCreate",
    "TaskGet",
    "TaskUpdate",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "Write",
    "Edit",
  ]).has(name);
}

export function toolTitle(name: string, path?: string) {
  if (name === "Read" || name === "read_file") return path ? `Read ${path}` : "Reading file";
  if (name === "Grep" || name === "search_files") return "Grep";
  if (name === "Glob") return "Glob";
  if (name === "shell") return "Shell command";
  if (name === "WebFetch") return path ? `Fetch ${path}` : "WebFetch";
  if (name === "BrowserSearch") return "BrowserSearch";
  if (name === "BrowserOpen") return path ? `Open ${path}` : "BrowserOpen";
  if (name === "BrowserListTabs") return "BrowserListTabs";
  if (name === "BrowserExtractContent") return path ? `Extract ${path}` : "BrowserExtractContent";
  if (name === "BrowserReadContentChunk") return "BrowserReadContentChunk";
  if (name === "BrowserGetHtml") return path ? `HTML ${path}` : "BrowserGetHtml";
  if (name === "LSP") return "LSP";
  if (isTodoToolName(name)) return name;
  if (name.startsWith("Task")) return name;
  return name;
}

export function toolBlockFromChunk(chunk: StreamChunk, existing?: ToolBlockUi): ToolBlockUi {
  const status = parseToolStatus(chunk.tool_status);
  const name = chunk.tool_name ?? existing?.name ?? "tool";
  const data = mergeToolData(existing?.data, normalizeToolInput(name, chunk.tool_input), chunk.tool_data);
  const path =
    stringValue(data?.display_path) ??
    stringValue(data?.path) ??
    stringValue(data?.url) ??
    stringValue(chunk.tool_input?.path);
  const content =
    stringValue(data?.content) ??
    chunk.tool_result ??
    chunk.tool_error ??
    existing?.content ??
    "";
  return {
    id: chunk.tool_call_id ?? existing?.id ?? "",
    name,
    status,
    title: toolTitle(name, path),
    message: toolMessage(chunk, existing, status),
    content,
    path,
    data,
    isCollapsed: shouldCollapseToolBlock(name, status),
  };
}

function normalizeToolInput(name: string, input?: Record<string, unknown>) {
  if (name !== "Write" || !input) return input;
  const writtenContent = input.content;
  if (typeof writtenContent !== "string") return input;
  return {
    ...input,
    written_content: writtenContent,
  };
}

function mergeToolData(
  existing?: Record<string, unknown>,
  input?: Record<string, unknown>,
  result?: Record<string, unknown>,
) {
  const merged = { ...(existing ?? {}), ...(input ?? {}), ...(result ?? {}) };
  return Object.keys(merged).length ? merged : undefined;
}

function toolMessage(chunk: StreamChunk, existing: ToolBlockUi | undefined, status: ToolBlockStatus) {
  if (chunk.tool_message) return chunk.tool_message;
  if (status === "queued" || status === "running") return existing?.message ?? "";
  return "";
}

export function applyToolChunk(
  chunk: StreamChunk,
  agentId: string,
  set: SetFn,
) {
  if (!chunk.tool_call_id) return;
  set((state) => {
    let updatedAgentMessage: ChatMessageUi | undefined;
    let updatedBlock: ToolBlockUi | undefined;
    const messages = state.messages.map((item) => {
      if (item.id !== agentId) return item;
      const message = closeActiveReasoning(item, true);
      const blocks = [...message.toolBlocks];
      const parts = [...message.parts];
      const existingIndex = blocks.findIndex((block) => block.id === chunk.tool_call_id);
      const existing = existingIndex >= 0 ? blocks[existingIndex] : undefined;
      const next = toolBlockFromChunk(chunk, existing);
      if (existingIndex >= 0) {
        blocks[existingIndex] = next;
      } else {
        blocks.push(next);
      }
      if (!parts.some((part) => part.toolBlockId === next.id)) {
        parts.push({
          kind: "tool",
          id: `tool-${next.id}`,
          toolBlockId: next.id,
        });
      }
      updatedBlock = next;
      updatedAgentMessage = { ...message, toolBlocks: blocks, parts };
      return updatedAgentMessage;
    });
    return {
      messages,
      latestTodoSnapshot: updatedAgentMessage
        ? latestTodoSnapshotFromMessage(updatedAgentMessage) ??
          (updatedAgentMessage.toolBlocks.some(isTodoToolBlock) ? undefined : state.latestTodoSnapshot)
        : state.latestTodoSnapshot,
      browserToolBlocks: updatedBlock && isBrowserToolBlock(updatedBlock)
        ? upsertBrowserToolBlock(state.browserToolBlocks, updatedBlock)
        : state.browserToolBlocks,
    };
  });
}
