import { contextBridge, ipcRenderer } from "electron";

const api = {
  platform: process.platform,
  auth: {
    getHeaders: () => ipcRenderer.invoke("auth:get-headers") as Promise<Record<string, string>>,
  },
  window: {
    minimize: () => ipcRenderer.invoke("window:minimize") as Promise<void>,
    maximizeToggle: () => ipcRenderer.invoke("window:maximize-toggle") as Promise<boolean>,
    close: () => ipcRenderer.invoke("window:close") as Promise<void>,
    isMaximized: () => ipcRenderer.invoke("window:is-maximized") as Promise<boolean>,
  },
  settings: {
    get: <T>(key: string) => ipcRenderer.invoke("settings:get", key) as Promise<T | null>,
    set: (key: string, value: unknown) => ipcRenderer.invoke("settings:set", key, value) as Promise<boolean>,
  },
  dialog: {
    selectWorkspace: (initialPath?: string) =>
      ipcRenderer.invoke("dialog:select-workspace", initialPath) as Promise<{ workspaceId: string; root: string } | null>,
  },
  workspace: {
    grant: (workspaceRoot: string) =>
      ipcRenderer.invoke("workspace:grant", workspaceRoot) as Promise<{ workspaceId: string; root: string }>,
  },
  security: {
    createActionApproval: (actionKind: string, args: Record<string, unknown>) =>
      ipcRenderer.invoke("security:create-action-approval", { actionKind, arguments: args }) as Promise<{
        approval_id: string;
        action_kind: string;
        args_hash: string;
        expires_at: number;
        approval_signature: string;
      }>,
  },
  fs: {
    readDir: (dirPath: string, workspaceRoot?: string, workspaceId?: string) =>
      ipcRenderer.invoke("fs:read-dir", dirPath, workspaceRoot, workspaceId) as Promise<Array<{ name: string; isDirectory: boolean; path: string }>>,
    readFile: (filePath: string, workspaceRoot?: string, workspaceId?: string) =>
      ipcRenderer.invoke("fs:read-file", filePath, workspaceRoot, workspaceId) as Promise<string>,
  },
  terminal: {
    create: (id: string, cwd?: string, workspaceRoot?: string, workspaceId?: string) =>
      ipcRenderer.invoke("terminal:create", id, cwd, workspaceRoot, workspaceId) as Promise<boolean>,
    write: (id: string, data: string) => ipcRenderer.invoke("terminal:write", id, data) as Promise<boolean>,
    resize: (id: string, cols: number, rows: number) => ipcRenderer.invoke("terminal:resize", id, cols, rows) as Promise<boolean>,
    kill: (id: string) => ipcRenderer.invoke("terminal:kill", id) as Promise<boolean>,
    onData: (callback: (id: string, data: string) => void) => {
      const handler = (_event: unknown, payload: { id: string; data: string }) => callback(payload.id, payload.data);
      ipcRenderer.on("terminal:data", handler);
      return () => ipcRenderer.off("terminal:data", handler);
    },
    onExit: (callback: (id: string) => void) => {
      const handler = (_event: unknown, payload: { id: string }) => callback(payload.id);
      ipcRenderer.on("terminal:exit", handler);
      return () => ipcRenderer.off("terminal:exit", handler);
    },
  },
  compact: {
    openSession: (context: { conversationId: string; workspaceRoot?: string | null; title?: string | null }) =>
      ipcRenderer.invoke("compact:open-session", context) as Promise<boolean>,
    getLaunchContext: () =>
      ipcRenderer.invoke("compact:get-launch-context") as Promise<{
        conversationId: string;
        workspaceRoot?: string | null;
        title?: string | null;
      } | null>,
  },
};

contextBridge.exposeInMainWorld("personAgent", api);

export type PersonAgentDesktopApi = typeof api;
