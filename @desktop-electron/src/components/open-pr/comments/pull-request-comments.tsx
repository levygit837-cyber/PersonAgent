import { Bot, UserRound } from "lucide-react";
import type { PullRequestComment } from "../../../api/client";
import { formatDateTime } from "../shared/pr-utils";
import { CommentKindPill } from "./comment-kind-pill";

export function PullRequestComments({ comments }: { comments: PullRequestComment[] }) {
  if (comments.length === 0) {
    return <p className="mt-2 text-xs leading-5 text-muted-foreground">No PR comments yet.</p>;
  }

  return (
    <div className="mt-3 space-y-2">
      {comments.slice(0, 5).map((comment) => (
        <article key={comment.id} className="rounded-xl border border-glass-border/25 bg-background/35 p-3">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1 font-medium text-foreground">
              {comment.source === "ai" ? <Bot className="h-3.5 w-3.5 text-primary" /> : <UserRound className="h-3.5 w-3.5" />}
              {comment.author}
            </span>
            <CommentKindPill comment={comment} />
            {comment.createdAt ? <span>{formatDateTime(comment.createdAt)}</span> : null}
          </div>
          <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">{comment.body}</p>
        </article>
      ))}
    </div>
  );
}
