import type { ComposerAnnotation } from "../../../stores/chat-store";
import type { TerminalSnippet } from "../../../stores/terminal-store";
import type {
  ChatCommandInfo,
  ContextAttachment,
  TodoDockSnapshotUi,
} from "../../../types/chat";
import type { ComposerMention } from "./mentions";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const PLAN_MODE_SYSTEM_PROMPT = [
  "The user enabled Plan Mode from the composer UI for this turn.",
  "Enter PlanMode before doing workspace-changing work.",
  "Research and inspect what is needed, then write a concrete plan and request approval instead of making changes.",
].join("\n");
export const TODO_DOCK_EXIT_MS = 280;
export const MODEL_CATALOG_STALE_MS = 10 * 60_000;
export const CODEX_AUTH_STALE_MS = 2 * 60_000;

// ---------------------------------------------------------------------------
// Slash command helpers
// ---------------------------------------------------------------------------

export function slashTokenFromText(value: string) {
  const trimmed = value.trimStart();
  if (!trimmed.startsWith("/") || trimmed.includes("\n")) return null;
  const token = trimmed.split(/\s+/, 1)[0];
  return token;
}

export function parseComposerSlashInvocation(value: string) {
  const trimmed = value.trim();
  if (!trimmed.startsWith("/") || trimmed === "/") return null;
  const head = trimmed.slice(1).split(/\s+/, 1)[0];
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:/-]*$/.test(head)) return null;
  return { name: head.toLowerCase() };
}

export function filterSlashCommands(commands: ChatCommandInfo[], slashToken: string | null) {
  if (slashToken === null) return [];
  const normalized = slashToken.toLowerCase();
  return commands
    .filter((command) => command.user_invocable && command.slash_name.toLowerCase().startsWith(normalized))
    .sort((left, right) => left.slash_name.localeCompare(right.slash_name));
}

// ---------------------------------------------------------------------------
// Context attachment builders
// ---------------------------------------------------------------------------

export function buildComposerContextAttachments(
  annotations: ComposerAnnotation[],
  terminalSnippet: TerminalSnippet | null,
  mentions: ComposerMention[] = [],
) {
  const mentionAttachments: ContextAttachment[] = mentions.map((mention) => contextAttachmentFromMention(mention));
  const annotationAttachments: ContextAttachment[] = annotations.map((annotation) => {
    if (annotation.source === "browser") {
      return {
        type: "browser_annotation",
        id: annotation.id,
        label: `@Annotation#${annotation.id}`,
        display_path: annotation.displayPath,
        url: annotation.browserUrl || annotation.filePath,
        title: annotation.browserTitle || annotation.fileName,
        node_id: annotation.browserNodeId,
        selector: annotation.browserSelector,
        role: annotation.browserRole,
        text: annotation.text,
        quote: annotation.browserQuote || annotation.selectedLines,
      };
    }
    return {
      type: "viewer_annotation",
      id: annotation.id,
      label: `@Annotation#${annotation.id}`,
      file_name: annotation.fileName,
      file_path: annotation.filePath,
      display_path: annotation.displayPath,
      start_line: annotation.startLine,
      end_line: annotation.endLine,
      language: annotation.language,
      text: annotation.text,
    };
  });
  const requestAttachments: ContextAttachment[] = [...mentionAttachments, ...annotationAttachments];
  const displayAttachments: ContextAttachment[] = [...requestAttachments];

  if (terminalSnippet?.content) {
    requestAttachments.push({
      type: "terminal_output",
      id: terminalSnippet.id,
      label: "@terminal:bash",
      shell: "bash",
      content: terminalSnippet.content,
    });
    displayAttachments.push({
      type: "terminal_output",
      id: terminalSnippet.id,
      label: "@terminal:bash",
      shell: "bash",
      content_preview: terminalSnippet.content.slice(0, 160).replace(/\s+/g, " ").trim(),
      content_char_count: terminalSnippet.content.length,
    });
  }

  return { requestAttachments, displayAttachments };
}

export function contextAttachmentFromMention(mention: ComposerMention): ContextAttachment {
  if (mention.type === "browser_tab") {
    return {
      type: "browser_tab",
      id: mention.id,
      label: mention.label,
      browser_id: mention.browserId,
      tab_id: mention.tabId,
      page_id: mention.pageId || mention.tabId,
      window_id: mention.windowId || mention.pageId || mention.tabId,
      url: mention.url,
      title: mention.title,
      runtime: mention.runtime,
      active: mention.active,
      is_active: mention.active,
      display_path: mention.displayPath,
      state: mention.state,
      updated_at: mention.updatedAt,
    };
  }
  if (mention.type === "directory") {
    return {
      type: "directory",
      id: mention.id,
      label: mention.label,
      directory_path: mention.directoryPath,
      display_path: mention.displayPath,
    };
  }
  if (mention.type === "skill") {
    return {
      type: "skill",
      id: mention.id,
      label: mention.label,
      name: mention.name,
      invocation_name: mention.invocationName,
      slash_name: mention.slashName,
      description: mention.description,
      path: mention.path,
      display_path: mention.displayPath,
      source: mention.source,
    };
  }
  return {
    type: "file",
    id: mention.id,
    label: mention.label,
    file_name: mention.fileName,
    file_path: mention.filePath,
    display_path: mention.displayPath,
  };
}

export function attachmentOnlyMessage(
  annotations: ComposerAnnotation[],
  terminalSnippet: TerminalSnippet | null,
  mentions: ComposerMention[] = [],
) {
  const annotationText = annotations
    .map((annotation) => annotation.text.trim())
    .filter(Boolean)
    .join("\n\n");
  if (annotationText) return annotationText;
  if (terminalSnippet) return "Use the attached terminal output.";
  if (mentions.length > 0) return "Use the selected @ references.";
  return "Use the attached context.";
}

// ---------------------------------------------------------------------------
// Formatting utilities
// ---------------------------------------------------------------------------

export function formatLineRange(start: number, end: number) {
  return start === end ? String(start) : `${start}-${end}`;
}

export function todoStatusLabel(status: TodoDockSnapshotUi["todos"][number]["status"]) {
  if (status === "completed") return "completed";
  if (status === "in_progress") return "in progress";
  return "pending";
}
