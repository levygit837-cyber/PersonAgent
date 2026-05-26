import { MessageSquarePlus, ListChecks } from "lucide-react";
import { cn } from "../../../../../lib/utils";
import { browserCssBadgeClass, browserCssLabel } from "../../helpers/browser-normalization-helpers";
import type { BrowserState } from "../../helpers";

interface BrowserTabStatusBarProps {
  browser: BrowserState;
  elementMapLength: number;
  backendTabsLength: number;
  annotationsLength: number;
  timelineEventsLength: number;
}

export function BrowserTabStatusBar({
  browser,
  elementMapLength,
  backendTabsLength,
  annotationsLength,
  timelineEventsLength,
}: BrowserTabStatusBarProps) {
  return (
    <div className="-mx-3 flex h-8 shrink-0 items-center gap-2 border-b border-glass-border/20 bg-background/55 px-3 text-[11px] text-muted-foreground">
      <span className={cn("rounded-full border px-2 py-0.5", browserCssBadgeClass(browser.view?.css_fidelity))}>
        {browserCssLabel(browser.view?.css_fidelity)}
      </span>
      <span className="min-w-0 flex-1 truncate">
        {browser.mode === "annotate"
          ? "Annotation mode · hover and click an element"
          : `${elementMapLength} mapped elements${backendTabsLength > 1 ? ` · ${backendTabsLength} tabs` : ""}`}
      </span>
      {annotationsLength ? (
        <span className="inline-flex items-center gap-1">
          <MessageSquarePlus className="h-3 w-3" />
          {annotationsLength}
        </span>
      ) : null}
      {timelineEventsLength ? (
        <span className="inline-flex items-center gap-1">
          <ListChecks className="h-3 w-3" />
          {timelineEventsLength}
        </span>
      ) : null}
    </div>
  );
}
