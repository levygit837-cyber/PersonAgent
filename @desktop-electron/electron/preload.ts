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
  },
};

contextBridge.exposeInMainWorld("personAgent", api);

export type PersonAgentDesktopApi = typeof api;
