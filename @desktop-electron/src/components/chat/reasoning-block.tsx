import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

const STREAMING_REASONING_CHAR_LIMIT = 12000;
const STREAMING_REASONING_LINE_LIMIT = 180;

export function ReasoningBlock({
  reasoning,
  isStreaming,
  autoCollapse = true,
}: {
  reasoning: string;
  isStreaming: boolean;
  autoCollapse?: boolean;
}) {
  const [expanded, setExpanded] = useState(isStreaming || !autoCollapse);
  const hasReasoning = reasoning.trim().length > 0;
  const displayReasoning = useMemo(() => {
    const displayReasoning =
      isStreaming && reasoning.length > STREAMING_REASONING_CHAR_LIMIT
        ? reasoning.slice(-STREAMING_REASONING_CHAR_LIMIT)
        : reasoning;
    const lines = displayReasoning
      .split("\n")
      .filter((line) => line.trimEnd());
    const visibleLines = isStreaming && lines.length > STREAMING_REASONING_LINE_LIMIT
      ? lines.slice(-STREAMING_REASONING_LINE_LIMIT)
      : lines;
    return visibleLines.join("\n").trimEnd();
  }, [isStreaming, reasoning]);

  useEffect(() => {
    if (!isStreaming) return;
    setExpanded(true);
  }, [isStreaming]);

  useEffect(() => {
    if (!autoCollapse) {
      setExpanded(true);
      return;
    }
    if (!isStreaming && hasReasoning) {
      const timer = window.setTimeout(() => setExpanded(false), 500);
      return () => window.clearTimeout(timer);
    }
  }, [autoCollapse, hasReasoning, isStreaming]);

  if (!hasReasoning && !isStreaming) return null;

  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => hasReasoning && setExpanded((value) => !value)}
        className="flex w-fit items-center gap-2 rounded-lg px-1.5 py-[2px] -ml-1.5 font-mono text-[11px] text-muted-foreground transition-colors hover:bg-glass/70 hover:text-foreground disabled:pointer-events-none"
        disabled={!hasReasoning}
      >
        {isStreaming ? <span className="personagent-spinner h-[11px] w-[11px]" aria-hidden="true" /> : null}
        <span>{isStreaming ? "Reasoning" : expanded ? "Reasoning Hide" : "Reasoning >"}</span>
      </button>
      {expanded ? (
        <div className="reasoning-markdown ml-[5px] mt-2 border-l border-glass-border/25 py-1 pl-[13px] font-mono text-[12px] leading-6 text-muted-foreground">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkBreaks]}
            components={{
              p: ({ children }) => <p className="my-0 whitespace-pre-wrap break-words">{children}</p>,
              strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
              em: ({ children }) => <em className="text-foreground/90">{children}</em>,
              code: ({ children }) => (
                <code className="rounded bg-secondary/70 px-1 py-0.5 text-[11px] text-foreground">
                  {children}
                </code>
              ),
              pre: ({ children }) => (
                <pre className="my-2 overflow-x-auto rounded-md border border-glass-border/25 bg-secondary/60 p-2 text-[11px] leading-5 text-foreground">
                  {children}
                </pre>
              ),
              ul: ({ children }) => <ul className="my-1 list-disc space-y-0.5 pl-4">{children}</ul>,
              ol: ({ children }) => <ol className="my-1 list-decimal space-y-0.5 pl-4">{children}</ol>,
              li: ({ children }) => <li className="pl-1">{children}</li>,
            }}
          >
            {displayReasoning}
          </ReactMarkdown>
        </div>
      ) : null}
    </div>
  );
}
