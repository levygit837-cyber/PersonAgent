import { ArrowUp, BookOpen, Command, FileText, Folder, Globe, ListChecks, Sparkles, Square, Terminal, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { listBrowserTabMentions, listChatCommands, listSkills, listWorkspaceMentions } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore, type ComposerAnnotation } from "../../stores/chat-store";
import { useTerminalStore, type TerminalSnippet } from "../../stores/terminal-store";
import { type ChatCommandInfo } from "../../types/chat";
import { BranchSwitcherButton } from "../git/branch-switcher-button";
import { Button } from "../ui/button";
import { FeatureMenu, ModelReasoningSelector, ContextWindowIndicator } from "./input-dock/toolbar";
import {
  type ComposerMention,
  type ComposerMentionKind,
  type MentionSuggestion,
  PLAN_MODE_SYSTEM_PROMPT,
  slashTokenFromText,
  parseComposerSlashInvocation,
  filterSlashCommands,
  mentionTriggerFromText,
  buildMentionSuggestions,
  browserMentionQueryFromText,
  autoResolveBrowserMentions,
  buildComposerContextAttachments,
  attachmentOnlyMessage,
  formatLineRange,
} from "./input-dock/helpers";
import { InputTodoDock } from "./input-dock/todo-dock";

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
  const conversationId = useChatStore((state) => state.conversationId);
  const nextStepSuggestion = useChatStore((state) => state.nextStepSuggestion);
  const composerAnnotations = useChatStore((state) => state.composerAnnotations);
  const composerPlanMode = useChatStore((state) => state.composerPlanMode);
  const setComposerPlanMode = useChatStore((state) => state.setComposerPlanMode);
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
  const browserMentionQuery = mentionTrigger ? browserMentionQueryFromText(mentionTrigger.query) : null;
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
  const browserTabMentionSuggestions = useQuery({
    queryKey: ["browser-tab-mentions", baseUrl, conversationId, browserMentionQuery ?? ""],
    queryFn: () => listBrowserTabMentions(baseUrl, conversationId || "", browserMentionQuery ?? ""),
    enabled: !disabled && mentionOpen && Boolean(baseUrl) && Boolean(conversationId) && browserMentionQuery !== null,
    staleTime: 2_000,
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
      browserTabMentionSuggestions.data ?? [],
      mentionTrigger?.query ?? "",
      conversationId,
    ),
    [browserTabMentionSuggestions.data, conversationId, mentionTrigger?.query, skillMentionSuggestions.data, workspaceMentionSuggestions.data],
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
    const slashInvocation = parseComposerSlashInvocation(value);

    // /plan without content activates the local Plan Mode banner
    if (slashInvocation?.name === "plan" && value.trim().length <= 5 && selectedMentions.length === 0 && composerAnnotations.length === 0 && !pendingSnippet) {
      setComposerPlanMode(true);
      setText("");
      setCursorPosition(0);
      requestAnimationFrame(() => textareaRef.current?.focus());
      return;
    }

    const mentionsForSubmit = autoResolveBrowserMentions(
      value,
      selectedMentions,
      browserTabMentionSuggestions.data ?? [],
      conversationId,
    );
    const { requestAttachments, displayAttachments } = buildComposerContextAttachments(
      composerAnnotations,
      pendingSnippet,
      mentionsForSubmit,
    );
    const visibleMessage = value || attachmentOnlyMessage(composerAnnotations, pendingSnippet, mentionsForSubmit);

    // /plan with content is forwarded as a normal message (not a hidden slash command)
    const isHiddenSlashCommand = slashInvocation !== null && slashInvocation.name !== "plan";
    const messageToSend = slashInvocation?.name === "plan" ? value.trim().slice(5).trim() : visibleMessage;
    const isPlanModeTurn = composerPlanMode || slashInvocation?.name === "plan";

    const sendOptions = requestAttachments.length || isHiddenSlashCommand || isPlanModeTurn
      ? {
          ...(requestAttachments.length ? { contextAttachments: requestAttachments, displayAttachments } : {}),
          ...(isHiddenSlashCommand ? { hideUserMessage: true } : {}),
          ...(isPlanModeTurn ? { planModeRequested: true } : {}),
        }
      : undefined;
    void sendMessage(messageToSend, isPlanModeTurn ? PLAN_MODE_SYSTEM_PROMPT : undefined, sendOptions);
    if (composerPlanMode) setComposerPlanMode(false);
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
          <ComposerPlanModeBanner active={composerPlanMode} onDismiss={() => setComposerPlanMode(false)} />
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

function ComposerPlanModeBanner({ active, onDismiss }: { active: boolean; onDismiss: () => void }) {
  if (!active) return null;

  return (
    <div className="flex items-center gap-2 border-b border-amber-400/20 bg-amber-400/10 px-3 py-2 text-amber-100" data-testid="composer-plan-mode">
      <ListChecks className="h-4 w-4 shrink-0 text-amber-200" />
      <span className="min-w-0 flex-1 text-xs font-medium">Plan Mode</span>
      <Button
        type="button"
        variant="ghost"
        size="iconSm"
        aria-label="Exit Plan Mode"
        onClick={onDismiss}
        className="h-6 w-6 shrink-0 rounded-lg text-amber-100 hover:bg-amber-400/15 hover:text-amber-50"
      >
        <X className="h-3.5 w-3.5" />
      </Button>
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
  if (type === "browser_tab") return <Globe className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  return <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
}
