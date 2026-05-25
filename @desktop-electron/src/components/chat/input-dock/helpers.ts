import type {
  BrowserTabMentionSuggestion,
  WorkspaceMentionSuggestion,
} from "../../../api/client";
import type { ComposerAnnotation } from "../../../stores/chat-store";
import type { TerminalSnippet } from "../../../stores/terminal-store";
import {
  type ChatCommandInfo,
  type ContextAttachment,
  type SkillSummary,
  type TodoDockSnapshotUi,
} from "../../../types/chat";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ComposerMentionKind = "file" | "directory" | "skill" | "browser_tab";

export type ComposerMention = {
  id: string;
  type: ComposerMentionKind;
  label: string;
  token: string;
  displayPath: string;
  fileName?: string;
  filePath?: string;
  directoryPath?: string;
  name?: string;
  invocationName?: string;
  slashName?: string;
  description?: string;
  path?: string;
  source?: string;
  browserId?: string;
  tabId?: string;
  pageId?: string;
  windowId?: string;
  url?: string;
  title?: string;
  runtime?: string;
  active?: boolean;
  state?: Record<string, unknown>;
  updatedAt?: string;
};

export type MentionTrigger = {
  start: number;
  end: number;
  query: string;
};

export type MentionSuggestion = {
  id: string;
  type: ComposerMentionKind;
  primary: string;
  secondary: string;
  token: string;
  mention: ComposerMention;
  score: number;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const PLAN_MODE_SYSTEM_PROMPT = [
  "The user enabled Plan Mode from the composer UI for this turn.",
  "Enter PlanMode before doing workspace-changing work.",
  "Research and inspect what is needed, then write a concrete plan and request approval instead of making changes.",
].join("\n");
export const TODO_DOCK_EXIT_MS = 280;
export const BROWSER_MENTION_RE = /(^|\s)(@Browser(?::([^\s"]+))?)/gi;
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
// Mention parsing + autocomplete helpers
// ---------------------------------------------------------------------------

export function mentionTriggerFromText(value: string, cursor: number): MentionTrigger | null {
  const beforeCursor = value.slice(0, cursor);
  const quoted = beforeCursor.match(/(^|\s)@"([^"]*)$/);
  if (quoted && quoted.index !== undefined) {
    return {
      start: quoted.index + (quoted[1]?.length ?? 0),
      end: cursor,
      query: quoted[2] ?? "",
    };
  }
  const regular = beforeCursor.match(/(^|\s)@([^\s"]*)$/);
  if (!regular || regular.index === undefined) return null;
  return {
    start: regular.index + (regular[1]?.length ?? 0),
    end: cursor,
    query: regular[2] ?? "",
  };
}

export function buildMentionSuggestions(
  workspaceSuggestions: WorkspaceMentionSuggestion[],
  skills: SkillSummary[],
  browserTabs: BrowserTabMentionSuggestion[],
  query: string,
  conversationId?: string,
): MentionSuggestion[] {
  const normalizedQuery = query.trim().toLowerCase();
  const skillQuery = normalizedQuery.startsWith("skill:")
    ? normalizedQuery.slice("skill:".length)
    : normalizedQuery;
  const browserQuery = browserMentionQueryFromText(query);
  const includeBrowser = browserQuery !== null;
  const includeWorkspace = !normalizedQuery.startsWith("skill:") && !includeBrowser;
  const includeSkills = !includeBrowser && (
    normalizedQuery.startsWith("skill:")
    || normalizedQuery === ""
    || "skill".startsWith(normalizedQuery)
    || skills.some((skill) => skill.invocation_name.toLowerCase().includes(normalizedQuery))
  );

  const fileItems = includeWorkspace
    ? workspaceSuggestions.map((item) => mentionSuggestionFromWorkspace(item))
    : [];
  const skillItems = includeSkills
    ? skills
      .filter((skill) => skill.enabled)
      .filter((skill) => {
        if (!skillQuery) return true;
        const haystack = `${skill.invocation_name} ${skill.name} ${skill.description}`.toLowerCase();
        return haystack.includes(skillQuery);
      })
      .slice(0, 20)
      .map((skill, index) => mentionSuggestionFromSkill(skill, index))
    : [];
  const browserItems = includeBrowser
    ? [
        ...browserTabs.map((tab) => mentionSuggestionFromBrowserTab(tab)),
        browserTargetMentionSuggestion(query, conversationId),
      ].filter((item): item is MentionSuggestion => Boolean(item))
    : [];

  return [...browserItems, ...fileItems, ...skillItems]
    .sort((left, right) => left.score - right.score || left.primary.localeCompare(right.primary))
    .slice(0, 12);
}

export function browserMentionQueryFromText(query: string): string | null {
  const normalized = query.trim();
  const lower = normalized.toLowerCase();
  if (lower.startsWith("browser:")) return normalized.slice("browser:".length);
  if (lower === "browser") return "";
  if (normalized && "browser".startsWith(lower)) return "";
  return null;
}

export function mentionSuggestionFromBrowserTab(tab: BrowserTabMentionSuggestion, tokenOverride?: string): MentionSuggestion {
  const domain = tab.domain || domainFromUrl(tab.url || "") || "tab";
  const token = tokenOverride || tab.token || `@Browser:${domain}`;
  const mention: ComposerMention = {
    id: tab.id || `browser_tab:${tab.browser_id}:${tab.page_id || tab.tab_id}`,
    type: "browser_tab",
    label: "@Browser",
    token,
    displayPath: tab.display_path || tab.title || tab.url || domain,
    browserId: tab.browser_id,
    tabId: tab.tab_id,
    pageId: tab.page_id || tab.tab_id,
    windowId: tab.window_id || tab.page_id || tab.tab_id,
    url: tab.url,
    title: tab.title,
    runtime: tab.runtime,
    active: Boolean(tab.active || tab.is_active),
    state: tab.state,
    updatedAt: tab.updated_at,
  };
  return {
    id: mention.id,
    type: mention.type,
    primary: tab.title || domain,
    secondary: `${tab.active || tab.is_active ? "Active browser tab" : "Browser tab"} - ${tab.url || tab.page_id}`,
    token,
    mention,
    score: tab.score,
  };
}

export function browserTargetMentionSuggestion(query: string, conversationId?: string): MentionSuggestion | null {
  const target = browserMentionQueryFromText(query);
  if (target === null) return null;
  const token = target ? `@Browser:${target}` : "@Browser";
  const mention = mentionFromBrowserTarget(target, token, conversationId);
  return {
    id: mention.id,
    type: mention.type,
    primary: target ? `Browser: ${target}` : "Browser",
    secondary: target ? "Open or target this URL in the shared Browser window" : "Shared Browser window",
    token,
    mention,
    score: target ? 1.25 : 0.25,
  };
}

export function mentionFromBrowserTarget(target: string, token: string, conversationId?: string): ComposerMention {
  const normalizedTarget = target.trim();
  const url = normalizeBrowserMentionUrl(normalizedTarget);
  const displayPath = normalizedTarget ? url || normalizedTarget : "Shared Browser window";
  const targetId = normalizedTarget
    ? normalizedTarget.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || "target"
    : "active";
  return {
    id: `browser_tab:${conversationId || "pending"}:${targetId}`,
    type: "browser_tab",
    label: "@Browser",
    token,
    displayPath,
    browserId: conversationId,
    url,
    title: normalizedTarget ? `Browser target: ${normalizedTarget}` : "Shared Browser window",
    active: !normalizedTarget,
  };
}

export function mentionSuggestionFromWorkspace(item: WorkspaceMentionSuggestion): MentionSuggestion {
  const token = mentionTokenForPath(item.display_path);
  const label = item.is_directory ? "@Directory" : "@File";
  const mention: ComposerMention = {
    id: `${item.type}:${item.path}`,
    type: item.is_directory ? "directory" : "file",
    label,
    token,
    displayPath: item.display_path,
    fileName: item.is_directory ? undefined : item.name,
    filePath: item.is_directory ? undefined : item.path,
    directoryPath: item.is_directory ? item.path : undefined,
  };
  return {
    id: mention.id,
    type: mention.type,
    primary: item.display_path,
    secondary: item.is_directory ? "Directory" : "File",
    token,
    mention,
    score: item.score,
  };
}

export function mentionSuggestionFromSkill(skill: SkillSummary, index: number): MentionSuggestion {
  const token = `@skill:${skill.invocation_name}`;
  const mention: ComposerMention = {
    id: `skill:${skill.invocation_name}`,
    type: "skill",
    label: token,
    token,
    displayPath: skill.path,
    name: skill.name,
    invocationName: skill.invocation_name,
    slashName: skill.slash_name,
    description: skill.description,
    path: skill.path,
    source: skill.source,
  };
  return {
    id: mention.id,
    type: "skill",
    primary: token,
    secondary: skill.description || skill.name,
    token,
    mention,
    score: 2.5 + index * 0.01,
  };
}

// ---------------------------------------------------------------------------
// Browser mention resolution helpers
// ---------------------------------------------------------------------------

export function autoResolveBrowserMentions(
  value: string,
  mentions: ComposerMention[],
  browserTabs: BrowserTabMentionSuggestion[],
  conversationId?: string,
): ComposerMention[] {
  const selectedBrowserMentions = mentions.filter((mention) => mention.type === "browser_tab");
  const parsedBrowserMentions = browserMentionsFromText(
    value,
    browserTabs,
    selectedBrowserMentions,
    conversationId,
  );
  if (parsedBrowserMentions.length > 0) {
    return dedupeMentions([
      ...mentions.filter((mention) => mention.type !== "browser_tab"),
      ...parsedBrowserMentions,
    ]);
  }
  return mentions;
}

export function domainFromUrl(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

export function browserMentionsFromText(
  value: string,
  browserTabs: BrowserTabMentionSuggestion[],
  selectedBrowserMentions: ComposerMention[],
  conversationId?: string,
): ComposerMention[] {
  const mentions: ComposerMention[] = [];
  const seen = new Set<string>();
  for (const match of value.matchAll(BROWSER_MENTION_RE)) {
    const token = match[2] || "";
    if (!token || seen.has(token.toLowerCase())) continue;
    seen.add(token.toLowerCase());
    const target = (match[3] || "").trim();
    const selectedMention = findSelectedBrowserMention(token, target, selectedBrowserMentions);
    if (selectedMention) {
      mentions.push(selectedMention);
      continue;
    }
    const matchedTab = target
      ? findBrowserTabMention(target, browserTabs)
      : browserTabs.find((tab) => tab.active || tab.is_active) || browserTabs[0];
    mentions.push(
      matchedTab
        ? mentionSuggestionFromBrowserTab(matchedTab, token).mention
        : mentionFromBrowserTarget(target, token, conversationId),
    );
  }
  return mentions;
}

export function findSelectedBrowserMention(
  token: string,
  target: string,
  selectedBrowserMentions: ComposerMention[],
) {
  const normalizedToken = token.toLowerCase();
  const normalizedTarget = target.trim().toLowerCase();
  return selectedBrowserMentions.find((mention) => {
    if (mention.token.toLowerCase() === normalizedToken) return true;
    if (!normalizedTarget) return false;
    const domain = domainFromUrl(mention.url || "").toLowerCase();
    const haystack = [domain, mention.url, mention.title, mention.displayPath, mention.pageId, mention.tabId, mention.windowId]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return domain === normalizedTarget || domain.startsWith(normalizedTarget) || haystack.includes(normalizedTarget);
  });
}

export function findBrowserTabMention(target: string, browserTabs: BrowserTabMentionSuggestion[]) {
  const normalized = target.trim().toLowerCase();
  if (!normalized) return undefined;
  return browserTabs.find((tab) => {
    const domain = (tab.domain || domainFromUrl(tab.url || "")).toLowerCase();
    const haystack = [domain, tab.url, tab.title, tab.page_id, tab.tab_id, tab.window_id]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return domain === normalized || domain.startsWith(normalized) || haystack.includes(normalized);
  });
}

export function normalizeBrowserMentionUrl(target: string) {
  const trimmed = target.trim();
  if (!trimmed) return undefined;
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(withScheme);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return undefined;
    if (!parsed.hostname || (!parsed.hostname.includes(".") && parsed.hostname !== "localhost")) return undefined;
    return parsed.toString();
  } catch {
    return undefined;
  }
}

export function dedupeMentions(mentions: ComposerMention[]) {
  const seen = new Set<string>();
  return mentions.filter((mention) => {
    const key = `${mention.type}:${mention.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function mentionTokenForPath(displayPath: string) {
  const normalized = displayPath.replace(/"/g, '\\"');
  return /\s/.test(displayPath) ? `@"${normalized}"` : `@${normalized}`;
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
