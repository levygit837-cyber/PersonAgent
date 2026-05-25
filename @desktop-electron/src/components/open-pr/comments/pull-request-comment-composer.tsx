import { type FormEvent, useState } from "react";
import { Send } from "lucide-react";
import type { PullRequestCommentKind, PullRequestStatus, PullRequestSummary } from "../../../api/client";
import { cn } from "../../../lib/utils";
import { Button } from "../../ui/button";

const COMMENT_OPTIONS: Array<{
  id: string;
  label: string;
  kind: PullRequestCommentKind;
  status?: PullRequestStatus;
}> = [
  { id: "human_review", label: "Human analysis", kind: "human_review" },
  { id: "ai_review", label: "AI analysis", kind: "ai_review" },
  { id: "needs_review", label: "Needs review", kind: "status", status: "needs_review" },
  { id: "merged", label: "Merged", kind: "status", status: "merged" },
  { id: "refused", label: "Refused", kind: "status", status: "refused" },
];

export function PullRequestCommentComposer({
  pullRequest,
  onCreateComment,
  disabled,
}: {
  pullRequest: PullRequestSummary;
  onCreateComment: (input: { number: number; body: string; kind: PullRequestCommentKind; status?: PullRequestStatus | null }) => Promise<unknown>;
  disabled: boolean;
}) {
  const [optionId, setOptionId] = useState(COMMENT_OPTIONS[0].id);
  const [body, setBody] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const selectedOption = COMMENT_OPTIONS.find((option) => option.id === optionId) ?? COMMENT_OPTIONS[0];

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const value = body.trim();
    if (!value) return;
    setFeedback(null);
    try {
      await onCreateComment({ number: pullRequest.number, body: value, kind: selectedOption.kind, status: selectedOption.status ?? null });
      setBody("");
      setFeedback("Comment sent");
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Comment failed");
    }
  };

  return (
    <form className="mt-3 rounded-xl border border-glass-border/25 bg-background/30 p-3" onSubmit={submit}>
      <div className="flex flex-wrap gap-1.5">
        {COMMENT_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={cn(
              "rounded-full border px-2.5 py-1 text-[11px] transition-[background,border-color,color] duration-150",
              option.id === optionId
                ? "border-primary/35 bg-primary/10 text-foreground"
                : "border-glass-border/30 text-muted-foreground hover:bg-glass/80 hover:text-foreground",
            )}
            onClick={() => setOptionId(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <textarea
        value={body}
        rows={3}
        onChange={(event) => setBody(event.currentTarget.value)}
        placeholder="Write a PR comment..."
        className="mt-3 min-h-20 w-full resize-none rounded-xl border border-glass-border/35 bg-background/55 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/70 focus:border-primary/35 focus:ring-1 focus:ring-primary/20"
      />
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="min-w-0 text-[11px] text-muted-foreground">{feedback}</span>
        <Button type="submit" size="xs" className="rounded-xl" disabled={disabled || !body.trim()}>
          <Send className="h-3.5 w-3.5" />
          Send comment
        </Button>
      </div>
    </form>
  );
}
