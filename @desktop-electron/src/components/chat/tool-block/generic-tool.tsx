import type { ToolBlockUi } from "../../../types/chat";
import { browserImageDataUrl, browserInlineText, isBrowserToolName, normalizedToolOutput, shellLabel } from "./browser-output";
import { todoItems } from "./todo";
import { isError, isRunning, isTodoTool, stringValue, numberValue, isRecord } from "./shared";
import { StatusDot, ArtifactNotice } from "./shared";
import { searchLabel, globLabel, webFetchLabel } from "./search-tool";
import { useToolOutputCollapsed } from "./visibility";

export function GenericToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean; forceExpanded?: boolean }) {
  const autoCollapse = shouldAutoCollapseToolOutput();
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true, { autoCollapse });
  const output = normalizedToolOutput(block);
  const browserImage = browserImageDataUrl(block);
  const outputCollapsed = collapsed;
  const hasDetails = output.trim().length > 0 || Boolean(browserImage);
  const error = isError(block);
  const canToggle = hasDetails;

  return (
    <div className={nested ? "mb-1" : "mb-1.5"}>
      <button
        type="button"
        disabled={!canToggle}
        onClick={() => canToggle && toggleCollapsed()}
        className="flex w-full items-center gap-2 text-left font-mono text-xs disabled:cursor-default"
      >
        <StatusDot status={block.status} />
        <span className={error ? "min-w-0 flex-1 truncate text-destructive" : "min-w-0 flex-1 truncate text-muted-foreground"}>
          {inlineToolText(block)}
          {canToggle ? ` - ${outputCollapsed ? "Show" : "Hide"}` : ""}
        </span>
      </button>
      {hasDetails && !outputCollapsed ? (
        <div className="ml-4 mt-2 overflow-hidden rounded-xl border border-glass-border/35 bg-card/80 shadow-soft">
          {browserImage ? (
            <img
              src={browserImage}
              alt="Browser screenshot"
              className="max-h-80 w-full object-contain bg-background/60"
            />
          ) : null}
          <ArtifactNotice block={block} />
          {output.trim() ? (
            <pre className={browserImage ? "max-h-72 overflow-auto border-t border-glass-border/35 p-3 font-mono text-[11px] leading-5 text-muted-foreground" : "max-h-72 overflow-auto p-3 font-mono text-[11px] leading-5 text-muted-foreground"}>
              {output}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function shouldAutoCollapseToolOutput() {
  return true;
}

function inlineToolText(block: ToolBlockUi) {
  const browserText = browserInlineText(block);
  if (browserText) return browserText;

  const label =
    block.name === "Grep" || block.name === "search_files"
      ? searchLabel(block)
      : block.name === "Glob"
        ? globLabel(block)
        : block.name === "WebFetch"
          ? webFetchLabel(block)
          : block.name === "LSP"
            ? lspLabel(block)
            : isTodoTool(block)
              ? todoLabel(block)
              : block.name === "shell"
                ? shellLabel(block)
                : block.name === "Task" || block.name.startsWith("Task")
                  ? taskLabel(block)
                  : block.title.trim() || block.name;

  if (block.status === "permission_required") return `Permission required for ${label}`;
  if (block.status === "error") return `Failed ${label}`;
  if (isRunning(block)) return `${label} running`;
  return label;
}

function lspLabel(block: ToolBlockUi) {
  const operation = stringValue(block.data?.operation);
  return operation ? `LSP ${operation}` : "LSP";
}

function todoLabel(block: ToolBlockUi) {
  const todos = todoItems(block);
  return todos.length > 0 ? `${block.name} ${todos.length} items` : block.name;
}

function taskLabel(block: ToolBlockUi) {
  const task = block.data?.task;
  if (task && typeof task === "object" && "title" in task) {
    const title = stringValue((task as Record<string, unknown>).title);
    if (title) return `${block.name} ${title}`;
  }
  const taskId = stringValue(block.data?.task_id);
  return taskId ? `${block.name} ${taskId}` : block.name;
}

export function compactGenericToolLabel(kindName: string) {
  return kindName.replace(/[_-]+/g, " ");
}
