import {
  type ChatMessageUi,
  type GeneratedImage,
  type PersistedMessage,
  type ToolBlockUi,
  parseToolStatus,
} from "../../types/chat";
import {
  isRecord,
  stringValue,
  toolTitle,
  shouldCollapseToolBlock,
  normalizeGeneratedImageUrls,
} from "./chunk-handlers";

export function messageFromPersisted(message: PersistedMessage): ChatMessageUi {
  const role = message.role === "user" ? "user" : message.role === "tool" ? "tool" : "agent";
  const timestamp = message.timestamp ?? String(Date.now());
  if (role === "tool") {
    const metadata = message.metadata ?? {};
    const data = isRecord(metadata.data) ? metadata.data : undefined;
    const name = stringValue(metadata.tool_name) ?? "tool";
    const status = parseToolStatus(stringValue(metadata.status));
    const path = stringValue(data?.display_path) ?? stringValue(data?.path);
    const block: ToolBlockUi = {
      id: message.tool_call_id ?? timestamp,
      name,
      status,
      title: toolTitle(name, path),
      message: "",
      content: stringValue(data?.content) ?? message.content,
      path,
      data,
      isCollapsed: shouldCollapseToolBlock(name, status),
    };
    return {
      id: timestamp,
      role,
      label: "Tool",
      content: "",
      reasoning: "",
      reasoningBlocks: [],
      toolBlocks: [block],
      teamEvents: [],
      parts: [{ kind: "tool", id: `tool-${block.id}`, toolBlockId: block.id }],
      isStreaming: false,
      isReasoningStreaming: false,
      metadata: message.metadata,
    };
  }

  const reasoning = message.reasoning_content ?? "";
  const images = imageListFromMetadata(message.metadata?.images);
  const reasoningBlock =
    reasoning.trim().length > 0
      ? { id: `reasoning-${timestamp}`, content: reasoning, isStreaming: false }
      : undefined;
  return {
    id: timestamp,
    role,
    label: role === "user" ? "You" : "PersonAgent",
    content: message.content,
    reasoning,
    reasoningBlocks: reasoningBlock ? [reasoningBlock] : [],
    toolBlocks: [],
    teamEvents: [],
    parts: [
      ...(reasoningBlock
        ? [{ kind: "reasoning" as const, id: `part-${reasoningBlock.id}`, reasoningBlockId: reasoningBlock.id }]
        : []),
      ...(message.content
        ? [{ kind: "content" as const, id: `content-${timestamp}`, content: message.content }]
        : []),
      ...images.map((image, index) => ({
        kind: "image" as const,
        id: `image-${timestamp}-${index}`,
        image,
      })),
    ],
    isStreaming: false,
    isReasoningStreaming: false,
    metadata: message.metadata,
  };
}

export function isRenderablePersistedMessage(message: PersistedMessage) {
  if (message.role === "user" || message.role === "tool") return true;
  if (message.content.trim().length > 0) return true;
  if ((message.reasoning_content ?? "").trim().length > 0) return true;
  if (imageListFromMetadata(message.metadata?.images).length > 0) return true;
  if (isRecord(message.metadata?.plan_approval)) return true;
  return false;
}

function imageListFromMetadata(value: unknown): GeneratedImage[] {
  if (!Array.isArray(value)) return [];
  return normalizeGeneratedImageUrls(value.filter(isGeneratedImage));
}

function isGeneratedImage(value: unknown): value is GeneratedImage {
  if (!isRecord(value)) return false;
  return (
    typeof value.mime_type === "string" &&
    (typeof value.data === "string" ||
      typeof value.url === "string" ||
      typeof value.artifact_id === "string")
  );
}
