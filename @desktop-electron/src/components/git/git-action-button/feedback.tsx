import { AlertCircle, CheckCircle2 } from "lucide-react";
import type { OperationFeedback } from "./types";

export function MenuFeedback({ feedback }: { feedback: OperationFeedback }) {
  const success = feedback.kind === "success";
  return (
    <div
      className={[
        "mx-2 my-2 flex items-start gap-2 rounded-lg border px-2 py-1.5 text-[11px] leading-4",
        success
          ? "border-success/30 bg-success/10 text-success"
          : "border-destructive/30 bg-destructive/10 text-destructive",
      ].join(" ")}
    >
      {success ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" /> : <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />}
      <div className="min-w-0">
        <div className="font-medium">{feedback.title}</div>
        {feedback.detail ? <div className="truncate opacity-80">{feedback.detail}</div> : null}
      </div>
    </div>
  );
}

export function CommitFeedback({ feedback }: { feedback: OperationFeedback }) {
  const success = feedback.kind === "success";
  return (
    <div
      className={[
        "mt-3 flex items-start gap-2 rounded-xl border px-3 py-2 text-xs leading-5",
        success
          ? "border-success/30 bg-success/10 text-success"
          : "border-destructive/30 bg-destructive/10 text-destructive",
      ].join(" ")}
    >
      {success ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
      <div className="min-w-0">
        <div className="font-medium">{feedback.title}</div>
        {feedback.detail ? <div className="break-words opacity-80">{feedback.detail}</div> : null}
      </div>
    </div>
  );
}
