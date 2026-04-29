import { useEffect, useRef } from "react";
import { useChatStore } from "../../stores/chat-store";
import { AgentMessage } from "./agent-message";
import { PlanApprovalPanel, ToolApprovalPanel } from "./plan-approval-panel";
import { UserMessage } from "./user-message";
import type { ChatMessageUi, PlanApprovalUi } from "../../types/chat";

const followThreshold = 120;
const scrollUpKeys = new Set(["ArrowUp", "PageUp", "Home"]);

export function MessageFeed({ extraBottomPadding = false, compact = false }: { extraBottomPadding?: boolean; compact?: boolean }) {
  const messages = useChatStore((state) => state.messages);
  const conversationId = useChatStore((state) => state.conversationId);
  const error = useChatStore((state) => state.error);
  const pendingPlanApproval = useChatStore((state) => state.pendingPlanApproval);
  const pendingToolApproval = useChatStore((state) => state.pendingToolApproval);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const scrollFrameRef = useRef<number | undefined>(undefined);
  const shouldAutoScrollRef = useRef(true);
  const lastMessage = messages.at(-1);

  useEffect(() => {
    shouldAutoScrollRef.current = true;
  }, [conversationId]);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const cancelScheduledScroll = () => {
      if (scrollFrameRef.current !== undefined) {
        window.cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = undefined;
      }
    };
    const setAutoScrollFromPosition = () => {
      const shouldFollow = isNearLatest(scroller);
      shouldAutoScrollRef.current = shouldFollow;
      if (!shouldFollow) cancelScheduledScroll();
    };
    const onScroll = () => {
      setAutoScrollFromPosition();
    };
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY < 0 && scroller.scrollTop > 0) {
        shouldAutoScrollRef.current = false;
        cancelScheduledScroll();
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (scrollUpKeys.has(event.key) || (event.key === " " && event.shiftKey)) {
        shouldAutoScrollRef.current = false;
        cancelScheduledScroll();
      }
    };
    scroller.addEventListener("scroll", onScroll);
    scroller.addEventListener("wheel", onWheel, { passive: true });
    scroller.addEventListener("keydown", onKeyDown);
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      scroller.removeEventListener("wheel", onWheel);
      scroller.removeEventListener("keydown", onKeyDown);
      cancelScheduledScroll();
    };
  }, []);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller || !shouldAutoScrollRef.current) return;
    if (scrollFrameRef.current !== undefined) {
      window.cancelAnimationFrame(scrollFrameRef.current);
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      if (shouldAutoScrollRef.current) {
        scroller.scrollTop = scroller.scrollHeight;
      }
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
    <div
      ref={scrollerRef}
      data-testid="message-feed-scroller"
      className={[
        "h-full overflow-x-hidden overflow-y-auto pt-6",
        compact ? "px-3" : "px-5",
        extraBottomPadding ? "pb-[380px]" : compact ? "pb-56" : "pb-64",
      ].join(" ")}
      style={{ overflowAnchor: "none" }}
      tabIndex={-1}
    >
      <div className={compact ? "mx-auto flex w-full min-w-0 max-w-[720px] flex-col" : "mx-auto flex w-full min-w-0 max-w-[820px] flex-col"}>
        {error ? <ErrorBanner message={error} /> : null}
        {messages.map((message) => {
          const planApproval = planApprovalArtifact(message);
          const isActivePlan = Boolean(
            pendingPlanApproval &&
              planApproval &&
              pendingPlanApproval.approvalId === planApproval.approvalId,
          );
          return (
            <div key={message.id}>
              {message.role === "user" ? (
                <UserMessage message={message} />
              ) : (
                <AgentMessage message={message} />
              )}
              {planApproval ? <PlanApprovalPanel approval={planApproval} active={isActivePlan} /> : null}
            </div>
          );
        })}
        {pendingPlanApproval && !messages.some((message) => planApprovalArtifact(message)?.approvalId === pendingPlanApproval.approvalId) ? (
          <PlanApprovalPanel approval={pendingPlanApproval} />
        ) : null}
        {pendingToolApproval ? <ToolApprovalPanel approval={pendingToolApproval} /> : null}
      </div>
    </div>
  );
}

function planApprovalArtifact(message: ChatMessageUi): PlanApprovalUi | undefined {
  const raw = message.metadata?.plan_approval;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const value = raw as Partial<PlanApprovalUi>;
  if (!value.approvalId || !value.planContent) return undefined;
  return {
    conversationId: String(value.conversationId ?? ""),
    approvalId: String(value.approvalId),
    planId: String(value.planId ?? ""),
    planContent: String(value.planContent),
    planStatus: String(value.planStatus ?? "awaiting_approval"),
    feedback: value.feedback,
  };
}

function isNearLatest(scroller: HTMLDivElement) {
  const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
  return distance <= followThreshold;
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mb-4 rounded-xl border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive shadow-soft">
      {message}
    </div>
  );
}
