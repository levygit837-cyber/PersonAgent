import type { ToolBlockUi } from "../../../types/chat";
import { isRunning, statusTextClass, stringValue } from "./shared";
import { StatusDot } from "./shared";

export function readRunningLabel(count: number) {
  return `Reading ${count} ${count === 1 ? "File" : "Files"}...`;
}

export function readCollapsedLabel(count: number) {
  return `Read ${count} ${count === 1 ? "File" : "Files"} >`;
}

export function ReadToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  return (
    <div className={nested ? "mb-1 flex items-center gap-2" : "mb-1.5 flex items-center gap-2"}>
      <StatusDot status={block.status} />
      <span className={`min-w-0 truncate font-mono text-xs ${statusTextClass(block.status)}`}>
        {readEventText(block)}
      </span>
    </div>
  );
}

function readEventText(block: ToolBlockUi) {
  const file = fileLabel(block);
  if (block.status === "permission_required") return `Permission required for Read ${file}`;
  if (block.status === "error") return `Failed Read ${file}`;
  if (isRunning(block)) return readRunningLabel(1);
  const detail = lineDetail(block);
  return `Read ${file}${detail ? ` - ${detail}` : ""}`;
}

function fileLabel(block: ToolBlockUi) {
  if (block.path?.trim()) return block.path.trim();
  const title = block.title.trim();
  if (title.startsWith("Read ") && title.length > 5) return title.slice(5);
  if (title && title !== "Reading file") return title;
  return "file";
}

function lineDetail(block: ToolBlockUi) {
  const start = block.data?.start_line;
  const end = block.data?.end_line;
  const truncated = block.data?.truncated === true;
  const range = typeof start === "number" && typeof end === "number" && end >= start ? (start === end ? `L${start}` : `L${start}-L${end}`) : undefined;
  if (!range && !truncated) return undefined;
  return [range, truncated ? "truncated" : undefined].filter(Boolean).join(" - ");
}
