import { memo, useState, type CSSProperties } from "react";
import { ChevronRight } from "lucide-react";
import type { TeamAgentTraceUi, TeamBlackboardTraceUi, TeamCompactStatus, TeamRunUi } from "../../../types/chat";
import { StatusDot, TracePill } from "./shared";
import { AgentLogPreview, AgentLogTimeline, isPrivateThinkingLog, visibleAgentLogs } from "./agent-logs";
import { BlackboardClaim, BlackboardFact, BlackboardTools, BlackboardTextList } from "./blackboard";

const TEAM_CARD_ARRIVAL_STAGGER_MS = 120;

const TeamModeCompactTrace = memo(function TeamModeCompactTrace({ run }: { run: TeamRunUi }) {
  return (
    <section className="mb-4 space-y-2" aria-label="Team Mode execution trace">
      {run.agents.length > 0 ? (
        <div className="space-y-2" aria-label="Agent lanes">
          {run.agents.map((agent, index) => (
            <TeamAgentCard key={agent.agentId} agent={agent} sequenceIndex={index} />
          ))}
        </div>
      ) : null}
      <TeamBlackboardCard blackboard={run.blackboard} runStatus={run.status} sequenceIndex={run.agents.length} />
    </section>
  );
});

const TeamAgentCard = memo(function TeamAgentCard({
  agent,
  sequenceIndex,
}: {
  agent: TeamAgentTraceUi;
  sequenceIndex: number;
}) {
  const [open, setOpen] = useState(false);
  const status = effectiveAgentStatus(agent);
  const summary = compactAgentSummary(agent);
  const previewLogs = visibleAgentLogs(agent).slice(-2);
  return (
    <section
      className="personagent-team-card-arrival overflow-hidden rounded-lg border border-glass-border/45 bg-card/45 shadow-soft"
      style={teamCardArrivalStyle(sequenceIndex)}
    >
      <button
        type="button"
        className="flex w-full min-w-0 cursor-pointer items-center justify-between gap-2 px-2.5 py-2 text-left"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md border border-glass-border/50 bg-background/70 text-[11px] font-bold text-foreground">
            {agentInitial(agent)}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-semibold text-foreground">{agent.agentName}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{agent.agentRole || agent.focus || agent.phase || "Agent"}</span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <StatusDot status={status} />
          <ChevronRight className={open ? "h-3.5 w-3.5 rotate-90 text-muted-foreground transition-transform" : "h-3.5 w-3.5 text-muted-foreground transition-transform"} aria-hidden="true" />
        </span>
      </button>
      <div className="border-t border-glass-border/25 px-2.5 py-1.5">
        {previewLogs.length > 0 ? (
          <div className="space-y-1">
            {previewLogs.map((log) => (
              <AgentLogPreview key={log.id} log={log} revealThinkingContent={!isPrivateThinkingLog(agent, log)} />
            ))}
          </div>
        ) : (
          <div className="truncate font-mono text-[11px] text-muted-foreground">{summary ?? agent.phase ?? "waiting"}</div>
        )}
      </div>
      {open ? (
        <div className="border-t border-glass-border/35 px-2.5 py-2.5">
          <AgentLogTimeline agent={agent} running={status === "running"} />
          {agent.error ? <div className="rounded-md border border-destructive/25 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">{agent.error}</div> : null}
        </div>
      ) : null}
    </section>
  );
});

