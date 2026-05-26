import { useEffect, useState, type DragEvent } from "react";
import { ChevronRight, FolderOpen, LayoutGrid, PanelRight, Terminal, X } from "lucide-react";
import { InputDock } from "./input-dock";
import { FileViewerPanel } from "./file-viewer-panel";
import { MessageFeed } from "./message-feed";
import { SessionPanel } from "./session-panel";
import { WorkspacePanel } from "./workspace-panel";
import { cn, workspaceName } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { ChatStoreProvider, getDefaultChatStore, useChatStore } from "../../stores/chat-store";
import { CHAT_SESSION_DRAG_MIME, MAIN_CHAT_PANE_ID, useChatLayoutStore } from "../../stores/chat-layout-store";
import { useTerminalStore } from "../../stores/terminal-store";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { TerminalPanel, TERMINAL_HEIGHT } from "../terminal/terminal-panel";
import { GitActionButton } from "../git/git-action-button";
import { ManagedSplitPane } from "./chat-workspace/managed-split-pane";
import { useFileTabs } from "./chat-workspace/use-file-tabs";
import { useSessionPanelResize, SESSION_PANEL_MIN_WIDTH, SESSION_PANEL_MIN_CHAT_WIDTH } from "./chat-workspace/use-session-panel-resize";

