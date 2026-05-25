import { type FormEvent, type PointerEvent, useEffect, useRef, useState } from "react";
import { ArrowUp, Bot, ChevronDown } from "lucide-react";
import type { PullRequestSummary } from "../../api/client";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";
import { clampValue, shortPath } from "./shared/pr-utils";

type PullRequestFile = PullRequestSummary["files"][number];

interface ReviewAgentMessage {
  id: string;
  role: "agent" | "user";
  content: string;
}

export function ReviewAgentWindow({
  pullRequest,
  activeFile,
}: {
  pullRequest: PullRequestSummary;
  activeFile?: PullRequestFile;
}) {
  const windowRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ dx: number; dy: number; width: number; height: number } | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const positionRef = useRef({
    x: Math.max(12, window.innerWidth - 420),
    y: Math.max(48, window.innerHeight - 330),
  });
  const messageNonceRef = useRef(1);
  const [expanded, setExpanded] = useState(false);
  const [input, setInput] = useState("");
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [dragging, setDragging] = useState(false);
  const [messages, setMessages] = useState<ReviewAgentMessage[]>([
    {
      id: "agent-initial",
      role: "agent",
      content: "Initial scan is ready. The highest-risk area is request context propagation across chat, workspace and git operations.",
    },
  ]);
  const [position, setPosition] = useState(() => ({
    x: Math.max(12, window.innerWidth - 420),
    y: Math.max(48, window.innerHeight - 330),
  }));

  useEffect(() => {
    positionRef.current = position;
  }, [position]);

  useEffect(() => {
    return () => {
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const clamp = () => {
      setViewportWidth(window.innerWidth);
      const rect = windowRef.current?.getBoundingClientRect();
      const width = rect?.width ?? 380;
      const height = rect?.height ?? 320;
      const nextPosition = {
        x: clampValue(positionRef.current.x, 8, Math.max(8, window.innerWidth - width - 8)),
        y: clampValue(positionRef.current.y, 44, Math.max(44, window.innerHeight - Math.min(height, window.innerHeight - 52))),
      };
      positionRef.current = nextPosition;
      setPosition(nextPosition);
    };
    clamp();
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
  }, [expanded]);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const rect = windowRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = { dx: event.clientX - rect.left, dy: event.clientY - rect.top, width: rect.width, height: rect.height };
    setDragging(true);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    positionRef.current = {
      x: clampValue(event.clientX - drag.dx, 8, Math.max(8, window.innerWidth - drag.width - 8)),
      y: clampValue(event.clientY - drag.dy, 44, Math.max(44, window.innerHeight - Math.min(drag.height, window.innerHeight - 52))),
    };
    if (animationFrameRef.current !== null) return;
    animationFrameRef.current = window.requestAnimationFrame(() => {
      animationFrameRef.current = null;
      setPosition(positionRef.current);
    });
  };

  const stopDrag = (event: PointerEvent<HTMLDivElement>) => {
    dragRef.current = null;
    setDragging(false);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  const submitPrompt = (event: FormEvent) => {
    event.preventDefault();
    const value = input.trim();
    if (!value) return;
    const nextId = messageNonceRef.current++;
    setMessages((current) => [
      ...current,
      { id: `user-${nextId}`, role: "user", content: value },
      {
        id: `agent-${nextId}`,
        role: "agent",
        content: `I will review ${shortPath(activeFile?.path ?? "the selected file")} in PR #${pullRequest.number}. Focus areas: contracts, regressions, missing tests and hidden context changes.`,
      },
    ]);
    setInput("");
  };

  const pickSuggestion = (value: string) => {
    setExpanded(true);
    setInput(value);
  };

  const narrowViewport = viewportWidth < 760;

  return (
    <aside
      ref={windowRef}
      role="dialog"
      aria-label="Review Agent"
      data-testid="review-agent-window"
      className={cn(
        "fixed left-0 top-0 z-50 flex max-h-[calc(100vh-56px)] flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-popover/98 shadow-floating will-change-transform",
        dragging ? "transition-none" : "transition-[width,border-color,box-shadow] duration-200",
        expanded ? "w-[min(390px,calc(100vw-24px))]" : "w-[min(300px,calc(100vw-24px))]",
      )}
      style={{ transform: `translate3d(${narrowViewport ? 12 : position.x}px, ${position.y}px, 0)` }}
    >
      <div
        className="flex items-center gap-2 border-b border-glass-border/25 bg-card/80 px-3 py-2"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={stopDrag}
        onPointerCancel={stopDrag}
      >
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-xl border border-primary/25 bg-primary/10 text-primary">
          <Bot className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-foreground">Review Agent</div>
          <div className="truncate text-[11px] text-muted-foreground">Watching {shortPath(activeFile?.path ?? "current PR")}</div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          aria-label={expanded ? "Compact Review Agent" : "Expand Review Agent"}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={() => setExpanded((current) => !current)}
        >
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform duration-150", expanded ? "rotate-180" : "")} />
        </Button>
      </div>

      {expanded ? (
        <>
          <div className="max-h-52 space-y-2 overflow-y-auto p-3">
            {messages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  "rounded-xl border px-3 py-2 text-xs leading-5",
                  message.role === "user"
                    ? "border-primary/25 bg-primary/10 text-foreground"
                    : "border-glass-border/25 bg-background/45 text-muted-foreground",
                )}
              >
                {message.content}
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 border-t border-glass-border/20 px-3 py-2">
            <AgentSuggestion onClick={() => pickSuggestion("Review only the selected file.")}>Selected file</AgentSuggestion>
            <AgentSuggestion onClick={() => pickSuggestion("Find regressions that could break existing tests.")}>Regressions</AgentSuggestion>
            <AgentSuggestion onClick={() => pickSuggestion("Search for the function usage across the repository.")}>Find usages</AgentSuggestion>
          </div>
          <form className="flex items-end gap-2 border-t border-glass-border/25 p-2.5" onSubmit={submitPrompt}>
            <textarea
              value={input}
              rows={1}
              onChange={(event) => setInput(event.currentTarget.value)}
              placeholder="Ask the PR agent..."
              className="min-h-10 min-w-0 flex-1 resize-none rounded-xl border border-glass-border/35 bg-background/55 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/70 focus:border-primary/35 focus:ring-1 focus:ring-primary/20"
            />
            <Button type="submit" size="icon" className="h-10 w-10 rounded-xl" aria-label="Send review agent message">
              <ArrowUp className="h-4 w-4" />
            </Button>
          </form>
        </>
      ) : null}
    </aside>
  );
}

function AgentSuggestion({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      className="rounded-full border border-glass-border/30 bg-background/40 px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-glass/80 hover:text-foreground"
      onClick={onClick}
    >
      {children}
    </button>
  );
}
