import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Code2,
  Eye,
  File,
  FileCode,
  Folder,
  FolderOpen,
  PencilLine,
  Plus,
  X,
} from "lucide-react";
import hljs from "highlight.js";
import {
  isCurrentWorkspaceRequest,
  isHidden,
  isPathInside,
  normalizeDirectoryEntries,
  normalizePath,
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
import { MarkdownContent } from "./agent-message";

export interface WorkspaceFileTab {
  name: string;
  path: string;
}

type ViewMode = "code" | "html" | "markdown";

interface FileLoadState {
  content?: string;
  error?: string;
}

interface AnnotationDraft {
  id: string;
  anchorLine: number;
  focusLine?: number;
  text: string;
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

const MAX_HIGHLIGHT_CHARS = 80_000;
const MAX_HIGHLIGHT_LINES = 1_500;

const EXT_TO_HIGHLIGHT_LANG: Record<string, string> = {
  bash: "bash",
  c: "c",
  cc: "cpp",
  cjs: "javascript",
  clj: "clojure",
  cpp: "cpp",
  cs: "csharp",
  css: "css",
  csv: "plaintext",
  cxx: "cpp",
  dart: "dart",
  diff: "diff",
  dockerfile: "dockerfile",
  ex: "elixir",
  exs: "elixir",
  go: "go",
  h: "c",
  hpp: "cpp",
  hs: "haskell",
  htm: "xml",
  html: "xml",
  java: "java",
  js: "javascript",
  json: "json",
  jsx: "javascript",
  kt: "kotlin",
  kts: "kotlin",
  less: "less",
  lua: "lua",
  md: "markdown",
  mjs: "javascript",
  php: "php",
  pl: "perl",
  ps1: "powershell",
  py: "python",
  rb: "ruby",
  rs: "rust",
  sass: "scss",
  scala: "scala",
  scss: "scss",
  sh: "bash",
  sql: "sql",
  svelte: "xml",
  swift: "swift",
  toml: "ini",
  ts: "typescript",
  tsx: "typescript",
  txt: "plaintext",
  vue: "xml",
  xml: "xml",
  yaml: "yaml",
  yml: "yaml",
  zsh: "bash",
};

const FILENAME_TO_HIGHLIGHT_LANG: Record<string, string> = {
  ".dockerignore": "plaintext",
  ".env": "ini",
  ".eslintrc": "json",
  ".gitattributes": "plaintext",
  ".gitignore": "plaintext",
  ".prettierrc": "json",
  "cmakelists.txt": "cmake",
  "dockerfile": "dockerfile",
  "gemfile": "ruby",
  "go.mod": "go",
  "go.sum": "go",
  "makefile": "makefile",
  "package-lock.json": "json",
  "package.json": "json",
  "pipfile": "toml",
  "pnpm-lock.yaml": "yaml",
  "pyproject.toml": "toml",
  "requirements.txt": "plaintext",
  "tsconfig.json": "json",
  "vite.config.js": "javascript",
  "vite.config.ts": "typescript",
  "yarn.lock": "yaml",
};

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
        <div role="tablist" aria-label="Arquivos abertos" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
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
                  aria-label={`Fechar aba ${tab.name}`}
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
                aria-label="Adicionar arquivo"
                onClick={() => setPickerOpen((value) => !value)}
                disabled={!workspaceRoot}
                className="rounded-xl"
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Adicionar arquivo</TooltipContent>
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
              aria-label="Solicitar edições"
              onClick={toggleAnnotationMode}
              className="rounded-xl"
            >
              <PencilLine className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Solicitar edições</TooltipContent>
        </Tooltip>

        <FileModeActions
          fileName={activeTab.name}
          mode={activeMode}
          onModeChange={setActiveMode}
        />

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="iconSm" aria-label="Fechar visualizador" onClick={onClose} className="rounded-xl">
              <X className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Fechar visualizador</TooltipContent>
        </Tooltip>
      </div>

      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-glass-border/20 bg-card/80 px-3 font-mono text-[11px] text-muted-foreground">
        <span className="min-w-0 flex-1 truncate">{relativePath}</span>
        {activeLineCount > 0 ? <span className="shrink-0">{activeLineCount} linhas</span> : null}
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
                aria-label={`Remover @Annotation#${annotation.id}`}
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
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Carregando arquivo...</div>
        ) : activeState?.error ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-xs text-destructive">{activeState.error}</div>
        ) : activeMode === "html" ? (
          <HtmlPreview content={activeContent} fileName={activeTab.name} />
        ) : activeMode === "markdown" ? (
          <div className="h-full overflow-y-auto bg-card/95 px-5 py-4">
            <MarkdownContent content={activeContent} />
          </div>
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

function FileModeActions({
  fileName,
  mode,
  onModeChange,
}: {
  fileName: string;
  mode: ViewMode;
  onModeChange: (mode: ViewMode) => void;
}) {
  const html = isHtmlFile(fileName);
  const markdown = isMarkdownFile(fileName);

  if (!html && !markdown) return null;

  return (
    <div className="flex shrink-0 items-center gap-1 border-l border-glass-border/25 pl-2">
      {html ? (
        <>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={mode === "html" ? "secondary" : "ghost"}
                size="iconSm"
                aria-label="Visualizar HTML"
                onClick={() => onModeChange("html")}
                className="rounded-xl"
              >
                <Eye className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Visualizar HTML</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={mode === "code" ? "secondary" : "ghost"}
                size="iconSm"
                aria-label="Ver código"
                onClick={() => onModeChange("code")}
                className="rounded-xl"
              >
                <Code2 className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Ver código</TooltipContent>
          </Tooltip>
        </>
      ) : null}

      {markdown ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={mode === "markdown" ? "secondary" : "ghost"}
              size="iconSm"
              aria-label="Visualização markdown"
              onClick={() => onModeChange(mode === "markdown" ? "code" : "markdown")}
              className="rounded-xl"
            >
              <BookOpen className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Visualização markdown</TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}

function AnnotationInputBar({
  range,
  draft,
  value,
  onChange,
  onCancel,
  onSubmit,
}: {
  range: { start: number; end: number };
  draft: AnnotationDraft;
  value: string;
  onChange: (value: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const rangeLabel = formatLineRange(range.start, range.end);
  return (
    <form
      className="my-1 max-w-[520px] rounded-2xl border border-glass-border/40 bg-card/75 p-2 shadow-floating ring-1 ring-white/[0.04] backdrop-blur-2xl"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      onClick={(event) => event.stopPropagation()}
    >
      <div className="mb-1.5 flex items-center gap-2 px-1 font-mono text-[11px] text-muted-foreground">
        <span className="rounded-md bg-foreground/[0.08] px-1.5 py-0.5 text-foreground">L{rangeLabel}</span>
        <span className="text-muted-foreground/60">#{draft.id.replace("draft-", "")}</span>
      </div>
      <div className="flex items-end gap-2">
        <textarea
          value={value}
          rows={1}
          placeholder="Write a Annotation..."
          onChange={(event) => onChange(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
            if (event.key === "Escape") {
              event.preventDefault();
              onCancel();
            }
          }}
          className="max-h-24 min-h-9 min-w-0 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/75"
          autoFocus
        />
        <Button
          variant="ghost"
          size="iconSm"
          type="button"
          aria-label={`Cancelar seleção ${rangeLabel}`}
          onClick={onCancel}
          className="rounded-xl"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
        <Button size="iconSm" type="submit" aria-label={`Adicionar annotation ${rangeLabel}`} disabled={!value.trim()} className="rounded-xl">
          <ArrowUp className="h-3.5 w-3.5" />
        </Button>
      </div>
    </form>
  );
}

function FileCodeContent({
  content,
  language,
  annotationMode,
  annotations,
  drafts,
  onLinePick,
  onDraftTextChange,
  onDraftCancel,
  onDraftSubmit,
}: {
  content: string;
  language: string;
  annotationMode: boolean;
  annotations: Array<Pick<FileAnnotation, "id" | "startLine" | "endLine" | "text">>;
  drafts: AnnotationDraft[];
  onLinePick: (lineNumber: number) => void;
  onDraftTextChange: (draftId: string, value: string) => void;
  onDraftCancel: (draftId: string) => void;
  onDraftSubmit: (draftId: string) => void;
}) {
  const lines = useMemo(() => splitLines(content), [content]);
  const highlightedLines = useMemo(() => {
    const html = highlightContent(content, language);
    return splitHighlightedLines(html);
  }, [content, language]);
  const gutterWidth = String(Math.max(lines.length, 1)).length;

  return (
    <div className={cn("file-viewer-code h-full overflow-auto bg-card/95", annotationMode && "cursor-zoom-in")}>
      <table className="w-max min-w-full border-collapse font-mono text-xs leading-6">
        <tbody>
          {highlightedLines.map((lineHtml, index) => {
            const lineNumber = index + 1;
            const lineAnnotations = annotations.filter((annotation) => lineInRange(lineNumber, annotation.startLine, annotation.endLine));
            const startAnnotations = lineAnnotations.filter((annotation) => annotation.startLine === lineNumber);
            const completedDraftsEndingHere = drafts.filter((draft) => {
              if (draft.focusLine === undefined) return false;
              const range = normalizeLineRange(draft.anchorLine, draft.focusLine);
              return range.end === lineNumber;
            });
            const selected = drafts.some((draft) => {
              const range = normalizeLineRange(draft.anchorLine, draft.focusLine ?? draft.anchorLine);
              return lineInRange(lineNumber, range.start, range.end);
            });
            const annotated = lineAnnotations.length > 0;
            return (
              <Fragment key={index}>
                <tr
                  className={cn(
                    "hover:bg-glass/30",
                    annotationMode && !annotated && "cursor-zoom-in",
                    annotated && "bg-foreground/[0.035]",
                    selected && "bg-foreground/[0.07]",
                  )}
                >
                  <td
                    className="select-none border-r border-glass-border/20 bg-background/50 px-2 text-right align-top text-muted-foreground/40"
                    style={{ minWidth: `${gutterWidth + 3}ch`, width: "1%" }}
                  >
                    <button
                      type="button"
                      aria-label={`Selecionar linha ${lineNumber}`}
                      disabled={!annotationMode || annotated}
                      onClick={() => onLinePick(lineNumber)}
                      className={cn(
                        "w-full rounded-sm px-1 text-right disabled:cursor-default",
                        annotationMode && !annotated && "cursor-zoom-in hover:bg-foreground/[0.08] hover:text-foreground",
                        annotated && "cursor-not-allowed text-muted-foreground/55",
                        selected && "text-foreground",
                      )}
                    >
                      {lineNumber}
                    </button>
                  </td>
                  <td
                    className={cn("whitespace-pre px-2 align-top text-foreground", annotationMode && !annotated && "cursor-zoom-in")}
                    onClick={() => annotationMode && !annotated && onLinePick(lineNumber)}
                  >
                    {startAnnotations.map((annotation) => (
                      <span
                        key={annotation.id}
                        className="mr-2 rounded-md border border-glass-border/35 bg-foreground/[0.055] px-1.5 py-0.5 font-sans text-[10px] leading-4 text-muted-foreground"
                      >
                        @Annotation#{annotation.id}
                      </span>
                    ))}
                    <span dangerouslySetInnerHTML={{ __html: lineHtml || "&nbsp;" }} />
                  </td>
                </tr>
                {completedDraftsEndingHere.map((draft) => {
                  const range = normalizeLineRange(draft.anchorLine, draft.focusLine ?? draft.anchorLine);
                  return (
                    <tr key={draft.id} className="bg-foreground/[0.045]">
                      <td
                        className="border-r border-glass-border/20 bg-background/50 align-top"
                        style={{ minWidth: `${gutterWidth + 3}ch`, width: "1%" }}
                      />
                      <td className="px-2 pb-3 pt-1 align-top">
                        <AnnotationInputBar
                          draft={draft}
                          range={range}
                          value={draft.text}
                          onChange={(value) => onDraftTextChange(draft.id, value)}
                          onCancel={() => onDraftCancel(draft.id)}
                          onSubmit={() => onDraftSubmit(draft.id)}
                        />
                      </td>
                    </tr>
                  );
                })}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HtmlPreview({ content, fileName }: { content: string; fileName: string }) {
  return (
    <iframe
      title={`Preview ${fileName}`}
      srcDoc={content}
      sandbox="allow-scripts"
      className="h-full w-full border-0 bg-white"
    />
  );
}

function WorkspaceFilePicker({
  baseUrl,
  workspaceRoot,
  onPick,
  onClose,
}: {
  baseUrl: string;
  workspaceRoot?: string;
  onPick: (entry: DirEntry) => void;
  onClose: () => void;
}) {
  const [tree, setTree] = useState<TreeNodeState[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeWorkspaceRef = useRef<string | undefined>(workspaceRoot);
  const requestVersionRef = useRef(0);

  useEffect(() => {
    activeWorkspaceRef.current = workspaceRoot;
  }, [workspaceRoot]);

  const loadDir = useCallback(async (path: string, activeWorkspace: string): Promise<TreeNodeState[]> => {
    const entries = await readWorkspaceDirectory(baseUrl, path, activeWorkspace);
    const visibleEntries = normalizeDirectoryEntries(entries, path, activeWorkspace).filter((entry) => !isHidden(entry.name));
    visibleEntries.sort((a, b) => {
      if (a.isDirectory === b.isDirectory) return a.name.localeCompare(b.name);
      return a.isDirectory ? -1 : 1;
    });
    return visibleEntries.map((entry) => ({ entry }));
  }, [baseUrl]);

  useEffect(() => {
    if (!workspaceRoot) return;
    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    const activeWorkspace = workspaceRoot;

    setLoading(true);
    setError(null);
    setTree([]);
    setExpanded(new Set([activeWorkspace]));

    loadDir(activeWorkspace, activeWorkspace)
      .then((nodes) => {
        if (!isCurrentWorkspaceRequest(requestVersionRef.current, requestVersion, activeWorkspaceRef.current, activeWorkspace)) return;
        setTree(nodes);
      })
      .catch((err) => {
        if (!isCurrentWorkspaceRequest(requestVersionRef.current, requestVersion, activeWorkspaceRef.current, activeWorkspace)) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (isCurrentWorkspaceRequest(requestVersionRef.current, requestVersion, activeWorkspaceRef.current, activeWorkspace)) {
          setLoading(false);
        }
      });

    return () => {
      requestVersionRef.current += 1;
    };
  }, [loadDir, workspaceRoot]);

  const toggleExpand = useCallback(async (node: TreeNodeState) => {
    if (!workspaceRoot) return;
    const path = node.entry.path;
    if (!isPathInside(path, workspaceRoot)) {
      setError(WORKSPACE_MISMATCH_ERROR);
      return;
    }
    const next = new Set(expanded);
    if (next.has(path)) {
      next.delete(path);
      setExpanded(next);
      return;
    }
    if (node.entry.isDirectory && !node.children) {
      const requestVersion = requestVersionRef.current;
      setTree((current) => updateTreeNode(current, path, (n) => ({ ...n, loading: true })));
      try {
        const children = await loadDir(path, workspaceRoot);
        if (!isCurrentWorkspaceRequest(requestVersionRef.current, requestVersion, activeWorkspaceRef.current, workspaceRoot)) return;
        setTree((current) => updateTreeNode(current, path, (n) => ({ ...n, children, loading: false })));
      } catch (err) {
        if (!isCurrentWorkspaceRequest(requestVersionRef.current, requestVersion, activeWorkspaceRef.current, workspaceRoot)) return;
        setTree((current) => updateTreeNode(current, path, (n) => ({ ...n, loading: false })));
        setError(err instanceof Error ? err.message : String(err));
      }
    }
    next.add(path);
    setExpanded(next);
  }, [expanded, loadDir, workspaceRoot]);

  return (
    <div
      role="dialog"
      aria-label="Arquivos do workspace"
      className="absolute right-0 top-10 z-50 flex h-[min(520px,calc(100vh-160px))] w-[340px] flex-col overflow-hidden rounded-xl border border-glass-border/35 bg-popover/98 shadow-floating backdrop-blur-xl"
    >
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-glass-border/25 px-3">
        <FolderOpen className="h-3.5 w-3.5 text-primary" />
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">Workspace</span>
        <Button variant="ghost" size="iconSm" aria-label="Fechar seleção de arquivo" onClick={onClose} className="rounded-xl">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-2">
        {!workspaceRoot ? (
          <PickerEmpty text="Nenhum workspace selecionado." />
        ) : loading ? (
          <div className="flex h-28 items-center justify-center text-xs text-muted-foreground">Carregando arquivos...</div>
        ) : error ? (
          <PickerEmpty text={error} />
        ) : (
          <ul className="space-y-0.5">
            {tree.map((node) => (
              <PickerNode key={node.entry.path} node={node} expanded={expanded} depth={0} onPick={onPick} onToggle={toggleExpand} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function PickerNode({
  node,
  expanded,
  depth,
  onPick,
  onToggle,
}: {
  node: TreeNodeState;
  expanded: Set<string>;
  depth: number;
  onPick: (entry: DirEntry) => void;
  onToggle: (node: TreeNodeState) => void;
}) {
  const isDir = node.entry.isDirectory;
  const isExpanded = expanded.has(node.entry.path);
  const paddingLeft = depth * 14 + 6;

  return (
    <li>
      <button
        type="button"
        onClick={() => (isDir ? onToggle(node) : onPick(node.entry))}
        className="flex w-full min-w-0 items-center gap-1.5 rounded-lg px-1.5 py-1 text-left text-xs text-foreground transition-colors hover:bg-accent/65"
        style={{ paddingLeft }}
      >
        {isDir ? (
          <span className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground/80">
            {node.loading ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-muted-foreground" />
            ) : isExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </span>
        ) : (
          <span className="h-4 w-4 shrink-0" />
        )}
        {isDir ? (
          isExpanded ? <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-400" /> : <Folder className="h-3.5 w-3.5 shrink-0 text-amber-400" />
        ) : (
          <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground/75" />
        )}
        <span className="min-w-0 flex-1 truncate">{node.entry.name}</span>
      </button>

      {isDir && isExpanded && node.children ? (
        <ul className="space-y-0.5">
          {node.children.map((child) => (
            <PickerNode key={child.entry.path} node={child} expanded={expanded} depth={depth + 1} onPick={onPick} onToggle={onToggle} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function PickerEmpty({ text }: { text: string }) {
  return (
    <div className="flex h-28 items-center justify-center px-4 text-center text-xs text-muted-foreground">
      {text}
    </div>
  );
}

function highlightContent(content: string, language: string) {
  if (shouldSkipHighlight(content, language)) return escapeHtml(content);
  try {
    const lang = hljs.getLanguage(language) ? language : "plaintext";
    return hljs.highlight(content, { language: lang }).value;
  } catch {
    return escapeHtml(content);
  }
}

function shouldSkipHighlight(content: string, language: string) {
  if (language === "plaintext") return true;
  if (content.length > MAX_HIGHLIGHT_CHARS) return true;
  if (splitLines(content).length > MAX_HIGHLIGHT_LINES) return true;
  return false;
}

function splitHighlightedLines(html: string): string[] {
  const raw = html.split("\n");
  const result: string[] = [];
  const openSpans: string[] = [];

  for (const line of raw) {
    const prefix = openSpans.join("");
    const enriched = prefix + line;
    const opens = line.match(/<span[^>]*>/g) || [];
    const closes = line.match(/<\/span>/g) || [];

    for (const tag of opens) openSpans.push(tag);
    for (let index = 0; index < closes.length; index += 1) openSpans.pop();

    result.push(enriched + "</span>".repeat(openSpans.length));
  }

  return result;
}

function splitLines(content: string) {
  return content.length === 0 ? [""] : content.replace(/\r\n/g, "\n").split("\n");
}

function escapeHtml(text: string) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function languageFromFilename(fileName: string) {
  const lower = fileName.toLowerCase();
  const known = FILENAME_TO_HIGHLIGHT_LANG[lower];
  if (known) return hljs.getLanguage(known) ? known : "plaintext";
  const ext = lower.split(".").pop();
  const lang = ext ? EXT_TO_HIGHLIGHT_LANG[ext] : undefined;
  return lang && hljs.getLanguage(lang) ? lang : "plaintext";
}

function isHtmlFile(fileName: string) {
  const lower = fileName.toLowerCase();
  return lower.endsWith(".html") || lower.endsWith(".htm");
}

function isMarkdownFile(fileName: string) {
  const lower = fileName.toLowerCase();
  return lower.endsWith(".md") || lower.endsWith(".mdx") || lower === "readme";
}

function normalizeLineRange(first: number, second: number) {
  return {
    start: Math.min(first, second),
    end: Math.max(first, second),
  };
}

function lineInRange(line: number, start: number, end: number) {
  return line >= start && line <= end;
}

function rangesOverlap(first: { start: number; end: number }, second: { start: number; end: number }) {
  return first.start <= second.end && second.start <= first.end;
}

function formatLineRange(start: number, end: number) {
  return start === end ? String(start) : `${start}-${end}`;
}

function selectedLinesExcerpt(content: string, startLine: number, endLine: number) {
  const lines = splitLines(content);
  return lines
    .slice(startLine - 1, endLine)
    .map((line, index) => `${startLine + index}: ${line}`)
    .join("\n");
}

function defaultViewMode(fileName: string): ViewMode {
  return isHtmlFile(fileName) ? "html" : "code";
}

function compactWorkspacePath(path: string, workspaceRoot?: string) {
  if (!workspaceRoot) return path;
  const normalizedPath = normalizePath(path);
  const normalizedRoot = normalizePath(workspaceRoot);
  if (normalizedPath === normalizedRoot) return ".";
  if (normalizedPath.startsWith(`${normalizedRoot}/`)) {
    return normalizedPath.slice(normalizedRoot.length + 1);
  }
  return path;
}

function filterRecord<T>(record: Record<string, T>, allowed: Set<string>) {
  const next: Record<string, T> = {};
  for (const [key, value] of Object.entries(record)) {
    if (allowed.has(key)) next[key] = value;
  }
  return next;
}
