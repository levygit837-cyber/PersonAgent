import type { ReactNode } from "react";
import { cn } from "../../../lib/utils";

export function QueueFilterButton({ children, active, bordered, onClick }: { children: ReactNode; active: boolean; bordered?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className={cn(
        "px-3 py-2 hover:bg-glass/80 hover:text-foreground",
        bordered && "border-l border-glass-border/25",
        active && "bg-primary/10 text-foreground",
      )}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
