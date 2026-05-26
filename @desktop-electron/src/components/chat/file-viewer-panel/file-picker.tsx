import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  File,
  Folder,
  FolderOpen,
  X,
} from "lucide-react";
import {
  isCurrentWorkspaceRequest,
  isHidden,
  isPathInside,
  normalizeDirectoryEntries,
  readWorkspaceDirectory,
  updateTreeNode,
  WORKSPACE_MISMATCH_ERROR,
  type DirEntry,
  type TreeNodeState,
} from "../../../lib/workspace-files";
import { Button } from "../../ui/button";

export function WorkspaceFilePicker({
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
      aria-label="Workspace files"
      className="absolute right-0 top-10 z-50 flex h-[min(520px,calc(100vh-160px))] w-[340px] flex-col overflow-hidden rounded-xl border border-glass-border/35 bg-popover/98 shadow-floating backdrop-blur-xl"
    >
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-glass-border/25 px-3">
        <FolderOpen className="h-3.5 w-3.5 text-primary" />
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">Workspace</span>
        <Button variant="ghost" size="iconSm" aria-label="Close file picker" onClick={onClose} className="rounded-xl">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-2">
        {!workspaceRoot ? (
          <PickerEmpty text="No workspace selected." />
        ) : loading ? (
          <div className="flex h-28 items-center justify-center text-xs text-muted-foreground">Loading files...</div>
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
