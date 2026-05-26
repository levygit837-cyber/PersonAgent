import type { ToolBlockUi } from "../../../types/chat";
import { isError, isRunning, stringValue } from "./shared";
import { StatusDot, ArtifactNotice } from "./shared";
import { useToolOutputCollapsed } from "./visibility";

export function ShellToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean; forceExpanded?: boolean }) {
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true, { autoCollapse: true });
  const outputCollapsed = collapsed;
  const output = block.content.trimEnd();
  const hasOutput = output.trim().length > 0;
  const canToggle = hasOutput;
  return (
    <div className={nested ? "mb-1.5" : "mb-2"}>
      <div className="flex items-start gap-2">
        <span className="pt-1">
          <StatusDot status={block.status} />
        </span>
        <button
          type="button"
          disabled={!canToggle}
          className="min-w-0 flex-1 text-left disabled:cursor-default"
          aria-label={canToggle ? `${outputCollapsed ? "Show" : "Hide"} shell output` : undefined}
          onClick={() => canToggle && toggleCollapsed()}
        >
          <div className={isError(block) ? "truncate font-mono text-xs text-destructive" : "truncate font-mono text-xs text-muted-foreground"}>
            {shellCommandText(block)}
          </div>
          {shellOutputPreview(output) ? (
            <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground/70">{shellOutputPreview(output)}</div>
          ) : null}
        </button>
      </div>
      {hasOutput && !outputCollapsed ? (
        <div className="ml-4 mt-2 overflow-hidden rounded-xl border border-glass-border/35 bg-card/80 shadow-soft">
          <ArtifactNotice block={block} />
          <pre className="max-h-72 overflow-auto p-3 font-mono text-[11px] leading-5 text-muted-foreground">
            {output}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

function shellCommandText(block: ToolBlockUi) {
  const command = stringValue(block.data?.command);
  const text = command || block.title.trim() || "Shell command";
  if (block.status === "permission_required") return `Permission required: ${text}`;
  if (block.status === "error") return `Failed: ${text}`;
  if (isRunning(block)) return `${text} running`;
  return text;
}

function shellOutputPreview(output: string) {
  const firstLine = output.split("\n").find((line) => line.trim().length > 0)?.trimEnd();
  if (!firstLine) return undefined;
  return firstLine.length > 140 ? `${firstLine.slice(0, 139)}...` : firstLine;
}
