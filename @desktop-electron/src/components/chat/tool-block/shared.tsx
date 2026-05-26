import type { ToolBlockStatus, ToolBlockUi } from "../../../types/chat";

export const TOOL_STATUS_DOT_SIZE = 6;
export const AUTO_COLLAPSE_TOOL_OUTPUTS = true;

export function isRunning(block: ToolBlockUi) {
  return block.status === "running" || block.status === "queued";
}

export function isError(block: ToolBlockUi) {
  return isErrorStatus(block.status);
}

export function isErrorStatus(status: ToolBlockStatus) {
  return status === "error";
}

export function isWarningStatus(status: ToolBlockStatus) {
  return status === "permission_required";
}

export function statusTextClass(status: ToolBlockStatus) {
  if (isErrorStatus(status)) return "text-destructive";
  if (isWarningStatus(status)) return "text-warning";
  return "text-muted-foreground";
}

export function statusDotClass(status: ToolBlockStatus) {
  if (isErrorStatus(status)) return "bg-destructive";
  if (isWarningStatus(status)) return "bg-warning";
  return "bg-success";
}

export function stringValue(value: unknown) {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length ? trimmed : undefined;
}

export function rawStringValue(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

export function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return undefined;
}

export function hasNonWhitespace(value: string) {
  return /\S/.test(value);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function shellCommandBase(command: string) {
  return /^\s*([^\s]+)/.exec(command)?.[1];
}

export function isTodoTool(block: Pick<ToolBlockUi, "name">) {
  return block.name.toLowerCase().startsWith("todo");
}

export function isFileMutationTool(block: Pick<ToolBlockUi, "name">) {
  return block.name === "Write" || block.name === "Edit";
}

export function isSearchTool(block: ToolBlockUi) {
  return block.name === "Glob" || block.name === "Grep" || block.name === "search_files" || isSearchShellCommand(block);
}

export function isSearchShellCommand(block: ToolBlockUi) {
  if (block.name !== "shell") return false;
  const command = stringValue(block.data?.command);
  const base = command ? shellCommandBase(command) : undefined;
  return base === "find" || base === "grep" || base === "rg";
}

export function StatusDot({ status, size = TOOL_STATUS_DOT_SIZE }: { status: ToolBlockStatus; size?: number }) {
  const running = status === "running" || status === "queued";
  const color = statusDotClass(status);
  return running ? (
    <span
      className="personagent-spinner personagent-tool-status-dot inline-block shrink-0 text-muted-foreground"
      data-status={status}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  ) : (
    <span
      className={`personagent-tool-status-dot inline-flex shrink-0 rounded-full ${color}`}
      data-status={status}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}

export function ArtifactNotice({ block }: { block: ToolBlockUi }) {
  const storageRef = stringValue(block.data?.storage_ref);
  if (!storageRef) return null;
  const originalChars = numberValue(block.data?.original_chars);
  return (
    <div className="border-b border-glass-border/35 bg-secondary/[0.25] px-3 py-2 font-mono text-[11px] leading-5 text-muted-foreground">
      Full output saved: <span className="break-all text-foreground/80">{storageRef}</span>
      {originalChars ? <span className="text-muted-foreground/70"> ({originalChars} chars)</span> : null}
    </div>
  );
}