export function ChatWorkspace() {
  const splitPanes = useChatLayoutStore((state) => state.panes);
  const addPane = useChatLayoutStore((state) => state.addPane);
  const focusPane = useChatLayoutStore((state) => state.focusPane);
  const activePaneId = useChatLayoutStore((state) => state.activePaneId);
  const splitMode = splitPanes.length > 0;

  const handleDragOver = (event: DragEvent<HTMLElement>) => {
    if (!event.dataTransfer.types.includes(CHAT_SESSION_DRAG_MIME)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };

  const handleDrop = (event: DragEvent<HTMLElement>) => {
    const raw = event.dataTransfer.getData(CHAT_SESSION_DRAG_MIME);
    if (!raw) return;
    event.preventDefault();
    try {
      const payload = JSON.parse(raw) as { conversationId?: string; workspaceRoot?: string; title?: string };
      if (!payload.conversationId) return;
      const mainConversationId = getDefaultChatStore().getState().conversationId;
      if (payload.conversationId === mainConversationId) {
        focusPane(MAIN_CHAT_PANE_ID);
        return;
      }
      addPane({
        conversationId: payload.conversationId,
        workspaceRoot: payload.workspaceRoot,
        title: payload.title,
      });
    } catch {
      // Ignore malformed drag payloads from outside the app.
    }
  };

  return (
    <section
      className={cn("relative h-full min-w-0 overflow-hidden bg-background", splitMode && "p-2")}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {splitMode ? (
        <div className={cn("grid h-full min-h-0 min-w-0 gap-2", splitPanes.length === 1 ? "grid-cols-2" : "grid-cols-2 grid-rows-2")}>
          <ChatStoreProvider store={getDefaultChatStore()}>
            <ChatPaneSurface
              paneId={MAIN_CHAT_PANE_ID}
              split
              active={activePaneId === MAIN_CHAT_PANE_ID}
              onFocus={() => focusPane(MAIN_CHAT_PANE_ID)}
            />
          </ChatStoreProvider>
          {splitPanes.map((pane) => (
            <ManagedSplitPane key={pane.id} pane={pane} active={activePaneId === pane.id} />
          ))}
        </div>
      ) : (
        <ChatStoreProvider store={getDefaultChatStore()}>
          <ChatPaneSurface paneId={MAIN_CHAT_PANE_ID} />
        </ChatStoreProvider>
      )}
    </section>
  );
}

export function ChatPaneSurface({
  paneId = MAIN_CHAT_PANE_ID,
  split = false,
  compact = false,
  active = true,
  onFocus,
  onClose,
}: {
  paneId?: string;
  split?: boolean;
  compact?: boolean;
  active?: boolean;
  onFocus?: () => void;
  onClose?: () => void;
}) {
  const [sessionPanelOpen, setSessionPanelOpen] = useState(false);
  const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
  const terminalOpen = useTerminalStore((state) => state.open);
  const toggleTerminal = useTerminalStore((state) => state.toggleOpen);
  const terminalAvailable = !split && !compact;
  const effectiveTerminalOpen = terminalAvailable && terminalOpen;
  const globalSelectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const paneWorkspaceRoot = useChatStore((state) => state.workspaceRoot);
  const selectedWorkspace = (paneId === MAIN_CHAT_PANE_ID
    ? globalSelectedWorkspace || paneWorkspaceRoot
    : paneWorkspaceRoot || globalSelectedWorkspace) || undefined;
  const conversationTitle = useChatStore((state) => state.conversationTitle);
  const folderLabel = selectedWorkspace ? workspaceName(selectedWorkspace) : "Folder";
  const sessionLabel = conversationTitle || "Session Name";

  const {
    activeFilePaths,
    fileViewerOpen,
    fileViewerMounted,
    visibleFileTabs,
    visibleActiveFilePath,
    openWorkspaceFile,
    closeFileTab,
    closeFileViewer,
    resetFileTabs,
    setActiveFilePath,
  } = useFileTabs();

  const {
    sessionPanelWidth,
    isSessionPanelResizing,
    sessionPanelResizeHandleRef,
    beginSessionPanelResize,
    handleSessionPanelResizeKeyDown,
  } = useSessionPanelResize(sessionPanelOpen);

  useEffect(() => {
    if (paneId !== MAIN_CHAT_PANE_ID) return;
    const chatStore = useChatStore.getState();
    const appStore = useAppStore.getState();
    chatStore.setWorkspaceRoot(selectedWorkspace);
    const currentConvId = chatStore.conversationId;
    if (currentConvId && !appStore.conversationBelongsToWorkspace(currentConvId)) {
      chatStore.startNewConversation();
    }
    resetFileTabs();
  }, [paneId, selectedWorkspace, resetFileTabs]);

  return (
    <section
      data-chat-pane-id={paneId}
      data-active={active ? "true" : "false"}
      onPointerDown={onFocus}
      className={cn(
        "relative flex h-full min-w-0 flex-col overflow-hidden bg-background",
        split && "rounded-2xl border border-glass-border/30 shadow-soft",
        split && active && "ring-1 ring-primary/25",
        compact && "rounded-none",
      )}
    >
      <header className={cn("flex shrink-0 items-center gap-3 border-b border-glass-border/25 bg-background/95 px-3", split || compact ? "h-9" : "h-10")}>
        <div className="flex min-w-0 flex-1 items-center gap-1.5 text-xs">
          <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 max-w-[34ch] truncate font-medium text-foreground">{folderLabel}</span>
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/70" />
          <span className="min-w-0 truncate text-muted-foreground">{sessionLabel}</span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={workspacePanelOpen ? "secondary" : "ghost"}
                size="iconSm"
                aria-label="Workspace"
                onClick={() => setWorkspacePanelOpen((value) => !value)}
                className="rounded-xl border border-glass-border/35 bg-background/80 shadow-soft backdrop-blur"
              >
                <LayoutGrid className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Workspace</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={sessionPanelOpen ? "secondary" : "ghost"}
                size="iconSm"
                aria-label="Session Panel"
                onClick={() => setSessionPanelOpen((value) => !value)}
                className="rounded-xl border border-glass-border/35 bg-background/80 shadow-soft backdrop-blur"
              >
                <PanelRight className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Session Panel</TooltipContent>
          </Tooltip>
          {terminalAvailable ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={effectiveTerminalOpen ? "secondary" : "ghost"}
                size="iconSm"
                aria-label="Terminal"
                onClick={() => toggleTerminal()}
                className="rounded-xl border border-glass-border/35 bg-background/80 shadow-soft backdrop-blur"
              >
                <Terminal className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Terminal</TooltipContent>
          </Tooltip>
          ) : null}
          <GitActionButton workspaceRoot={selectedWorkspace} compact={split || compact} />
          {onClose ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="iconSm"
                  aria-label="Close split session"
                  onClick={(event) => {
                    event.stopPropagation();
                    onClose();
                  }}
                  className="rounded-xl border border-glass-border/35 bg-background/80 shadow-soft backdrop-blur"
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Close session</TooltipContent>
            </Tooltip>
          ) : null}
        </div>
      </header>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="relative min-w-0 flex-1 overflow-hidden transition-[width,transform] duration-300 ease-out">
          <MessageFeed extraBottomPadding={effectiveTerminalOpen} compact={split || compact} />
          {terminalAvailable ? <TerminalPanel open={effectiveTerminalOpen} /> : null}
          <div
            className="pointer-events-none absolute inset-x-0 z-30 transition-[bottom] duration-300 ease-out"
            style={{ bottom: effectiveTerminalOpen ? TERMINAL_HEIGHT : 0 }}
          >
            <InputDock compact={split || compact} workspaceRoot={selectedWorkspace} />
          </div>
        </div>
        <div
          data-testid="file-viewer-shell"
          aria-hidden={!fileViewerOpen}
          className={
            fileViewerOpen
              ? "h-full w-[min(720px,calc(100vw-420px))] shrink-0 translate-x-0 overflow-visible opacity-100 transition-[width,opacity,transform] duration-300 ease-out"
              : "pointer-events-none h-full w-0 shrink-0 translate-x-6 overflow-hidden opacity-0 transition-[width,opacity,transform] duration-300 ease-out"
          }
        >
          {fileViewerMounted ? (
            <FileViewerPanel
              tabs={visibleFileTabs}
              activePath={visibleActiveFilePath}
              workspaceRoot={selectedWorkspace}
              onOpenFile={openWorkspaceFile}
              onSelectTab={setActiveFilePath}
              onCloseTab={closeFileTab}
              onClose={closeFileViewer}
            />
          ) : null}
        </div>
        <div
          data-testid="workspace-panel-shell"
          aria-hidden={!workspacePanelOpen}
          className={
            workspacePanelOpen
              ? "h-full w-[min(320px,calc(100vw-64px))] shrink-0 translate-x-0 overflow-hidden border-l border-glass-border/25 opacity-100 transition-[width,opacity,transform] duration-300 ease-out"
              : "pointer-events-none h-full w-0 shrink-0 translate-x-6 overflow-hidden border-l-0 border-glass-border/25 opacity-0 transition-[width,opacity,transform] duration-300 ease-out"
          }
        >
          <WorkspacePanel
            key={selectedWorkspace || "no-workspace"}
            visible={workspacePanelOpen}
            onClose={() => setWorkspacePanelOpen(false)}
            onOpenFile={openWorkspaceFile}
            activeFilePaths={activeFilePaths}
            workspaceRoot={selectedWorkspace}
          />
        </div>
        <div
          data-testid="session-panel-shell"
          data-resizing={isSessionPanelResizing ? "true" : "false"}
          aria-hidden={!sessionPanelOpen}
          style={sessionPanelOpen ? { width: `${sessionPanelWidth}px` } : undefined}
          className={
            sessionPanelOpen
              ? cn(
                  "relative h-full shrink-0 translate-x-0 overflow-visible border-l border-glass-border/25 opacity-100",
                  isSessionPanelResizing ? "bg-popover/95 shadow-[inset_1px_0_0_hsl(var(--primary)/0.4)] transition-none" : "transition-[width,opacity,transform] duration-300 ease-out",
                )
              : "pointer-events-none h-full w-0 shrink-0 translate-x-6 overflow-hidden border-l-0 border-glass-border/25 opacity-0 transition-[width,opacity,transform] duration-300 ease-out"
          }
        >
          {sessionPanelOpen ? (
            <>
              <div
                ref={sessionPanelResizeHandleRef}
                aria-label="Resize session panel"
                aria-orientation="vertical"
                aria-valuemin={SESSION_PANEL_MIN_WIDTH}
                aria-valuemax={Math.max(SESSION_PANEL_MIN_WIDTH, window.innerWidth - SESSION_PANEL_MIN_CHAT_WIDTH)}
                aria-valuenow={Math.round(sessionPanelWidth)}
                data-testid="session-panel-resize-handle"
                data-resizing={isSessionPanelResizing ? "true" : "false"}
                role="separator"
                tabIndex={-1}
                className={cn(
                  "absolute -left-3 top-0 z-30 h-full w-6 cursor-col-resize touch-none select-none",
                  isSessionPanelResizing ? "bg-primary/10" : "bg-transparent",
                )}
                onKeyDown={handleSessionPanelResizeKeyDown}
                onPointerDown={beginSessionPanelResize}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute inset-y-3 left-[7px] w-px rounded-full transition-colors",
                    isSessionPanelResizing ? "bg-primary/90 shadow-[0_0_14px_hsl(var(--primary)/0.55)]" : "bg-glass-border/80",
                  )}
                />
              </div>
              <div className="relative h-full overflow-hidden">
                <SessionPanel key={selectedWorkspace || "no-workspace"} visible={sessionPanelOpen} onClose={() => setSessionPanelOpen(false)} />
              </div>
            </>
          ) : null}
        </div>
      </div>
    </section>
  );
}
