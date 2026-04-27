import { useEffect, useRef, useState, type PointerEvent } from "react";
import { ExternalLink, GripHorizontal, X } from "lucide-react";
import type { ProjectDetail } from "../../types/chat";
import { Button } from "../ui/button";

export interface SessionDetailView extends ProjectDetail {
  subtitle?: string;
}

export function SessionDetailWindow({
  detail,
  onClose,
}: {
  detail: SessionDetailView;
  onClose: () => void;
}) {
  const windowRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const [position, setPosition] = useState(() => ({
    x: Math.max(16, window.innerWidth - 660),
    y: 70,
  }));

  useEffect(() => {
    const clamp = () => {
      const rect = windowRef.current?.getBoundingClientRect();
      const width = rect?.width ?? 620;
      const height = rect?.height ?? 520;
      setPosition((current) => ({
        x: clampValue(current.x, 8, Math.max(8, window.innerWidth - width - 8)),
        y: clampValue(current.y, 44, Math.max(44, window.innerHeight - Math.min(height, window.innerHeight - 52))),
      }));
    };
    clamp();
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
  }, [detail.id, detail.type]);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const rect = windowRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = { dx: event.clientX - rect.left, dy: event.clientY - rect.top };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const rect = windowRef.current?.getBoundingClientRect();
    const width = rect?.width ?? 620;
    const height = rect?.height ?? 520;
    setPosition({
      x: clampValue(event.clientX - drag.dx, 8, Math.max(8, window.innerWidth - width - 8)),
      y: clampValue(event.clientY - drag.dy, 44, Math.max(44, window.innerHeight - Math.min(height, window.innerHeight - 52))),
    });
  };

  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    dragRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  return (
    <div
      ref={windowRef}
      className="fixed z-50 flex max-h-[calc(100vh-64px)] w-[min(640px,calc(100vw-24px))] flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-popover/95 shadow-floating backdrop-blur-xl"
      style={{ left: position.x, top: position.y }}
      role="dialog"
      aria-label={detail.title}
    >
      <div
        className="flex cursor-grab items-center gap-2 border-b border-glass-border/25 bg-card/80 px-3 py-2 active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <GripHorizontal className="h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">{detail.title}</div>
          {detail.subtitle ? <div className="truncate text-[11px] text-muted-foreground">{detail.subtitle}</div> : null}
        </div>
        {detail.url ? (
          <a
            href={detail.url}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg p-1 text-muted-foreground hover:bg-glass/80 hover:text-foreground"
            aria-label="Open detail URL"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        ) : null}
        <Button variant="ghost" size="iconSm" aria-label="Close detail" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {detail.error ? (
          <div className="mb-3 rounded-xl border border-destructive/25 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {detail.error}
          </div>
        ) : null}
        {detail.metadata ? <MetadataBlock metadata={detail.metadata} /> : null}
        {detail.files?.length ? <FilesBlock files={detail.files} /> : null}
        {detail.commits?.length ? <CommitsBlock commits={detail.commits} /> : null}
        {detail.patch ? (
          <pre className="mt-3 max-h-[46vh] overflow-auto rounded-xl border border-glass-border/35 bg-background/70 p-3 font-mono text-[11px] leading-5 text-muted-foreground">
            {detail.patch}
          </pre>
        ) : null}
      </div>
    </div>
  );
}

function MetadataBlock({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (entries.length === 0) return null;
  return (
    <dl className="grid gap-x-4 gap-y-2 text-xs sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="min-w-0 border-b border-glass-border/25 pb-2">
          <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground/70">{labelize(key)}</dt>
          <dd className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words text-muted-foreground">
            {formatValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function FilesBlock({ files }: { files: Array<Record<string, unknown>> }) {
  return (
    <div className="mt-3 border-t border-glass-border/25 pt-3">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">Files</div>
      <div className="divide-y divide-glass-border/25 rounded-xl border border-glass-border/35">
        {files.map((file, index) => (
          <div key={`${String(file.filename ?? file.path ?? index)}-${index}`} className="p-2">
            <div className="flex min-w-0 items-center gap-2 text-xs">
              <span className="min-w-0 flex-1 truncate text-foreground">{String(file.filename ?? file.path ?? "file")}</span>
              {file.additions !== undefined ? <span className="font-mono text-success">+{String(file.additions)}</span> : null}
              {file.deletions !== undefined ? <span className="font-mono text-destructive">-{String(file.deletions)}</span> : null}
            </div>
            {typeof file.patch === "string" && file.patch.trim() ? (
              <pre className="mt-2 max-h-44 overflow-auto rounded-lg border border-glass-border/35 bg-background/70 p-2 font-mono text-[11px] leading-5 text-muted-foreground">
                {file.patch}
              </pre>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function CommitsBlock({ commits }: { commits: Array<Record<string, unknown>> }) {
  return (
    <div className="mt-3 border-t border-glass-border/25 pt-3">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">Commits</div>
      <div className="divide-y divide-glass-border/25 rounded-xl border border-glass-border/35">
        {commits.map((commit, index) => (
          <div key={`${String(commit.sha ?? index)}-${index}`} className="p-2 text-xs">
            <div className="truncate font-medium text-foreground">{String(commit.message ?? commit.sha ?? "commit")}</div>
            <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
              {String(commit.sha ?? "")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function labelize(value: string) {
  return value.replace(/_/g, " ");
}

function clampValue(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
