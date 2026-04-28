import ReactMarkdown from "react-markdown";
import { memo, useState, type CSSProperties, type ReactElement } from "react";
import { AlertCircle, Brain, Check, ChevronRight, Database, GitBranchPlus, Hammer, Loader2, MessageSquareText, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import type {
  ChatMessageUi,
  GeneratedImage,
  TeamAgentLogUi,
  TeamAgentTraceUi,
  TeamBlackboardTraceUi,
  TeamClaimTraceUi,
  TeamCompactStatus,
  TeamRunUi,
  TeamToolTraceUi,
  TeamTraceEventUi,
  ToolBlockUi,
} from "../../types/chat";
import { useChatStore } from "../../stores/chat-store";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../ui/tooltip";
import { ReasoningBlock } from "./reasoning-block";
import { CompactToolGroupBlock, ToolBlock, isBrowserToolName, isSearchShellCommand, isTodoTool } from "./tool-block";
import { CodeBlock } from "./code-block";

const TEAM_CARD_ARRIVAL_STAGGER_MS = 120;

export const AgentMessage = memo(function AgentMessage({ message }: { message: ChatMessageUi }) {
  if (!message.isStreaming && !hasRenderableProgress(message)) {
    return null;
  }

  const hasVisibleAnswerContent = hasVisibleContent(message);
  const body = message.parts.length > 0 ? orderedParts(message) : legacyBody(message);
  const hasLegacyThinking = message.parts.length === 0 && (message.reasoning || message.isReasoningStreaming);
  const orphanReasoningBlocks =
    message.parts.length > 0
      ? message.reasoningBlocks.filter(
          (block) => !message.parts.some((part) => part.reasoningBlockId === block.id),
        )
      : [];
  const hasOrphanReasoningFallback =
    orphanReasoningBlocks.length === 0 &&
    message.parts.length > 0 &&
    message.reasoning.trim().length > 0 &&
    !message.parts.some((part) => part.kind === "reasoning");
  const showExecutionStatus = message.isStreaming && !hasRenderableProgress(message);
  const showActions = !message.isStreaming && hasVisibleAnswerContent;

  return (
    <article className="group/agent-message mb-7 min-w-0 max-w-full">
      {showExecutionStatus ? <ChatExecutionStatus /> : null}
      {hasLegacyThinking ? (
        <ReasoningBlock
          reasoning={message.reasoning}
          isStreaming={message.isReasoningStreaming}
          autoCollapse={hasVisibleAnswerContent}
        />
      ) : null}
      {orphanReasoningBlocks.map((block) => (
        <ReasoningBlock
          key={block.id}
          reasoning={block.content}
          isStreaming={block.isStreaming}
          autoCollapse={hasVisibleAnswerContent}
        />
      ))}
      {hasOrphanReasoningFallback ? (
        <ReasoningBlock
          reasoning={message.reasoning}
          isStreaming={message.isReasoningStreaming}
          autoCollapse={hasVisibleAnswerContent}
        />
      ) : null}
      {message.teamRun ? <TeamModeCompactTrace run={message.teamRun} /> : message.teamEvents.length > 0 ? <TeamTrace events={message.teamEvents} /> : null}
      {body.length > 0 ? (
        <div className="min-w-0 max-w-full space-y-1.5">{body}</div>
      ) : null}
      {showActions ? <AgentMessageActions message={message} /> : null}
    </article>
  );

  function orderedParts(current: ChatMessageUi) {
    const widgets: ReactElement[] = [];
    const reasoningById = new Map(current.reasoningBlocks.map((block) => [block.id, block]));
    const toolsById = new Map(current.toolBlocks.map((block) => [block.id, block]));
    let pendingTools: ToolBlockUi[] = [];

    const flushTools = () => {
      if (pendingTools.length === 0) return;
      widgets.push(...renderToolBlocks(pendingTools));
      pendingTools = [];
    };

    current.parts.forEach((part, index) => {
      if (part.kind === "reasoning") {
        flushTools();
        const block = part.reasoningBlockId ? reasoningById.get(part.reasoningBlockId) : undefined;
        if (block) {
          widgets.push(
            <ReasoningBlock
              key={block.id}
              reasoning={block.content}
              isStreaming={block.isStreaming}
              autoCollapse={hasVisibleAnswerContent}
            />,
          );
        }
        return;
      }
      if (part.kind === "tool") {
        const block = part.toolBlockId ? toolsById.get(part.toolBlockId) : undefined;
        if (block) pendingTools.push(block);
        return;
      }
      if (part.kind === "image") {
        flushTools();
        if (part.image) {
          widgets.push(<GeneratedImageContent key={`${current.id}-image-${index}`} image={part.image} />);
        }
        return;
      }
      flushTools();
      if (part.content?.trim()) {
        widgets.push(<MarkdownContent key={`${current.id}-content-${index}`} content={part.content} isStreaming={current.isStreaming} />);
      }
    });
    flushTools();
    return widgets;
  }

  function legacyBody(current: ChatMessageUi) {
    const widgets: ReactElement[] = [];
    if (current.toolBlocks.length > 0) widgets.push(...renderToolBlocks(current.toolBlocks));
    if (current.content) widgets.push(<MarkdownContent key={`${current.id}-content`} content={current.content} isStreaming={current.isStreaming} />);
    return widgets;
  }
});

function AgentMessageActions({ message }: { message: ChatMessageUi }) {
  const isStreaming = useChatStore((state) => state.isStreaming);
  const setAgentFeedback = useChatStore((state) => state.setAgentFeedback);
  const regenerateAgentMessage = useChatStore((state) => state.regenerateAgentMessage);
  const branchAgentMessage = useChatStore((state) => state.branchAgentMessage);
  const feedback = stringMetadata(message.metadata?.feedback);
  const worktreeStatus = stringMetadata(message.metadata?.worktree_status);
  const worktreeError = stringMetadata(message.metadata?.worktree_error);
  const worktreePath = stringMetadata(message.metadata?.worktree_path);
  const worktreeBranch = stringMetadata(message.metadata?.worktree_branch);
  const branchPending = worktreeStatus === "running";

  return (
    <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5 opacity-70 transition-opacity group-hover/agent-message:opacity-100 focus-within:opacity-100">
      <TooltipIconButton
        label={feedback === "positive" ? "Positive feedback selected" : "Positive feedback"}
        active={feedback === "positive"}
        activeClassName="bg-success/15 text-success"
        disabled={isStreaming}
        onClick={() => setAgentFeedback(message.id, "positive")}
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </TooltipIconButton>
      <TooltipIconButton
        label={feedback === "negative" ? "Negative feedback selected" : "Negative feedback"}
        active={feedback === "negative"}
        activeClassName="bg-destructive/15 text-destructive"
        disabled={isStreaming}
        onClick={() => setAgentFeedback(message.id, "negative")}
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </TooltipIconButton>
      <TooltipIconButton
        label="Regenerate"
        disabled={isStreaming}
        onClick={() => {
          void regenerateAgentMessage(message.id);
        }}
      >
        <RotateCcw className="h-3.5 w-3.5" />
      </TooltipIconButton>
      <TooltipIconButton
        label={branchPending ? "Creating worktree" : "Branch to worktree"}
        active={worktreeStatus === "ready"}
        activeClassName="bg-primary/15 text-primary"
        disabled={isStreaming || branchPending}
        onClick={() => {
          void branchAgentMessage(message.id);
        }}
      >
        {branchPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitBranchPlus className="h-3.5 w-3.5" />}
      </TooltipIconButton>
      {feedback ? (
        <span className="ml-1 inline-flex items-center gap-1 rounded-full border border-glass-border/30 bg-background/45 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
          <Check className="h-3 w-3" />
          Feedback saved
        </span>
      ) : null}
      {worktreeStatus === "ready" ? (
        <span
          className="ml-1 min-w-0 truncate rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 font-mono text-[10px] text-primary"
          title={worktreePath}
        >
          Worktree: {worktreeBranch || compactMetadataPath(worktreePath)}
        </span>
      ) : null}
      {worktreeStatus === "error" && worktreeError ? (
        <span className="ml-1 inline-flex min-w-0 items-center gap-1 rounded-full border border-destructive/25 bg-destructive/10 px-2 py-0.5 font-mono text-[10px] text-destructive">
          <AlertCircle className="h-3 w-3 shrink-0" />
          <span className="truncate">{worktreeError}</span>
        </span>
      ) : null}
    </div>
  );
}

function TooltipIconButton({
  label,
  active = false,
  activeClassName = "bg-glass/80 text-foreground",
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  activeClassName?: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactElement;
}) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            disabled={disabled}
            aria-label={label}
            onClick={onClick}
            className={`h-7 w-7 rounded-lg text-muted-foreground hover:text-foreground ${active ? activeClassName : ""}`}
          >
            {children}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

const GeneratedImageContent = memo(function GeneratedImageContent({ image }: { image: GeneratedImage }) {
  const mimeType = image.mime_type || "image/png";
  const src = `data:${mimeType};base64,${image.data}`;
  return (
    <figure className="my-3 max-w-3xl">
      <img
        src={src}
        alt={image.alt || "Generated image"}
        className="max-h-[70vh] w-auto max-w-full rounded-2xl border border-glass-border/35 bg-secondary object-contain shadow-soft"
        loading="lazy"
      />
    </figure>
  );
});

function hasRenderableProgress(message: ChatMessageUi) {
  if (message.content.trim().length > 0) return true;
  if (message.reasoning.trim().length > 0 || message.isReasoningStreaming) return true;
  if (message.reasoningBlocks.some((block) => block.content.trim().length > 0 || block.isStreaming)) return true;
  if (message.toolBlocks.length > 0) return true;
  if (message.teamRun) return true;
  if (message.teamEvents.length > 0) return true;
  return message.parts.some(
    (part) => (part.kind === "content" && Boolean(part.content?.trim())) || part.kind === "image",
  );
}

function hasVisibleContent(message: ChatMessageUi) {
  if (message.content.trim().length > 0) return true;
  return message.parts.some(
    (part) => (part.kind === "content" && Boolean(part.content?.trim())) || part.kind === "image",
  );
}

function stringMetadata(value: unknown) {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}

function compactMetadataPath(path?: string) {
  if (!path) return "ready";
  const parts = path.split("/").filter(Boolean);
  return parts.slice(-2).join("/") || path;
}

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
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks, remarkBreakTags]}>{log.content}</ReactMarkdown>
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

