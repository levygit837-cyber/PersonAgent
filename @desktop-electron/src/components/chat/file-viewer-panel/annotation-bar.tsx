import { ArrowUp, X } from "lucide-react";
import { Button } from "../../ui/button";
import { formatLineRange } from "./utils";
import type { AnnotationDraft } from "./types";

export function AnnotationInputBar({
  range,
  draft,
  value,
  onChange,
  onCancel,
  onSubmit,
}: {
  range: { start: number; end: number };
  draft: AnnotationDraft;
  value: string;
  onChange: (value: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const rangeLabel = formatLineRange(range.start, range.end);
  return (
    <form
      className="my-1 max-w-[520px] rounded-2xl border border-glass-border/40 bg-card/75 p-2 shadow-floating ring-1 ring-white/[0.04] backdrop-blur-2xl"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      onClick={(event) => event.stopPropagation()}
    >
      <div className="mb-1.5 flex items-center gap-2 px-1 font-mono text-[11px] text-muted-foreground">
        <span className="rounded-md bg-foreground/[0.08] px-1.5 py-0.5 text-foreground">L{rangeLabel}</span>
        <span className="text-muted-foreground/60">#{draft.id.replace("draft-", "")}</span>
      </div>
      <div className="flex items-end gap-2">
        <textarea
          value={value}
          rows={1}
          placeholder="Write a Annotation..."
          onChange={(event) => onChange(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
            if (event.key === "Escape") {
              event.preventDefault();
              onCancel();
            }
          }}
          className="max-h-24 min-h-9 min-w-0 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/75"
          autoFocus
        />
        <Button
          variant="ghost"
          size="iconSm"
          type="button"
          aria-label={`Cancel selection ${rangeLabel}`}
          onClick={onCancel}
          className="rounded-xl"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
        <Button size="iconSm" type="submit" aria-label={`Add annotation ${rangeLabel}`} disabled={!value.trim()} className="rounded-xl">
          <ArrowUp className="h-3.5 w-3.5" />
        </Button>
      </div>
    </form>
  );
}

