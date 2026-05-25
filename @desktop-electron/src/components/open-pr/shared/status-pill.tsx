import type { ReactNode } from "react";
import type { PullRequestStatus } from "../../../api/client";
import { cn } from "../../../lib/utils";

export function StatusPill({
  status,
  children,
}: {
  status: PullRequestStatus;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-1 text-[10px] font-semibold",
        status === "approved" && "border-success/30 bg-success/10 text-success",
        status === "merged" && "border-success/30 bg-success/10 text-success",
        status === "needs_review" && "border-warning/30 bg-warning/10 text-warning",
        status === "refused" && "border-destructive/30 bg-destructive/10 text-destructive",
      )}
    >
      {children}
    </span>
  );
}
