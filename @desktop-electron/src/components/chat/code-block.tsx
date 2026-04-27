import { useState, useMemo } from "react";
import { Copy, Check, ChevronDown, ChevronRight, FileCode } from "lucide-react";
import hljs from "highlight.js";
import { detectLanguage } from "../../lib/highlight-theme";

interface CodeBlockProps {
  children?: React.ReactNode;
  className?: string;
  node?: any;
  filePath?: string;
  isStreaming?: boolean;
}

const COLLAPSE_THRESHOLD = 25;
const MAX_HEIGHT = "400px";

export function CodeBlock({ children, className, node, filePath, isStreaming = false }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(true);

  // Extract code content from children
  const codeContent = extractCodeContent(children);
  const language = detectLanguage(className) || "text";

  // Highlight the full code, then split into per-line HTML
  const highlightedLines = useMemo(() => {
    let html: string;
    try {
      if (isStreaming) {
        html = escapeHtml(codeContent);
      } else {
        const lang = hljs.getLanguage(language) ? language : "plaintext";
        html = hljs.highlight(codeContent, { language: lang }).value;
      }
    } catch {
      html = escapeHtml(codeContent);
    }
    return splitHighlightedLines(html);
  }, [codeContent, language, isStreaming]);

  const lineCount = highlightedLines.length;
  const shouldCollapse = lineCount > COLLAPSE_THRESHOLD;
  const effectiveCollapsed = shouldCollapse && collapsed;
  const visibleLines = effectiveCollapsed ? highlightedLines.slice(0, COLLAPSE_THRESHOLD) : highlightedLines;
  const gutterWidth = String(lineCount).length;
  const displayLabel = filePath || language;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(codeContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy code:", error);
    }
  };

  return (
    <div className="code-block-wrapper not-prose my-3 rounded-lg border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="code-block-header flex items-center justify-between px-3 py-2 border-b border-border bg-card/50">
        <div className="flex items-center gap-2">
          <FileCode className="h-4 w-4 text-muted-foreground" />
          <span className="text-xs font-mono text-muted-foreground">{displayLabel}</span>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          title={copied ? "Copied!" : "Copy code"}
        >
          {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>

      {/* Code body — table layout ensures line numbers and code share the same row */}
      <div
        className="code-block-body relative overflow-x-auto"
        style={effectiveCollapsed ? { maxHeight: MAX_HEIGHT } : undefined}
      >
        <table className="w-full border-collapse" style={{ tableLayout: "auto" }}>
          <tbody>
            {visibleLines.map((lineHtml, i) => (
              <tr key={i} className="code-block-row hover:bg-white/[0.02]">
                {/* Line number */}
                <td
                  className="code-block-gutter select-none text-right align-top px-3 font-mono text-xs text-muted-foreground/40"
                  style={{ minWidth: `${gutterWidth + 2}ch`, userSelect: "none", width: "1%" }}
                >
                  {i + 1}
                </td>
                {/* Code line */}
                <td className="code-block-line pl-4 pr-3 font-mono text-xs whitespace-pre align-top">
                  <span dangerouslySetInnerHTML={{ __html: lineHtml || "&nbsp;" }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Collapse overlay */}
        {effectiveCollapsed && (
          <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-card to-transparent pointer-events-none" />
        )}
      </div>

      {/* Collapse button */}
      {shouldCollapse && (
        <div className="flex items-center justify-center border-t border-border bg-card/50 py-1.5">
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            className="flex items-center gap-1.5 px-3 py-1 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors"
          >
            {effectiveCollapsed ? (
              <>
                <ChevronDown className="h-3.5 w-3.5" />
                <span>Show all {lineCount} lines</span>
              </>
            ) : (
              <>
                <ChevronRight className="h-3.5 w-3.5" />
                <span>Collapse</span>
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Splits highlight.js HTML output into per-line HTML strings,
 * correctly handling spans that cross line boundaries.
 */
function splitHighlightedLines(html: string): string[] {
  const raw = html.split("\n");
  const result: string[] = [];
  const openSpans: string[] = [];

  for (const line of raw) {
    // Re-open any spans that were still open from the previous line
    let prefix = openSpans.join("");
    let enriched = prefix + line;

    // Track which spans open/close on this line
    const opens = (line.match(/<span[^>]*>/g) || []);
    const closes = (line.match(/<\/span>/g) || []);

    // Update the open-spans stack
    for (const tag of opens) openSpans.push(tag);
    for (let j = 0; j < closes.length; j++) openSpans.pop();

    // Close still-open spans at end of line so each line is valid HTML
    let suffix = "</span>".repeat(openSpans.length);
    result.push(enriched + suffix);
  }

  return result;
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/**
 * Extracts raw code content from react-markdown children
 */
function extractCodeContent(children?: React.ReactNode): string {
  if (!children) return "";
  if (typeof children === "string") return children;
  if (Array.isArray(children)) {
    return children.map(extractCodeContent).join("");
  }
  if (children && typeof children === "object" && "props" in children) {
    return extractCodeContent((children as any).props.children);
  }
  return "";
}
