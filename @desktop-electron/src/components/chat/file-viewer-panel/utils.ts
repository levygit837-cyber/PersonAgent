import type { ViewMode } from "./types";
import { normalizePath } from "../../../lib/workspace-files";

export function isHtmlFile(fileName: string) {
  const lower = fileName.toLowerCase();
  return lower.endsWith(".html") || lower.endsWith(".htm");
}

export function isMarkdownFile(fileName: string) {
  const lower = fileName.toLowerCase();
  return lower.endsWith(".md") || lower.endsWith(".mdx") || lower === "readme";
}

export function defaultViewMode(fileName: string): ViewMode {
  return isHtmlFile(fileName) ? "html" : "code";
}

export function splitLines(content: string) {
  return content.length === 0 ? [""] : content.replace(/\r\n/g, "\n").split("\n");
}

export function normalizeLineRange(first: number, second: number) {
  return {
    start: Math.min(first, second),
    end: Math.max(first, second),
  };
}

export function lineInRange(line: number, start: number, end: number) {
  return line >= start && line <= end;
}

export function rangesOverlap(first: { start: number; end: number }, second: { start: number; end: number }) {
  return first.start <= second.end && second.start <= first.end;
}

export function formatLineRange(start: number, end: number) {
  return start === end ? String(start) : `${start}-${end}`;
}

export function selectedLinesExcerpt(content: string, startLine: number, endLine: number) {
  const lines = splitLines(content);
  return lines
    .slice(startLine - 1, endLine)
    .map((line, index) => `${startLine + index}: ${line}`)
    .join("\n");
}

export function compactWorkspacePath(path: string, workspaceRoot?: string) {
  if (!workspaceRoot) return path;
  const normalizedPath = normalizePath(path);
  const normalizedRoot = normalizePath(workspaceRoot);
  if (normalizedPath === normalizedRoot) return ".";
  if (normalizedPath.startsWith(`${normalizedRoot}/`)) {
    return normalizedPath.slice(normalizedRoot.length + 1);
  }
  return path;
}

export function filterRecord<T>(record: Record<string, T>, allowed: Set<string>) {
  const next: Record<string, T> = {};
  for (const [key, value] of Object.entries(record)) {
    if (allowed.has(key)) next[key] = value;
  }
  return next;
}
