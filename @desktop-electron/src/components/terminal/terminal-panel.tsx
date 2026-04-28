import { useEffect } from "react";
import { TerminalManager } from "./terminal-manager";
import { useTerminalStore } from "../../stores/terminal-store";

interface TerminalPanelProps {
  open: boolean;
}

const TERMINAL_HEIGHT = 280;

export function TerminalPanel({ open }: TerminalPanelProps) {
  const addInstance = useTerminalStore((s) => s.addInstance);
  const leftInstances = useTerminalStore((s) => s.leftPane.instances);
  const rightInstances = useTerminalStore((s) => s.rightPane?.instances ?? []);
  const totalInstances = leftInstances.length + rightInstances.length;

  // Ensure at least one terminal exists when panel opens
  useEffect(() => {
    if (open && totalInstances === 0) {
      addInstance("left", "Shell");
    }
  }, [open, totalInstances, addInstance]);

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
