import type { ConversationStatus } from "../../../../types/chat";

export function ConversationStatusIndicator({
  status,
  compact = false,
}: {
  status: ConversationStatus;
  compact?: boolean;
}) {
  if (status === "idle") return null;

  const labelByStatus: Record<Exclude<ConversationStatus, "idle">, string> = {
    error: "Error in last request",
    pending: "Pending approval",
    running: "Agent running",
  };

  return (
    <span
      aria-label={labelByStatus[status]}
      title={labelByStatus[status]}
      data-status={status}
      className={[
        "personagent-session-status shrink-0",
        compact ? "h-2.5 w-2.5" : "h-3 w-3",
      ].join(" ")}
    />
  );
}
