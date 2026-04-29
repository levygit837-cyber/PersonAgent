import { ArrowUp, BookOpen, Brain, ChevronDown, ChevronRight, ChevronUp, Command, FileText, Folder, LogOut, Plus, Sparkles, Square, Terminal, UsersRound, X } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../ui/tooltip";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { getCodexAuthStatus, listChatCommands, listModels, listSkills, listWorkspaceMentions, logoutCodex, type WorkspaceMentionSuggestion } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore, type ComposerAnnotation } from "../../stores/chat-store";
import { useTerminalStore, type TerminalSnippet } from "../../stores/terminal-store";
import { localModel, reasoningPresets, type ChatCommandInfo, type ChatMessageUi, type ContextAttachment, type LlmModel, type ModelProvider, type ReasoningPreset, type SkillSummary, type ToolBlockStatus, type ToolBlockUi } from "../../types/chat";
import { BranchSwitcherButton } from "../git/branch-switcher-button";
import { Button } from "../ui/button";
import { isTodoTool, todoItems, type TodoItem } from "./tool-block";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

type ModelOption = {
  id: string;
  provider: ModelProvider;
  label: string;
  group: string;
  contextLength?: number;
};

const DEEPSEEK_API_GROUP = "DeepSeek API";
const DEEPSEEK_NVIDIA_GROUP = "DeepSeek NVIDIA";
const MODEL_CATALOG_STALE_MS = 10 * 60_000;
const CODEX_AUTH_STALE_MS = 2 * 60_000;

type ComposerMentionKind = "file" | "directory" | "skill";

type ComposerMention = {
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
};

type MentionTrigger = {
  start: number;
  end: number;
  query: string;
};

type MentionSuggestion = {
  id: string;
  type: ComposerMentionKind;
  primary: string;
  secondary: string;
  token: string;
  mention: ComposerMention;
  score: number;
};

const curatedHostedModels: ModelOption[] = [
  { id: "kimi-for-coding", provider: "kimi", label: "Kimi K2.6", group: "Kimi Code", contextLength: 262144 },
  { id: "gpt-5.5", provider: "codex", label: "GPT-5.5", group: "ChatGPT Subscription", contextLength: 272000 },
  { id: "gpt-5.4-mini", provider: "codex", label: "GPT-5.4-Mini", group: "ChatGPT Subscription", contextLength: 272000 },
  { id: "qwen/qwen3.5-397b-a17b", provider: "nvidia", label: "Qwen3.5-397B", group: "Qwen" },
  { id: "qwen/qwen3-coder-480b-a35b-instruct", provider: "nvidia", label: "Qwen3 Coder 480B", group: "Qwen" },
  { id: "minimaxai/minimax-m2.5", provider: "nvidia", label: "Minimax M2.5", group: "Minimax" },
  { id: "moonshotai/kimi-k2.5", provider: "nvidia", label: "Kimi K2.5", group: "Moonshot" },
  { id: "deepseek-v4-flash", provider: "deepseek", label: "DeepSeek V4 Flash", group: DEEPSEEK_API_GROUP },
  { id: "deepseek-v4-pro", provider: "deepseek", label: "DeepSeek V4 Pro", group: DEEPSEEK_API_GROUP },
  { id: "deepseek-ai/deepseek-v4-flash", provider: "nvidia", label: "DeepSeek V4 Flash", group: DEEPSEEK_NVIDIA_GROUP },
  { id: "deepseek-ai/deepseek-v4-pro", provider: "nvidia", label: "DeepSeek V4 Pro", group: DEEPSEEK_NVIDIA_GROUP },
  { id: "gemini-3.1-pro-preview", provider: "vertex", label: "Gemini 3.1 Pro", group: "Google Vertex" },
  { id: "gemini-3.1-pro-preview-customtools", provider: "vertex", label: "Gemini 3.1 Pro Custom Tools", group: "Google Vertex" },
  { id: "gemini-3.1-flash-lite-preview", provider: "vertex", label: "Gemini 3.1 Flash-Lite", group: "Google Vertex" },
  { id: "gemini-3.1-flash-image-preview", provider: "vertex", label: "Gemini 3.1 Flash Image", group: "Google Vertex" },
  { id: "gemini-3-flash-preview", provider: "vertex", label: "Gemini 3 Flash", group: "Google Vertex" },
  { id: "gemini-3-pro-image-preview", provider: "vertex", label: "Gemini 3 Pro Image", group: "Google Vertex" },
];

const modelGroupOrder = [
  "Local",
  "Kimi Code",
  "ChatGPT Subscription",
  "OpenAI",
  "Qwen",
  "Minimax",
  "Moonshot",
  DEEPSEEK_API_GROUP,
  DEEPSEEK_NVIDIA_GROUP,
  "Google Vertex",
  "NVIDIA",
  "Mistral",
  "Meta",
  "Google",
  "Microsoft",
  "IBM",
  "Writer",
  "Other",
];

const ICONIFY_BASE = "https://api.iconify.design/simple-icons";

const GROUP_ICON_SLUG: Record<string, string> = {
  Local: "ollama",
  "Kimi Code": "moonshotai",
  "ChatGPT Subscription": "openai",
  OpenAI: "openai",
  Qwen: "qwen",
  Minimax: "minimax",
  Moonshot: "moonshotai",
  [DEEPSEEK_API_GROUP]: "deepseek",
  [DEEPSEEK_NVIDIA_GROUP]: "nvidia",
  "Google Vertex": "google",
  NVIDIA: "nvidia",
  Mistral: "mistralai",
  Meta: "meta",
  Google: "google",
  Microsoft: "microsoft",
  IBM: "ibm",
};
const TODO_DOCK_EXIT_MS = 280;

function providerIconUrl(group: string): string | null {
  const slug = GROUP_ICON_SLUG[group];
  if (!slug) return null;
  return `${ICONIFY_BASE}/${slug}.svg?color=white`;
}

