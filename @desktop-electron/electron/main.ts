import { app, BrowserWindow, dialog, ipcMain, shell, type OpenDialogOptions } from "electron";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mkdir, readFile, writeFile } from "node:fs/promises";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

type SettingsRecord = Record<string, unknown>;

let mainWindow: BrowserWindow | null = null;

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
  await writeFile(settingsPath(), JSON.stringify(next, null, 2), "utf8");
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
    mainWindow?.show();
    mainWindow?.focus();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    await mainWindow.loadURL(devServerUrl);
    if (process.env.PERSONAGENT_DEVTOOLS === "1") {
      mainWindow.webContents.openDevTools({ mode: "detach" });
    }
    return;
  }

  await mainWindow.loadFile(join(__dirname, "../dist/index.html"));
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
  const settings = await readSettings();
  settings[key] = value;
  await writeSettings(settings);
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
