import { useEffect } from "react";
import { TerminalManager } from "./terminal-manager";
import { useAppStore } from "../../stores/app-store";
import { useTerminalStore } from "../../stores/terminal-store";
import { TERMINAL_HEIGHT } from "./constants";

interface TerminalPanelProps {
  open: boolean;
}

export function TerminalPanel({ open }: TerminalPanelProps) {
  const leftInstanceCount = useTerminalStore((s) => s.leftPane.instances.length);
  const rightInstanceCount = useTerminalStore((s) => s.rightPane?.instances.length ?? 0);
  const selectedWorkspace = useAppStore((s) => s.selectedWorkspace);
  const totalInstances = leftInstanceCount + rightInstanceCount;

  // Ensure at least one terminal exists when panel opens
  useEffect(() => {
    if (open && totalInstances === 0) {
      useTerminalStore.getState().addInstance("left", "Shell", selectedWorkspace);
    }
  }, [open, selectedWorkspace, totalInstances]);

  return (
    <div
      data-testid="terminal-panel"
      className={[
        "absolute inset-x-0 z-20 border-t border-glass-border/35 bg-card/95 shadow-dock backdrop-blur-xl",
        "transition-[transform,opacity] duration-300 ease-out will-change-transform",
        open ? "translate-y-0 opacity-100" : "translate-y-full opacity-80",
      ].join(" ")}
      style={{ bottom: 0, height: TERMINAL_HEIGHT }}
    >
      <TerminalManager />
    </div>
  );
}

export { TERMINAL_HEIGHT };
