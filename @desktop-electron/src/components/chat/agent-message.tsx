import ReactMarkdown from "react-markdown";
import { memo, type ReactElement } from "react";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import type { ChatMessageUi, GeneratedImage, TeamTraceEventUi, ToolBlockUi } from "../../types/chat";
import { ReasoningBlock } from "./reasoning-block";
import { CompactToolGroupBlock, ToolBlock, isSearchShellCommand } from "./tool-block";
import { CodeBlock } from "./code-block";

export const AgentMessage = memo(function AgentMessage({ message }: { message: ChatMessageUi }) {
  const hasVisibleAnswerContent = hasVisibleContent(message);
  const body = message.parts.length > 0 ? orderedParts(message) : legacyBody(message);
  const hasLegacyThinking = message.parts.length === 0 && (message.reasoning || message.isReasoningStreaming);
  const orphanReasoningBlocks =
    message.parts.length > 0
      ? message.reasoningBlocks.filter(
          (block) => !message.parts.some((part) => part.reasoningBlockId === block.id),
        )
      : [];
  const hasOrphanReasoningFallback =
    orphanReasoningBlocks.length === 0 &&
    message.parts.length > 0 &&
    message.reasoning.trim().length > 0 &&
    !message.parts.some((part) => part.kind === "reasoning");
  const showExecutionStatus = message.isStreaming && !hasRenderableProgress(message);

  return (
    <article className="mb-9 min-w-0 max-w-full">
      <div className="mb-3 font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-primary">PersonAgent</div>
      {showExecutionStatus ? <ChatExecutionStatus /> : null}
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
        />
      ))}
      {hasOrphanReasoningFallback ? (
        <ReasoningBlock
          reasoning={message.reasoning}
          isStreaming={message.isReasoningStreaming}
          autoCollapse={hasVisibleAnswerContent}
        />
      ) : null}
      {message.teamEvents.length > 0 ? <TeamTrace events={message.teamEvents} /> : null}
      {body.length > 0 ? (
        <div className="min-w-0 max-w-full space-y-3">{body}</div>
      ) : null}
    </article>
  );

  function orderedParts(current: ChatMessageUi) {
    const widgets: ReactElement[] = [];
    const reasoningById = new Map(current.reasoningBlocks.map((block) => [block.id, block]));
    const toolsById = new Map(current.toolBlocks.map((block) => [block.id, block]));
    let pendingTools: ToolBlockUi[] = [];

    const flushTools = () => {
      if (pendingTools.length === 0) return;
      widgets.push(...renderToolBlocks(pendingTools));
      pendingTools = [];
    };

    current.parts.forEach((part, index) => {
      if (part.kind === "reasoning") {
        flushTools();
        const block = part.reasoningBlockId ? reasoningById.get(part.reasoningBlockId) : undefined;
        if (block) {
          widgets.push(
            <ReasoningBlock
              key={block.id}
              reasoning={block.content}
              isStreaming={block.isStreaming}
              autoCollapse={hasVisibleAnswerContent}
            />,
          );
        }
        return;
      }
      if (part.kind === "tool") {
        const block = part.toolBlockId ? toolsById.get(part.toolBlockId) : undefined;
        if (block) pendingTools.push(block);
        return;
      }
      if (part.kind === "image") {
        flushTools();
        if (part.image) {
          widgets.push(<GeneratedImageContent key={`${current.id}-image-${index}`} image={part.image} />);
        }
        return;
      }
      flushTools();
      if (part.content?.trim()) {
        widgets.push(<MarkdownContent key={`${current.id}-content-${index}`} content={part.content} isStreaming={current.isStreaming} />);
      }
    });
    flushTools();
    return widgets;
  }

  function legacyBody(current: ChatMessageUi) {
    const widgets: ReactElement[] = [];
    if (current.toolBlocks.length > 0) widgets.push(...renderToolBlocks(current.toolBlocks));
    if (current.content) widgets.push(<MarkdownContent key={`${current.id}-content`} content={current.content} isStreaming={current.isStreaming} />);
    return widgets;
  }
});

const GeneratedImageContent = memo(function GeneratedImageContent({ image }: { image: GeneratedImage }) {
  const mimeType = image.mime_type || "image/png";
  const src = `data:${mimeType};base64,${image.data}`;
  return (
    <figure className="my-3 max-w-3xl">
      <img
        src={src}
        alt={image.alt || "Generated image"}
        className="max-h-[70vh] w-auto max-w-full rounded-2xl border border-glass-border/35 bg-secondary object-contain shadow-soft"
        loading="lazy"
      />
    </figure>
  );
});

