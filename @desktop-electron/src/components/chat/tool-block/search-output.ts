import type { ToolBlockUi } from "../../../types/chat";

export type SearchOutputRow = {
  kind: "file" | "match" | "line";
  file?: string;
  line?: string;
  text: string;
};
export function searchMetadata(block: ToolBlockUi) {
  const data = block.data;
  const items: { label: string; value: string }[] = [];
  const command = stringValue(data?.command);
  const pattern = stringValue(data?.pattern);
  const path = stringValue(data?.display_path) ?? stringValue(data?.path);
  const count = numberValue(data?.matches) ?? numberValue(data?.count);
  const shown = numberValue(data?.shown);
  const returnCode = numberValue(data?.return_code);

  if (command) items.push({ label: "Command", value: command });
  if (pattern) items.push({ label: "Pattern", value: pattern });
  if (path) items.push({ label: "Path", value: path });
  if (typeof count === "number") items.push({ label: block.name === "Glob" ? "Files" : "Matches", value: String(count) });
  if (typeof shown === "number") items.push({ label: "Shown", value: String(shown) });
  if (typeof returnCode === "number") items.push({ label: "Return code", value: String(returnCode) });
  if (data?.truncated === true) items.push({ label: "Truncated", value: "true" });
  if (data?.timed_out === true) items.push({ label: "Timed out", value: "true" });

  return items;
}

export function searchSummary(block: ToolBlockUi) {
  if (block.status === "running" || block.status === "queued") return undefined;
  const data = block.data;
  const parts: string[] = [];
  const count = numberValue(data?.matches) ?? numberValue(data?.count);
  const shown = numberValue(data?.shown);

  if (typeof count === "number") {
    const label = block.name === "Glob" ? "file" : "match";
    parts.push(`${count} ${count === 1 ? label : `${label}s`}`);
  }
  if (typeof shown === "number" && typeof count === "number" && shown !== count) {
    parts.push(`showing ${shown}`);
  }
  if (data?.truncated === true) parts.push("truncated");
  if (data?.timed_out === true) parts.push("timed out");

  return parts.join(" - ");
}

export function searchOutputRows(block: ToolBlockUi): SearchOutputRow[] {
  const matches = block.data?.matches;
  if (Array.isArray(matches)) {
    return matches.map((item) => ({ kind: "file" as const, text: String(item) })).filter((row) => row.text.trim().length > 0);
  }

  const output = searchOutputText(block);
  if (!output.trim()) return [];
  return output
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0)
    .map((line) => searchOutputRowFromLine(line, block));
}

function searchOutputRowFromLine(line: string, block: ToolBlockUi): SearchOutputRow {
  const parsed = /^(.+?):(\d+):(.*)$/.exec(line);
  if (parsed) {
    return {
      kind: "match",
      file: parsed[1],
      line: parsed[2],
      text: parsed[3].trim(),
    };
  }

  const command = stringValue(block.data?.command);
  const base = command ? shellCommandBase(command) : undefined;
  if (block.name === "Glob" || base === "find") {
    return { kind: "file", text: line };
  }

  return { kind: "line", text: line };
}

export function searchOutputText(block: ToolBlockUi) {
  return rawStringValue(block.data?.content) ?? block.content;
}

export function searchHasOutput(block: ToolBlockUi) {
  const matches = block.data?.matches;
  return (Array.isArray(matches) && matches.length > 0) || hasNonWhitespace(searchOutputText(block));
}

export function searchOutputPreview(block: ToolBlockUi) {
  const matches = block.data?.matches;
  const firstLine = firstNonEmptyLine(searchOutputText(block));
  const first =
    Array.isArray(matches) && matches.length > 0
      ? { kind: "file" as const, text: String(matches[0]) }
      : firstLine
        ? searchOutputRowFromLine(firstLine, block)
        : undefined;
  if (!first) return undefined;
  const text = first.kind === "match" ? `${first.file}:${first.line} ${first.text}` : first.text;
  return text.length > 140 ? `${text.slice(0, 139)}...` : text;
}

function firstNonEmptyLine(output: string) {
  let start = 0;
  while (start <= output.length) {
    const end = output.indexOf("\n", start);
    const lineEnd = end === -1 ? output.length : end;
    const line = output.slice(start, lineEnd).trimEnd();
    if (line.trim().length > 0) return line;
    if (end === -1) return undefined;
    start = end + 1;
  }
  return undefined;
}

function hasNonWhitespace(value: string) {
  return /\S/.test(value);
}

function stringValue(value: unknown) {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length ? trimmed : undefined;
}

function rawStringValue(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return undefined;
}

function shellCommandBase(command: string) {
  return /^\s*([^\s]+)/.exec(command)?.[1];
}