function BlackboardClaim({ claim }: { claim: TeamClaimTraceUi }) {
  return (
    <div className="rounded-md border border-glass-border/35 bg-background/35 px-2.5 py-2">
      <div className="mb-1 flex items-center justify-between gap-2 font-mono text-[10px] uppercase">
        <span className="text-primary">{claim.type}</span>
        <span className="truncate text-muted-foreground">{claim.agentName ?? claim.agentId ?? "Blackboard"}</span>
      </div>
      <p className="line-clamp-3 text-[12px] leading-5 text-muted-foreground">{claim.text}</p>
    </div>
  );
}

function BlackboardFact({ title, value, detail }: { title: string; value: string; detail?: string }) {
  return (
    <div className="rounded-md border border-glass-border/35 bg-background/35 px-2.5 py-2">
      <div className="mb-1 flex items-center justify-between gap-2 font-mono text-[10px] uppercase">
        <span className="text-primary">{title}</span>
        <span className="truncate text-muted-foreground">{value}</span>
      </div>
      {detail ? <p className="text-[12px] leading-5 text-muted-foreground">{detail}</p> : null}
    </div>
  );
}

function BlackboardTools({ tools }: { tools: TeamToolTraceUi[] }) {
  return (
    <div className="rounded-md border border-glass-border/35 bg-background/35 px-2.5 py-2">
      <div className="mb-1 flex items-center gap-1.5 font-mono text-[10px] uppercase text-primary">
        <Database className="h-3 w-3" aria-hidden="true" />
        Tool audit
      </div>
      <div className="space-y-1">
        {tools.slice(-3).map((tool) => (
          <div key={tool.id} className="flex min-w-0 items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span className="truncate">{tool.summary ?? tool.title}</span>
            <StatusDot status={tool.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

function BlackboardTextList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-md border border-glass-border/35 bg-background/35 px-2.5 py-2">
      <div className="mb-1 font-mono text-[10px] uppercase text-primary">{title}</div>
      <ul className="space-y-1 text-[12px] leading-5 text-muted-foreground">
        {items.map((item, index) => (
          <li key={`${title}-${index}`} className="line-clamp-2">{item}</li>
        ))}
      </ul>
    </div>
  );
}

function TracePill({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded-full border border-glass-border/35 px-2 py-0.5">
      {label} <strong className="font-semibold text-foreground">{value}</strong>
    </span>
  );
}

function StatusDot({ status }: { status: TeamCompactStatus }) {
  if (status === "running" || status === "blocked") {
    return (
      <span className="relative inline-flex h-2 w-2 shrink-0" aria-label={status}>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/45" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
      </span>
    );
  }
  const color =
    status === "completed" ? "bg-success" : status === "failed" ? "bg-destructive" : status === "cancelled" ? "bg-muted-foreground" : "bg-muted-foreground/70";
  return <span className={`inline-flex h-2 w-2 shrink-0 rounded-full ${color}`} aria-label={status} />;
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

function formatToolPayload(tool: TeamToolTraceUi) {
  const payload = {
    phase: tool.phase,
    calls: tool.calls,
    results: tool.results,
    proposals: tool.proposals,
  };
  return JSON.stringify(payload, null, 2);
}

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
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks, remarkBreakTags]}>{content}</ReactMarkdown>
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

function renderToolBlocks(blocks: ToolBlockUi[]) {
  const widgets: ReactElement[] = [];
  let compactBlocks: ToolBlockUi[] = [];
  let compactKind: string | undefined;

  const flush = () => {
    if (compactBlocks.length === 0 || !compactKind) return;
    const group = compactBlocks;
    if (group.length === 1 && compactKind !== "shell") {
      widgets.push(<ToolBlock key={group[0].id} block={group[0]} />);
    } else {
      widgets.push(<CompactToolGroupBlock key={`${compactKind}-${group.map((item) => item.id).join("-")}`} kind={compactKind} blocks={group} />);
    }
    compactBlocks = [];
    compactKind = undefined;
  };

  for (const block of blocks) {
    if (isTodoTool(block)) {
      flush();
      continue;
    }
    const kind = compactToolKindFor(block);
    if (kind) {
      if (compactKind && compactKind !== kind) flush();
      compactKind = kind;
      compactBlocks.push(block);
    } else {
      flush();
      widgets.push(<ToolBlock key={block.id} block={block} />);
    }
  }
  flush();
  return widgets;
}

export function compactToolKindFor(block: ToolBlockUi) {
  if (block.name === "Read" || block.name === "read_file") return "read";
  if (block.name === "Write" || block.name === "Edit") return "write";
  if (block.name === "Glob" || block.name === "Grep" || block.name === "search_files") return "search";
  if (block.name === "shell" && isSearchShellCommand(block)) return "search";
  if (block.name === "shell") return "shell";
  if (block.name === "WebFetch") return "web";
  if (block.name === "BrowserOpen") return "browser_open";
  if (block.name === "BrowserExtractContent") return "browser_extract";
  if (block.name === "BrowserSearch") return "browser_search";
  if (block.name === "BrowserListTabs") return "browser_tabs";
  if (block.name === "BrowserReadContentChunk") return "browser_chunks";
  if (block.name === "BrowserGetHtml") return "browser_html";
  if (block.name === "LSP") return "lsp";
  if (isTodoTool(block)) return "todo";
  if (block.name === "Task" || block.name.startsWith("Task")) return "task";
  if (isBrowserToolName(block.name)) return `tool:${block.name}`;
  if (block.name.trim()) return `tool:${block.name.trim().toLowerCase()}`;
  return undefined;
}

function ChatExecutionStatus() {
  return (
    <div className="mb-3 mt-1 flex items-center gap-2 font-mono text-[11px]" role="status" aria-live="polite">
      <span className="personagent-spinner h-3 w-3 text-primary/80" aria-hidden="true" />
      <span className="personagent-shimmer font-medium tracking-wide">Thinking...</span>
    </div>
  );
}

export const MarkdownContent = memo(function MarkdownContent({
  content,
  isStreaming = false,
}: {
  content: string;
  isStreaming?: boolean;
}) {
  return (
    <div className="markdown-content prose prose-invert min-w-0 max-w-full overflow-hidden text-[14px] leading-6 prose-p:my-1.5 prose-code:rounded prose-code:bg-secondary prose-code:px-1 prose-code:py-0.5 prose-code:text-foreground prose-a:text-primary">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks, remarkBreakTags]}
        components={{
          h1: ({ children }) => <h1 className="my-3 text-[22px] font-semibold leading-8 text-foreground">{children}</h1>,
          h2: ({ children }) => <h2 className="my-2.5 text-[18px] font-semibold leading-7 text-foreground">{children}</h2>,
          h3: ({ children }) => <h3 className="my-2 text-[15px] font-semibold leading-6 text-foreground">{children}</h3>,
          p: ({ children }) => <p className="my-1.5 min-w-0 break-words">{children}</p>,
          a: ({ children, ...props }) => (
            <a {...props} className="break-words text-primary">
              {children}
            </a>
          ),
          ul: ({ children }) => <ul className="my-2 list-disc space-y-0.5 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal space-y-0.5 pl-5">{children}</ol>,
          li: ({ children }) => <li className="min-w-0 break-words pl-1">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-3 border-l border-glass-border/50 pl-4 text-muted-foreground">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="not-prose my-4 w-full max-w-full overflow-x-auto rounded-xl border border-glass-border/35 bg-card/45 shadow-soft">
              <table className="w-max min-w-full border-collapse text-left text-[13px] leading-6">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-secondary/55 text-foreground">{children}</thead>,
          tbody: ({ children }) => <tbody className="divide-y divide-glass-border/35">{children}</tbody>,
          tr: ({ children }) => <tr className="align-top">{children}</tr>,
          th: ({ children }) => (
            <th className="min-w-[9rem] max-w-[18rem] border-b border-glass-border/45 px-3 py-2 align-top font-semibold text-foreground">
              <div className="whitespace-normal break-words">{children}</div>
            </th>
          ),
          td: ({ children }) => (
            <td className="min-w-[9rem] max-w-[18rem] px-3 py-2 align-top text-foreground/90">
              <div className="whitespace-normal break-words">{children}</div>
            </td>
          ),
          pre: ({ node, children, ...props }: any) => {
            // Check if this is a code block (has code child with className)
            const codeElement = node?.children?.[0];
            const isCodeBlock = codeElement?.tagName === "code" && codeElement?.properties?.className;
            
            if (isCodeBlock) {
              const rawClassName = codeElement.properties.className;
              const className = Array.isArray(rawClassName) ? rawClassName.join(" ") : String(rawClassName ?? "");
              return (
                <CodeBlock 
                  className={className} 
                  node={node} 
                  isStreaming={isStreaming}
                  {...props}
                >
                  {children}
                </CodeBlock>
              );
            }
            
            // Fallback for pre elements that aren't code blocks
            return (
              <pre
                {...props}
                className="not-prose my-3 max-w-full overflow-x-auto rounded-xl border border-glass-border/35 bg-card/80 p-3 text-[12px] leading-5"
              >
                {children}
              </pre>
            );
          },
          code: ({ node, className, children, ...props }: any) => {
            // Inline code (not inside pre)
            const match = /language-(\w+)/.exec(className || "");
            const isInline = !match;
            
            if (isInline) {
              return (
                <code className={`${className ?? ""} break-words`} {...props}>
                  {children}
                </code>
              );
            }
            
            // Code block content - let the pre component handle it
            return <>{children}</>;
          },
        }}
      >
        {content.trimEnd()}
      </ReactMarkdown>
    </div>
  );
});

type MarkdownNode = {
  type?: string;
  value?: string;
  children?: MarkdownNode[];
};

function remarkBreakTags() {
  return (tree: MarkdownNode) => transformBreakTags(tree);
}

function transformBreakTags(node: MarkdownNode) {
  if (!node.children) return;
  const nextChildren: MarkdownNode[] = [];

  for (const child of node.children) {
    if (child.type === "html" && isBreakTag(child.value)) {
      nextChildren.push({ type: "break" });
      continue;
    }

    if (child.type === "text" && child.value && hasBreakTag(child.value)) {
      nextChildren.push(...splitBreakTagText(child.value));
      continue;
    }

    transformBreakTags(child);
    nextChildren.push(child);
  }

  node.children = nextChildren;
}

function splitBreakTagText(value: string): MarkdownNode[] {
  const nodes: MarkdownNode[] = [];
  let cursor = 0;
  for (const match of value.matchAll(/<br\s*\/?>/gi)) {
    const index = match.index ?? 0;
    if (index > cursor) nodes.push({ type: "text", value: value.slice(cursor, index) });
    nodes.push({ type: "break" });
    cursor = index + match[0].length;
  }
  if (cursor < value.length) nodes.push({ type: "text", value: value.slice(cursor) });
  return nodes;
}

function isBreakTag(value?: string) {
  return Boolean(value && /^<br\s*\/?>$/i.test(value.trim()));
}

function hasBreakTag(value: string) {
  return /<br\s*\/?>/i.test(value);
}
