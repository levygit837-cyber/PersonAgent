import type { ChatMessagePartUi, ChatMessageUi, GeneratedImage, StreamChunk } from "../../../types/chat";
import {
  thinkingStates,
  textFlushBuffers,
  STREAM_TEXT_FLUSH_MS,
} from "../internal";
import { appendReasoningChunk, closeActiveReasoning } from "./reasoning";
import type { SetFn } from "./utils";
import { useAppStore } from "../../app-store";

export function queueTextChunk(
  agentId: string,
  chunk: StreamChunk,
  set: SetFn,
) {
  const buffer = textFlushBuffers.get(agentId) ?? { content: "", reasoning: "" };
  buffer.content += chunk.content ?? "";
  buffer.reasoning += chunk.reasoning_content ?? "";
  if (chunk.finish_reason) buffer.finishReason = chunk.finish_reason;
  textFlushBuffers.set(agentId, buffer);

  if (chunk.finish_reason) {
    flushTextBuffer(agentId, set);
    return;
  }

  if (!buffer.timer) {
    buffer.timer = setTimeout(() => flushTextBuffer(agentId, set), STREAM_TEXT_FLUSH_MS);
  }
}

export function flushTextBuffer(
  agentId: string,
  set: SetFn,
) {
  const buffer = textFlushBuffers.get(agentId);
  if (!buffer) return;
  if (buffer.timer) clearTimeout(buffer.timer);
  textFlushBuffers.delete(agentId);

  const content = buffer.content;
  const reasoning = buffer.reasoning;
  const finishReason = buffer.finishReason;
  if (!content && !reasoning && !finishReason) return;
  const isFinalFinish = Boolean(finishReason && finishReason !== "tool_calls");

  set((state) => ({
    messages: state.messages.map((item) => {
      if (item.id !== agentId) return item;
      let next = item;
      if (reasoning) {
        next = appendReasoningChunk(next, reasoning);
      }
      if (content || finishReason) {
        next = closeActiveReasoning(next, true);
      }
      if (content) {
        next = {
          ...next,
          content: next.content + content,
          parts: appendContentPart(next.parts, next.id, content),
        };
      }
      if (isFinalFinish) thinkingStates.delete(agentId);
      return {
        ...next,
        isStreaming: !isFinalFinish,
        isReasoningStreaming:
          !isFinalFinish &&
          !content &&
          next.reasoningBlocks.some((block) => block.isStreaming),
      };
    }),
  }));
}

function appendContentPart(parts: ChatMessagePartUi[], messageId: string, chunk: string) {
  const next = [...parts];
  const last = next.at(-1);
  if (last?.kind === "content") {
    next[next.length - 1] = { ...last, content: `${last.content ?? ""}${chunk}` };
    return next;
  }
  next.push({
    kind: "content",
    id: `${messageId}-content-${next.length}`,
    content: chunk,
  });
  return next;
}

function appendImageParts(parts: ChatMessagePartUi[], messageId: string, images: GeneratedImage[]) {
  const next = [...parts];
  for (const image of images) {
    next.push({
      kind: "image",
      id: `${messageId}-image-${next.length}`,
      image,
    });
  }
  return next;
}

export function applyImageChunks(
  agentId: string,
  images: GeneratedImage[],
  set: SetFn,
) {
  if (images.length === 0) return;
  const normalizedImages = normalizeGeneratedImageUrls(images);
  set((state) => ({
    messages: state.messages.map((item) => {
      if (item.id !== agentId) return item;
      const next = closeActiveReasoning(item, true);
      return {
        ...next,
        parts: appendImageParts(next.parts, next.id, normalizedImages),
      };
    }),
  }));
}

export function normalizeGeneratedImageUrls(images: GeneratedImage[]) {
  const baseUrl = useAppStore.getState().baseUrl.replace(/\/+$/, "");
  return images.map((image) => {
    if (!image.url || /^https?:\/\//i.test(image.url) || image.url.startsWith("data:") || image.url.startsWith("blob:")) {
      return image;
    }
    const url = image.url.startsWith("/") ? `${baseUrl}${image.url}` : `${baseUrl}/${image.url}`;
    return { ...image, url };
  });
}
