import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { ChevronRight, FolderOpen, LayoutGrid, PanelRight, Terminal } from "lucide-react";
import { type DirEntry } from "../../lib/workspace-files";
import { InputDock } from "./input-dock";
import { FileViewerPanel, type WorkspaceFileTab } from "./file-viewer-panel";
import { MessageFeed } from "./message-feed";
import { SessionPanel } from "./session-panel";
import { WorkspacePanel } from "./workspace-panel";
import { cn, workspaceName } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { useTerminalStore } from "../../stores/terminal-store";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { TerminalPanel, TERMINAL_HEIGHT } from "../terminal/terminal-panel";
import { GitActionButton } from "../git/git-action-button";

const FILE_VIEWER_TRANSITION_MS = 300;
const SESSION_PANEL_DEFAULT_WIDTH = 430;
const SESSION_PANEL_MIN_WIDTH = 320;
const SESSION_PANEL_MIN_CHAT_WIDTH = 360;

function clampSessionPanelWidth(width: number) {
  if (typeof window === "undefined") return width;
  const maxWidth = Math.max(SESSION_PANEL_MIN_WIDTH, window.innerWidth - SESSION_PANEL_MIN_CHAT_WIDTH);
  return Math.min(Math.max(width, SESSION_PANEL_MIN_WIDTH), maxWidth);
}

