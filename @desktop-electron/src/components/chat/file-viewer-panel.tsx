import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  ChevronDown,
  ChevronRight,
  File,
  FileCode,
  Folder,
  FolderOpen,
  Plus,
  X,
  PencilLine,
} from "lucide-react";
import {
  isCurrentWorkspaceRequest,
  isHidden,
  isPathInside,
  normalizeDirectoryEntries,
  readWorkspaceDirectory,
  readWorkspaceTextFile,
  updateTreeNode,
  WORKSPACE_MISMATCH_ERROR,
  type DirEntry,
  type TreeNodeState,
} from "../../lib/workspace-files";
import { cn } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { useChatStore, type ComposerAnnotation } from "../../stores/chat-store";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { FileModeActions } from "./file-viewer-panel/file-mode-actions";
import { HtmlPreview } from "./file-viewer-panel/html-preview";
import { MarkdownPreview } from "./file-viewer-panel/markdown-preview";
import { highlightContent, languageFromFilename, splitHighlightedLines } from "./file-viewer-panel/highlight-utils";
import type { AnnotationDraft, FileLoadState, ViewMode } from "./file-viewer-panel/types";
import {
  compactWorkspacePath,
  defaultViewMode,
  filterRecord,
  formatLineRange,
  lineInRange,
  normalizeLineRange,
  rangesOverlap,
  selectedLinesExcerpt,
  splitLines,
} from "./file-viewer-panel/utils";
import { FileCodeContent } from "./file-viewer-panel/code-content";
import { WorkspaceFilePicker } from "./file-viewer-panel/file-picker";

export interface WorkspaceFileTab {
  name: string;
  path: string;
}

export interface FileAnnotation {
  id: number;
  fileName: string;
  filePath: string;
  displayPath: string;
  startLine: number;
  endLine: number;
  text: string;
}

interface FileViewerPanelProps {
  tabs: WorkspaceFileTab[];
  activePath?: string;
  workspaceRoot?: string;
  onOpenFile: (entry: DirEntry) => void;
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
  onClose: () => void;
}

