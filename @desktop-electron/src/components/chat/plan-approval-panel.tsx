import { Check, PencilLine, X, FileText, AlertCircle } from "lucide-react";
import { useState } from "react";
import { useChatStore } from "../../stores/chat-store";
import type { PlanApprovalUi, ToolApprovalUi } from "../../types/chat";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { MarkdownContent } from "./agent-message";

export function PlanApprovalPanel({ approval, active = true }: { approval: PlanApprovalUi; active?: boolean }) {
  const [feedback, setFeedback] = useState("");
  const isStreaming = useChatStore((state) => state.isStreaming);
  const isProcessingPlanDecision = useChatStore((state) => state.isProcessingPlanDecision);
  const proceed = useChatStore((state) => state.approvePendingPlan);
  const continuePlanning = useChatStore((state) => state.continuePendingPlan);
  const cancel = useChatStore((state) => state.cancelPendingPlan);
  const disabled = !active || isStreaming || isProcessingPlanDecision || !approval.approvalId;

  const hasContent = !!(approval.planContent || "").trim();
  const isShortContent = hasContent && (approval.planContent || "").trim().length < 200;

  return (
    <section className="mb-9 rounded-2xl border border-primary/25 bg-card/80 p-5 shadow-soft">
      {/* Header */}
      <div className="mb-4 flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-primary" />
          <div>
            <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
              Plan approval
            </div>
            <div className="mt-0.5 text-sm font-medium text-foreground">
              {approval.planId || "Plan"}
            </div>
          </div>
        </div>
        <span className="inline-flex items-center rounded-full border border-warning/30 bg-warning/10 px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-warning">
          {approval.planStatus?.replace("_", " ")}
        </span>
      </div>

      {/* Content */}
      <div
        className={
          "overflow-y-auto rounded-xl border border-glass-border/35 bg-background/[0.45] px-4 py-3 " +
          (hasContent ? "max-h-[70vh] min-h-[200px]" : "min-h-[120px]")
        }
      >
        {hasContent ? (
          <>
            <MarkdownContent content={approval.planContent || ""} />
            {isShortContent && (
              <div className="mt-3 flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 px-3 py-2 text-xs text-warning">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  This plan looks short. Consider clicking "Continue planning" to ask the agent to
                  expand with more detail.
                </span>
              </div>
            )}
          </>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 py-6 text-muted-foreground">
            <div className="flex flex-col items-center gap-2">
              <div className="h-8 w-8 animate-pulse rounded-full bg-muted" />
              <div className="h-3 w-32 animate-pulse rounded bg-muted" />
              <div className="h-3 w-24 animate-pulse rounded bg-muted" />
            </div>
            <p className="text-xs">Waiting for plan content...</p>
          </div>
        )}
      </div>

      {/* Feedback + Actions */}
      {active ? (
        <>
          <Textarea
            className="mt-4 min-h-14 text-sm"
            placeholder="Optional feedback before deciding..."
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            disabled={disabled}
          />

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <Button
              size="xs"
              onClick={() => void proceed(feedback)}
              disabled={disabled}
              tabIndex={-1}
            >
              <Check className="h-3.5 w-3.5" />
              Proceed
            </Button>
            <Button
              size="xs"
              variant="outline"
              onClick={() => void continuePlanning(feedback)}
              disabled={disabled}
              tabIndex={-1}
            >
              <PencilLine className="h-3.5 w-3.5" />
              Continue planning
            </Button>
            <Button
              size="xs"
              variant="ghost"
              onClick={() => void cancel(feedback)}
              disabled={disabled}
              tabIndex={-1}
            >
              <X className="h-3.5 w-3.5" />
              Cancel
            </Button>
          </div>
        </>
      ) : null}
    </section>
  );
}

export function ToolApprovalPanel({ approval }: { approval: ToolApprovalUi }) {
  const isStreaming = useChatStore((state) => state.isStreaming);
  const approve = useChatStore((state) => state.approvePendingTool);
  const reject = useChatStore((state) => state.rejectPendingTool);
  const disabled = isStreaming || !approval.approvalId;

  return (
    <section className="mb-9 rounded-2xl border border-warning/30 bg-card/80 p-4 shadow-soft">
      <div className="mb-3">
        <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-warning">
          Command approval
        </div>
        <div className="mt-1 text-sm font-medium text-foreground">{approval.toolName}</div>
      </div>
      {approval.message ? (
        <p className="mb-3 text-sm leading-6 text-muted-foreground">{approval.message}</p>
      ) : null}
      {approval.toolInput ? (
        <pre className="mb-3 max-h-40 overflow-auto rounded-xl border border-glass-border/35 bg-background/50 p-3 text-xs text-muted-foreground">
          {JSON.stringify(approval.toolInput, null, 2)}
        </pre>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void approve()} disabled={disabled} tabIndex={-1}>
          <Check className="h-3.5 w-3.5" />
          Approve
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void reject()} disabled={disabled} tabIndex={-1}>
          <X className="h-3.5 w-3.5" />
          Reject
        </Button>
      </div>
    </section>
  );
}
