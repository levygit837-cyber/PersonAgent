import { listWorkspaceFiles, readWorkspaceFile } from "../api/client";

export interface DirEntry {
  name: string;
  isDirectory: boolean;
  path: string;
}

export interface TreeNodeState {
  entry: DirEntry;
  children?: TreeNodeState[];
  loading?: boolean;
}

export const WORKSPACE_MISMATCH_ERROR = "A listagem recebida não pertence ao workspace ativo.";

export async function readWorkspaceDirectory(
  baseUrl: string,
  dirPath: string,
  workspaceRoot?: string,
): Promise<DirEntry[]> {
  if (window.personAgent?.fs?.readDir) {
    return window.personAgent.fs.readDir(dirPath, workspaceRoot);
  }
  return listWorkspaceFiles(baseUrl, dirPath, workspaceRoot);
}

export async function readWorkspaceTextFile(
  baseUrl: string,
  filePath: string,
  workspaceRoot?: string,
): Promise<string> {
  if (window.personAgent?.fs?.readFile) {
    return window.personAgent.fs.readFile(filePath, workspaceRoot);
  }
  const response = await readWorkspaceFile(baseUrl, filePath, workspaceRoot);
  return response.content;
}

export function normalizeDirectoryEntries(entries: DirEntry[], requestedPath: string, workspaceRoot: string): DirEntry[] {
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

export function normalizePath(path: string) {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return normalized || "/";
}

export function isPathInside(path: string, root: string) {
  const normalizedPath = normalizePath(path);
  const normalizedRoot = normalizePath(root);
  if (normalizedRoot === "/") return normalizedPath.startsWith("/");
  return normalizedPath === normalizedRoot || normalizedPath.startsWith(`${normalizedRoot}/`);
}

export function isHidden(name: string): boolean {
  return name.startsWith(".") && name !== ".gitignore" && name !== ".dockerignore" && name !== ".eslintrc" && name !== ".prettierrc" && name !== ".gitattributes";
}

export function isCurrentWorkspaceRequest(
  currentVersion: number,
  requestVersion: number,
  currentWorkspace: string | undefined,
  requestWorkspace: string,
) {
  return currentVersion === requestVersion && currentWorkspace === requestWorkspace;
}

export function updateTreeNode(
  nodes: TreeNodeState[],
  path: string,
  updater: (node: TreeNodeState) => TreeNodeState,
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

function isDirEntry(value: unknown): value is DirEntry {
  if (!value || typeof value !== "object") return false;
  const entry = value as Partial<DirEntry>;
  return typeof entry.name === "string" && entry.name.trim().length > 0
    && typeof entry.path === "string" && entry.path.trim().length > 0
    && typeof entry.isDirectory === "boolean";
}
