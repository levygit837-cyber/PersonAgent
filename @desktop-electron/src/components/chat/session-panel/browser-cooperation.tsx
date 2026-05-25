import { Check, ChevronDown } from "lucide-react";
import type { SessionBrowserCooperationMode, SessionBrowserElement, SessionBrowserView } from "../../../api/client";
import { cn } from "../../../lib/utils";
import { Button } from "../../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "../../ui/dropdown-menu";
import { browserRenderedElementStyle, browserTraceBounds } from "./browser-viewport-helpers";

export function BrowserCooperationModeMenu({
  value,
  disabled,
  onChange,
}: {
  value: SessionBrowserCooperationMode | "off";
  disabled: boolean;
  onChange: (mode: SessionBrowserCooperationMode | "off") => void;
}) {
  const options: Array<{ value: SessionBrowserCooperationMode | "off"; label: string }> = [
    { value: "off", label: "Off" },
    { value: "observe_only", label: "Observe" },
    { value: "suggest_before_action", label: "Suggest" },
    { value: "agent_control", label: "Control" },
  ];
  const active = options.find((option) => option.value === value) ?? options[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Browser cooperation mode"
          disabled={disabled}
          className={cn(
            "inline-flex h-7 max-w-[132px] shrink-0 items-center gap-1.5 rounded-full border border-glass-border/35 bg-card/70 px-2.5 text-[11px] text-foreground outline-none transition-colors hover:bg-accent disabled:pointer-events-none disabled:opacity-35",
            value !== "off" && "border-primary/35 bg-primary/10 text-primary",
          )}
        >
          <span className="truncate">{active.label}</span>
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuLabel>Cooperation</DropdownMenuLabel>
        {options.map((option) => (
          <DropdownMenuItem key={option.value} onSelect={() => onChange(option.value)}>
            <Check className={cn("mr-2 h-3.5 w-3.5", option.value === value ? "opacity-100" : "opacity-0")} />
            <span>{option.label}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function BrowserProposalOverlay({
  proposal,
  target,
  elementMap,
  view,
  surface,
  onDecision,
}: {
  proposal: Record<string, unknown>;
  target: Record<string, unknown>;
  elementMap: SessionBrowserElement[];
  view: SessionBrowserView;
  surface: HTMLElement | null;
  onDecision: (proposal: Record<string, unknown>, decision: "approve" | "deny" | "dismiss") => void;
}) {
  const bounds = browserTraceBounds(target, elementMap);
  if (!bounds) {
    return (
      <div className="absolute right-3 top-3 z-40 w-[min(340px,calc(100%-24px))] rounded-lg border border-primary/35 bg-background/94 p-3 text-xs shadow-floating backdrop-blur-xl">
        <ProposalBody proposal={proposal} onDecision={onDecision} />
      </div>
    );
  }
  const highlight = browserRenderedElementStyle(bounds, surface, view);
  const barTop = Math.max(8, highlight.top - 38);
  const barLeft = Math.max(8, Math.min(highlight.left, (view.viewport_width || 420) - 230));
  return (
    <>
      <div
        className="pointer-events-none absolute z-30 rounded-[4px] border-2 border-primary bg-primary/18 shadow-[0_0_0_3px_rgba(34,150,255,0.14)]"
        style={highlight}
      />
      <div
        className="absolute z-40 flex max-w-[min(360px,calc(100%-16px))] items-center gap-2 rounded-full border border-primary/35 bg-background/94 px-2 py-1.5 text-[11px] shadow-floating backdrop-blur-xl"
        style={{ left: barLeft, top: barTop }}
      >
        <span className="min-w-0 max-w-32 truncate text-muted-foreground">
          {String(proposal.tool_name ?? "Browser action")}
        </span>
        <button
          type="button"
          className="rounded-full bg-primary px-2.5 py-1 font-medium text-primary-foreground"
          onClick={(event) => {
            event.stopPropagation();
            onDecision(proposal, "approve");
          }}
        >
          Allow
        </button>
        <button
          type="button"
          className="rounded-full border border-destructive/35 px-2.5 py-1 font-medium text-destructive"
          onClick={(event) => {
            event.stopPropagation();
            onDecision(proposal, "deny");
          }}
        >
          Deny
        </button>
        <button
          type="button"
          className="rounded-full px-2 py-1 text-muted-foreground hover:text-foreground"
          onClick={(event) => {
            event.stopPropagation();
            onDecision(proposal, "dismiss");
          }}
        >
          Dismiss
        </button>
      </div>
    </>
  );
}

export function ProposalBody({
  proposal,
  onDecision,
}: {
  proposal: Record<string, unknown>;
  onDecision: (proposal: Record<string, unknown>, decision: "approve" | "deny" | "dismiss") => void;
}) {
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-foreground">
            {String(proposal.tool_name ?? "Browser action")}
          </div>
          <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
            {String(proposal.reason ?? "The agent needs permission before executing this action.")}
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-primary/30 px-2 py-0.5 font-mono text-[10px] text-primary">
          {String(proposal.mode ?? "ask")}
        </span>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" onClick={() => onDecision(proposal, "approve")}>
          Allow
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDecision(proposal, "deny")}>
          Deny
        </Button>
      </div>
    </div>
  );
}
