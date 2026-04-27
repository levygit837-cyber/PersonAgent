import { useEffect, useState, useCallback, useRef } from "react";
import {
  ChevronDown,
  ChevronRight,
  File,
  Folder,
  FolderOpen,
  LayoutGrid,
  PanelRightClose,
} from "lucide-react";
import { listWorkspaceFiles } from "../../api/client";
import { workspaceName } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

interface DirEntry {
  name: string;
  isDirectory: boolean;
  path: string;
}

interface TreeNodeState {
  entry: DirEntry;
  children?: TreeNodeState[];
  loading?: boolean;
}

const DEVICON_BASE = "https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons";
const WORKSPACE_MISMATCH_ERROR = "A listagem recebida não pertence ao workspace ativo.";

const EXT_TO_LANG: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  py: "python",
  java: "java",
  kt: "kotlin",
  kts: "kotlin",
  go: "go",
  rs: "rust",
  cpp: "cplusplus",
  cc: "cplusplus",
  cxx: "cplusplus",
  hpp: "cplusplus",
  c: "c",
  h: "c",
  cs: "csharp",
  rb: "ruby",
  php: "php",
  swift: "swift",
  scala: "scala",
  r: "r",
  dart: "dart",
  lua: "lua",
  pl: "perl",
  perl: "perl",
  hs: "haskell",
  erl: "erlang",
  ex: "elixir",
  exs: "elixir",
  clj: "clojure",
  fs: "fsharp",
  fsharp: "fsharp",
  groovy: "groovy",
  ml: "ocaml",
  ps1: "powershell",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  dockerfile: "docker",
  yaml: "yaml",
  yml: "yaml",
  json: "json",
  xml: "xml",
  html: "html5",
  htm: "html5",
  css: "css3",
  scss: "sass",
  sass: "sass",
  less: "less",
  sql: "mysql",
  md: "markdown",
  vue: "vuejs",
  svelte: "svelte",
  gitignore: "git",
  gitattributes: "git",
  vite: "vitejs",
  webpack: "webpack",
  npm: "npm",
  yarn: "yarn",
  pnpm: "pnpm",
  prisma: "prisma",
  gradle: "gradle",
  maven: "maven",
  jenkins: "jenkins",
  nginx: "nginx",
  apache: "apache",
  redis: "redis",
  mongo: "mongodb",
  postgres: "postgresql",
  sqlite: "sqlite",
  graphql: "graphql",
  terraform: "terraform",
  ansible: "ansible",
  kubernetes: "kubernetes",
  julia: "julia",
  nim: "nim",
  crystal: "crystal",
  vala: "vala",
  zig: "zig",
  v: "vlang",
  solidity: "solidity",
 vy: "python",
};

const FILENAME_TO_LANG: Record<string, string> = {
  "dockerfile": "docker",
  "makefile": "cmake",
  "cmakelists.txt": "cmake",
  "package.json": "npm",
  "package-lock.json": "npm",
  "yarn.lock": "yarn",
  "pnpm-lock.yaml": "pnpm",
  "tsconfig.json": "typescript",
  "jsconfig.json": "javascript",
  "vite.config.ts": "vitejs",
  "vite.config.js": "vitejs",
  "webpack.config.js": "webpack",
  "rollup.config.js": "rollupjs",
  ".gitignore": "git",
  ".gitattributes": "git",
  ".dockerignore": "docker",
  ".eslintrc": "eslint",
  ".prettierrc": "prettier",
  "cargo.toml": "rust",
  "go.mod": "go",
  "go.sum": "go",
  "requirements.txt": "python",
  "pyproject.toml": "python",
  "setup.py": "python",
  "pipfile": "python",
  "gemfile": "ruby",
  "composer.json": "composer",
  "build.gradle": "gradle",
  "pom.xml": "maven",
  "CMakeLists.txt": "cmake",
};

function getLangKey(filename: string): string | null {
  const lower = filename.toLowerCase();
  if (FILENAME_TO_LANG[lower]) return FILENAME_TO_LANG[lower];
  const ext = lower.split(".").pop();
  if (ext && EXT_TO_LANG[ext]) return EXT_TO_LANG[ext];
  return null;
}

function getFileIconUrl(filename: string): string | null {
  const lang = getLangKey(filename);
  if (!lang) return null;
  return `${DEVICON_BASE}/${lang}/${lang}-original.svg`;
}