export function FileViewerPanel({
  tabs,
  activePath,
  workspaceRoot,
  onOpenFile,
  onSelectTab,
  onCloseTab,
  onClose,
}: FileViewerPanelProps) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const addComposerAnnotation = useChatStore((state) => state.addComposerAnnotation);
  const removeComposerAnnotation = useChatStore((state) => state.removeComposerAnnotation);
  const composerAnnotations = useChatStore((state) => state.composerAnnotations);
  const [files, setFiles] = useState<Record<string, FileLoadState>>({});
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [viewModes, setViewModes] = useState<Record<string, ViewMode>>({});
  const [pickerOpen, setPickerOpen] = useState(false);
  const [annotationMode, setAnnotationMode] = useState(false);
  const [annotationDrafts, setAnnotationDrafts] = useState<Record<string, AnnotationDraft[]>>({});
  const fileStatusRef = useRef<Record<string, "loading" | "loaded" | "error">>({});
  const nextAnnotationIdRef = useRef(1);
  const nextDraftIdRef = useRef(1);
  const activeTab = tabs.find((tab) => tab.path === activePath) ?? tabs[0];
  const activeState = activeTab ? files[activeTab.path] : undefined;
  const activeMode = activeTab ? viewModes[activeTab.path] ?? defaultViewMode(activeTab.name) : "code";
  const activeContent = activeState?.content ?? "";
  const activeLineCount = activeContent ? splitLines(activeContent).length : 0;
  const activeAnnotations = activeTab ? composerAnnotations.filter((annotation) => annotation.filePath === activeTab.path) : [];
  const activeDrafts = activeTab ? annotationDrafts[activeTab.path] ?? [] : [];

  useEffect(() => {
    const openPaths = new Set(tabs.map((tab) => tab.path));
    setFiles((current) => filterRecord(current, openPaths));
    setViewModes((current) => filterRecord(current, openPaths));
    setAnnotationDrafts((current) => filterRecord(current, openPaths));
    setLoadingPaths((current) => new Set([...current].filter((path) => openPaths.has(path))));
    fileStatusRef.current = filterRecord(fileStatusRef.current, openPaths);
  }, [tabs]);

  useEffect(() => {
    if (!activeTab || !workspaceRoot) return;
    const path = activeTab.path;
    if (!isPathInside(path, workspaceRoot) || fileStatusRef.current[path]) return;

    setViewModes((current) => current[path] ? current : { ...current, [path]: defaultViewMode(activeTab.name) });
    fileStatusRef.current[path] = "loading";
    setLoadingPaths((current) => new Set(current).add(path));

    readWorkspaceTextFile(baseUrl, path, workspaceRoot)
      .then((content) => {
        fileStatusRef.current[path] = "loaded";
        setFiles((current) => ({ ...current, [path]: { content } }));
      })
      .catch((error) => {
        fileStatusRef.current[path] = "error";
        setFiles((current) => ({
          ...current,
          [path]: { error: error instanceof Error ? error.message : String(error) },
        }));
      })
      .finally(() => {
        setLoadingPaths((current) => {
          const next = new Set(current);
          next.delete(path);
          return next;
        });
      });
  }, [activeTab, baseUrl, workspaceRoot]);

  const setActiveMode = useCallback((mode: ViewMode) => {
    if (!activeTab) return;
    setViewModes((current) => ({ ...current, [activeTab.path]: mode }));
  }, [activeTab]);

  const toggleAnnotationMode = useCallback(() => {
    if (!activeTab) return;
    setAnnotationMode((current) => !current);
    setViewModes((current) => ({ ...current, [activeTab.path]: "code" }));
  }, [activeTab]);

  const handleLinePick = useCallback((lineNumber: number) => {
    if (!activeTab || !annotationMode) return;
    const path = activeTab.path;
    const persistedRanges = composerAnnotations
      .filter((annotation) => annotation.filePath === path)
      .map((annotation) => normalizeLineRange(annotation.startLine, annotation.endLine));
    if (persistedRanges.some((range) => lineInRange(lineNumber, range.start, range.end))) return;

    setAnnotationDrafts((current) => {
      const drafts = current[path] ?? [];
      const pendingIndex = drafts.findIndex((draft) => draft.focusLine === undefined);
      if (pendingIndex >= 0) {
        const pendingDraft = drafts[pendingIndex];
        const nextRange = normalizeLineRange(pendingDraft.anchorLine, lineNumber);
        if (persistedRanges.some((range) => rangesOverlap(range, nextRange))) {
          return {
            ...current,
            [path]: drafts.filter((_, index) => index !== pendingIndex),
          };
        }

        return {
          ...current,
          [path]: drafts.map((draft, index) => index === pendingIndex ? { ...draft, focusLine: lineNumber } : draft),
        };
      }

      const draft: AnnotationDraft = {
        id: `draft-${nextDraftIdRef.current}`,
        anchorLine: lineNumber,
        text: "",
      };
      nextDraftIdRef.current += 1;
      return { ...current, [path]: [...drafts, draft] };
    });
  }, [activeTab, annotationMode, composerAnnotations]);

  const updateDraftText = useCallback((draftId: string, text: string) => {
    if (!activeTab) return;
    const path = activeTab.path;
    setAnnotationDrafts((current) => ({
      ...current,
      [path]: (current[path] ?? []).map((draft) => draft.id === draftId ? { ...draft, text } : draft),
    }));
  }, [activeTab]);

  const cancelDraft = useCallback((draftId: string) => {
    if (!activeTab) return;
    const path = activeTab.path;
    setAnnotationDrafts((current) => ({
      ...current,
      [path]: (current[path] ?? []).filter((draft) => draft.id !== draftId),
    }));
  }, [activeTab]);

  const submitAnnotation = useCallback((draftId: string) => {
    if (!activeTab) return;
    const path = activeTab.path;
    const draft = (annotationDrafts[path] ?? []).find((item) => item.id === draftId);
    if (!draft) return;
    const text = draft.text.trim();
    if (!text) return;

    const range = normalizeLineRange(draft.anchorLine, draft.focusLine ?? draft.anchorLine);
    const activeAnnotationRanges = composerAnnotations
      .filter((annotation) => annotation.filePath === path)
      .map((annotation) => normalizeLineRange(annotation.startLine, annotation.endLine));
    if (activeAnnotationRanges.some((annotationRange) => rangesOverlap(annotationRange, range))) {
      setAnnotationDrafts((current) => ({
        ...current,
        [activeTab.path]: (current[activeTab.path] ?? []).filter((item) => item.id !== draftId),
      }));
      return;
    }

    const nextAvailableId = Math.max(nextAnnotationIdRef.current, ...composerAnnotations.map((annotation) => annotation.id + 1), 1);
    const id = nextAvailableId;
    nextAnnotationIdRef.current = nextAvailableId + 1;
    const displayPath = compactWorkspacePath(activeTab.path, workspaceRoot);
    const language = languageFromFilename(activeTab.name);
    const annotation: FileAnnotation = {
      id,
      fileName: activeTab.name,
      filePath: activeTab.path,
      displayPath,
      startLine: range.start,
      endLine: range.end,
      text,
    };
    const composerAnnotation: ComposerAnnotation = {
      ...annotation,
      selectedLines: selectedLinesExcerpt(activeContent, range.start, range.end),
      language,
    };

    setAnnotationDrafts((current) => ({
      ...current,
      [activeTab.path]: (current[activeTab.path] ?? []).filter((item) => item.id !== draftId),
    }));
    addComposerAnnotation(composerAnnotation);
  }, [activeContent, activeTab, addComposerAnnotation, annotationDrafts, composerAnnotations, workspaceRoot]);

  if (!activeTab) return null;

  const loading = loadingPaths.has(activeTab.path);
  const relativePath = compactWorkspacePath(activeTab.path, workspaceRoot);
  const language = languageFromFilename(activeTab.name);

  return (
    <aside className="relative flex h-full w-[min(720px,calc(100vw-420px))] min-w-[360px] flex-col overflow-hidden border-l border-glass-border/25 bg-card/95 shadow-[0_10px_24px_rgb(0_0_0_/_0.34),0_0_0_1px_rgb(237_141_78_/_0.018),inset_0_1px_0_rgb(255_236_214_/_0.018)]">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-glass-border/25 bg-card/80 px-2">
        <div role="tablist" aria-label="Open files" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {tabs.map((tab) => {
            const selected = tab.path === activeTab.path;
            return (
              <div
                key={tab.path}
                className={cn(
                  "group flex h-8 max-w-[220px] shrink-0 items-center rounded-lg border border-transparent bg-transparent text-xs transition-colors",
                  selected && "border-glass-border/40 bg-glass/70 text-foreground",
                )}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-label={tab.name}
                  onClick={() => onSelectTab(tab.path)}
                  className="flex h-full min-w-0 flex-1 items-center gap-1.5 rounded-l-lg px-2 text-left text-muted-foreground transition-colors hover:text-foreground data-[selected=true]:text-foreground"
                  data-selected={selected}
                  title={tab.path}
                >
                  <FileCode className="h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 truncate">{tab.name}</span>
                </button>
                <button
                  type="button"
                  aria-label={`Close tab ${tab.name}`}
                  onClick={() => onCloseTab(tab.path)}
                  className="mr-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 opacity-80 transition hover:bg-accent hover:text-foreground group-hover:opacity-100"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            );
          })}
        </div>

        <div className="relative shrink-0">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="iconSm"
                aria-label="Add file"
                onClick={() => setPickerOpen((value) => !value)}
                disabled={!workspaceRoot}
                className="rounded-xl"
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Add file</TooltipContent>
          </Tooltip>
          {pickerOpen ? (
            <WorkspaceFilePicker
              baseUrl={baseUrl}
              workspaceRoot={workspaceRoot}
              onPick={(entry) => {
                onOpenFile(entry);
                setPickerOpen(false);
              }}
              onClose={() => setPickerOpen(false)}
            />
          ) : null}
        </div>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={annotationMode ? "secondary" : "ghost"}
              size="iconSm"
              aria-label="Request edits"
              onClick={toggleAnnotationMode}
              className="rounded-xl"
            >
              <PencilLine className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Request edits</TooltipContent>
        </Tooltip>

        <FileModeActions
          fileName={activeTab.name}
          mode={activeMode}
          onModeChange={setActiveMode}
        />

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="iconSm" aria-label="Close viewer" onClick={onClose} className="rounded-xl">
              <X className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Close viewer</TooltipContent>
        </Tooltip>
      </div>

      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-glass-border/20 bg-card/80 px-3 font-mono text-[11px] text-muted-foreground">
        <span className="min-w-0 flex-1 truncate">{relativePath}</span>
        {activeLineCount > 0 ? <span className="shrink-0">{activeLineCount} lines</span> : null}
        {language !== "plaintext" ? <span className="shrink-0 uppercase text-muted-foreground/70">{language}</span> : null}
      </div>
      {activeAnnotations.length > 0 ? (
        <div className="flex shrink-0 gap-1.5 overflow-x-auto border-b border-glass-border/20 bg-card/85 px-3 py-2">
          {activeAnnotations.map((annotation) => (
            <div
              key={annotation.id}
              className="group flex max-w-[280px] shrink-0 items-center gap-1.5 rounded-lg border border-glass-border/35 bg-foreground/[0.045] px-2 py-1 text-left text-[11px] text-muted-foreground ring-1 ring-white/[0.03]"
              title={annotation.text}
            >
              <span className="rounded-md bg-foreground/[0.08] px-1.5 py-0.5 font-mono text-foreground">@Annotation#{annotation.id}</span>
              <span className="rounded-md bg-background/45 px-1.5 py-0.5 font-mono text-muted-foreground">
                L{formatLineRange(annotation.startLine, annotation.endLine)}
              </span>
              <span className="min-w-0 truncate text-foreground/80">{annotation.text}</span>
              <Button
                type="button"
                variant="ghost"
                size="iconSm"
                aria-label={`Remove @Annotation#${annotation.id}`}
                onClick={() => removeComposerAnnotation(annotation.id)}
                className="h-5 w-5 shrink-0 rounded-md opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {loading ? (
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Loading file...</div>
        ) : activeState?.error ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-xs text-destructive">{activeState.error}</div>
        ) : activeMode === "html" ? (
          <HtmlPreview content={activeContent} fileName={activeTab.name} />
        ) : activeMode === "markdown" ? (
          <MarkdownPreview content={activeContent} />
        ) : (
          <FileCodeContent
            content={activeContent}
            language={language}
            annotationMode={annotationMode}
            annotations={activeAnnotations}
            drafts={activeDrafts}
            onLinePick={handleLinePick}
            onDraftTextChange={updateDraftText}
            onDraftCancel={cancelDraft}
            onDraftSubmit={submitAnnotation}
          />
        )}
      </div>
    </aside>
  );
}

