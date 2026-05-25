import { X } from "lucide-react";
import type { PullRequestSummary } from "../../../api/client";
import { cn } from "../../../lib/utils";
import { Button } from "../../ui/button";

export type DiffLineKind = "context" | "add" | "delete";

export interface DiffLine {
  number: string;
  kind: DiffLineKind;
  content: string;
}

type PullRequestFile = PullRequestSummary["files"][number];

export function DiffCard({
  file,
  active,
  canClose,
  onFocus,
  onClose,
}: {
  file: PullRequestFile;
  active: boolean;
  canClose: boolean;
  onFocus: () => void;
  onClose: () => void;
}) {
  return (
    <article
      className={cn(
        "overflow-hidden rounded-2xl border bg-background/45 transition-[border-color,box-shadow] duration-150",
        active ? "border-primary/30 shadow-soft" : "border-glass-border/30",
      )}
      data-testid={`open-diff-card-${file.id}`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-glass-border/25 px-3 py-2">
        <button type="button" className="min-w-0 text-left" onClick={onFocus}>
          <div className="truncate text-xs font-semibold text-foreground">{file.path}</div>
          <div className="mt-0.5 text-[10px] text-muted-foreground">
            {file.changeType} / +{file.additions} -{file.deletions}
          </div>
        </button>
        <Button variant="ghost" size="iconSm" aria-label={`Close diff for ${file.path}`} disabled={!canClose} onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      {file.lines.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full table-fixed border-collapse font-mono text-[12px] leading-6">
            <tbody>
              {file.lines.map((line, index) => (
                <tr key={`${file.id}-${line.number}-${index}`} className="border-b border-glass-border/10 last:border-b-0">
                  <td className="w-14 select-none px-3 py-0.5 text-right text-muted-foreground/60">{line.number}</td>
                  <td className={cn("whitespace-pre-wrap break-words px-3 py-0.5 text-foreground/85", diffLineClass(line.kind))}>
                    {linePrefix(line.kind)} {line.content}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="m-3 rounded-xl border border-glass-border/25 bg-background/35 px-3 py-2 text-xs leading-5 text-muted-foreground">
          Diff lines are not available from the current GitHub PR metadata.
        </div>
      )}
    </article>
  );
}

export function diffLineClass(kind: DiffLineKind) {
  if (kind === "add") return "bg-success/10 text-success";
  if (kind === "delete") return "bg-destructive/10 text-destructive line-through decoration-destructive/50";
  return "";
}

export function linePrefix(kind: DiffLineKind) {
  if (kind === "add") return "+";
  if (kind === "delete") return "-";
  return " ";
}