function ProviderIcon({ group, className }: { group: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  const url = providerIconUrl(group);

  useEffect(() => {
    setFailed(false);
  }, [url]);

  if (!url || failed) {
    return <Brain className={className || "h-3.5 w-3.5 shrink-0 text-muted-foreground/70"} />;
  }
  return (
    <img
      key={url}
      src={url}
      alt=""
      className={className || "h-3.5 w-3.5 shrink-0 object-contain"}
      onError={() => setFailed(true)}
    />
  );
}

export function InputDock({
  compact = false,
  workspaceRoot,
}: {
  compact?: boolean;
  workspaceRoot?: string | null;
}) {
  const [text, setText] = useState("");
  const [cursorPosition, setCursorPosition] = useState(0);
  const [selectedMentions, setSelectedMentions] = useState<ComposerMention[]>([]);
  const [selectedMentionIndex, setSelectedMentionIndex] = useState(0);
  const [dismissedMentionKey, setDismissedMentionKey] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const sendMessage = useChatStore((state) => state.sendMessage);
  const stopStreaming = useChatStore((state) => state.stopStreaming);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const nextStepSuggestion = useChatStore((state) => state.nextStepSuggestion);
  const composerAnnotations = useChatStore((state) => state.composerAnnotations);
  const removeComposerAnnotation = useChatStore((state) => state.removeComposerAnnotation);
  const clearComposerAnnotations = useChatStore((state) => state.clearComposerAnnotations);
  const pendingSnippet = useTerminalStore((state) => state.pendingSnippet);
  const clearPendingSnippet = useTerminalStore((state) => state.clearPendingSnippet);
  const snippetNonce = useTerminalStore((state) => state.snippetNonce);
  const baseUrl = useAppStore((state) => state.baseUrl);
  const globalSelectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const paneWorkspaceRoot = useChatStore((state) => state.workspaceRoot);
  const selectedWorkspace = workspaceRoot || paneWorkspaceRoot || globalSelectedWorkspace;
  const disabled = isStreaming;
  const slashToken = slashTokenFromText(text);
  const mentionTrigger = mentionTriggerFromText(text, cursorPosition);
  const mentionKey = mentionTrigger ? `${mentionTrigger.start}:${mentionTrigger.end}:${mentionTrigger.query}:${text}` : null;
  const mentionOpen = Boolean(mentionTrigger && mentionKey !== dismissedMentionKey);
  const slashCommands = useQuery({
    queryKey: ["chat-commands", baseUrl, selectedWorkspace],
    queryFn: () => listChatCommands(baseUrl, selectedWorkspace),
    enabled: !disabled && Boolean(baseUrl) && slashToken !== null,
    staleTime: 30_000,
  });
  const workspaceMentionSuggestions = useQuery({
    queryKey: ["workspace-mentions", baseUrl, selectedWorkspace, mentionTrigger?.query ?? ""],
    queryFn: () => listWorkspaceMentions(baseUrl, mentionTrigger?.query ?? "", selectedWorkspace || ""),
    enabled: !disabled && mentionOpen && Boolean(baseUrl) && Boolean(selectedWorkspace),
    staleTime: 5_000,
  });
  const skillMentionSuggestions = useQuery({
    queryKey: ["skills", baseUrl, selectedWorkspace, "mention"],
    queryFn: () => listSkills(baseUrl, selectedWorkspace),
    enabled: !disabled && mentionOpen && Boolean(baseUrl),
    staleTime: 30_000,
  });
  const commandMatches = filterSlashCommands(slashCommands.data ?? [], slashToken);
  const mentionSuggestions = useMemo(
    () => buildMentionSuggestions(
      workspaceMentionSuggestions.data ?? [],
      skillMentionSuggestions.data ?? [],
      mentionTrigger?.query ?? "",
    ),
    [mentionTrigger?.query, skillMentionSuggestions.data, workspaceMentionSuggestions.data],
  );
  const visibleMentionSuggestions = mentionOpen ? mentionSuggestions : [];
  const canSend = Boolean(text.trim()) || selectedMentions.length > 0 || composerAnnotations.length > 0 || Boolean(pendingSnippet);

  const syncCursorPosition = () => {
    const el = textareaRef.current;
    if (!el) return;
    setCursorPosition(el.selectionStart ?? el.value.length);
  };

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 148)}px`;
  }, [text]);

  useEffect(() => {
    if (!pendingSnippet) return;
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [snippetNonce, pendingSnippet?.id]);

  useEffect(() => {
    setSelectedMentionIndex(0);
  }, [mentionTrigger?.query, mentionOpen]);

  useEffect(() => {
    if (dismissedMentionKey && dismissedMentionKey !== mentionKey) {
      setDismissedMentionKey(null);
    }
  }, [dismissedMentionKey, mentionKey]);

  useEffect(() => {
    setSelectedMentions((mentions) => mentions.filter((mention) => text.includes(mention.token)));
  }, [text]);

  const pickMentionSuggestion = (suggestion: MentionSuggestion) => {
    if (!mentionTrigger) return;
    const before = text.slice(0, mentionTrigger.start);
    const after = text.slice(mentionTrigger.end);
    const replacement = `${suggestion.token} `;
    const nextText = `${before}${replacement}${after}`;
    const nextCursor = before.length + replacement.length;
    setText(nextText);
    setSelectedMentions((mentions) => {
      const withoutDuplicate = mentions.filter((mention) => mention.id !== suggestion.mention.id);
      return [...withoutDuplicate, suggestion.mention];
    });
    setDismissedMentionKey(null);
    setCursorPosition(nextCursor);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  };

  const removeMention = (mention: ComposerMention) => {
    setSelectedMentions((mentions) => mentions.filter((item) => item.id !== mention.id));
    setText((current) => current.replace(mention.token, "").replace(/[ \t]{2,}/g, " "));
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const submit = () => {
    if (isStreaming) {
      stopStreaming();
      textareaRef.current?.focus();
      return;
    }
    const value = text.trim();
    if (!value && selectedMentions.length === 0 && composerAnnotations.length === 0 && !pendingSnippet) return;
    const { requestAttachments, displayAttachments } = buildComposerContextAttachments(
      composerAnnotations,
      pendingSnippet,
      selectedMentions,
    );
    const visibleMessage = value || attachmentOnlyMessage(composerAnnotations, pendingSnippet, selectedMentions);
    const sendOptions = requestAttachments.length
      ? { contextAttachments: requestAttachments, displayAttachments }
      : undefined;
    void sendMessage(visibleMessage, undefined, sendOptions);
    setText("");
    setCursorPosition(0);
    setSelectedMentions([]);
    clearComposerAnnotations();
    clearPendingSnippet();
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  return (
    <div className={compact ? "pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-3 pb-3" : "pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-5 pb-5"}>
      <div className={compact ? "flex w-full max-w-[680px] flex-col gap-0" : "flex w-full max-w-[780px] flex-col gap-0"} data-testid="input-dock-stack">
        <InputTodoDock />
        <div
          className="personagent-input-composer pointer-events-auto w-full overflow-hidden rounded-2xl border border-glass-border/35 bg-card/90 shadow-dock ring-1 ring-primary/10 backdrop-blur-2xl"
          data-testid="input-composer"
        >
          <ComposerAssist
            disabled={disabled}
            nextStepSuggestion={!text.trim() && composerAnnotations.length === 0 ? nextStepSuggestion : undefined}
            slashToken={slashToken}
            commands={commandMatches}
            mentionSuggestions={visibleMentionSuggestions}
            selectedMentionIndex={selectedMentionIndex}
            onPickSuggestion={(value) => {
              if (!value.trim()) return;
              void sendMessage(value);
            }}
            onPickCommand={(command) => {
              setText(`${command.slash_name} `);
              requestAnimationFrame(() => textareaRef.current?.focus());
            }}
            onPickMention={pickMentionSuggestion}
          />
          <ComposerAnnotationTray annotations={composerAnnotations} onRemove={removeComposerAnnotation} />
          <ComposerMentionTray mentions={selectedMentions} onRemove={removeMention} />
          <TerminalSnippetTray snippet={pendingSnippet} onRemove={clearPendingSnippet} />
          <div className={compact ? "flex items-end gap-1.5 px-2 py-2" : "flex items-end gap-2 px-2.5 py-2.5 sm:gap-2.5 sm:px-3"}>
            <FeatureMenu enabled={!disabled} />
            <BranchSwitcherButton enabled={!disabled} workspaceRoot={selectedWorkspace} compact={compact} />
            <textarea
              ref={textareaRef}
              value={text}
              disabled={disabled}
              rows={1}
              placeholder="Ask the local agent..."
              onChange={(event) => {
                setText(event.currentTarget.value);
                setCursorPosition(event.currentTarget.selectionStart ?? event.currentTarget.value.length);
              }}
              onClick={syncCursorPosition}
              onKeyUp={syncCursorPosition}
              onSelect={syncCursorPosition}
              onKeyDown={(event) => {
                if (visibleMentionSuggestions.length > 0) {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setSelectedMentionIndex((index) => (index + 1) % visibleMentionSuggestions.length);
                    return;
                  }
                  if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setSelectedMentionIndex((index) => (index - 1 + visibleMentionSuggestions.length) % visibleMentionSuggestions.length);
                    return;
                  }
                  if (event.key === "Tab" || event.key === "Enter") {
                    event.preventDefault();
                    const suggestion = visibleMentionSuggestions[selectedMentionIndex] ?? visibleMentionSuggestions[0];
                    if (suggestion) pickMentionSuggestion(suggestion);
                    return;
                  }
                  if (event.key === "Escape") {
                    event.preventDefault();
                    setDismissedMentionKey(mentionKey);
                    return;
                  }
                }
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
              className={compact ? "min-h-9 min-w-0 flex-1 resize-none bg-transparent px-1 py-1.5 text-[13px] leading-5 text-foreground outline-none placeholder:text-muted-foreground/80 disabled:opacity-60" : "min-h-10 min-w-0 flex-1 resize-none bg-transparent px-1 py-2 text-[15px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/80 disabled:opacity-60"}
            />
            <ModelReasoningSelector enabled={!disabled} />
            {compact ? null : <ContextWindowIndicator />}
            <Button
              size="icon"
              variant={isStreaming ? "destructive" : canSend ? "default" : "secondary"}
              disabled={!isStreaming && !canSend}
              onClick={submit}
              aria-label={isStreaming ? "Stop" : "Send"}
              className="h-10 w-10 rounded-xl"
            >
              {isStreaming ? <Square className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TerminalSnippetTray({
  snippet,
  onRemove,
}: {
  snippet: { id: string; content: string } | null;
  onRemove: () => void;
}) {
  if (!snippet) return null;

  return (
    <div className="flex flex-col gap-1.5 overflow-y-auto border-b border-glass-border/20 px-3 py-2">
      <div className="group flex min-w-0 items-center gap-2 rounded-xl border border-primary/25 bg-primary/10 px-2.5 py-2 text-left ring-1 ring-primary/10">
        <span className="shrink-0 rounded-md bg-primary/20 px-2 py-1 font-mono text-[11px] font-semibold text-primary">
          <Terminal className="inline h-3 w-3" />
          {" "}@terminal:bash
        </span>
        <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
          {snippet.content.slice(0, 120).replace(/\n/g, " ")}
          {snippet.content.length > 120 ? "..." : ""}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          aria-label="Remover terminal snippet"
          onClick={onRemove}
          className="h-6 w-6 shrink-0 rounded-lg opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
        >
          <X className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

function ComposerAnnotationTray({
  annotations,
  onRemove,
}: {
  annotations: ComposerAnnotation[];
  onRemove: (id: number) => void;
}) {
  if (annotations.length === 0) return null;

  return (
    <div
      data-testid="composer-annotations"
      className="flex max-h-28 flex-col gap-1.5 overflow-y-auto border-b border-glass-border/20 px-3 py-2"
    >
      {annotations.map((annotation) => (
        <div
          key={annotation.id}
          className="group flex min-w-0 items-center gap-2 rounded-xl border border-glass-border/35 bg-foreground/[0.045] px-2.5 py-2 text-left ring-1 ring-white/[0.035]"
          title={annotation.filePath}
        >
          <span className="shrink-0 rounded-md bg-foreground/[0.08] px-2 py-1 font-mono text-[11px] font-semibold text-foreground">
            @Annotation#{annotation.id}
          </span>
          <span className="min-w-0 truncate rounded-md bg-background/45 px-2 py-1 font-mono text-[11px] text-foreground/90">
            {annotation.displayPath}
          </span>
          <span className="shrink-0 rounded-md bg-background/45 px-2 py-1 font-mono text-[11px] text-muted-foreground">
            {annotation.source === "browser" ? "DOM" : `L${formatLineRange(annotation.startLine, annotation.endLine)}`}
          </span>
          <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
            {annotation.text}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            aria-label={`Remove @Annotation#${annotation.id}`}
            onClick={() => onRemove(annotation.id)}
            className="h-6 w-6 shrink-0 rounded-lg opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      ))}
    </div>
  );
}

