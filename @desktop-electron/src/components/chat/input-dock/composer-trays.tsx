import { ListChecks, Terminal, X } from "lucide-react";
import { Button } from "../../ui/button";
import type { ComposerAnnotation } from "../../../stores/chat-store";
import type { ComposerMention } from "./mentions";
import { formatLineRange } from "./helpers";
import { MentionSuggestionIcon } from "./mention-suggestion-icon";

export function TerminalSnippetTray({
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

export function ComposerPlanModeBanner({ active, onDismiss }: { active: boolean; onDismiss: () => void }) {
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

export function ComposerAnnotationTray({
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

export function ComposerMentionTray({
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
