import { Check, PencilLine, X } from "lucide-react";
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

  return (
    <section className="mb-9 rounded-2xl border border-primary/25 bg-card/80 p-4 shadow-soft">
      <div className="mb-3 flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
            Plan approval
          </div>
          <div className="mt-1 text-sm font-medium text-foreground">{approval.planId || "Plan"}</div>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-warning">
          {approval.planStatus}
        </span>
      </div>

      <div className="max-h-[46vh] overflow-y-auto rounded-xl border border-glass-border/35 bg-background/[0.45] px-3 py-2">
        <MarkdownContent content={approval.planContent || "No plan content was provided."} />
      </div>

      {active ? (
        <Textarea
          className="mt-3 min-h-16"
          placeholder="Optional feedback"
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          disabled={disabled}
        />
      ) : null}

      {active ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => void proceed(feedback)} disabled={disabled} tabIndex={-1}>
            <Check className="h-3.5 w-3.5" />
            Proceed
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void continuePlanning(feedback)}
            disabled={disabled}
            tabIndex={-1}
          >
            <PencilLine className="h-3.5 w-3.5" />
            Continue planning
          </Button>
          <Button size="sm" variant="ghost" onClick={() => void cancel(feedback)} disabled={disabled} tabIndex={-1}>
            <X className="h-3.5 w-3.5" />
            Cancel
          </Button>
        </div>
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