export function ChatWorkspace() {
  const [sessionPanelOpen, setSessionPanelOpen] = useState(false);
  const [sessionPanelWidth, setSessionPanelWidth] = useState(() => clampSessionPanelWidth(SESSION_PANEL_DEFAULT_WIDTH));
  const [isSessionPanelResizing, setIsSessionPanelResizing] = useState(false);
  const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
  const sessionPanelResizeCleanupRef = useRef<(() => void) | null>(null);
  const sessionPanelResizeHandleRef = useRef<HTMLDivElement | null>(null);
  const sessionPanelResizePointerIdRef = useRef<number | null>(null);
  const terminalOpen = useTerminalStore((state) => state.open);
  const toggleTerminal = useTerminalStore((state) => state.toggleOpen);
  const [fileTabs, setFileTabs] = useState<WorkspaceFileTab[]>([]);
  const [activeFilePath, setActiveFilePath] = useState<string | undefined>();
  const [renderedFileTabs, setRenderedFileTabs] = useState<WorkspaceFileTab[]>([]);
  const [renderedActiveFilePath, setRenderedActiveFilePath] = useState<string | undefined>();
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const conversationTitle = useChatStore((state) => state.conversationTitle);
  const folderLabel = selectedWorkspace ? workspaceName(selectedWorkspace) : "Folder";
  const sessionLabel = conversationTitle || "Session Name";
  const activeFilePaths = useMemo(() => new Set(fileTabs.map((tab) => tab.path)), [fileTabs]);
  const fileViewerOpen = fileTabs.length > 0;
  const fileViewerMounted = fileViewerOpen || renderedFileTabs.length > 0;
  const visibleFileTabs = fileViewerOpen ? fileTabs : renderedFileTabs;
  const visibleActiveFilePath = fileViewerOpen ? activeFilePath : renderedActiveFilePath;

  const stopSessionPanelResize = () => {
    sessionPanelResizeCleanupRef.current?.();
    sessionPanelResizeCleanupRef.current = null;
    const resizeHandle = sessionPanelResizeHandleRef.current;
    const pointerId = sessionPanelResizePointerIdRef.current;
    sessionPanelResizePointerIdRef.current = null;
    if (resizeHandle && pointerId !== null) {
      try {
        resizeHandle.releasePointerCapture?.(pointerId);
      } catch {
        // Ignore browsers that already cleared capture or do not support it.
      }
    }
    setIsSessionPanelResizing(false);
    if (typeof document !== "undefined") {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
  };

  const beginSessionPanelResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    stopSessionPanelResize();
    setIsSessionPanelResizing(true);
    if (typeof document !== "undefined") {
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    }

    const updateWidthFromPointer = (clientX: number) => {
      setSessionPanelWidth(clampSessionPanelWidth(window.innerWidth - clientX));
    };

    const stopResize = () => {
      stopSessionPanelResize();
    };

    const onPointerMove = (moveEvent: PointerEvent) => {
      updateWidthFromPointer(moveEvent.clientX);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
    window.addEventListener("blur", stopResize);

    sessionPanelResizeCleanupRef.current = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
      window.removeEventListener("blur", stopResize);
    };

    sessionPanelResizePointerIdRef.current = event.pointerId;
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // The window listeners still cover the resize interaction if capture fails.
    }
    updateWidthFromPointer(event.clientX);
  };

  const handleSessionPanelResizeKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 48 : 24;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setSessionPanelWidth((current) => clampSessionPanelWidth(current - step));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setSessionPanelWidth((current) => clampSessionPanelWidth(current + step));
    } else if (event.key === "Home") {
      event.preventDefault();
      setSessionPanelWidth(SESSION_PANEL_MIN_WIDTH);
    } else if (event.key === "End") {
      event.preventDefault();
      setSessionPanelWidth(clampSessionPanelWidth(window.innerWidth));
    }
  };

  useEffect(() => {
    const chatStore = useChatStore.getState();
    const appStore = useAppStore.getState();
    const currentConvId = chatStore.conversationId;
    if (currentConvId && !appStore.conversationBelongsToWorkspace(currentConvId)) {
      chatStore.startNewConversation();
    }
    setFileTabs([]);
    setActiveFilePath(undefined);
    setRenderedFileTabs([]);
    setRenderedActiveFilePath(undefined);
  }, [selectedWorkspace]);

  useEffect(() => {
    if (!sessionPanelOpen) {
      stopSessionPanelResize();
      return;
    }
    setSessionPanelWidth((current) => clampSessionPanelWidth(current));
    const clampWidth = () => setSessionPanelWidth((current) => clampSessionPanelWidth(current));
    window.addEventListener("resize", clampWidth);
    return () => window.removeEventListener("resize", clampWidth);
  }, [sessionPanelOpen]);

  useEffect(() => {
    return () => {
      stopSessionPanelResize();
    };
  }, []);

  useEffect(() => {
    if (fileTabs.length > 0) {
      setRenderedFileTabs(fileTabs);
      setRenderedActiveFilePath(activeFilePath ?? fileTabs[0]?.path);
      return;
    }

    if (renderedFileTabs.length === 0) return;

    const timeout = window.setTimeout(() => {
      setRenderedFileTabs([]);
      setRenderedActiveFilePath(undefined);
    }, FILE_VIEWER_TRANSITION_MS);

    return () => window.clearTimeout(timeout);
  }, [activeFilePath, fileTabs, renderedFileTabs.length]);

  const openWorkspaceFile = (entry: DirEntry) => {
    if (entry.isDirectory) return;
    setWorkspacePanelOpen(true);
    setFileTabs((current) => {
      if (current.some((tab) => tab.path === entry.path)) return current;
      return [...current, { name: entry.name, path: entry.path }];
    });
    setActiveFilePath(entry.path);
  };

  const closeFileTab = (path: string) => {
    setFileTabs((current) => {
      const index = current.findIndex((tab) => tab.path === path);
      if (index === -1) return current;
      const next = current.filter((tab) => tab.path !== path);
      if (activeFilePath === path) {
        setActiveFilePath(next[Math.max(0, index - 1)]?.path ?? next[0]?.path);
      }
      return next;
    });
  };

  const closeFileViewer = () => {
    setFileTabs([]);
    setActiveFilePath(undefined);
  };

  return (
    <section className="relative flex h-full min-w-0 flex-col overflow-hidden bg-background">
      <header className="flex h-10 shrink-0 items-center gap-3 border-b border-glass-border/25 bg-background/95 px-3">
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
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={terminalOpen ? "secondary" : "ghost"}
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
          <GitActionButton />
        </div>
      </header>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="relative min-w-0 flex-1 overflow-hidden transition-[width,transform] duration-300 ease-out">
          <MessageFeed extraBottomPadding={terminalOpen} />
          <TerminalPanel open={terminalOpen} />
          <div
            className="pointer-events-none absolute inset-x-0 z-30 transition-[bottom] duration-300 ease-out"
            style={{ bottom: terminalOpen ? TERMINAL_HEIGHT : 0 }}
          >
            <InputDock />
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
                tabIndex={0}
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