function isHidden(name: string): boolean {
  return name.startsWith(".") && name !== ".gitignore" && name !== ".dockerignore" && name !== ".eslintrc" && name !== ".prettierrc" && name !== ".gitattributes";
}

async function readDirectory(dirPath: string, baseUrl: string, workspaceRoot?: string): Promise<DirEntry[]> {
  if (window.personAgent?.fs?.readDir) {
    return window.personAgent.fs.readDir(dirPath, workspaceRoot);
  }
  return listWorkspaceFiles(baseUrl, dirPath, workspaceRoot);
}

interface WorkspacePanelProps {
  visible: boolean;
  onClose: () => void;
  workspaceRoot?: string;
}

function useWorkspaceBaseUrl() {
  return useAppStore((state) => state.baseUrl);
}

export function WorkspacePanel({ visible, onClose, workspaceRoot }: WorkspacePanelProps) {
  const [tree, setTree] = useState<TreeNodeState[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const baseUrl = useWorkspaceBaseUrl();
  const activeWorkspaceRef = useRef<string | undefined>(workspaceRoot);
  const requestVersionRef = useRef(0);

  useEffect(() => {
    activeWorkspaceRef.current = workspaceRoot;
  }, [workspaceRoot]);

  const loadDir = useCallback(async (path: string, activeWorkspace: string): Promise<TreeNodeState[]> => {
    const entries = await readDirectory(path, baseUrl, activeWorkspace);
    const visibleEntries = normalizeDirectoryEntries(entries, path, activeWorkspace).filter((e) => !isHidden(e.name));
    visibleEntries.sort((a, b) => {
      if (a.isDirectory === b.isDirectory) return a.name.localeCompare(b.name);
      return a.isDirectory ? -1 : 1;
    });
    return visibleEntries.map((entry) => ({ entry }));
  }, [baseUrl]);

  useEffect(() => {
    requestVersionRef.current += 1;
    setTree([]);
    setExpanded(new Set());
    setError(null);
    setLoading(false);
  }, [workspaceRoot]);

  useEffect(() => {
    if (!visible || !workspaceRoot) return;
    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    const activeWorkspace = workspaceRoot;

    setLoading(true);
    setError(null);
    setTree([]);
    setExpanded(new Set());

    loadDir(activeWorkspace, activeWorkspace)
      .then((nodes) => {
        if (!isCurrentWorkspaceRequest(requestVersionRef.current, requestVersion, activeWorkspaceRef.current, activeWorkspace)) return;
        setTree(nodes);
        setExpanded(new Set([activeWorkspace]));
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
  }, [visible, workspaceRoot, loadDir]);

  const toggleExpand = useCallback(
    async (node: TreeNodeState) => {
      const path = node.entry.path;
      const activeWorkspace = activeWorkspaceRef.current;
      if (!activeWorkspace || !isPathInside(path, activeWorkspace)) {
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
          const children = await loadDir(path, activeWorkspace);
          if (!isCurrentWorkspaceRequest(requestVersionRef.current, requestVersion, activeWorkspaceRef.current, activeWorkspace)) return;
          setTree((current) => updateTreeNode(current, path, (n) => ({ ...n, children, loading: false })));
        } catch (err) {
          if (!isCurrentWorkspaceRequest(requestVersionRef.current, requestVersion, activeWorkspaceRef.current, activeWorkspace)) return;
          setTree((current) => updateTreeNode(current, path, (n) => ({ ...n, loading: false })));
          setError(err instanceof Error ? err.message : String(err));
        }
      }
      next.add(path);
      setExpanded(next);
    },
    [expanded, loadDir]
  );

  const label = workspaceRoot ? workspaceName(workspaceRoot) : "Workspace";

  return (
    <aside className="flex h-full w-[min(320px,calc(100vw-64px))] flex-col bg-popover">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-glass-border/25 bg-card/80 px-3">
        <LayoutGrid className="h-4 w-4 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">Workspace</div>
          <div className="truncate text-[11px] text-muted-foreground">{label}</div>
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="iconSm" aria-label="Fechar workspace" onClick={onClose}>
              <PanelRightClose className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Fechar</TooltipContent>
        </Tooltip>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1 py-2">
        {!workspaceRoot ? (
          <EmptyState text="Nenhum workspace selecionado." />
        ) : loading ? (
          <div className="flex min-h-[120px] items-center justify-center text-xs text-muted-foreground">
            Carregando diretório...
          </div>
        ) : error ? (
          <EmptyState text={error} />
        ) : (
          <ul className="space-y-0.5">
            {tree.map((node) => (
              <TreeNodeItem key={node.entry.path} node={node} expanded={expanded} onToggle={toggleExpand} depth={0} />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function TreeNodeItem({
  node,
  expanded,
  onToggle,
  depth,
}: {
  node: TreeNodeState;
  expanded: Set<string>;
  onToggle: (node: TreeNodeState) => void;
  depth: number;
}) {
  const isExpanded = expanded.has(node.entry.path);
  const isDir = node.entry.isDirectory;
  const paddingLeft = depth * 14 + 4;

  const iconUrl = !isDir ? getFileIconUrl(node.entry.name) : null;

  return (
    <li>
      <button
        type="button"
        onClick={() => isDir && onToggle(node)}
        className="group flex w-full min-w-0 items-center gap-1 rounded-lg px-1.5 py-1 text-left text-xs transition-colors hover:bg-accent/60"
        style={{ paddingLeft: `${paddingLeft}px` }}
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
          isExpanded ? (
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-400" />
          ) : (
            <Folder className="h-3.5 w-3.5 shrink-0 text-amber-400" />
          )
        ) : (
          <FileIcon url={iconUrl} />
        )}

        <span className="min-w-0 flex-1 truncate text-foreground">{node.entry.name}</span>
      </button>

      {isDir && isExpanded && node.children ? (
        <ul className="space-y-0.5">
          {node.children.map((child) => (
            <TreeNodeItem key={child.entry.path} node={child} expanded={expanded} onToggle={onToggle} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function FileIcon({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />;
  }
  return (
    <img
      src={url}
      alt=""
      className="h-3.5 w-3.5 shrink-0 object-contain"
      onError={() => setFailed(true)}
    />
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex min-h-[120px] flex-col items-center justify-center gap-2 px-4 text-center text-xs text-muted-foreground">
      <FolderOpen className="h-6 w-6 text-muted-foreground/30" />
      <span>{text}</span>
    </div>
  );
}

function normalizeDirectoryEntries(entries: DirEntry[], requestedPath: string, workspaceRoot: string): DirEntry[] {
  if (!Array.isArray(entries)) {
    throw new Error("Resposta inválida ao listar o workspace.");
  }

  const normalized: DirEntry[] = [];
  for (const entry of entries) {
    if (!isDirEntry(entry) || !isPathInside(entry.path, workspaceRoot) || !isPathInside(entry.path, requestedPath)) {
      throw new Error(WORKSPACE_MISMATCH_ERROR);
    }
    normalized.push({
      name: entry.name.trim(),
      isDirectory: entry.isDirectory,
      path: entry.path.trim(),
    });
  }
  return normalized;
}

function isDirEntry(value: unknown): value is DirEntry {
  if (!value || typeof value !== "object") return false;
  const entry = value as Partial<DirEntry>;
  return typeof entry.name === "string" && entry.name.trim().length > 0
    && typeof entry.path === "string" && entry.path.trim().length > 0
    && typeof entry.isDirectory === "boolean";
}

function normalizePath(path: string) {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return normalized || "/";
}

function isPathInside(path: string, root: string) {
  const normalizedPath = normalizePath(path);
  const normalizedRoot = normalizePath(root);
  if (normalizedRoot === "/") return normalizedPath.startsWith("/");
  return normalizedPath === normalizedRoot || normalizedPath.startsWith(`${normalizedRoot}/`);
}

function isCurrentWorkspaceRequest(
  currentVersion: number,
  requestVersion: number,
  currentWorkspace: string | undefined,
  requestWorkspace: string,
) {
  return currentVersion === requestVersion && currentWorkspace === requestWorkspace;
}

function updateTreeNode(
  nodes: TreeNodeState[],
  path: string,
  updater: (node: TreeNodeState) => TreeNodeState
): TreeNodeState[] {
  return nodes.map((node) => {
    if (node.entry.path === path) {
      return updater(node);
    }
    if (node.children) {
      return { ...node, children: updateTreeNode(node.children, path, updater) };
    }
    return node;
  });
}
