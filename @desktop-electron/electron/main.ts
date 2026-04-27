import { app, BrowserWindow, dialog, ipcMain, shell, type OpenDialogOptions } from "electron";
import { fileURLToPath } from "node:url";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { mkdir, readFile, readdir, rename, stat, writeFile } from "node:fs/promises";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

type SettingsRecord = Record<string, unknown>;

let mainWindow: BrowserWindow | null = null;
let settingsWriteQueue: Promise<void> = Promise.resolve();
const MAX_FILE_PREVIEW_BYTES = 2 * 1024 * 1024;

function desktopDebug(message: string, details?: Record<string, unknown>) {
  if (process.env.PERSONAGENT_DESKTOP_DEBUG !== "1") return;

  const suffix = details ? ` ${JSON.stringify(details)}` : "";
  console.log(`[desktop] ${message}${suffix}`);
}

function configureChromiumRuntime() {
  if (process.platform !== "linux") return;

  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch("disable-gpu");
  app.commandLine.appendSwitch("disable-gpu-compositing");
  app.commandLine.appendSwitch("disable-features", "VaapiVideoDecoder,VaapiVideoEncoder,UseChromeOSDirectVideoDecoder");
  app.commandLine.appendSwitch("log-level", "3");
  app.commandLine.appendSwitch("disable-logging");
}

configureChromiumRuntime();

function settingsPath() {
  return join(app.getPath("userData"), "personagent-settings.json");
}

async function readSettings(): Promise<SettingsRecord> {
  try {
    const raw = await readFile(settingsPath(), "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

async function writeSettings(next: SettingsRecord) {
  await mkdir(app.getPath("userData"), { recursive: true });
  const target = settingsPath();
  const temp = `${target}.${process.pid}.tmp`;
  await writeFile(temp, JSON.stringify(next, null, 2), "utf8");
  await rename(temp, target);
}

async function updateSettings(mutator: (settings: SettingsRecord) => void) {
  const write = settingsWriteQueue.then(async () => {
    const settings = await readSettings();
    mutator(settings);
    await writeSettings(settings);
  });
  settingsWriteQueue = write.catch(() => undefined);
  await write;
}

function isPathInside(candidatePath: string, rootPath: string) {
  const resolvedCandidate = resolve(candidatePath);
  const resolvedRoot = resolve(rootPath);
  const relativePath = relative(resolvedRoot, resolvedCandidate);
  return relativePath === "" || Boolean(relativePath && !relativePath.startsWith("..") && !isAbsolute(relativePath));
}

function revealMainWindow(reason: string) {
  if (!mainWindow || mainWindow.isDestroyed()) return;

  desktopDebug("reveal window", {
    reason,
    visible: mainWindow.isVisible(),
    minimized: mainWindow.isMinimized(),
    bounds: mainWindow.getBounds(),
  });

  mainWindow.setSkipTaskbar(false);
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  if (!mainWindow.isVisible()) {
    mainWindow.show();
  }
  mainWindow.moveTop();
  mainWindow.focus();

  desktopDebug("window state after reveal", {
    reason,
    visible: mainWindow.isVisible(),
    focused: mainWindow.isFocused(),
    minimized: mainWindow.isMinimized(),
    bounds: mainWindow.getBounds(),
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 940,
    minHeight: 640,
    title: "PersonAgent",
    frame: false,
    titleBarStyle: "hidden",
    backgroundColor: "#08090b",
    show: false,
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.once("ready-to-show", () => {
    revealMainWindow("ready-to-show");
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    await mainWindow.loadURL(devServerUrl);
    revealMainWindow("load-url");
    if (process.env.PERSONAGENT_DEVTOOLS === "1") {
      mainWindow.webContents.openDevTools({ mode: "detach" });
    }
    return;
  }

  await mainWindow.loadFile(join(__dirname, "../dist/index.html"));
  revealMainWindow("load-file");
}

ipcMain.handle("window:minimize", () => mainWindow?.minimize());
ipcMain.handle("window:maximize-toggle", () => {
  if (!mainWindow) return false;
  if (mainWindow.isMaximized()) {
    mainWindow.restore();
    return false;
  }
  mainWindow.maximize();
  return true;
});
ipcMain.handle("window:close", () => mainWindow?.close());
ipcMain.handle("window:is-maximized", () => mainWindow?.isMaximized() ?? false);

ipcMain.handle("settings:get", async (_event, key: string) => {
  const settings = await readSettings();
  return settings[key] ?? null;
});

ipcMain.handle("settings:set", async (_event, key: string, value: unknown) => {
  await updateSettings((settings) => {
    settings[key] = value;
  });
  return true;
});

ipcMain.handle("dialog:select-workspace", async (_event, initialPath?: string) => {
  const options: OpenDialogOptions = {
    title: "Select workspace",
    defaultPath: initialPath,
    properties: ["openDirectory", "createDirectory"],
  };
  const result = mainWindow
    ? await dialog.showOpenDialog(mainWindow, options)
    : await dialog.showOpenDialog(options);
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

ipcMain.handle("fs:read-dir", async (_event, dirPath: string, workspaceRoot?: string) => {
  const resolvedPath = resolve(dirPath);
  const resolvedWorkspace = workspaceRoot?.trim() ? resolve(workspaceRoot) : undefined;
  if (resolvedWorkspace && !isPathInside(resolvedPath, resolvedWorkspace)) {
    throw new Error(`Path '${dirPath}' is outside active workspace: ${resolvedWorkspace}`);
  }

  const entries = await readdir(resolvedPath, { withFileTypes: true });
  return entries.map((entry) => ({
    name: entry.name,
    isDirectory: entry.isDirectory(),
    path: join(resolvedPath, entry.name),
  }));
});

ipcMain.handle("fs:read-file", async (_event, filePath: string, workspaceRoot?: string) => {
  const resolvedPath = resolve(filePath);
  const resolvedWorkspace = workspaceRoot?.trim() ? resolve(workspaceRoot) : undefined;
  if (resolvedWorkspace && !isPathInside(resolvedPath, resolvedWorkspace)) {
    throw new Error(`Path '${filePath}' is outside active workspace: ${resolvedWorkspace}`);
  }

  const info = await stat(resolvedPath);
  if (!info.isFile()) {
    throw new Error(`Path is not a file: ${filePath}`);
  }
  if (info.size > MAX_FILE_PREVIEW_BYTES) {
    throw new Error(`File is too large to preview: ${filePath}`);
  }
  return readFile(resolvedPath, "utf8");
});

app.whenReady().then(async () => {
  await createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
