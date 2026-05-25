import type { ReactNode } from "react";

export function SectionTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
      {icon}
      <span>{title}</span>
    </div>
  );
}

export function EmptyPanel({ text }: { text: string }) {
  return <div className="flex min-h-[220px] items-center justify-center px-6 text-center text-xs text-muted-foreground">{text}</div>;
}

export function EmptyList({ text }: { text: string }) {
  return <div className="py-2 text-[11px] text-muted-foreground">{text}</div>;
}

export function PanelSkeleton() {
  return (
    <div className="space-y-5 animate-pulse">
      <div className="grid grid-cols-4 gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="border-b border-glass-border/25 pb-2">
            <div className="h-5 w-8 rounded bg-muted" />
            <div className="mt-1 h-3 w-14 rounded bg-muted/60" />
          </div>
        ))}
      </div>
      <section className="border-t border-glass-border/25 pt-3">
        <div className="flex items-center gap-2">
          <div className="h-3.5 w-3.5 rounded bg-muted" />
          <div className="h-3 w-24 rounded bg-muted/60" />
        </div>
        <div className="mt-2 divide-y divide-glass-border/25">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 py-2">
              <div className="h-3 w-full rounded bg-muted/50" />
              <div className="h-3 w-8 rounded bg-muted/30" />
            </div>
          ))}
        </div>
      </section>
      <section className="border-t border-glass-border/25 pt-3">
        <div className="flex items-center gap-2">
          <div className="h-3.5 w-3.5 rounded bg-muted" />
          <div className="h-3 w-28 rounded bg-muted/60" />
        </div>
        <div className="mt-2 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-8 w-full rounded-lg border border-glass-border/25 bg-muted/20" />
          ))}
        </div>
      </section>
    </div>
  );
}