function hasRenderableProgress(message: ChatMessageUi) {
  if (message.content.trim().length > 0) return true;
  if (message.reasoning.trim().length > 0 || message.isReasoningStreaming) return true;
  if (message.reasoningBlocks.some((block) => block.content.trim().length > 0 || block.isStreaming)) return true;
  if (message.toolBlocks.length > 0) return true;
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

const TeamTrace = memo(function TeamTrace({ events }: { events: TeamTraceEventUi[] }) {
  return (
    <div className="mb-4 space-y-2 border-l border-glass-border/25 pl-3">
      {events.map((event) => (
        <TeamTraceEvent key={event.id} event={event} />
      ))}
    </div>
  );
});

const TeamTraceEvent = memo(function TeamTraceEvent({ event }: { event: TeamTraceEventUi }) {
  const content = event.content?.trimEnd();
  const isRunning = event.status === "running";
  return (
    <div className="text-sm">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span className={teamStatusClass(event.status)}>{teamStatusLabel(event)}</span>
        <span className="font-medium text-foreground">{event.title}</span>
        {event.detail ? <span className="font-mono text-[11px] text-muted-foreground">{event.detail}</span> : null}
      </div>
      {content ? (
        <div className="mt-1 max-w-none text-[13px] leading-6 text-muted-foreground">
          {isRunning ? (
            <div className="whitespace-pre-wrap break-words">{content}</div>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks, remarkBreakTags]}>{content}</ReactMarkdown>
          )}
        </div>
      ) : null}
    </div>
  );
});

function teamStatusLabel(event: TeamTraceEventUi) {
  if (event.kind === "round") return "Round";
  if (event.kind === "vote") return event.status === "approved" ? "Approve" : event.status === "rejected" ? "Block" : "Vote";
  if (event.kind === "consensus") return "Consensus";
  if (event.kind === "blackboard") return "Board";
  if (event.kind === "tool") return "Tool";
  if (event.kind === "debate") return "Debate";
  if (event.kind === "coordinator") {
    return event.title.toLowerCase().includes("planning") || event.status !== "completed" ? "Coord" : "Final";
  }
  if (event.kind === "failed") return "Failed";
  if (event.kind === "cancelled") return "Stopped";
  if (event.kind === "turn") return event.status === "completed" ? "Done" : "Turn";
  return "Team";
}

function teamStatusClass(status?: TeamTraceEventUi["status"]) {
  const base = "font-mono text-[10px] uppercase tracking-[0.12em]";
  if (status === "approved" || status === "completed") return `${base} text-success`;
  if (status === "rejected" || status === "failed") return `${base} text-destructive`;
  if (status === "cancelled") return `${base} text-muted-foreground`;
  return `${base} text-warning`;
}

function renderToolBlocks(blocks: ToolBlockUi[]) {
  const widgets: ReactElement[] = [];
  let compactBlocks: ToolBlockUi[] = [];
  let compactKind: string | undefined;

  const flush = () => {
    if (compactBlocks.length === 0 || !compactKind) return;
    const group = compactBlocks;
    if (group.length === 1 && compactKind !== "shell") {
      widgets.push(<ToolBlock key={group[0].id} block={group[0]} />);
    } else {
      widgets.push(<CompactToolGroupBlock key={`${compactKind}-${group.map((item) => item.id).join("-")}`} kind={compactKind} blocks={group} />);
    }
    compactBlocks = [];
    compactKind = undefined;
  };

  for (const block of blocks) {
    const kind = compactToolKindFor(block);
    if (kind) {
      if (compactKind && compactKind !== kind) flush();
      compactKind = kind;
      compactBlocks.push(block);
    } else {
      flush();
      widgets.push(<ToolBlock key={block.id} block={block} />);
    }
  }
  flush();
  return widgets;
}

export function compactToolKindFor(block: ToolBlockUi) {
  if (block.name === "Read" || block.name === "read_file") return "read";
  if (block.name === "Glob" || block.name === "Grep" || block.name === "search_files") return "search";
  if (block.name === "shell" && isSearchShellCommand(block)) return "search";
  if (block.name === "shell") return "shell";
  if (block.name === "WebFetch") return "web";
  if (block.name === "LSP") return "lsp";
  if (block.name === "TodoWrite") return "todo";
  if (block.name === "Task" || block.name.startsWith("Task")) return "task";
  return undefined;
}

function ChatExecutionStatus() {
  return (
    <div className="mb-3 mt-1 flex items-center gap-2 font-mono text-[11px]" role="status" aria-live="polite">
      <span className="personagent-spinner h-3 w-3 text-primary/80" aria-hidden="true" />
      <span className="personagent-shimmer font-medium tracking-wide">Thinking...</span>
    </div>
  );
}

