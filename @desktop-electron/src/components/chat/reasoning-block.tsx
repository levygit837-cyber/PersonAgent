import { useEffect, useMemo, useState } from "react";

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
  const reasoningLines = useMemo(() => {
    const displayReasoning =
      isStreaming && reasoning.length > STREAMING_REASONING_CHAR_LIMIT
        ? reasoning.slice(-STREAMING_REASONING_CHAR_LIMIT)
        : reasoning;
    const lines = displayReasoning
      .split("\n")
      .filter((line) => line.trim());
    return isStreaming && lines.length > STREAMING_REASONING_LINE_LIMIT
      ? lines.slice(-STREAMING_REASONING_LINE_LIMIT)
      : lines;
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
        className="flex w-fit items-center gap-2 rounded-md px-1.5 py-[2px] -ml-1.5 font-mono text-[11px] text-muted-foreground transition-colors hover:bg-white/[0.04] hover:text-foreground disabled:pointer-events-none"
        disabled={!hasReasoning}
      >
        {isStreaming ? <span className="personagent-spinner h-[11px] w-[11px]" aria-hidden="true" /> : null}
        <span>{isStreaming ? "Reasoning" : expanded ? "Reasoning Hide" : "Reasoning >"}</span>
      </button>
      {expanded ? (
        <div className="ml-[5px] mt-2 border-l border-white/[0.08] py-1 pl-[13px] font-mono text-[12px] leading-6 text-muted-foreground">
          {reasoningLines.map((line, index) => (
            <div key={`${line}-${index}`}>{line}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
