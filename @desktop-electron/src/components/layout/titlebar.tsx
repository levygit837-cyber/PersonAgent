import { Minus, Square, X } from "lucide-react";
import { Button } from "../ui/button";

export function TitleBar({ compactTitle }: { compactTitle?: string }) {
  return (
    <header className="drag-region flex h-9 shrink-0 select-none items-center border-b border-glass-border/25 bg-background">
      <div className="ml-3 flex min-w-0 flex-1 items-center gap-1.5">
        <div className="grid h-[18px] w-[18px] place-items-center rounded bg-primary/15 text-[9px] font-bold text-primary">
          P
        </div>
        <span className="shrink-0 text-[13px] font-medium tracking-tight text-foreground">PersonAgent</span>
        <span className="max-w-[24ch] truncate text-[11px] text-muted-foreground">
          {compactTitle ? compactTitle : ".local"}
        </span>
      </div>
      <div className="no-drag ml-auto flex h-full items-center">
        <Button
          aria-label="Minimize"
          variant="ghost"
          size="icon"
          className="no-drag h-9 w-10 rounded-none"
          onClick={() => void window.personAgent?.window.minimize()}
        >
          <Minus className="h-3 w-3" />
        </Button>
        <Button
          aria-label="Maximize"
          variant="ghost"
          size="icon"
          className="no-drag h-9 w-10 rounded-none"
          onClick={() => void window.personAgent?.window.maximizeToggle()}
        >
          <Square className="h-3 w-3" />
        </Button>
        <Button
          aria-label="Close"
          variant="ghost"
          size="icon"
          className="no-drag h-9 w-10 rounded-none hover:bg-destructive/90 hover:text-destructive-foreground"
          onClick={() => void window.personAgent?.window.close()}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
    </header>
  );
}
