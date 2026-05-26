import { memo, useState } from "react";
import type { ChatMessageUi } from "../../types/chat";
import {
  AgentMessageContent,
  ChatExecutionStatus,
  MarkdownContent,
  compactToolKindFor,
} from "./agent-message/content-blocks";
import {
  AgentMessageActions,
  MemoryTraceInspector,
  memoryTraceFromMetadata,
  type MemoryTraceTab,
} from "./agent-message/actions";
import { AgentMessageThinking } from "./agent-message/thinking-block";
import { TeamModeCompactTrace } from "./agent-message/team-compact-trace";
import { TeamTrace } from "./agent-message/team-trace";

export const AgentMessage = memo(function AgentMessage({ message }: { message: ChatMessageUi }) {
  const memoryTrace = memoryTraceFromMetadata(message.metadata?.memory_trace);
  const [memoryInspectorOpen, setMemoryInspectorOpen] = useState(false);
  const [memoryTraceTab, setMemoryTraceTab] = useState<MemoryTraceTab>("used");

  if (!message.isStreaming && !hasRenderableProgress(message)) {
    return null;
  }

  const hasVisibleAnswerContent = hasVisibleContent(message);
  const showExecutionStatus = message.isStreaming && !hasRenderableProgress(message);
  const showActions = !message.isStreaming && hasVisibleAnswerContent;

  return (
    <article className="group/agent-message mb-7 min-w-0 max-w-full">
      {showExecutionStatus ? <ChatExecutionStatus /> : null}
      <AgentMessageThinking message={message} hasVisibleAnswerContent={hasVisibleAnswerContent} />
      {message.teamRun ? <TeamModeCompactTrace run={message.teamRun} /> : message.teamEvents.length > 0 ? <TeamTrace events={message.teamEvents} /> : null}
      <AgentMessageContent message={message} hasVisibleAnswerContent={hasVisibleAnswerContent} />
      {memoryTrace && memoryInspectorOpen ? (
        <MemoryTraceInspector trace={memoryTrace} activeTab={memoryTraceTab} onTabChange={setMemoryTraceTab} />
      ) : null}
      {showActions ? (
        <AgentMessageActions
          message={message}
          memoryTrace={memoryTrace}
          memoryInspectorOpen={memoryInspectorOpen}
          onToggleMemoryInspector={() => setMemoryInspectorOpen((value) => !value)}
        />
      ) : null}
    </article>
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

export { MarkdownContent, compactToolKindFor } from "./agent-message/content-blocks";
