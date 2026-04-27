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
const MAX_HIGHLIGHT_CHARS = 20_000;
const MAX_HIGHLIGHT_LINES = 400;

export function CodeBlock({ children, className, node, filePath, isStreaming = false }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(true);

  // Extract code content from children
  const codeContent = extractCodeContent(children);
  const language = detectLanguage(className) || "text";
  const rawLines = useMemo(() => codeContent.split("\n"), [codeContent]);
  const lineCount = rawLines.length;
  const shouldCollapse = lineCount > COLLAPSE_THRESHOLD;
  const effectiveCollapsed = shouldCollapse && collapsed;
  const sourceForRender = effectiveCollapsed
    ? rawLines.slice(0, COLLAPSE_THRESHOLD).join("\n")
    : codeContent;

  const highlightedLines = useMemo(() => {
    let html: string;
    try {
      if (isStreaming || shouldSkipHighlight(sourceForRender, language)) {
        html = escapeHtml(sourceForRender);
      } else {
        const lang = hljs.getLanguage(language) ? language : "plaintext";
        html = hljs.highlight(sourceForRender, { language: lang }).value;
      }
    } catch {
      html = escapeHtml(sourceForRender);
    }
    return splitHighlightedLines(html);
  }, [sourceForRender, language, isStreaming]);

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
    <div className="code-block-wrapper not-prose my-3 w-full min-w-0 max-w-full overflow-hidden rounded-2xl border border-glass-border/35 bg-card/90 shadow-soft">
      {/* Header */}
      <div className="code-block-header flex items-center justify-between border-b border-glass-border/25 bg-glass/45 px-3 py-2">
        <div className="flex items-center gap-2">
          <FileCode className="h-4 w-4 text-muted-foreground" />
          <span className="text-xs font-mono text-muted-foreground">{displayLabel}</span>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-glass/80 hover:text-foreground"
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
        <table className="w-max min-w-full border-collapse" style={{ tableLayout: "auto" }}>
          <tbody>
            {highlightedLines.map((lineHtml, i) => (
              <tr key={i} className="code-block-row hover:bg-glass/35">
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
        <div className="flex items-center justify-center border-t border-glass-border/25 bg-glass/45 py-1.5">
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-glass/80 hover:text-foreground"
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

function shouldSkipHighlight(code: string, language: string): boolean {
  if (language === "text" || language === "plaintext") return true;
  if (code.length > MAX_HIGHLIGHT_CHARS) return true;
  if (code.split("\n").length > MAX_HIGHLIGHT_LINES) return true;
  return false;
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
