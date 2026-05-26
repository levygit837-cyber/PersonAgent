import { ArrowUp, Square } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { listBrowserTabMentions, listChatCommands, listSkills, listWorkspaceMentions } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { useTerminalStore } from "../../stores/terminal-store";
import { BranchSwitcherButton } from "../git/branch-switcher-button";
import { Button } from "../ui/button";
import { FeatureMenu, ModelReasoningSelector, ContextWindowIndicator } from "./input-dock/toolbar";
import {
  type ComposerMention,
  type MentionSuggestion,
  mentionTriggerFromText,
  buildMentionSuggestions,
  browserMentionQueryFromText,
  autoResolveBrowserMentions,
} from "./input-dock/mentions";
import {
  PLAN_MODE_SYSTEM_PROMPT,
  slashTokenFromText,
  parseComposerSlashInvocation,
  filterSlashCommands,
  buildComposerContextAttachments,
  attachmentOnlyMessage,
} from "./input-dock/helpers";
import { InputTodoDock } from "./input-dock/todo-dock";
import { ComposerAssist } from "./input-dock/composer-assist";
import {
  TerminalSnippetTray,
  ComposerPlanModeBanner,
  ComposerAnnotationTray,
  ComposerMentionTray,
} from "./input-dock/composer-trays";

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
