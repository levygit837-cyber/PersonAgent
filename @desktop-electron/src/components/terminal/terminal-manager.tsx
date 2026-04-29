import { Columns2, Plus, X } from "lucide-react";
import { Button } from "../ui/button";
import { useAppStore } from "../../stores/app-store";
import { useTerminalStore, type TerminalInstance, type TerminalPane } from "../../stores/terminal-store";
import { TerminalView } from "./terminal-view";

interface TerminalPaneProps {
  pane: TerminalPane;
  showPanelActions: boolean;
}

const EMPTY_TERMINAL_INSTANCES: TerminalInstance[] = [];

function TerminalPaneComponent({ pane, showPanelActions }: TerminalPaneProps) {
  const instances = useTerminalStore((s) =>
    pane === "left" ? s.leftPane.instances : (s.rightPane?.instances ?? EMPTY_TERMINAL_INSTANCES)
  );
  const activeInstanceId = useTerminalStore((s) =>
    pane === "left" ? s.leftPane.activeInstanceId : (s.rightPane?.activeInstanceId ?? null)
  );
  const addInstance = useTerminalStore((s) => s.addInstance);
  const removeInstance = useTerminalStore((s) => s.removeInstance);
  const setActiveInstance = useTerminalStore((s) => s.setActiveInstance);
  const splitMode = useTerminalStore((s) => s.splitMode);
  const toggleSplit = useTerminalStore((s) => s.toggleSplit);
  const toggleOpen = useTerminalStore((s) => s.toggleOpen);
  const selectedWorkspace = useAppStore((s) => s.selectedWorkspace);

  const hasInstances = instances.length > 0;

  return (
    <div className="flex h-full flex-col">
      {/* Header próprio do painel */}
      <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-glass-border/25 bg-background/80 px-2">
        <div className="flex min-w-0 flex-1 items-center gap-1">
          {instances.map((inst) => (
            <button
              key={inst.id}
              type="button"
              onClick={() => setActiveInstance(pane, inst.id)}
              className={[
                "group relative flex h-6 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[11px] transition-colors",
                activeInstanceId === inst.id
                  ? "bg-secondary/80 text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              <span className="truncate">{inst.name}</span>
              {!inst.alive && (
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-destructive" />
              )}
              <span
                role="button"
                tabIndex={-1}
                onClick={(e) => {
                  e.stopPropagation();
                  removeInstance(pane, inst.id);
                }}
                className="inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-md opacity-0 transition-opacity group-hover:opacity-100 hover:bg-glass/60"
              >
                <X className="h-2.5 w-2.5" />
              </span>
            </button>
          ))}
          <Button
            variant="ghost"
            size="iconSm"
            onClick={() => {
              const newId = addInstance(pane, undefined, selectedWorkspace);
              setActiveInstance(pane, newId);
            }}
            className="h-6 w-6 rounded-lg text-muted-foreground hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
        {showPanelActions ? (
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <Button
              variant={splitMode ? "secondary" : "ghost"}
              size="iconSm"
              onClick={toggleSplit}
              className="h-6 w-6 rounded-lg text-muted-foreground hover:text-foreground"
              aria-label="Split terminal"
              title="Split terminal"
            >
              <Columns2 className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="iconSm"
              onClick={toggleOpen}
              className="h-6 w-6 rounded-lg text-muted-foreground hover:text-foreground"
              aria-label="Close terminal panel"
              title="Close terminal"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : null}
      </div>

      {/* Content */}
      <div className="relative min-h-0 flex-1 overflow-hidden bg-[#0a0a0a]">
        {instances.map((inst) => (
          <div
            key={inst.id}
            className={[
              "absolute inset-0",
              activeInstanceId === inst.id
                ? "z-10 opacity-100"
                : "z-0 opacity-0 pointer-events-none",
            ].join(" ")}
          >
            <TerminalView instanceId={inst.id} focused={activeInstanceId === inst.id} />
          </div>
        ))}

        {!hasInstances && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-xs text-muted-foreground/60">
            <span>Nenhum terminal neste painel</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                const newId = addInstance(pane, undefined, selectedWorkspace);
                setActiveInstance(pane, newId);
              }}
              className="h-7 gap-1.5 rounded-lg text-xs text-muted-foreground hover:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" />
              Criar terminal
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

export function TerminalManager() {
  const splitMode = useTerminalStore((s) => s.splitMode);

  return (
    <div className="flex h-full flex-col">
      {/* Content area */}
      <div className="min-h-0 flex-1">
        {splitMode ? (
          <div className="grid h-full grid-cols-2 divide-x divide-glass-border/25">
            <TerminalPaneComponent pane="left" showPanelActions={false} />
            <TerminalPaneComponent pane="right" showPanelActions />
          </div>
        ) : (
          <TerminalPaneComponent pane="left" showPanelActions />
        )}
      </div>
    </div>
  );
}
