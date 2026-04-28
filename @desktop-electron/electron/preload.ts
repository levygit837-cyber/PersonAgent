import { contextBridge, ipcRenderer } from "electron";

const api = {
  platform: process.platform,
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
      ipcRenderer.invoke("dialog:select-workspace", initialPath) as Promise<string | null>,
  },
  fs: {
    readDir: (dirPath: string, workspaceRoot?: string) =>
      ipcRenderer.invoke("fs:read-dir", dirPath, workspaceRoot) as Promise<Array<{ name: string; isDirectory: boolean; path: string }>>,
    readFile: (filePath: string, workspaceRoot?: string) =>
      ipcRenderer.invoke("fs:read-file", filePath, workspaceRoot) as Promise<string>,
  },
  terminal: {
    create: (id: string, cwd?: string) => ipcRenderer.invoke("terminal:create", id, cwd) as Promise<boolean>,
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
};

contextBridge.exposeInMainWorld("personAgent", api);

export type PersonAgentDesktopApi = typeof api;