const TeamBlackboardCard = memo(function TeamBlackboardCard({
  blackboard,
  runStatus,
  sequenceIndex,
}: {
  blackboard: TeamBlackboardTraceUi;
  runStatus: TeamCompactStatus;
  sequenceIndex: number;
}) {
  const [open, setOpen] = useState(false);
  const status = runStatus === "running" ? "running" : blackboard.status;
  const claims = blackboard.claims.slice(-6).reverse();
  const coverage = blackboard.coverage.slice(0, 4);
  return (
    <section
      className="personagent-team-card-arrival overflow-hidden rounded-lg border border-glass-border/50 bg-card/40 shadow-soft"
      style={teamCardArrivalStyle(sequenceIndex)}
      aria-label="Blackboard compact snapshot"
    >
      <button
        type="button"
        className="flex w-full min-w-0 cursor-pointer items-center justify-between gap-3 px-2.5 py-2.5 text-left"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <StatusDot status={status} />
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-semibold text-foreground">Blackboard compact snapshot</span>
            <span className="block truncate font-mono text-[11px] text-muted-foreground">claims, evidence, risks, tools, coverage</span>
          </span>
        </span>
        <span className="flex shrink-0 flex-wrap justify-end gap-1.5 font-mono text-[10px] text-muted-foreground">
          <TracePill label="actual phase" value={blackboard.actualPhase ?? "starting"} />
          <TracePill label="claims" value={String(blackboard.claims.length)} />
          {blackboard.coherencyScore != null ? <TracePill label="coherency" value={blackboard.coherencyScore.toFixed(2)} /> : null}
          <span className="rounded-full border border-glass-border/35 px-2 py-0.5 text-primary">show</span>
        </span>
      </button>
      {open ? (
        <div className="max-h-80 overflow-y-auto border-t border-glass-border/35 px-2.5 py-2.5">
          <div className="grid gap-2 min-[720px]:grid-cols-[minmax(0,1.2fr)_minmax(220px,0.8fr)]">
            <div className="space-y-2">
              {claims.length > 0 ? (
                claims.map((claim) => <BlackboardClaim key={claim.id} claim={claim} />)
              ) : (
                <div className="rounded-md border border-glass-border/35 bg-background/35 px-2 py-1.5 text-xs text-muted-foreground">No claims yet.</div>
              )}
            </div>
            <div className="space-y-2">
              <BlackboardFact title="Actual phase" value={blackboard.actualPhase ?? "starting"} detail={phaseDetail(blackboard.actualPhase)} />
              {blackboard.coverageTotal != null || blackboard.coverageComplete != null ? (
                <BlackboardFact
                  title="Coverage"
                  value={`${blackboard.coverageComplete ?? 0}/${blackboard.coverageTotal ?? blackboard.coverage.length}`}
                  detail={coverageDetail(coverage)}
                />
              ) : null}
              <BlackboardFact title="Next action" value={blackboard.nextAction ?? "Collect deltas"} detail={nextActionDetail(blackboard)} />
              {blackboard.tools.length > 0 ? <BlackboardTools tools={blackboard.tools} /> : null}
              {blackboard.blockers.length > 0 ? <BlackboardTextList title="Blockers" items={blackboard.blockers.slice(-3)} /> : null}
              {blackboard.decisions.length > 0 ? <BlackboardTextList title="Decisions" items={blackboard.decisions.slice(-3)} /> : null}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
});

function teamCardArrivalStyle(sequenceIndex: number) {
  return {
    "--personagent-team-card-delay": `${sequenceIndex * TEAM_CARD_ARRIVAL_STAGGER_MS}ms`,
  } as CSSProperties & Record<"--personagent-team-card-delay", string>;
}

function effectiveAgentStatus(agent: TeamAgentTraceUi): TeamCompactStatus {
  if (agent.status === "failed" || agent.status === "cancelled") return agent.status;
  if (agent.tools.some((tool) => tool.status === "running" || tool.status === "blocked")) return "running";
  return agent.status;
}

function compactAgentSummary(agent: TeamAgentTraceUi) {
  if (agent.error) return agent.error;
  if (agent.digest) return agent.digest;
  if (agent.output.trim()) return agent.output.trim().split(/\s+/).slice(0, 18).join(" ");
  if (agent.thinking.trim()) return "Thinking";
  if (agent.tools.length > 0) return agent.tools[agent.tools.length - 1]?.summary;
  return agent.phase;
}

function agentInitial(agent: TeamAgentTraceUi) {
  if (agent.isCoordinator) return "C";
  return (agent.agentName || agent.agentId || "A").trim().charAt(0).toUpperCase();
}

function phaseDetail(phase?: string) {
  if (!phase) return undefined;
  if (phase.includes("independent")) return "Agents are producing isolated first-pass findings.";
  if (phase.includes("debate")) return "Agents are reviewing the compact Blackboard snapshot.";
  if (phase.includes("vote")) return "Agents are casting compact ballots on blockers and consensus.";
  if (phase.includes("coordinator")) return "Coordinator is preparing the final synthesis.";
  return "Current Team Mode execution phase.";
}

function coverageDetail(coverage: Array<{ title: string; status?: string }>) {
  if (coverage.length === 0) return undefined;
  return coverage.map((item) => `${item.title}: ${item.status ?? "open"}`).join(" | ");
}

function nextActionDetail(blackboard: TeamBlackboardTraceUi) {
  if (blackboard.blockers.length > 0) return blackboard.blockers[blackboard.blockers.length - 1];
  if (blackboard.lowCoherencyCount && blackboard.lowCoherencyCount > 0) return `${blackboard.lowCoherencyCount} low coherency claim${blackboard.lowCoherencyCount === 1 ? "" : "s"} need review.`;
  return "Continue from the latest Blackboard delta.";
}

export { TeamModeCompactTrace };
