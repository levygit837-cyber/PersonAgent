import { useEffect, useRef, useState } from "react";
import { useChatStore } from "../../stores/chat-store";
import { AgentMessage } from "./agent-message";
import { PlanApprovalPanel, ToolApprovalPanel } from "./plan-approval-panel";
import { UserMessage } from "./user-message";

const threshold = 120;

export function MessageFeed() {
  const messages = useChatStore((state) => state.messages);
  const error = useChatStore((state) => state.error);
  const pendingPlanApproval = useChatStore((state) => state.pendingPlanApproval);
  const pendingToolApproval = useChatStore((state) => state.pendingToolApproval);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const scrollFrameRef = useRef<number | undefined>(undefined);
  const [shouldAutoScroll, setShouldAutoScroll] = useState(true);
  const lastMessage = messages.at(-1);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const onScroll = () => {
      const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      setShouldAutoScroll(distance <= threshold);
    };
    scroller.addEventListener("scroll", onScroll);
    return () => scroller.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller || !shouldAutoScroll) return;
    if (scrollFrameRef.current !== undefined) {
      window.cancelAnimationFrame(scrollFrameRef.current);
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scroller.scrollTop = scroller.scrollHeight;
      scrollFrameRef.current = undefined;
    });
    return () => {
      if (scrollFrameRef.current !== undefined) {
        window.cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = undefined;
      }
    };
  }, [
    lastMessage?.content,
    lastMessage?.reasoning,
    lastMessage?.toolBlocks,
    messages.length,
    pendingPlanApproval,
    pendingToolApproval,
    shouldAutoScroll,
  ]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-8 pb-40 text-center">
        <div className="w-full max-w-[calc(100vw-48px)] md:max-w-sm">
          <div className="mb-3 inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-sm font-bold text-primary">
            P
          </div>
          <div className="text-base font-medium text-foreground">Ready</div>
          <p className="mt-1.5 text-[13px] leading-5 text-muted-foreground">
            Start a session with your local agent.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div ref={scrollerRef} className="h-full overflow-y-auto px-5 pb-44 pt-6">
      <div className="mx-auto flex w-full max-w-[820px] flex-col">
        {error ? <ErrorBanner message={error} /> : null}
        {messages.map((message) =>
          message.role === "user" ? (
            <UserMessage key={message.id} message={message} />
          ) : (
            <AgentMessage key={message.id} message={message} />
          ),
        )}
        {pendingPlanApproval ? <PlanApprovalPanel approval={pendingPlanApproval} /> : null}
        {pendingToolApproval ? <ToolApprovalPanel approval={pendingToolApproval} /> : null}
      </div>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {message}
    </div>
  );
}
