import { Database } from "lucide-react";
import type { TeamClaimTraceUi, TeamToolTraceUi } from "../../../types/chat";
import { StatusDot } from "./shared";

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

export { BlackboardClaim, BlackboardFact, BlackboardTools, BlackboardTextList };
