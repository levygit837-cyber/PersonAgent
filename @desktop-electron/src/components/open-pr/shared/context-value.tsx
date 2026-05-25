export function ContextValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-glass-border/20 bg-background/30 px-3 py-2">
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className="mt-1 break-words text-foreground">{value}</div>
    </div>
  );
}
