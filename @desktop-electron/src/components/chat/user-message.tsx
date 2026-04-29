import { useState } from "react";
import { RotateCcw, Send, X } from "lucide-react";
import type { ChatMessageUi, ContextAttachment } from "../../types/chat";
import { useChatStore } from "../../stores/chat-store";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../ui/tooltip";
import { MarkdownContent } from "./agent-message";

const USER_MESSAGE_CARD_SCROLL_CLASS = "max-h-[min(58vh,520px)] overflow-y-auto overscroll-contain";

export function UserMessage({ message }: { message: ChatMessageUi }) {
  const rewindUserMessage = useChatStore((state) => state.rewindUserMessage);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const [rewindOpen, setRewindOpen] = useState(false);
  const contextAttachments = contextAttachmentsFromMetadata(message.metadata?.context_attachments);
  const annotationBundle = parseAnnotationMessage(message.content);

  return (
    <article className="group/user-message mb-9 flex justify-end">
      <div className="relative min-w-0 max-w-[min(680px,88%)]">
        {!rewindOpen ? (
          <TooltipProvider delayDuration={150}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="iconSm"
                  disabled={isStreaming}
                  aria-label="Rewind message"
                  onClick={() => setRewindOpen(true)}
                  className="absolute -left-9 top-1 h-7 w-7 rounded-lg opacity-0 transition-opacity group-hover/user-message:opacity-100 focus-visible:opacity-100"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Rewind</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : null}
        {rewindOpen ? (
          <RewindEditor
            message={message}
            attachments={contextAttachments}
            onCancel={() => setRewindOpen(false)}
            onSubmit={(content) => {
              setRewindOpen(false);
              void rewindUserMessage(message.id, content);
            }}
          />
        ) : contextAttachments.length > 0 ? (
          <ContextAttachmentMessageCard content={message.content} attachments={contextAttachments} />
        ) : annotationBundle ? (
          <AnnotationMessageCard bundle={annotationBundle} />
        ) : (
          <div
            className={`rounded-2xl border border-glass-border/35 bg-foreground/[0.055] px-3.5 py-3 text-foreground shadow-soft ring-1 ring-white/[0.035] ${USER_MESSAGE_CARD_SCROLL_CLASS}`}
            data-testid="user-message-card"
          >
            <MarkdownContent content={message.content} />
          </div>
        )}
      </div>
    </article>
  );
}

function RewindEditor({
  message,
  attachments,
  onCancel,
  onSubmit,
}: {
  message: ChatMessageUi;
  attachments: ContextAttachment[];
  onCancel: () => void;
  onSubmit: (content: string) => void;
}) {
  const [draft, setDraft] = useState(message.content);
  const canSubmit = draft.trim().length > 0 || attachments.length > 0;

  return (
    <div className="w-full overflow-hidden rounded-2xl border border-primary/25 bg-card/95 shadow-floating ring-1 ring-primary/10 backdrop-blur-xl">
      <div className="border-b border-glass-border/25 px-3 py-2 font-mono text-[11px] text-muted-foreground">
        Rewind from this message
      </div>
      {attachments.length > 0 ? (
        <div className="flex max-h-28 flex-col gap-1.5 overflow-y-auto border-b border-glass-border/20 px-3 py-2">
          {attachments.map((attachment, index) => (
            <AttachmentChip key={`${attachment.type}:${attachment.id ?? index}`} attachment={attachment} />
          ))}
        </div>
      ) : null}
      <textarea
        value={draft}
        rows={Math.min(8, Math.max(3, draft.split(/\r?\n/).length))}
        onChange={(event) => setDraft(event.currentTarget.value)}
        className="min-h-28 w-full resize-y bg-transparent px-3 py-3 text-[14px] leading-6 text-foreground outline-none placeholder:text-muted-foreground"
        aria-label="Rewind message content"
      />
      <div className="flex items-center justify-end gap-2 border-t border-glass-border/25 px-3 py-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} className="h-8 rounded-lg">
          <X className="mr-1.5 h-3.5 w-3.5" />
          Cancel
        </Button>
        <Button type="button" size="sm" disabled={!canSubmit} onClick={() => onSubmit(draft)} className="h-8 rounded-lg">
          <Send className="mr-1.5 h-3.5 w-3.5" />
          Resend
        </Button>
      </div>
    </div>
  );
}

function ContextAttachmentMessageCard({
  content,
  attachments,
}: {
  content: string;
  attachments: ContextAttachment[];
}) {
  return (
    <div
      className={`max-w-full rounded-2xl border border-glass-border/35 bg-foreground/[0.055] p-3 shadow-soft ring-1 ring-white/[0.035] ${USER_MESSAGE_CARD_SCROLL_CLASS}`}
      data-testid="user-message-card"
    >
      <div className="mb-2 flex flex-col gap-1.5">
        {attachments.map((attachment, index) => (
          <AttachmentChip key={`${attachment.type}:${attachment.id ?? index}`} attachment={attachment} />
        ))}
      </div>
      {content.trim() ? (
        <MarkdownContent content={content} />
      ) : null}
    </div>
  );
}

function AttachmentChip({ attachment }: { attachment: ContextAttachment }) {
  const label = attachment.label || attachmentLabel(attachment);
  const path = attachment.display_path || attachment.file_path || attachment.directory_path || attachment.path || attachment.uri || "";
  const detail = attachmentDetail(attachment);

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <span className="rounded-md bg-foreground/[0.08] px-2 py-1 font-mono text-[11px] font-semibold text-foreground">
        {label}
      </span>
      {path ? (
        <span className="min-w-0 truncate rounded-md border border-glass-border/35 bg-background/55 px-2 py-1 font-mono text-[11px] text-foreground">
          {path}
        </span>
      ) : null}
      {detail ? (
        <span className="rounded-md border border-glass-border/35 bg-background/55 px-2 py-1 font-mono text-[11px] text-muted-foreground">
          {detail}
        </span>
      ) : null}
      {attachment.text ? (
        <span className="min-w-0 truncate text-[11px] text-muted-foreground">
          {String(attachment.text)}
        </span>
      ) : null}
      {attachment.content_preview ? (
        <span className="min-w-0 truncate text-[11px] text-muted-foreground">
          {String(attachment.content_preview)}
        </span>
      ) : null}
    </div>
  );
}

