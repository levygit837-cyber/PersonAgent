import { useEffect, useMemo, useState } from "react";
import { ChevronRight, FolderOpen, LayoutGrid, PanelRight } from "lucide-react";
import { type DirEntry } from "../../lib/workspace-files";
import { InputDock } from "./input-dock";
import { FileViewerPanel, type WorkspaceFileTab } from "./file-viewer-panel";
import { MessageFeed } from "./message-feed";
import { SessionPanel } from "./session-panel";
import { WorkspacePanel } from "./workspace-panel";
import { workspaceName } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

const FILE_VIEWER_TRANSITION_MS = 300;

export function ChatWorkspace() {
  const [sessionPanelOpen, setSessionPanelOpen] = useState(false);
  const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
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
        </div>
      </header>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="relative min-w-0 flex-1 overflow-hidden transition-[width,transform] duration-300 ease-out">
          <MessageFeed />
          <InputDock />
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
          aria-hidden={!sessionPanelOpen}
          className={
            sessionPanelOpen
              ? "h-full w-[min(430px,calc(100vw-64px))] shrink-0 translate-x-0 overflow-hidden border-l border-glass-border/25 opacity-100 transition-[width,opacity,transform] duration-300 ease-out"
              : "pointer-events-none h-full w-0 shrink-0 translate-x-6 overflow-hidden border-l-0 border-glass-border/25 opacity-0 transition-[width,opacity,transform] duration-300 ease-out"
          }
        >
          <SessionPanel key={selectedWorkspace || "no-workspace"} visible={sessionPanelOpen} onClose={() => setSessionPanelOpen(false)} />
        </div>
      </div>
    </section>
  );
}
