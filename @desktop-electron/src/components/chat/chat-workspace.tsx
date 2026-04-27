import { useState } from "react";
import { ChevronRight, FolderOpen, PanelRight } from "lucide-react";
import { InputDock } from "./input-dock";
import { MessageFeed } from "./message-feed";
import { SessionPanel } from "./session-panel";
import { workspaceName } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

export function ChatWorkspace() {
  const [sessionPanelOpen, setSessionPanelOpen] = useState(false);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const conversationTitle = useChatStore((state) => state.conversationTitle);
  const folderLabel = selectedWorkspace ? workspaceName(selectedWorkspace) : "Folder";
  const sessionLabel = conversationTitle || "Session Name";

  return (
    <section className="relative flex h-full min-w-0 flex-col overflow-hidden bg-background">
      <header className="flex h-10 shrink-0 items-center gap-3 border-b border-glass-border/25 bg-background/95 px-3">
        <div className="flex min-w-0 flex-1 items-center gap-1.5 text-xs">
          <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 max-w-[34ch] truncate font-medium text-foreground">{folderLabel}</span>
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/70" />
          <span className="min-w-0 truncate text-muted-foreground">{sessionLabel}</span>
        </div>
        <div className="shrink-0">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={sessionPanelOpen ? "secondary" : "ghost"}
                size="iconSm"
                aria-label="Painel da Sessão"
                onClick={() => setSessionPanelOpen((value) => !value)}
                className="rounded-xl border border-glass-border/35 bg-background/80 shadow-soft backdrop-blur"
              >
                <PanelRight className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Painel da Sessão</TooltipContent>
          </Tooltip>
        </div>
      </header>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="relative min-w-0 flex-1 overflow-hidden transition-[width,transform] duration-300 ease-out">
          <MessageFeed />
          <InputDock />
        </div>
        <div
          data-testid="session-panel-shell"
          aria-hidden={!sessionPanelOpen}
          className={
            sessionPanelOpen
              ? "h-full w-[min(430px,calc(100vw-64px))] shrink-0 translate-x-0 overflow-hidden border-l border-glass-border/25 opacity-100 transition-[width,opacity,transform] duration-300 ease-out"
              : "pointer-events-none h-full w-0 shrink-0 translate-x-6 overflow-hidden border-l-0 border-glass-border/25 opacity-0 transition-[width,opacity,transform] duration-300 ease-out"
          }
        >
          <SessionPanel visible={sessionPanelOpen} onClose={() => setSessionPanelOpen(false)} />
        </div>
      </div>
    </section>
  );
}