function attachmentLabel(attachment: ContextAttachment) {
  if (attachment.type === "terminal_output") return "@terminal";
  if (attachment.type === "mcp_resource") return "@mcp";
  if (attachment.type === "directory") return "@Directory";
  if (attachment.type === "skill") return attachment.invocation_name ? `@skill:${String(attachment.invocation_name)}` : "@skill";
  if (attachment.type === "browser_tab") return "@Browser";
  if (attachment.type === "file") return "@File";
  if (attachment.type === "file_range") return "@FileRange";
  if (attachment.type === "command_context") return `/${String(attachment.command || "command")}`;
  return "@Annotation";
}

function attachmentDetail(attachment: ContextAttachment) {
  if (attachment.type === "viewer_annotation" || attachment.type === "file_range") {
    const start = Number(attachment.start_line || 0);
    const end = Number(attachment.end_line || start);
    if (start > 0) return `L${start === end ? start : `${start}-${end}`}`;
  }
  if (attachment.type === "terminal_output") {
    const count = Number(attachment.content_char_count || 0);
    return count > 0 ? `${count} chars` : attachment.shell || "";
  }
  if (attachment.type === "directory") {
    const count = Number(attachment.entry_count || 0);
    return count > 0 ? `${count} entries` : "";
  }
  if (attachment.type === "skill") return attachment.slash_name ? String(attachment.slash_name) : "";
  if (attachment.type === "mcp_resource") return attachment.server ? String(attachment.server) : "";
  if (attachment.type === "browser_tab") {
    if (attachment.active || attachment.is_active) return "active tab";
    return attachment.page_id ? String(attachment.page_id) : "";
  }
  return "";
}

function contextAttachmentsFromMetadata(value: unknown): ContextAttachment[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isContextAttachment);
}

function isContextAttachment(value: unknown): value is ContextAttachment {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const type = (value as { type?: unknown }).type;
  return typeof type === "string" && type.length > 0;
}

interface ParsedAnnotationMessage {
  id: string;
  file: string;
  path: string;
  lines: string;
  annotation: string;
}

interface ParsedAnnotationBundle {
  annotations: ParsedAnnotationMessage[];
  request: string;
}

function AnnotationMessageCard({ bundle }: { bundle: ParsedAnnotationBundle }) {
  return (
    <div
      className={`max-w-full rounded-2xl border border-glass-border/35 bg-foreground/[0.055] p-3 shadow-soft ring-1 ring-white/[0.035] ${USER_MESSAGE_CARD_SCROLL_CLASS}`}
      data-testid="user-message-card"
    >
      <div className="mb-2 flex flex-col gap-1.5">
        {bundle.annotations.map((annotation) => (
          <div key={annotation.id} className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="rounded-md bg-foreground/[0.08] px-2 py-1 font-mono text-[11px] font-semibold text-foreground">
              @Annotation#{annotation.id}
            </span>
            <span className="min-w-0 truncate rounded-md border border-glass-border/35 bg-background/55 px-2 py-1 font-mono text-[11px] text-foreground">
              {annotation.file}
            </span>
            <span className="rounded-md border border-glass-border/35 bg-background/55 px-2 py-1 font-mono text-[11px] text-muted-foreground">
              L{annotation.lines}
            </span>
            <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
              {annotation.path}
            </span>
          </div>
        ))}
      </div>
      {bundle.request ? <MarkdownContent content={bundle.request} /> : null}
    </div>
  );
}

function parseAnnotationMessage(content: string): ParsedAnnotationBundle | null {
  if (!content.startsWith("@Annotation#")) return null;

  const finalRequestMarker = "\n\nRequest:\n";
  const finalRequestIndex = content.includes("\n\nAnnotation:\n") ? content.lastIndexOf(finalRequestMarker) : -1;
  const annotationSection = finalRequestIndex >= 0 ? content.slice(0, finalRequestIndex) : content;
  const explicitRequest = finalRequestIndex >= 0 ? content.slice(finalRequestIndex + finalRequestMarker.length).trim() : "";
  const annotations: ParsedAnnotationMessage[] = [];
  const blockPattern =
    /@Annotation#(\d+)\nFile: ([^\n]+)\nPath: ([^\n]+)\nLines: ([^\n]+)\n\n(?:Annotation|Request):\n([\s\S]*?)\n\nSelected lines:\n```[^\n]*\n[\s\S]*?```/g;

  for (const match of annotationSection.matchAll(blockPattern)) {
    annotations.push({
      id: match[1],
      file: match[2],
      path: match[3],
      lines: match[4],
      annotation: match[5].trim(),
    });
  }

  if (annotations.length === 0) return null;

  return {
    annotations,
    request: explicitRequest || annotations.map((annotation) => annotation.annotation).filter(Boolean).join("\n\n"),
  };
}
