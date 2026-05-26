import { memo } from "react";
import type { TeamTraceEventUi } from "../../../types/chat";
import { MarkdownContent } from "./content-blocks";

const TeamTrace = memo(function TeamTrace({ events }: { events: TeamTraceEventUi[] }) {
  return (
    <div className="mb-4 space-y-2 border-l border-glass-border/25 pl-3">
      {events.map((event) => (
        <TeamTraceEvent key={event.id} event={event} />
      ))}
    </div>
  );
});

const TeamTraceEvent = memo(function TeamTraceEvent({ event }: { event: TeamTraceEventUi }) {
  const content = event.content?.trimEnd();
  const isRunning = event.status === "running";
  return (
    <div className="text-sm">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span className={teamStatusClass(event.status)}>{teamStatusLabel(event)}</span>
        <span className="font-medium text-foreground">{event.title}</span>
        {event.detail ? <span className="font-mono text-[11px] text-muted-foreground">{event.detail}</span> : null}
      </div>
      {content ? (
        <div className="mt-1 max-w-none text-[13px] leading-6 text-muted-foreground">
          {isRunning ? (
            <div className="whitespace-pre-wrap break-words">{content}</div>
          ) : (
            <MarkdownContent content={content} />
          )}
        </div>
      ) : null}
    </div>
  );
});

function teamStatusLabel(event: TeamTraceEventUi) {
  if (event.kind === "round") return "Round";
  if (event.kind === "vote") return event.status === "approved" ? "Approve" : event.status === "rejected" ? "Block" : "Vote";
  if (event.kind === "consensus") return "Consensus";
  if (event.kind === "blackboard") return "Board";
  if (event.kind === "tool") return "Tool";
  if (event.kind === "debate") return "Debate";
  if (event.kind === "coordinator") {
    return event.title.toLowerCase().includes("planning") || event.status !== "completed" ? "Coord" : "Final";
  }
  if (event.kind === "failed") return "Failed";
  if (event.kind === "cancelled") return "Stopped";
  if (event.kind === "turn") return event.status === "completed" ? "Done" : "Turn";
  return "Team";
}

function teamStatusClass(status?: TeamTraceEventUi["status"]) {
  const base = "font-mono text-[10px] uppercase tracking-[0.12em]";
  if (status === "approved" || status === "completed") return `${base} text-success`;
  if (status === "rejected" || status === "failed") return `${base} text-destructive`;
  if (status === "cancelled") return `${base} text-muted-foreground`;
  return `${base} text-warning`;
}

export { TeamTrace };
