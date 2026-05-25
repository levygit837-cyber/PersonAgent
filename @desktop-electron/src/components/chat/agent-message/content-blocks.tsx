import ReactMarkdown from "react-markdown";
import { memo, type ReactElement } from "react";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import type { ChatMessageUi, GeneratedImage, ToolBlockUi } from "../../../types/chat";
import { useChatStore } from "../../../stores/chat-store";
import { ReasoningBlock } from "../reasoning-block";
import { CompactToolGroupBlock, ToolBlock, isBrowserToolName, isSearchShellCommand, isTodoTool } from "../tool-block";
import { CodeBlock } from "../code-block";

export function AgentMessageContent({
  message,
  hasVisibleAnswerContent,
}: {
  message: ChatMessageUi;
  hasVisibleAnswerContent: boolean;
}) {
  const setReasoningBlockExpanded = useChatStore((state) => state.setReasoningBlockExpanded);
  const body = message.parts.length > 0 ? orderedParts(message) : legacyBody(message);
  if (body.length === 0) return null;
  return <div className="min-w-0 max-w-full space-y-1.5">{body}</div>;

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
              userExpanded={block.userExpanded}
              onToggleExpanded={() => setReasoningBlockExpanded(current.id, block.id, !block.userExpanded)}
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
}

const GeneratedImageContent = memo(function GeneratedImageContent({ image }: { image: GeneratedImage }) {
  const mimeType = image.mime_type || "image/png";
  const src = image.url || (image.data ? `data:${mimeType};base64,${image.data}` : "");
  if (!src) return null;
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
    if (isTodoTool(block)) {
      flush();
      continue;
    }
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
  if (block.name === "Write" || block.name === "Edit") return "write";
  if (block.name === "Glob" || block.name === "Grep" || block.name === "search_files") return "search";
  if (block.name === "shell" && isSearchShellCommand(block)) return "search";
  if (block.name === "shell") return "shell";
  if (block.name === "WebFetch") return "web";
  if (block.name === "BrowserOpen") return "browser_open";
  if (block.name === "BrowserExtractContent") return "browser_extract";
  if (block.name === "BrowserSearch") return "browser_search";
  if (block.name === "BrowserListTabs") return "browser_tabs";
  if (block.name === "BrowserReadContentChunk") return "browser_chunks";
  if (block.name === "BrowserGetHtml") return "browser_html";
  if (block.name === "BrowserGetElementMap") return "browser_elements";
  if (block.name === "BrowserClick") return "browser_click";
  if (block.name === "BrowserType") return "browser_type";
  if (block.name === "BrowserScreenshot") return "browser_screenshot";
  if (block.name === "BrowserCloseTab") return "browser_close_tab";
  if (block.name === "BrowserReadConsole") return "browser_console";
  if (block.name === "BrowserScript") return "browser_script";
  if (block.name === "BrowserScroll") return "browser_scroll";
  if (block.name === "BrowserReload") return "browser_reload";
  if (block.name === "BrowserHistory") return "browser_history";
  if (block.name === "BrowserSwitchTab") return "browser_switch_tab";
  if (block.name === "BrowserWait") return "browser_wait";
  if (block.name === "BrowserAct") return "browser_act";
  if (block.name === "LSP") return "lsp";
  if (isTodoTool(block)) return "todo";
  if (block.name === "Task" || block.name.startsWith("Task")) return "task";
  if (isBrowserToolName(block.name)) return `tool:${block.name}`;
  if (block.name.trim()) return `tool:${block.name.trim().toLowerCase()}`;
  return undefined;
}

export function ChatExecutionStatus() {
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
    <div className="markdown-content prose prose-invert min-w-0 max-w-full overflow-hidden text-[14px] leading-6 prose-p:my-1.5 prose-code:rounded prose-code:bg-secondary prose-code:px-1 prose-code:py-0.5 prose-code:text-foreground prose-a:text-primary">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks, remarkBreakTags]}
        components={{
          h1: ({ children }) => <h1 className="my-3 text-[22px] font-semibold leading-8 text-foreground">{children}</h1>,
          h2: ({ children }) => <h2 className="my-2.5 text-[18px] font-semibold leading-7 text-foreground">{children}</h2>,
          h3: ({ children }) => <h3 className="my-2 text-[15px] font-semibold leading-6 text-foreground">{children}</h3>,
          p: ({ children }) => <p className="my-1.5 min-w-0 break-words">{children}</p>,
          a: ({ children, ...props }) => (
            <a {...props} className="break-words text-primary">
              {children}
            </a>
          ),
          ul: ({ children }) => <ul className="my-2 list-disc space-y-0.5 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal space-y-0.5 pl-5">{children}</ol>,
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
            const match = /language-(\w+)/.exec(className || "");
            const isInline = !match;

            if (isInline) {
              return (
                <code className={`${className ?? ""} break-words`} {...props}>
                  {children}
                </code>
              );
            }

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
