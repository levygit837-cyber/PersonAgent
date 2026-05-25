import type { PullRequestComment } from "../../../api/client";
import { cn } from "../../../lib/utils";
import { statusText } from "../shared/pr-utils";

export function CommentKindPill({ comment }: { comment: PullRequestComment }) {
  const label = comment.kind === "status" && comment.status
    ? statusText(comment.status)
    : comment.kind === "ai_review"
      ? "AI analysis"
      : "Human analysis";

  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 font-medium",
        comment.kind === "ai_review" && "border-primary/25 bg-primary/10 text-primary",
        comment.kind === "human_review" && "border-glass-border/30 bg-muted text-muted-foreground",
        comment.kind === "status" && "border-warning/25 bg-warning/10 text-warning",
      )}
    >
      {label}
    </span>
  );
}