function ComposerMentionTray({
  mentions,
  onRemove,
}: {
  mentions: ComposerMention[];
  onRemove: (mention: ComposerMention) => void;
}) {
  if (mentions.length === 0) return null;

  return (
    <div
      data-testid="composer-mentions"
      className="flex max-h-24 flex-wrap gap-1.5 overflow-y-auto border-b border-glass-border/20 px-3 py-2"
    >
      {mentions.map((mention) => (
        <div
          key={mention.id}
          className="group flex min-w-0 max-w-full items-center gap-2 rounded-xl border border-primary/25 bg-primary/10 px-2.5 py-1.5 text-left ring-1 ring-primary/10"
          title={mention.displayPath}
        >
          <MentionSuggestionIcon type={mention.type} />
          <span className="shrink-0 rounded-md bg-primary/15 px-2 py-1 font-mono text-[11px] font-semibold text-primary">
            {mention.label}
          </span>
          <span className="min-w-0 truncate rounded-md bg-background/45 px-2 py-1 font-mono text-[11px] text-foreground/90">
            {mention.displayPath}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            aria-label={`Remove ${mention.label}`}
            onClick={() => onRemove(mention)}
            className="h-6 w-6 shrink-0 rounded-lg opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      ))}
    </div>
  );
}

type TodoDockSnapshot = {
  key: string;
  toolName: string;
  updateCount: number;
  status: ToolBlockStatus;
  todos: TodoItem[];
};

function InputTodoDock() {
  const messages = useChatStore((state) => state.messages);
  const activeAgentId = useChatStore((state) => state.activeAgentId);
  const isExecuting = useChatStore((state) => state.isStreaming || state.isFinalizing);
  const liveSnapshot = useMemo(() => latestTodoSnapshot(messages, activeAgentId), [messages, activeAgentId]);
  const [displaySnapshot, setDisplaySnapshot] = useState<TodoDockSnapshot | undefined>();
  const [exiting, setExiting] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [restoring, setRestoring] = useState(false);

  useEffect(() => {
    if (isExecuting && liveSnapshot) {
      setDisplaySnapshot(liveSnapshot);
      setExiting(false);
    }
  }, [isExecuting, liveSnapshot]);

  useEffect(() => {
    if (isExecuting || !displaySnapshot || exiting) return;
    setExiting(true);
  }, [displaySnapshot, exiting, isExecuting]);

  useEffect(() => {
    if (!exiting) return undefined;
    const timer = window.setTimeout(() => {
      setDisplaySnapshot(undefined);
      setExiting(false);
    }, TODO_DOCK_EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [exiting]);

  useEffect(() => {
    if (!restoring) return undefined;
    const timer = window.setTimeout(() => setRestoring(false), 240);
    return () => window.clearTimeout(timer);
  }, [restoring]);

  if (!displaySnapshot) return null;

  return (
    <TodoDockPanel
      snapshot={displaySnapshot}
      exiting={exiting}
      minimized={minimized}
      restoring={restoring}
      onToggleMinimized={() => {
        setMinimized((value) => {
          if (value) setRestoring(true);
          return !value;
        });
      }}
      onExitComplete={() => {
        if (!exiting) return;
        setDisplaySnapshot(undefined);
        setExiting(false);
      }}
    />
  );
}

function TodoDockPanel({
  snapshot,
  exiting,
  minimized,
  restoring,
  onToggleMinimized,
  onExitComplete,
}: {
  snapshot: TodoDockSnapshot;
  exiting: boolean;
  minimized: boolean;
  restoring: boolean;
  onToggleMinimized: () => void;
  onExitComplete: () => void;
}) {
  const completed = snapshot.todos.filter((todo) => todo.status === "completed").length;
  const active = snapshot.todos.find((todo) => todo.status === "in_progress");
  const progressLabel = `${completed}/${snapshot.todos.length}`;
  return (
    <section
      className={`${exiting ? "personagent-todo-exit" : "personagent-todo-rise"} ${minimized ? "is-minimized" : restoring ? "is-restoring" : ""} personagent-input-todo-dock personagent-todo-panel pointer-events-auto overflow-hidden rounded-t-2xl rounded-b-none border border-b-0 border-glass-border/35 bg-card/90 shadow-dock ring-1 ring-primary/10 backdrop-blur-2xl`}
      aria-label="Todo tracker"
      data-testid="input-todo-tracker"
      data-state={exiting ? "exiting" : minimized ? "minimized" : "visible"}
      onAnimationEnd={() => {
        if (exiting) onExitComplete();
      }}
    >
      <div className="flex min-w-0 items-center justify-between gap-2 border-b border-glass-border/20 px-2.5 py-1.5">
        <div className="flex min-w-0 items-center gap-1.5">
          <TodoDockStatusDot status={snapshot.status} />
          <div className="min-w-0">
            <div className="truncate font-mono text-[10px] font-semibold uppercase text-foreground">
              {minimized ? `Todos ${progressLabel}` : "Todos"}
            </div>
            <div className={`${minimized ? "hidden" : "block"} truncate font-mono text-[9px] text-muted-foreground`}>
              {snapshot.toolName}
              {snapshot.updateCount > 1 ? ` - ${snapshot.updateCount} updates` : ""}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <div className="rounded-full border border-glass-border/30 bg-background/40 px-1.5 py-0 font-mono text-[9px] leading-4 text-muted-foreground">
            {minimized ? progressLabel : snapshot.status === "running" || snapshot.status === "queued" ? "updating" : `${progressLabel} done`}
          </div>
          <button
            type="button"
            className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-glass/80 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/60"
            aria-label={minimized ? "Restore Todo tracker" : "Minimize Todo tracker"}
            onClick={onToggleMinimized}
          >
            {minimized ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
        </div>
      </div>
      <ul className={`${minimized ? "max-h-0 py-0 opacity-0" : "max-h-24 py-0.5 opacity-100"} personagent-input-todo-scroll overflow-y-auto overscroll-contain transition-[max-height,opacity,padding] duration-200 ease-out`} data-testid="input-todo-scroll">
        {snapshot.todos.map((todo, index) => (
          <li
            key={todo.id || `${todo.content}-${index}`}
            className="personagent-todo-item grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-1.5 border-b border-glass-border/15 px-2.5 py-1 last:border-0"
            style={{ animationDelay: `${Math.min(index * 24, 144)}ms` }}
          >
            <span className="pt-[5px]">
              <span
                className={`personagent-todo-dot inline-flex h-2 w-2 shrink-0 rounded-full ${todo.status === "completed" ? "bg-success" : "bg-warning"}`}
                data-status={todo.status}
                aria-label={todoStatusLabel(todo.status)}
              />
            </span>
            <span
              className={
                todo.status === "completed"
                  ? "min-w-0 break-words text-[11px] leading-4 text-muted-foreground/70 line-through decoration-success/50"
                  : "min-w-0 break-words text-[11px] leading-4 text-foreground/90"
              }
            >
              {todo.content}
            </span>
            {active?.id === todo.id ? (
              <span className="mt-px rounded-full border border-warning/25 px-1 py-0 font-mono text-[9px] leading-4 text-warning">active</span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function TodoDockStatusDot({ status }: { status: ToolBlockStatus }) {
  if (status === "running" || status === "queued") {
    return <span className="personagent-spinner h-1.5 w-1.5 shrink-0 text-primary/80" aria-hidden="true" />;
  }
  const color = status === "error" || status === "permission_required" ? "bg-destructive" : "bg-success";
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${color}`} aria-hidden="true" />;
}

function latestTodoSnapshot(messages: ChatMessageUi[], activeAgentId?: string): TodoDockSnapshot | undefined {
  const preferred = activeAgentId ? messages.find((message) => message.id === activeAgentId) : undefined;
  const message = preferred ?? [...messages].reverse().find((item) => item.role === "agent" && item.toolBlocks.some(isTodoTool));
  if (!message) return undefined;
  const blocks = message.toolBlocks.filter(isTodoTool);
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index];
    const todos = todoItems(block);
    if (todos.length === 0) continue;
    return {
      key: `${block.id}:${todos.map((todo) => `${todo.id}:${todo.status}:${todo.content}`).join("|")}`,
      toolName: block.name,
      updateCount: blocks.length,
      status: todoSnapshotStatus(blocks),
      todos,
    };
  }
  return undefined;
}

function todoSnapshotStatus(blocks: ToolBlockUi[]): ToolBlockStatus {
  if (blocks.some((block) => block.status === "error" || block.status === "permission_required")) return "error";
  if (blocks.some((block) => block.status === "running" || block.status === "queued")) return "running";
  return "completed";
}

function todoStatusLabel(status: TodoItem["status"]) {
  if (status === "completed") return "completed";
  if (status === "in_progress") return "in progress";
  return "pending";
}

function ComposerAssist({
  disabled,
  nextStepSuggestion,
  slashToken,
  commands,
  mentionSuggestions,
  selectedMentionIndex,
  onPickSuggestion,
  onPickCommand,
  onPickMention,
}: {
  disabled: boolean;
  nextStepSuggestion?: string;
  slashToken: string | null;
  commands: ChatCommandInfo[];
  mentionSuggestions: MentionSuggestion[];
  selectedMentionIndex: number;
  onPickSuggestion: (value: string) => void;
  onPickCommand: (command: ChatCommandInfo) => void;
  onPickMention: (suggestion: MentionSuggestion) => void;
}) {
  if (disabled) return null;
  if (mentionSuggestions.length > 0) {
    return (
      <div className="border-b border-glass-border/25 px-2 py-1.5">
        <div className="max-h-52 overflow-y-auto rounded-xl bg-background/70 p-1 text-popover-foreground">
          {mentionSuggestions.slice(0, 8).map((suggestion, index) => (
            <button
              key={suggestion.id}
              type="button"
              data-selected={index === selectedMentionIndex}
              onMouseDown={(event) => {
                event.preventDefault();
                onPickMention(suggestion);
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-glass/80 hover:text-accent-foreground data-[selected=true]:bg-glass/80 data-[selected=true]:text-accent-foreground"
            >
              <MentionSuggestionIcon type={suggestion.type} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{suggestion.primary}</span>
                <span className="block truncate text-muted-foreground">{suggestion.secondary}</span>
              </span>
              <span className="shrink-0 rounded-md border border-glass-border/35 bg-background/50 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                {suggestion.type}
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  }
  if (slashToken !== null) {
    if (commands.length === 0) return null;
    return (
      <div className="border-b border-glass-border/25 px-2 py-1.5">
        <div className="max-h-44 overflow-y-auto rounded-xl bg-background/70 p-1 text-popover-foreground">
          {commands.slice(0, 6).map((command) => (
            <button
              key={`${command.source}:${command.slash_name}`}
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                onPickCommand(command);
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-glass/80 hover:text-accent-foreground"
            >
              <Command className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{command.slash_name}</span>
                <span className="block truncate text-muted-foreground">
                  {command.argument_hint || command.description || command.source}
                </span>
              </span>
              <span className="shrink-0 rounded-md border border-glass-border/35 bg-background/50 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                {command.should_query === false ? "local" : "model"}
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  }
  if (!nextStepSuggestion) return null;
  return (
    <div className="border-b border-glass-border/25 px-2 py-1.5">
      <button
        type="button"
        onMouseDown={(event) => {
          event.preventDefault();
          onPickSuggestion(nextStepSuggestion);
        }}
        className="flex max-w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-glass/80 hover:text-accent-foreground"
      >
        <Sparkles className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{nextStepSuggestion}</span>
      </button>
    </div>
  );
}

function MentionSuggestionIcon({ type }: { type: ComposerMentionKind }) {
  if (type === "directory") return <Folder className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  if (type === "skill") return <BookOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  return <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
}

function slashTokenFromText(value: string) {
  const trimmed = value.trimStart();
  if (!trimmed.startsWith("/") || trimmed.includes("\n")) return null;
  const token = trimmed.split(/\s+/, 1)[0];
  return token;
}

function filterSlashCommands(commands: ChatCommandInfo[], slashToken: string | null) {
  if (slashToken === null) return [];
  const normalized = slashToken.toLowerCase();
  return commands
    .filter((command) => command.user_invocable && command.slash_name.toLowerCase().startsWith(normalized))
    .sort((left, right) => left.slash_name.localeCompare(right.slash_name));
}

function mentionTriggerFromText(value: string, cursor: number): MentionTrigger | null {
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

function buildMentionSuggestions(
  workspaceSuggestions: WorkspaceMentionSuggestion[],
  skills: SkillSummary[],
  query: string,
): MentionSuggestion[] {
  const normalizedQuery = query.trim().toLowerCase();
  const skillQuery = normalizedQuery.startsWith("skill:")
    ? normalizedQuery.slice("skill:".length)
    : normalizedQuery;
  const includeWorkspace = !normalizedQuery.startsWith("skill:");
  const includeSkills = normalizedQuery.startsWith("skill:")
    || normalizedQuery === ""
    || "skill".startsWith(normalizedQuery)
    || skills.some((skill) => skill.invocation_name.toLowerCase().includes(normalizedQuery));

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

  return [...fileItems, ...skillItems]
    .sort((left, right) => left.score - right.score || left.primary.localeCompare(right.primary))
    .slice(0, 12);
}

function mentionSuggestionFromWorkspace(item: WorkspaceMentionSuggestion): MentionSuggestion {
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

function mentionSuggestionFromSkill(skill: SkillSummary, index: number): MentionSuggestion {
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

function mentionTokenForPath(displayPath: string) {
  const normalized = displayPath.replace(/"/g, '\\"');
  return /\s/.test(displayPath) ? `@"${normalized}"` : `@${normalized}`;
}

function FeatureMenu({ enabled }: { enabled: boolean }) {
  const teamMode = useAppStore((state) => state.teamMode);
  const setTeamMode = useAppStore((state) => state.setTeamMode);
  const agentsBranchRef = useRef<HTMLDivElement | null>(null);
  const agentsCloseTimerRef = useRef<number | null>(null);
  const [agentsOpen, setAgentsOpen] = useState(false);
  const clearAgentsCloseTimer = () => {
    if (agentsCloseTimerRef.current) {
      window.clearTimeout(agentsCloseTimerRef.current);
      agentsCloseTimerRef.current = null;
    }
  };
  const openAgents = () => {
    clearAgentsCloseTimer();
    setAgentsOpen(true);
  };
  const scheduleAgentsClose = () => {
    clearAgentsCloseTimer();
    agentsCloseTimerRef.current = window.setTimeout(() => {
      setAgentsOpen(false);
      agentsCloseTimerRef.current = null;
    }, 180);
  };

  useEffect(() => clearAgentsCloseTimer, []);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          disabled={!enabled}
          aria-label="System features"
          title="System features"
          className="h-10 w-10 shrink-0 rounded-xl text-muted-foreground hover:text-foreground"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side="top"
        align="start"
        className="personagent-dropdown-fade personagent-feature-menu w-56 overflow-visible"
      >
        <DropdownMenuLabel>Features</DropdownMenuLabel>
        <div
          ref={agentsBranchRef}
          className="personagent-feature-branch relative"
          onPointerEnter={openAgents}
          onPointerLeave={scheduleAgentsClose}
          onFocus={openAgents}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              scheduleAgentsClose();
            }
          }}
        >
          <DropdownMenuItem
            aria-haspopup="menu"
            aria-expanded={agentsOpen}
            onSelect={(event) => event.preventDefault()}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setAgentsOpen(true);
              }
            }}
            className="h-8 justify-between gap-2"
          >
            <span className="flex min-w-0 items-center gap-2">
              <UsersRound className="h-3.5 w-3.5 text-muted-foreground" />
              <span>Agentes</span>
            </span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          </DropdownMenuItem>
          <div
            aria-hidden={!agentsOpen}
            className={[
              "personagent-feature-submenu-panel absolute bottom-0 left-[calc(100%+8px)] z-50 w-52 rounded-xl border",
              "border-glass-border/35 bg-popover/95 p-1 text-popover-foreground shadow-floating backdrop-blur-xl",
              agentsOpen ? "is-open" : "",
            ].join(" ")}
          >
            <DropdownMenuItem
              role="menuitemcheckbox"
              aria-checked={teamMode}
              onSelect={(event) => {
                event.preventDefault();
                setTeamMode(!teamMode);
              }}
              className="flex h-8 w-full cursor-default items-center justify-between gap-3 px-2 text-xs"
            >
              <span className="flex min-w-0 items-center gap-2">
                <UsersRound className="h-3.5 w-3.5 text-muted-foreground" />
                <span>Teams</span>
              </span>
              <span
                aria-hidden="true"
                className={[
                  "relative h-4 w-7 shrink-0 rounded-full transition-colors",
                  teamMode ? "bg-primary" : "bg-muted-foreground/[0.35]",
                ].join(" ")}
              >
                <span
                  className={[
                    "absolute left-0.5 top-0.5 h-3 w-3 rounded-full bg-foreground shadow-sm transition-transform",
                    teamMode ? "translate-x-3.5" : "translate-x-0",
                  ].join(" ")}
                />
              </span>
            </DropdownMenuItem>
          </div>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ModelReasoningSelector({ enabled }: { enabled: boolean }) {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const provider = useAppStore((state) => state.provider);
  const setProvider = useAppStore((state) => state.setProvider);
  const selectedModelId = useAppStore((state) => state.selectedModelId);
  const setSelectedModelId = useAppStore((state) => state.setSelectedModelId);
  const preset = useAppStore((state) => state.reasoningPreset);
  const setReasoningPreset = useAppStore((state) => state.setReasoningPreset);
  const [codexLogoutPending, setCodexLogoutPending] = useState(false);
  const localModels = useQuery({
    queryKey: ["models", baseUrl, "llama"],
    queryFn: () => listModels(baseUrl, "llama"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const hostedModels = useQuery({
    queryKey: ["models", baseUrl, "nvidia"],
    queryFn: () => listModels(baseUrl, "nvidia"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const deepSeekModels = useQuery({
    queryKey: ["models", baseUrl, "deepseek"],
    queryFn: () => listModels(baseUrl, "deepseek"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const vertexModels = useQuery({
    queryKey: ["models", baseUrl, "vertex"],
    queryFn: () => listModels(baseUrl, "vertex"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const kimiModels = useQuery({
    queryKey: ["models", baseUrl, "kimi"],
    queryFn: () => listModels(baseUrl, "kimi"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const codexModels = useQuery({
    queryKey: ["models", baseUrl, "codex"],
    queryFn: () => listModels(baseUrl, "codex"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const codexAuth = useQuery({
    queryKey: ["codex-auth", baseUrl],
    queryFn: () => getCodexAuthStatus(baseUrl),
    enabled: enabled && Boolean(baseUrl),
    staleTime: CODEX_AUTH_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const modelOptions = buildModelOptions(
    localModels.data,
    hostedModels.data,
    deepSeekModels.data,
    vertexModels.data,
    kimiModels.data,
    codexModels.data,
  );
  const selectedOption =
    modelOptions.find((item) => item.provider === provider && item.id === selectedModelId) ??
    modelOptions.find((item) => item.id === selectedModelId) ??
    toModelOption({ ...localModel, id: selectedModelId || localModel.id, name: selectedModelId || localModel.name, provider }, provider);
  const groupedModels = groupModelOptions(modelOptions);

  const selectModel = (option: ModelOption) => {
    if (option.provider !== provider) setProvider(option.provider);
    setSelectedModelId(option.id);
  };
  const handleCodexLogout = async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setCodexLogoutPending(true);
    try {
      await logoutCodex(baseUrl);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["codex-auth", baseUrl] }),
        queryClient.invalidateQueries({ queryKey: ["models", baseUrl, "codex"] }),
      ]);
    } finally {
      setCodexLogoutPending(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="subtle"
          size="default"
          disabled={!enabled}
          aria-label="Model and reasoning"
          className="h-10 min-w-[112px] max-w-[180px] shrink-0 justify-between gap-2 rounded-xl border-glass-border/35 bg-background/[0.45] px-3 text-xs shadow-soft hover:border-glass-border/50 hover:bg-glass/80 sm:max-w-[220px]"
        >
          <ProviderIcon key={selectedOption.group} group={selectedOption.group} className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{selectedOption.label}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="end" className="personagent-dropdown-fade w-72 rounded-2xl">
        <DropdownMenuLabel>Reasoning</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={preset} onValueChange={(value) => setReasoningPreset(value as ReasoningPreset)}>
          {reasoningPresets.map((item) => (
            <DropdownMenuRadioItem key={item.value} value={item.value}>
              {item.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <div className="px-2 py-1.5">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="flex min-w-0 items-center gap-2 font-medium">
              <ProviderIcon group="ChatGPT Subscription" />
              <span className="truncate">ChatGPT Subscription</span>
            </span>
            <span className={codexAuth.data?.authenticated ? "text-emerald-400" : "text-muted-foreground"}>
              {codexAuth.isLoading
                ? "Checking"
                : codexAuth.data?.authenticated
                  ? "Connected"
                  : "Disconnected"}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span className="min-w-0 truncate">
              {codexAuth.data?.authenticated
                ? codexAuth.data.email || codexAuth.data.account_id || "Codex CLI"
                : codexAuth.data?.error || "Run codex login"}
            </span>
            <button
              type="button"
              disabled={codexLogoutPending || !codexAuth.data?.authenticated}
              onClick={handleCodexLogout}
              className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-muted-foreground hover:bg-glass/70 hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
            >
              <LogOut className="h-3 w-3" />
              Logout
            </button>
          </div>
        </div>
        <DropdownMenuSeparator />
        <div className="max-h-72 overflow-y-auto">
          {groupedModels.map((group, index) => (
            <div key={group.name}>
              {index > 0 ? <DropdownMenuSeparator /> : null}
              <DropdownMenuLabel>{group.name}</DropdownMenuLabel>
              <DropdownMenuRadioGroup value={`${provider}:${selectedModelId}`}>
                {group.items.map((model) => (
                  <DropdownMenuRadioItem
                    key={`${model.provider}:${model.id}`}
                    value={`${model.provider}:${model.id}`}
                    onSelect={() => selectModel(model)}
                    className="gap-2"
                  >
                    <ProviderIcon group={model.group} />
                    <span className="truncate">{model.label}</span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </div>
          ))}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function buildModelOptions(
  localModels?: LlmModel[],
  hostedModels?: LlmModel[],
  deepSeekModels?: LlmModel[],
  vertexModels?: LlmModel[],
  kimiModels?: LlmModel[],
  codexModels?: LlmModel[],
) {
  const byKey = new Map<string, ModelOption>();
  const add = (option: ModelOption) => {
    byKey.set(`${option.provider}:${option.id}`, option);
  };

  for (const model of localModels?.length ? localModels : [localModel]) {
    add(toModelOption(model, "llama"));
  }
  for (const model of curatedHostedModels) {
    add(model);
  }
  for (const model of hostedModels ?? []) {
    add(toModelOption(model, "nvidia"));
  }
  for (const model of deepSeekModels ?? []) {
    add(toModelOption(model, "deepseek"));
  }
  for (const model of vertexModels ?? []) {
    add(toModelOption(model, "vertex"));
  }
  for (const model of kimiModels ?? []) {
    add(toModelOption(model, "kimi"));
  }
  for (const model of codexModels ?? []) {
    add(toModelOption(model, "codex"));
  }

  return [...byKey.values()];
}

function groupModelOptions(options: ModelOption[]) {
  const groups = new Map<string, ModelOption[]>();
  for (const option of options) {
    const group = groups.get(option.group) ?? [];
    group.push(option);
    groups.set(option.group, group);
  }

  return [...groups.entries()]
    .sort(([left], [right]) => groupRank(left) - groupRank(right) || left.localeCompare(right))
    .map(([name, items]) => ({ name, items: items.sort((left, right) => left.label.localeCompare(right.label)) }));
}

function groupRank(group: string) {
  const index = modelGroupOrder.indexOf(group);
  return index === -1 ? modelGroupOrder.length : index;
}

function toModelOption(model: LlmModel, fallbackProvider: ModelProvider): ModelOption {
  const provider = model.provider || fallbackProvider;
  const id = model.id || localModel.id;
  return {
    id,
    provider,
    label: formatModelLabel(model.name || id),
    group: modelGroup(id, provider),
    contextLength: model.context_length,
  };
}

function modelGroup(id: string, provider: ModelProvider) {
  const normalized = id.toLowerCase();
  if (provider === "llama") return "Local";
  if (provider === "kimi") return "Kimi Code";
  if (provider === "codex") return "ChatGPT Subscription";
  if (provider === "vertex") return "Google Vertex";
  if (provider === "deepseek") return DEEPSEEK_API_GROUP;
  if (normalized.startsWith("openai/") || normalized.startsWith("gpt-")) return "OpenAI";
  if (normalized.startsWith("qwen/")) return "Qwen";
  if (normalized.startsWith("minimax") || normalized.startsWith("minimaxai/")) return "Minimax";
  if (normalized.startsWith("moonshotai/")) return "Moonshot";
  if (normalized.startsWith("deepseek-ai/")) return DEEPSEEK_NVIDIA_GROUP;
  if (normalized.startsWith("nvidia/")) return "NVIDIA";
  if (normalized.startsWith("mistralai/") || normalized.startsWith("nv-mistralai/")) return "Mistral";
  if (normalized.startsWith("meta/")) return "Meta";
  if (normalized.startsWith("google/")) return "Google";
  if (normalized.startsWith("microsoft/")) return "Microsoft";
  if (normalized.startsWith("ibm/")) return "IBM";
  if (normalized.startsWith("writer/")) return "Writer";
  if (normalized.includes("/")) return formatVendorLabel(normalized.split("/", 1)[0]);
  return "Other";
}

function formatModelLabel(value: string) {
  const normalized = value.trim();
  if (!normalized || normalized === "local-model" || normalized.toLowerCase() === "local model") return "Local";
  const exact: Record<string, string> = {
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4-mini": "GPT-5.4-Mini",
    "kimi-for-coding": "Kimi K2.6",
    "qwen/qwen3.5-397b-a17b": "Qwen3.5-397B",
    "qwen/qwen3-coder-480b-a35b-instruct": "Qwen3 Coder 480B",
    "minimaxai/minimax-m2.5": "Minimax M2.5",
    "moonshotai/kimi-k2.5": "Kimi K2.5",
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "deepseek-ai/deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-ai/deepseek-v4-pro": "DeepSeek V4 Pro",
    "nvidia/nemotron-3-nano-30b-a3b": "Nemotron 3 Nano 30B",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
    "gemini-3.1-pro-preview-customtools": "Gemini 3.1 Pro Custom Tools",
    "gemini-3.1-flash-lite-preview": "Gemini 3.1 Flash-Lite",
    "gemini-3.1-flash-image-preview": "Gemini 3.1 Flash Image",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "gemini-3-pro-image-preview": "Gemini 3 Pro Image",
  };
  if (exact[normalized]) return exact[normalized];

  const leaf = normalized.includes("/") ? normalized.split("/").at(-1) || normalized : normalized;
  const brandNames: Record<string, string> = {
    ai: "AI",
    deepseek: "DeepSeek",
    gpt: "GPT",
    gemini: "Gemini",
    kimi: "Kimi",
    llama: "Llama",
    minimax: "Minimax",
    mistral: "Mistral",
    nemotron: "Nemotron",
    oss: "OSS",
    qwen: "Qwen",
  };
  return leaf
    .replace(/[-_]+/g, " ")
    .replace(/\b(gpt|oss|qwen|kimi|mistral|llama|nemotron|deepseek|minimax|gemini|ai)\b/gi, (part) => brandNames[part.toLowerCase()])
    .replace(/\b(qwen|gpt|kimi|llama)(?=\d)/gi, (part) => brandNames[part.toLowerCase()])
    .replace(/\b([0-9]+)b\b/gi, "$1B")
    .replace(/\b([0-9]+)k\b/gi, "$1K")
    .replace(/\s+/g, " ")
    .trim();
}

function ContextWindowIndicator() {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const provider = useAppStore((state) => state.provider);
  const selectedModelId = useAppStore((state) => state.selectedModelId);
  const messages = useChatStore((state) => state.messages);
  const liveSessionUsage = useChatStore((state) => state.liveSessionUsage);

  const localModels = useQuery({
    queryKey: ["models", baseUrl, "llama"],
    queryFn: () => listModels(baseUrl, "llama"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const hostedModels = useQuery({
    queryKey: ["models", baseUrl, "nvidia"],
    queryFn: () => listModels(baseUrl, "nvidia"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const deepSeekModels = useQuery({
    queryKey: ["models", baseUrl, "deepseek"],
    queryFn: () => listModels(baseUrl, "deepseek"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const vertexModels = useQuery({
    queryKey: ["models", baseUrl, "vertex"],
    queryFn: () => listModels(baseUrl, "vertex"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const kimiModels = useQuery({
    queryKey: ["models", baseUrl, "kimi"],
    queryFn: () => listModels(baseUrl, "kimi"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const codexModels = useQuery({
    queryKey: ["models", baseUrl, "codex"],
    queryFn: () => listModels(baseUrl, "codex"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });

  const modelOptions = buildModelOptions(
    localModels.data,
    hostedModels.data,
    deepSeekModels.data,
    vertexModels.data,
    kimiModels.data,
    codexModels.data,
  );
  const selectedOption =
    modelOptions.find((item) => item.provider === provider && item.id === selectedModelId) ??
    modelOptions.find((item) => item.id === selectedModelId);

  const contextLength = selectedOption?.contextLength ?? 131072; // 128K default

  const usedTokens = useMemo(() => {
    const fromMessages = messages.reduce((acc, msg) => {
      const contentTokens = msg.content ? Math.max(1, Math.ceil(msg.content.length / 4)) : 0;
      const reasoningTokens = msg.reasoning ? Math.max(1, Math.ceil(msg.reasoning.length / 4)) : 0;
      return acc + contentTokens + reasoningTokens;
    }, 0);
    const fromLive = liveSessionUsage.agent_output_tokens.value + liveSessionUsage.thinking_output_tokens.value;
    // Use the larger estimate to account for streaming content not yet flushed into messages
    return Math.max(fromMessages, fromLive);
  }, [messages, liveSessionUsage]);

  const totalK = Math.round(contextLength / 1024);
  const usedK = Math.ceil(usedTokens / 1024);
  const usageRatio = Math.min(1, usedTokens / contextLength);
  const remainingPct = Math.max(0, Math.min(100, Math.round((1 - usageRatio) * 100)));

  const radius = 8;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - usageRatio);

  let color = "text-emerald-400";
  if (usageRatio > 0.9) color = "text-red-400";
  else if (usageRatio > 0.7) color = "text-amber-400";
  else if (usageRatio > 0.5) color = "text-yellow-400";

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex h-10 w-10 shrink-0 cursor-default items-center justify-center rounded-xl hover:bg-glass/60">
            <svg width="20" height="20" viewBox="0 0 20 20" className="-rotate-90">
              <circle
                cx="10"
                cy="10"
                r={radius}
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                className="text-muted-foreground/20"
              />
              <circle
                cx="10"
                cy="10"
                r={radius}
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={dashOffset}
                className={color}
              />
            </svg>
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" align="center" className="text-center">
          <div className="leading-relaxed">
            <div className="text-[11px] text-muted-foreground">
              {remainingPct}%
            </div>
            <div className="text-[11px] font-medium text-foreground">
              {usedK}K/{totalK}K Contexto
            </div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function formatVendorLabel(value: string) {
  const exact: Record<string, string> = {
    "01-ai": "01.AI",
    ai21labs: "AI21 Labs",
    baai: "BAAI",
    bigcode: "BigCode",
    bytedance: "ByteDance",
    sarvamai: "SarvamAI",
    "stepfun-ai": "StepFun",
    "z-ai": "Z.ai",
  };
  if (exact[value]) return exact[value];

  return value
    .replace(/[-_]+/g, " ")
    .replace(/\b(ai|ibm|baai)\b/gi, (part) => part.toUpperCase())
    .replace(/\b\w/g, (part) => part.toUpperCase())
    .trim();
}

function buildComposerContextAttachments(
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

function contextAttachmentFromMention(mention: ComposerMention): ContextAttachment {
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

function attachmentOnlyMessage(
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

function formatLineRange(start: number, end: number) {
  return start === end ? String(start) : `${start}-${end}`;
}
