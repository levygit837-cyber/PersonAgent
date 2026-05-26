import { useCallback, useEffect, useMemo, useState } from "react";
import { type DirEntry } from "../../../lib/workspace-files";
import { type WorkspaceFileTab } from "../file-viewer-panel";

const FILE_VIEWER_TRANSITION_MS = 300;

export function useFileTabs() {
  const [fileTabs, setFileTabs] = useState<WorkspaceFileTab[]>([]);
  const [activeFilePath, setActiveFilePath] = useState<string | undefined>();
  const [renderedFileTabs, setRenderedFileTabs] = useState<WorkspaceFileTab[]>([]);
  const [renderedActiveFilePath, setRenderedActiveFilePath] = useState<string | undefined>();

  const activeFilePaths = useMemo(() => new Set(fileTabs.map((tab) => tab.path)), [fileTabs]);
  const fileViewerOpen = fileTabs.length > 0;
  const fileViewerMounted = fileViewerOpen || renderedFileTabs.length > 0;
  const visibleFileTabs = fileViewerOpen ? fileTabs : renderedFileTabs;
  const visibleActiveFilePath = fileViewerOpen ? activeFilePath : renderedActiveFilePath;

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

  const resetFileTabs = useCallback(() => {
    setFileTabs([]);
    setActiveFilePath(undefined);
    setRenderedFileTabs([]);
    setRenderedActiveFilePath(undefined);
  }, []);

  return {
    fileTabs,
    activeFilePath,
    renderedFileTabs,
    renderedActiveFilePath,
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
  };
}
