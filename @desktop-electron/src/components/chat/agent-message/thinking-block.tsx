import { memo } from "react";
import type { ChatMessageUi } from "../../../types/chat";
import { useChatStore } from "../../../stores/chat-store";
import { ReasoningBlock } from "../reasoning-block";

export const AgentMessageThinking = memo(function AgentMessageThinking({
  message,
  hasVisibleAnswerContent,
}: {
  message: ChatMessageUi;
  hasVisibleAnswerContent: boolean;
}) {
  const setReasoningBlockExpanded = useChatStore(
    (state) => state.setReasoningBlockExpanded,
  );

  const hasLegacyThinking =
    message.parts.length === 0 &&
    (message.reasoning || message.isReasoningStreaming);

  const orphanReasoningBlocks =
    message.parts.length > 0
      ? message.reasoningBlocks.filter(
          (block) =>
            !message.parts.some(
              (part) => part.reasoningBlockId === block.id,
            ),
        )
      : [];

  const hasOrphanReasoningFallback =
    orphanReasoningBlocks.length === 0 &&
    message.parts.length > 0 &&
    message.reasoning.trim().length > 0 &&
    !message.parts.some((part) => part.kind === "reasoning");

  return (
    <>
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
          userExpanded={block.userExpanded}
          onToggleExpanded={() =>
            setReasoningBlockExpanded(
              message.id,
              block.id,
              !block.userExpanded,
            )
          }
        />
      ))}
      {hasOrphanReasoningFallback ? (
        <ReasoningBlock
          reasoning={message.reasoning}
          isStreaming={message.isReasoningStreaming}
          autoCollapse={hasVisibleAnswerContent}
        />
      ) : null}
    </>
  );
});
