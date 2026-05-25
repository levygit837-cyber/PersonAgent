import { type DragEvent } from "react";
import { FileCode2 } from "lucide-react";
import type { PullRequestSummary } from "../../../api/client";
import { cn } from "../../../lib/utils";

export const DND_FILE_MIME = "application/personagent-pr-file";

type PullRequestFile = PullRequestSummary["files"][number];

export function FileRailButton({
  file,
  active,
  onOpen,
}: {
  file: PullRequestFile;
  active: boolean;
  onOpen: () => void;
}) {
  const onDragStart = (event: DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(DND_FILE_MIME, file.id);
    event.dataTransfer.setData("text/plain", file.id);
  };

  return (
    <button
      type="button"
      draggable
      onDragStart={onDragStart}
      onClick={onOpen}
      aria-label={`Open diff for ${file.path}`}
      className={cn(
        "mb-1.5 w-full rounded-xl border p-3 text-left transition-[background,border-color,box-shadow,transform] duration-150",
        active
          ? "border-primary/30 bg-accent/70 text-foreground shadow-soft"
          : "border-transparent text-muted-foreground hover:border-glass-border/30 hover:bg-glass/70 hover:text-foreground",
      )}
    >
      <div className="flex min-w-0 items-start gap-2">
        <FileCode2 className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="break-words text-xs font-semibold leading-5 text-foreground">{file.path}</div>
          <div className="mt-1 flex flex-wrap gap-2 text-[11px]">
            <span>{file.changeType}</span>
            <span className="font-mono text-success">+{file.additions}</span>
            <span className="font-mono text-destructive">-{file.deletions}</span>
          </div>
          <p className="mt-2 text-[11px] leading-4 text-muted-foreground">{file.summary}</p>
        </div>
      </div>
    </button>
  );
}
