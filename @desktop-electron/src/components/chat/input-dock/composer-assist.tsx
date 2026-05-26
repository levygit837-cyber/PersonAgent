import { Command, Sparkles } from "lucide-react";
import type { ChatCommandInfo } from "../../../types/chat";
import type { MentionSuggestion } from "./mentions";
import { MentionSuggestionIcon } from "./mention-suggestion-icon";

export function ComposerAssist({
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
