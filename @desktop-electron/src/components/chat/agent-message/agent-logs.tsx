import { memo, useState } from "react";
import { Brain, Hammer, MessageSquareText } from "lucide-react";
import type { TeamAgentTraceUi, TeamAgentLogUi, TeamToolTraceUi } from "../../../types/chat";
import { MarkdownContent } from "./content-blocks";
import { StatusDot } from "./shared";

function AgentLogTimeline({ agent, running }: { agent: TeamAgentTraceUi; running: boolean }) {
  const logs = visibleAgentLogs(agent);
  return (
    <div className="max-h-64 overflow-y-auto pr-1" aria-label={`${agent.agentName} events`}>
      <div className="space-y-1.5">
        {logs.length > 0 ? (
          logs.map((log) => <AgentLogRow key={log.id} log={log} running={running && log.kind === "thinking"} />)
        ) : (
          <div className="rounded-md border border-glass-border/30 bg-background/30 px-2 py-1.5 font-mono text-[11px] text-muted-foreground">
            Waiting for events.
          </div>
        )}
        {agent.tools.length > 0 ? (
          <div className="space-y-1.5 pt-1">
            <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase text-primary">
              <Hammer className="h-3 w-3" aria-hidden="true" />
              Tools
            </div>
            {agent.tools.slice(-4).map((tool) => <AgentToolRow key={tool.id} tool={tool} />)}
          </div>
        ) : null}
        {agent.claims.length > 0 ? (
          <div className="space-y-1.5 pt-1">
            <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase text-primary">
              <Brain className="h-3 w-3" aria-hidden="true" />
              Claims
            </div>
            {agent.claims.slice(-4).map((claim) => (
              <div key={claim.id} className="truncate rounded-md border border-glass-border/30 bg-background/30 px-2 py-1.5 text-[11px] text-muted-foreground">
                <span className="font-mono uppercase text-primary">{claim.type}</span> {claim.text}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AgentLogPreview({
  log,
  revealThinkingContent,
}: {
  log: TeamAgentLogUi;
  revealThinkingContent: boolean;
}) {
  const preview = agentLogPreview(log, revealThinkingContent);
  return (
    <div className="flex min-w-0 items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
      <span className="shrink-0 uppercase text-primary">{agentLogKindLabel(log.kind)}</span>
      <span className="truncate">{preview}</span>
    </div>
  );
}

function AgentLogRow({ log, running }: { log: TeamAgentLogUi; running: boolean }) {
  const isThinking = log.kind === "thinking";
  return (
    <div className="rounded-md border border-glass-border/30 bg-background/30 px-2 py-1.5">
      <div className="mb-1 flex min-w-0 items-center justify-between gap-2 font-mono text-[10px] uppercase text-primary">
        <span className="flex min-w-0 items-center gap-1.5">
          {agentLogIcon(log.kind)}
          <span className="truncate">{agentLogKindLabel(log.kind)}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5 text-muted-foreground">
          {log.phase ? <span className="max-w-24 truncate">{formatPhaseLabel(log.phase)}</span> : null}
          {running ? <StatusDot status="running" /> : log.status ? <StatusDot status={log.status} /> : null}
        </span>
      </div>
      {log.content ? (
        <div
          className={
            isThinking
              ? "max-h-32 overflow-y-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-muted-foreground"
              : "max-h-36 overflow-y-auto text-[12px] leading-5 text-muted-foreground"
          }
        >
          {isThinking ? (
            log.content
          ) : (
            <MarkdownContent content={log.content} />
          )}
        </div>
      ) : (
        <div className="truncate text-[12px] text-muted-foreground">{agentLogPreview(log)}</div>
      )}
    </div>
  );
}

function agentLogIcon(kind: TeamAgentLogUi["kind"]) {
  if (kind === "response") return <MessageSquareText className="h-3 w-3" aria-hidden="true" />;
  if (kind === "tool") return <Hammer className="h-3 w-3" aria-hidden="true" />;
  if (kind === "claim") return <Brain className="h-3 w-3" aria-hidden="true" />;
  return null;
}

function agentLogKindLabel(kind: TeamAgentLogUi["kind"]) {
  if (kind === "thinking") return "thinking";
  if (kind === "response") return "response";
  if (kind === "tool") return "tool";
  if (kind === "claim") return "claim";
  if (kind === "error") return "error";
  return "status";
}

function visibleAgentLogs(agent: TeamAgentTraceUi): TeamAgentLogUi[] {
  const logs = agent.logs.filter(isVisibleAgentLog);
  const hasTextLog = logs.some((log) => log.kind === "thinking" || log.kind === "response");
  const fallbackLogs = hasTextLog ? [] : fallbackAgentLogs(agent);
  return logs.length > 0 || fallbackLogs.length > 0 ? [...logs, ...fallbackLogs] : [];
}

function isVisibleAgentLog(log: TeamAgentLogUi) {
  if (log.kind === "thinking" || log.kind === "response") return Boolean(log.content?.trim());
  return Boolean(log.content?.trim() || log.title.trim());
}

function agentLogPreview(log: TeamAgentLogUi, revealThinkingContent = true) {
  if (log.kind === "thinking" && !revealThinkingContent) {
    return log.phase ? formatPhaseLabel(log.phase) : "working";
  }
  return (log.content?.trim() || log.title).replace(/\s+/g, " ");
}

function isPrivateThinkingLog(agent: TeamAgentTraceUi, log: TeamAgentLogUi) {
  if (log.kind !== "thinking") return false;
  const privateThinking = agent.thinking.trim();
  return Boolean(privateThinking && log.content?.trim() === privateThinking);
}

function formatPhaseLabel(phase: string) {
  return phase.replace(/_/g, " ");
}

function fallbackAgentLogs(agent: TeamAgentTraceUi): TeamAgentLogUi[] {
  const logs: TeamAgentLogUi[] = [];
  if (agent.thinking.trim()) {
    logs.push({
      id: `${agent.agentId}-fallback-thinking`,
      kind: "thinking",
      title: "Thinking",
      content: agent.thinking,
      status: agent.status,
      phase: agent.phase,
      round: agent.round,
    });
  }
  if (agent.output.trim() || agent.digest) {
    logs.push({
      id: `${agent.agentId}-fallback-response`,
      kind: "response",
      title: "Output",
      content: agent.output || agent.digest,
      status: agent.status,
      phase: agent.phase,
      round: agent.round,
    });
  }
  return logs;
}

function AgentToolRow({ tool }: { tool: TeamToolTraceUi }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-glass-border/30 bg-background/30 px-2 py-1.5">
      <button type="button" className="flex w-full cursor-pointer items-center justify-between gap-2 text-left" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">{tool.summary ?? tool.title}</span>
        <span className="flex shrink-0 items-center gap-1.5">
          <StatusDot status={tool.status} />
          <span className="font-mono text-[10px] text-primary">output</span>
        </span>
      </button>
      {open ? (
        <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-md border border-glass-border/25 bg-card/70 p-2 font-mono text-[11px] leading-5 text-muted-foreground">
          {formatToolPayload(tool)}
        </pre>
      ) : null}
    </div>
  );
}

function formatToolPayload(tool: TeamToolTraceUi) {
  const payload = {
    phase: tool.phase,
    calls: tool.calls,
    results: tool.results,
    proposals: tool.proposals,
  };
  return JSON.stringify(payload, null, 2);
}

export { AgentLogTimeline, AgentLogPreview, isPrivateThinkingLog, visibleAgentLogs, formatToolPayload };
