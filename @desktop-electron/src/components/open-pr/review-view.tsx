import { type DragEvent } from "react";
import { ArrowLeft, Bug, Check, MessageSquarePlus, Route, ShieldAlert } from "lucide-react";
import type { PullRequestSummary } from "../../api/client";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";
import { DiffCard } from "./diff/diff-card";
import { DND_FILE_MIME, FileRailButton } from "./diff/file-rail-button";
import { ReviewAgentWindow } from "./review-agent-window";

type PullRequestFile = PullRequestSummary["files"][number];

export function PullRequestReviewView({
  pullRequest,
  totals,
  activeFileId,
  activeFile,
  openFiles,
  onBack,
  onSelectFile,
  onAddFile,
  onFocusFile,
  onCloseFile,
}: {
  pullRequest: PullRequestSummary;
  totals: { additions: number; deletions: number };
  activeFileId: string;
  activeFile?: PullRequestFile;
  openFiles: PullRequestFile[];
  onBack: () => void;
  onSelectFile: (fileId: string) => void;
  onAddFile: (fileId: string) => void;
  onFocusFile: (fileId: string) => void;
  onCloseFile: (fileId: string) => void;
}) {
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const fileId = event.dataTransfer.getData(DND_FILE_MIME) || event.dataTransfer.getData("text/plain");
    if (fileId) onAddFile(fileId);
  };

  return (
    <>
      <header className="flex h-auto shrink-0 items-start gap-4 border-b border-glass-border/25 bg-background/95 px-5 py-4 max-[760px]:flex-col">
        <div className="min-w-0 flex-1">
          <div className="break-words font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
            PR #{pullRequest.number} / {pullRequest.branch}
          </div>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-foreground">{pullRequest.title}</h1>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {pullRequest.files.length} files changed, {pullRequest.commentsCount} review comments, {pullRequest.risk.toLowerCase()} risk.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 max-[760px]:w-full max-[760px]:justify-start">
          <Button variant="subtle" className="rounded-xl" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
            Queue
          </Button>
          <Button variant="subtle" className="rounded-xl">
            <MessageSquarePlus className="h-4 w-4" />
            Draft comment
          </Button>
          <Button className="rounded-xl">
            <Check className="h-4 w-4" />
            Approve
          </Button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(260px,330px)_minmax(0,1fr)] gap-4 overflow-hidden p-5 max-[940px]:grid-cols-1 max-[940px]:overflow-auto">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-card/75 shadow-soft backdrop-blur-xl">
          <div className="shrink-0 border-b border-glass-border/25 px-4 py-3">
            <div className="text-sm font-semibold text-foreground">Files changed</div>
            <div className="mt-1 text-[11px] text-muted-foreground">{totals.additions} additions, {totals.deletions} deletions</div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {pullRequest.files.map((file) => (
              <FileRailButton
                key={file.id}
                file={file}
                active={file.id === activeFileId}
                onOpen={() => onSelectFile(file.id)}
              />
            ))}
          </div>
        </section>

        <section
          className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-card/75 shadow-soft backdrop-blur-xl"
          onDragOver={(event) => event.preventDefault()}
          onDrop={handleDrop}
          data-testid="pr-diff-dropzone"
        >
          <div className="flex shrink-0 items-start justify-between gap-3 border-b border-glass-border/25 px-4 py-3 max-[760px]:flex-col">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-foreground">{activeFile?.path ?? "Diff viewer"}</div>
              <div className="mt-1 text-[11px] text-muted-foreground">Drop files here to compare more than one diff.</div>
            </div>
            <div className="flex shrink-0 flex-wrap justify-end gap-2 max-[760px]:justify-start">
              <Button variant="subtle" size="xs" className="rounded-xl">
                <Bug className="h-3.5 w-3.5" />
                Find errors
              </Button>
              <Button variant="subtle" size="xs" className="rounded-xl">
                <Route className="h-3.5 w-3.5" />
                Trace function
              </Button>
              <Button variant="subtle" size="xs" className="rounded-xl">
                <ShieldAlert className="h-3.5 w-3.5" />
                Risk
              </Button>
            </div>
          </div>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
            {openFiles.map((file) => (
              <DiffCard
                key={file.id}
                file={file}
                active={file.id === activeFileId}
                canClose={openFiles.length > 1}
                onFocus={() => onFocusFile(file.id)}
                onClose={() => onCloseFile(file.id)}
              />
            ))}
          </div>
        </section>
      </div>

      <ReviewAgentWindow pullRequest={pullRequest} activeFile={activeFile} />
    </>
  );
}
