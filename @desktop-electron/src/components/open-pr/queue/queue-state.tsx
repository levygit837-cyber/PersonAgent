import type { ReactNode } from "react";

export function QueueState({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return (
    <div className="rounded-xl border border-glass-border/30 bg-background/35 p-3 text-xs leading-5 text-muted-foreground">
      <div className="flex items-center gap-2 font-semibold text-foreground">
        <span className="text-primary">{icon}</span>
        {title}
      </div>
      {detail ? <p className="mt-1">{detail}</p> : null}
    </div>
  );
}
