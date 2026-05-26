import { Fragment, useMemo } from "react";
import { cn } from "../../../lib/utils";
import { highlightContent, splitHighlightedLines } from "./highlight-utils";
import type { AnnotationDraft } from "./types";
import { lineInRange, normalizeLineRange, splitLines } from "./utils";
import { AnnotationInputBar } from "./annotation-bar";

interface FileAnnotationLite {
  id: number;
  startLine: number;
  endLine: number;
  text: string;
}

export function FileCodeContent({
  content,
  language,
  annotationMode,
  annotations,
  drafts,
  onLinePick,
  onDraftTextChange,
  onDraftCancel,
  onDraftSubmit,
}: {
  content: string;
  language: string;
  annotationMode: boolean;
  annotations: Array<FileAnnotationLite>;
  drafts: AnnotationDraft[];
  onLinePick: (lineNumber: number) => void;
  onDraftTextChange: (draftId: string, value: string) => void;
  onDraftCancel: (draftId: string) => void;
  onDraftSubmit: (draftId: string) => void;
}) {
  const lines = useMemo(() => splitLines(content), [content]);
  const highlightedLines = useMemo(() => {
    const html = highlightContent(content, language);
    return splitHighlightedLines(html);
  }, [content, language]);
  const gutterWidth = String(Math.max(lines.length, 1)).length;

  return (
    <div className={cn("file-viewer-code h-full overflow-auto bg-card/95", annotationMode && "cursor-zoom-in")}>
      <table className="w-max min-w-full border-collapse font-mono text-xs leading-6">
        <tbody>
          {highlightedLines.map((lineHtml, index) => {
            const lineNumber = index + 1;
            const lineAnnotations = annotations.filter((annotation) =>
              lineInRange(lineNumber, annotation.startLine, annotation.endLine)
            );
            const startAnnotations = lineAnnotations.filter(
              (annotation) => annotation.startLine === lineNumber
            );
            const completedDraftsEndingHere = drafts.filter((draft) => {
              if (draft.focusLine === undefined) return false;
              const range = normalizeLineRange(draft.anchorLine, draft.focusLine);
              return range.end === lineNumber;
            });
            const selected = drafts.some((draft) => {
              const range = normalizeLineRange(
                draft.anchorLine,
                draft.focusLine ?? draft.anchorLine
              );
              return lineInRange(lineNumber, range.start, range.end);
            });
            const annotated = lineAnnotations.length > 0;
            return (
              <Fragment key={index}>
                <tr
                  className={cn(
                    "hover:bg-glass/30",
                    annotationMode && !annotated && "cursor-zoom-in",
                    annotated && "bg-foreground/[0.035]",
                    selected && "bg-foreground/[0.07]"
                  )}
                >
                  <td
                    className="select-none border-r border-glass-border/20 bg-background/50 px-2 text-right align-top text-muted-foreground/40"
                    style={{ minWidth: `${gutterWidth + 3}ch`, width: "1%" }}
                  >
                    <button
                      type="button"
                      aria-label={`Select line ${lineNumber}`}
                      disabled={!annotationMode || annotated}
                      onClick={() => onLinePick(lineNumber)}
                      className={cn(
                        "w-full rounded-sm px-1 text-right disabled:cursor-default",
                        annotationMode &&
                          !annotated &&
                          "cursor-zoom-in hover:bg-foreground/[0.08] hover:text-foreground",
                        annotated && "cursor-not-allowed text-muted-foreground/55",
                        selected && "text-foreground"
                      )}
                    >
                      {lineNumber}
                    </button>
                  </td>
                  <td
                    className={cn(
                      "whitespace-pre px-2 align-top text-foreground",
                      annotationMode && !annotated && "cursor-zoom-in"
                    )}
                    onClick={() => annotationMode && !annotated && onLinePick(lineNumber)}
                  >
                    {startAnnotations.map((annotation) => (
                      <span
                        key={annotation.id}
                        className="mr-2 rounded-md border border-glass-border/35 bg-foreground/[0.055] px-1.5 py-0.5 font-sans text-[10px] leading-4 text-muted-foreground"
                      >
                        @Annotation#{annotation.id}
                      </span>
                    ))}
                    <span dangerouslySetInnerHTML={{ __html: lineHtml || "&nbsp;" }} />
                  </td>
                </tr>
                {completedDraftsEndingHere.map((draft) => {
                  const range = normalizeLineRange(
                    draft.anchorLine,
                    draft.focusLine ?? draft.anchorLine
                  );
                  return (
                    <tr key={draft.id} className="bg-foreground/[0.045]">
                      <td
                        className="border-r border-glass-border/20 bg-background/50 align-top"
                        style={{ minWidth: `${gutterWidth + 3}ch`, width: "1%" }}
                      />
                      <td className="px-2 pb-3 pt-1 align-top">
                        <AnnotationInputBar
                          draft={draft}
                          range={range}
                          value={draft.text}
                          onChange={(value: string) => onDraftTextChange(draft.id, value)}
                          onCancel={() => onDraftCancel(draft.id)}
                          onSubmit={() => onDraftSubmit(draft.id)}
                        />
                      </td>
                    </tr>
                  );
                })}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
