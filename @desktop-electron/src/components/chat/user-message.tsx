import type { ChatMessageUi, ContextAttachment } from "../../types/chat";

export function UserMessage({ message }: { message: ChatMessageUi }) {
  const contextAttachments = contextAttachmentsFromMetadata(message.metadata?.context_attachments);
  const annotationBundle = parseAnnotationMessage(message.content);

  return (
    <article className="mb-9">
      <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">User</div>
      {contextAttachments.length > 0 ? (
        <ContextAttachmentMessageCard content={message.content} attachments={contextAttachments} />
      ) : annotationBundle ? (
        <AnnotationMessageCard bundle={annotationBundle} />
      ) : (
        <div className="whitespace-pre-wrap pl-4 text-[15px] leading-7 text-foreground">{message.content}</div>
      )}
    </article>
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
    <div className="ml-4 max-w-full overflow-hidden rounded-2xl border border-glass-border/35 bg-foreground/[0.045] p-3 shadow-soft ring-1 ring-white/[0.035]">
      <div className="mb-2 flex flex-col gap-1.5">
        {attachments.map((attachment, index) => (
          <AttachmentChip key={`${attachment.type}:${attachment.id ?? index}`} attachment={attachment} />
        ))}
      </div>
      {content.trim() ? (
        <div className="whitespace-pre-wrap text-[15px] leading-7 text-foreground">{content}</div>
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
    <div className="ml-4 max-w-full overflow-hidden rounded-2xl border border-glass-border/35 bg-foreground/[0.045] p-3 shadow-soft ring-1 ring-white/[0.035]">
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
      {bundle.request ? <div className="whitespace-pre-wrap text-[15px] leading-7 text-foreground">{bundle.request}</div> : null}
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