export const MarkdownContent = memo(function MarkdownContent({
  content,
  isStreaming = false,
}: {
  content: string;
  isStreaming?: boolean;
}) {
  return (
    <div className="markdown-content prose prose-invert min-w-0 max-w-full overflow-hidden text-[15px] leading-7 prose-p:my-2 prose-code:rounded prose-code:bg-secondary prose-code:px-1 prose-code:py-0.5 prose-code:text-foreground prose-a:text-primary">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks, remarkBreakTags]}
        components={{
          p: ({ children }) => <p className="my-2 min-w-0 break-words">{children}</p>,
          a: ({ children, ...props }) => (
            <a {...props} className="break-words text-primary">
              {children}
            </a>
          ),
          ul: ({ children }) => <ul className="my-3 list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-3 list-decimal space-y-1 pl-5">{children}</ol>,
          li: ({ children }) => <li className="min-w-0 break-words pl-1">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-3 border-l border-glass-border/50 pl-4 text-muted-foreground">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="not-prose my-4 w-full max-w-full overflow-x-auto rounded-xl border border-glass-border/35 bg-card/45 shadow-soft">
              <table className="w-max min-w-full border-collapse text-left text-[13px] leading-6">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-secondary/55 text-foreground">{children}</thead>,
          tbody: ({ children }) => <tbody className="divide-y divide-glass-border/35">{children}</tbody>,
          tr: ({ children }) => <tr className="align-top">{children}</tr>,
          th: ({ children }) => (
            <th className="min-w-[9rem] max-w-[18rem] border-b border-glass-border/45 px-3 py-2 align-top font-semibold text-foreground">
              <div className="whitespace-normal break-words">{children}</div>
            </th>
          ),
          td: ({ children }) => (
            <td className="min-w-[9rem] max-w-[18rem] px-3 py-2 align-top text-foreground/90">
              <div className="whitespace-normal break-words">{children}</div>
            </td>
          ),
          pre: ({ node, children, ...props }: any) => {
            // Check if this is a code block (has code child with className)
            const codeElement = node?.children?.[0];
            const isCodeBlock = codeElement?.tagName === "code" && codeElement?.properties?.className;
            
            if (isCodeBlock) {
              const rawClassName = codeElement.properties.className;
              const className = Array.isArray(rawClassName) ? rawClassName.join(" ") : String(rawClassName ?? "");
              return (
                <CodeBlock 
                  className={className} 
                  node={node} 
                  isStreaming={isStreaming}
                  {...props}
                >
                  {children}
                </CodeBlock>
              );
            }
            
            // Fallback for pre elements that aren't code blocks
            return (
              <pre
                {...props}
                className="not-prose my-3 max-w-full overflow-x-auto rounded-xl border border-glass-border/35 bg-card/80 p-3 text-[12px] leading-5"
              >
                {children}
              </pre>
            );
          },
          code: ({ node, className, children, ...props }: any) => {
            // Inline code (not inside pre)
            const match = /language-(\w+)/.exec(className || "");
            const isInline = !match;
            
            if (isInline) {
              return (
                <code className={`${className ?? ""} break-words`} {...props}>
                  {children}
                </code>
              );
            }
            
            // Code block content - let the pre component handle it
            return <>{children}</>;
          },
        }}
      >
        {content.trimEnd()}
      </ReactMarkdown>
    </div>
  );
});

type MarkdownNode = {
  type?: string;
  value?: string;
  children?: MarkdownNode[];
};

function remarkBreakTags() {
  return (tree: MarkdownNode) => transformBreakTags(tree);
}

function transformBreakTags(node: MarkdownNode) {
  if (!node.children) return;
  const nextChildren: MarkdownNode[] = [];

  for (const child of node.children) {
    if (child.type === "html" && isBreakTag(child.value)) {
      nextChildren.push({ type: "break" });
      continue;
    }

    if (child.type === "text" && child.value && hasBreakTag(child.value)) {
      nextChildren.push(...splitBreakTagText(child.value));
      continue;
    }

    transformBreakTags(child);
    nextChildren.push(child);
  }

  node.children = nextChildren;
}

function splitBreakTagText(value: string): MarkdownNode[] {
  const nodes: MarkdownNode[] = [];
  let cursor = 0;
  for (const match of value.matchAll(/<br\s*\/?>/gi)) {
    const index = match.index ?? 0;
    if (index > cursor) nodes.push({ type: "text", value: value.slice(cursor, index) });
    nodes.push({ type: "break" });
    cursor = index + match[0].length;
  }
  if (cursor < value.length) nodes.push({ type: "text", value: value.slice(cursor) });
  return nodes;
}

function isBreakTag(value?: string) {
  return Boolean(value && /^<br\s*\/?>$/i.test(value.trim()));
}

function hasBreakTag(value: string) {
  return /<br\s*\/?>/i.test(value);
}
