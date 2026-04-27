import type { ChatMessageUi } from "../../types/chat";

export function UserMessage({ message }: { message: ChatMessageUi }) {
  const annotationBundle = parseAnnotationMessage(message.content);

  return (
    <article className="mb-9">
      <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">User</div>
      {annotationBundle ? (
        <AnnotationMessageCard bundle={annotationBundle} />
      ) : (
        <div className="whitespace-pre-wrap pl-4 text-[15px] leading-7 text-foreground">{message.content}</div>
      )}
    </article>
  );
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
