import { app, BrowserWindow, dialog, ipcMain, shell, type OpenDialogOptions, type IpcMainInvokeEvent } from "electron";
import { fileURLToPath } from "node:url";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { createHash, createHmac, randomBytes } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { mkdir, readFile, readdir, rename, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import * as pty from "node-pty";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

type SettingsRecord = Record<string, unknown>;
type CompactLaunchContext = {
  conversationId: string;
  workspaceRoot?: string | null;
  title?: string | null;
};
type ActionApprovalRequest = {
  actionKind: string;
  arguments: Record<string, unknown>;
};

let mainWindow: BrowserWindow | null = null;
const compactWindows = new Map<string, BrowserWindow>();
const compactContextsByWebContentsId = new Map<number, CompactLaunchContext>();
const workspaceGrants = new Map<string, string>();
let settingsWriteQueue: Promise<void> = Promise.resolve();
const MAX_FILE_PREVIEW_BYTES = 2 * 1024 * 1024;
const ALLOWED_SETTINGS_KEYS = new Set([
  "personagent_base_url",
  "personagent_selected_workspace",
  "personagent_recent_workspaces",
  "personagent_conv_workspace_map",
]);
const ACTION_APPROVAL_TTL_SECONDS = 300;
const ALLOWED_ACTION_APPROVALS = new Map([
  ["workspace.git_commit", "Create git commit"],
  ["workspace.git_push", "Push git branch"],
  ["workspace.git_pr", "Open pull request"],
]);

// Terminal PTY manager
const terminals = new Map<string, pty.IPty>();

function getDefaultShell(): string {
  if (process.platform === "win32") return process.env.COMSPEC || "cmd.exe";
  return process.env.SHELL || "/bin/bash";
}

function createTerminalInstance(id: string, cwd?: string) {
  const shell = getDefaultShell();
  const terminalEnv = safeTerminalEnv();
  const term = pty.spawn(shell, [], {
    name: "xterm-color",
    cwd: cwd || process.env.HOME || process.cwd(),
    env: terminalEnv,
  });

  term.onData((data) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("terminal:data", { id, data });
    }
  });

  term.onExit(() => {
    terminals.delete(id);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("terminal:exit", { id });
    }
  });

  terminals.set(id, term);
  return term;
}

function safeTerminalEnv(): { [key: string]: string } {
  const keys = ["HOME", "PATH", "SHELL", "TERM", "LANG", "LC_ALL", "USER", "LOGNAME"];
  const env: { [key: string]: string } = {};
  for (const key of keys) {
    const value = process.env[key];
    if (typeof value === "string") env[key] = value;
  }
  env.TERM = env.TERM || "xterm-256color";
  return env;
}

function localAuthTokenPath() {
  return localEnvValue("PERSONAGENT_LOCAL_AUTH_TOKEN_PATH") || join(homedir(), ".cache", "personagent", "local_auth_token");
}

function localAuthHeaders() {
  const configuredToken = localEnvValue("PERSONAGENT_LOCAL_AUTH_TOKEN");
  if (configuredToken) {
    return {
      Authorization: `Bearer ${configuredToken}`,
      "X-PersonAgent-Client": "desktop-electron",
    };
  }
  const path = localAuthTokenPath();
  if (!existsSync(path)) return {};
  const token = readFileSync(path, "utf8").trim();
  if (!token) return {};
  return {
    Authorization: `Bearer ${token}`,
    "X-PersonAgent-Client": "desktop-electron",
  };
}

function actionApprovalSecretPath() {
  return localEnvValue("PERSONAGENT_ACTION_APPROVAL_SECRET_PATH") || join(homedir(), ".cache", "personagent", "action_approval_secret");
}

function actionApprovalSecret() {
  const configuredSecret = localEnvValue("PERSONAGENT_ACTION_APPROVAL_SECRET");
  if (configuredSecret) return configuredSecret;
  return readOrCreateSecret(actionApprovalSecretPath());
}

function readOrCreateSecret(path: string) {
  if (existsSync(path)) {
    const existing = readFileSync(path, "utf8").trim();
    if (existing) {
      chmodPrivate(path, 0o600);
      return existing;
    }
  }
  mkdirSync(dirname(path), { recursive: true });
  chmodPrivate(dirname(path), 0o700);
  const secret = randomBytes(48).toString("base64url");
  writeFileSync(path, `${secret}\n`, "utf8");
  chmodPrivate(path, 0o600);
  return secret;
}

function chmodPrivate(path: string, mode: number) {
  try {
    chmodSync(path, mode);
  } catch {
    return;
  }
}

function localEnvValue(key: string) {
  const direct = process.env[key]?.trim();
  if (direct) return direct;
  return readProjectEnvValue(key);
}

function readProjectEnvValue(key: string) {
  for (const envPath of projectEnvCandidates()) {
    try {
      const raw = readFileSync(envPath, "utf8");
      const value = parseEnvValue(raw, key);
      if (value) return value;
    } catch {
      continue;
    }
  }
  return "";
}

function projectEnvCandidates() {
  return [
    join(process.cwd(), "..", ".env"),
    join(__dirname, "..", "..", ".env"),
    join(app.getPath("userData"), ".env"),
  ];
}

function parseEnvValue(raw: string, key: string) {
  const pattern = new RegExp(`^${key}=([^\\r\\n]*)`, "m");
  const match = raw.match(pattern);
  if (!match) return "";
  return match[1].trim().replace(/^['"]|['"]$/g, "");
}

function createSignedActionApproval(actionKind: string, args: Record<string, unknown>) {
  if (!ALLOWED_ACTION_APPROVALS.has(actionKind)) {
    throw new Error(`Unsupported action approval kind: ${actionKind}`);
  }
  const approvalId = `act_${randomBytes(24).toString("base64url")}`;
  const argsHash = canonicalArgsHash(actionKind, args);
  const expiresAt = Math.floor(Date.now() / 1000) + ACTION_APPROVAL_TTL_SECONDS;
  const payload = `${approvalId}\n${actionKind}\n${argsHash}\n${expiresAt}`;
  const approvalSignature = createHmac("sha256", actionApprovalSecret()).update(payload).digest("hex");
  return {
    approval_id: approvalId,
    action_kind: actionKind,
    args_hash: argsHash,
    expires_at: expiresAt,
    approval_signature: approvalSignature,
  };
}

function canonicalArgsHash(actionKind: string, args: Record<string, unknown>) {
  const payload = stableStringify({ action_kind: actionKind, arguments: args });
  return createHash("sha256").update(payload).digest("hex");
}

function stableStringify(value: unknown): string {
  return JSON.stringify(stableValue(value));
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => stableValue(item));
  if (!value || typeof value !== "object") return value;
  const source = value as Record<string, unknown>;
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(source).sort()) {
    const item = source[key];
    if (item !== undefined) sorted[key] = stableValue(item);
  }
  return sorted;
}

function actionApprovalDetail(actionKind: string, args: Record<string, unknown>) {
  const workspace = typeof args.workspace_root === "string" ? args.workspace_root : "";
  if (actionKind === "workspace.git_commit") {
    const message = typeof args.message === "string" && args.message.trim() ? args.message.trim() : "Auto-generate commit message";
    return `${message}${workspace ? `\n\nWorkspace: ${workspace}` : ""}`;
  }
  return workspace ? `Workspace: ${workspace}` : "Confirm this protected workspace action.";
}

function workspaceIdForRoot(root: string) {
  const resolved = resolve(root);
  return `wks_${createHash("sha256").update(resolved).digest("hex").slice(0, 24)}`;
}

function registerLocalWorkspaceGrant(root: string) {
  const resolved = resolve(assertString(root, "workspace root"));
  const workspaceId = workspaceIdForRoot(resolved);
  workspaceGrants.set(workspaceId, resolved);
  return { workspaceId, root: resolved };
}

function resolveGrantedWorkspace(workspaceRoot?: string | null, workspaceId?: string | null) {
  if (workspaceId) {
    const granted = workspaceGrants.get(workspaceId);
    if (!granted) throw new Error(`Unknown workspace grant: ${workspaceId}`);
    return granted;
  }
  if (!workspaceRoot) return undefined;
  const resolved = resolve(workspaceRoot);
  if (![...workspaceGrants.values()].includes(resolved)) {
    throw new Error(`Workspace root is not granted: ${resolved}`);
  }
  return resolved;
}

function assertString(value: unknown, label: string) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string.`);
  return value;
}

function assertStringValue(value: unknown, label: string) {
  if (typeof value !== "string") throw new Error(`${label} must be a string.`);
  return value;
}

function openExternalSafe(url: string) {
  try {
    const parsed = new URL(url);
    if (!["https:", "mailto:"].includes(parsed.protocol)) return;
    void shell.openExternal(parsed.toString());
  } catch {
    return;
  }
}

function desktopDebug(message: string, details?: Record<string, unknown>) {
  if (process.env.PERSONAGENT_DESKTOP_DEBUG !== "1") return;

  const suffix = details ? ` ${JSON.stringify(details)}` : "";
  console.log(`[desktop] ${message}${suffix}`);
}



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
      preload: join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once("ready-to-show", () => {
    revealMainWindow("ready-to-show");
  });

  mainWindow.webContents.on("console-message", (_event, level, message, _line, sourceId) => {
    const labels = ["verbose", "info", "warning", "error"];
    const label = labels[level] ?? String(level);
    console.log(`[renderer:${label}] ${sourceId}: ${message}`);
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    openExternalSafe(url);
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

async function createCompactWindow(context: CompactLaunchContext) {
  const conversationId = context.conversationId.trim();
  if (!conversationId) return false;

  const existing = compactWindows.get(conversationId);
  if (existing && !existing.isDestroyed()) {
    if (existing.isMinimized()) existing.restore();
    existing.show();
    existing.focus();
    return true;
  }

  const compactWindow = new BrowserWindow({
    width: 420,
    height: 680,
    minWidth: 360,
    minHeight: 520,
    title: context.title || "PersonAgent Compact",
    frame: false,
    titleBarStyle: "hidden",
    backgroundColor: "#08090b",
    show: false,
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  const compactWebContentsId = compactWindow.webContents.id;

  compactWindows.set(conversationId, compactWindow);
  compactContextsByWebContentsId.set(compactWebContentsId, {
    conversationId,
    workspaceRoot: context.workspaceRoot,
    title: context.title,
  });

  compactWindow.once("ready-to-show", () => {
    compactWindow.show();
    compactWindow.focus();
  });

  compactWindow.on("closed", () => {
    compactWindows.delete(conversationId);
    compactContextsByWebContentsId.delete(compactWebContentsId);
  });

  compactWindow.webContents.on("console-message", (_event, level, message, _line, sourceId) => {
    const labels = ["verbose", "info", "warning", "error"];
    const label = labels[level] ?? String(level);
    console.log(`[compact:${label}] ${sourceId}: ${message}`);
  });

  compactWindow.webContents.setWindowOpenHandler(({ url }) => {
    openExternalSafe(url);
    return { action: "deny" };
  });

  const query = {
    mode: "compact",
    conversationId,
    workspaceRoot: context.workspaceRoot || "",
    title: context.title || "",
  };
  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    const url = new URL(devServerUrl);
    for (const [key, value] of Object.entries(query)) {
      url.searchParams.set(key, value);
    }
    await compactWindow.loadURL(url.toString());
  } else {
    await compactWindow.loadFile(join(__dirname, "../dist/index.html"), { query });
  }
  return true;
}

function getWindowForEvent(event: IpcMainInvokeEvent) {
  const senderWindow = BrowserWindow.fromWebContents(event.sender);
  if (senderWindow && !senderWindow.isDestroyed()) return senderWindow;
  return mainWindow && !mainWindow.isDestroyed() ? mainWindow : null;
}

ipcMain.handle("window:minimize", (event) => {
  getWindowForEvent(event)?.minimize();
});

ipcMain.handle("window:maximize-toggle", (event) => {
  const targetWindow = getWindowForEvent(event);
  if (!targetWindow) return false;
  if (targetWindow.isMaximized()) {
    targetWindow.restore();
    return false;
  }
  targetWindow.maximize();
  return true;
});

ipcMain.handle("window:close", (event) => {
  getWindowForEvent(event)?.close();
});

ipcMain.handle("window:is-maximized", (event) => getWindowForEvent(event)?.isMaximized() ?? false);

ipcMain.handle("compact:open-session", async (_event, context: CompactLaunchContext) => {
  return createCompactWindow(context);
});

ipcMain.handle("compact:get-launch-context", (event) => {
  return compactContextsByWebContentsId.get(event.sender.id) ?? null;
});

ipcMain.handle("settings:get", async (_event, key: string) => {
  if (!ALLOWED_SETTINGS_KEYS.has(assertString(key, "settings key"))) {
    throw new Error(`Unsupported settings key: ${key}`);
  }
  const settings = await readSettings();
  return settings[key] ?? null;
});

ipcMain.handle("settings:set", async (_event, key: string, value: unknown) => {
  if (!ALLOWED_SETTINGS_KEYS.has(assertString(key, "settings key"))) {
    throw new Error(`Unsupported settings key: ${key}`);
  }
  await updateSettings((settings) => {
    settings[key] = value;
  });
  return true;
});

ipcMain.handle("dialog:select-workspace", async (event, initialPath?: string) => {
  const targetWindow = getWindowForEvent(event);
  const options: OpenDialogOptions = {
    title: "Select workspace",
    defaultPath: typeof initialPath === "string" && initialPath.trim() ? initialPath : undefined,
    properties: ["openDirectory", "createDirectory"],
  };
  const result = targetWindow
    ? await dialog.showOpenDialog(targetWindow, options)
    : await dialog.showOpenDialog(options);
  targetWindow?.focus();
  if (result.canceled || result.filePaths.length === 0) return null;
  return registerLocalWorkspaceGrant(result.filePaths[0]);
});

ipcMain.handle("workspace:grant", async (_event, workspaceRoot: string) => {
  return registerLocalWorkspaceGrant(workspaceRoot);
});

ipcMain.handle("auth:get-headers", async () => {
  return localAuthHeaders();
});

ipcMain.handle("security:create-action-approval", async (event, request: ActionApprovalRequest) => {
  const actionKind = assertString(request?.actionKind, "action kind");
  const args = request?.arguments && typeof request.arguments === "object" ? request.arguments : {};
  const actionLabel = ALLOWED_ACTION_APPROVALS.get(actionKind);
  if (!actionLabel) {
    throw new Error(`Unsupported action approval kind: ${actionKind}`);
  }
  const targetWindow = getWindowForEvent(event);
  const result = targetWindow
    ? await dialog.showMessageBox(targetWindow, {
        type: "warning",
        buttons: ["Approve", "Cancel"],
        defaultId: 1,
        cancelId: 1,
        title: "Confirm protected action",
        message: actionLabel,
        detail: actionApprovalDetail(actionKind, args),
      })
    : await dialog.showMessageBox({
        type: "warning",
        buttons: ["Approve", "Cancel"],
        defaultId: 1,
        cancelId: 1,
        title: "Confirm protected action",
        message: actionLabel,
        detail: actionApprovalDetail(actionKind, args),
      });
  targetWindow?.focus();
  if (result.response !== 0) {
    throw new Error("Action approval cancelled.");
  }
  return createSignedActionApproval(actionKind, args);
});

ipcMain.handle("fs:read-dir", async (_event, dirPath: string, workspaceRoot?: string, workspaceId?: string) => {
  const resolvedPath = resolve(assertString(dirPath, "directory path"));
  const resolvedWorkspace = resolveGrantedWorkspace(workspaceRoot, workspaceId);
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

ipcMain.handle("fs:read-file", async (_event, filePath: string, workspaceRoot?: string, workspaceId?: string) => {
  const resolvedPath = resolve(assertString(filePath, "file path"));
  const resolvedWorkspace = resolveGrantedWorkspace(workspaceRoot, workspaceId);
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

ipcMain.handle("terminal:create", (_event: IpcMainInvokeEvent, id: string, cwd?: string, workspaceRoot?: string, workspaceId?: string) => {
  const terminalId = assertString(id, "terminal id");
  const resolvedWorkspace = resolveGrantedWorkspace(workspaceRoot, workspaceId);
  const resolvedCwd = cwd ? resolve(assertString(cwd, "terminal cwd")) : resolvedWorkspace;
  if (resolvedWorkspace && resolvedCwd && !isPathInside(resolvedCwd, resolvedWorkspace)) {
    throw new Error(`Terminal cwd is outside active workspace: ${resolvedWorkspace}`);
  }
  if (terminals.has(terminalId)) {
    terminals.get(terminalId)?.kill();
    terminals.delete(terminalId);
  }
  createTerminalInstance(terminalId, resolvedCwd);
  return true;
});

ipcMain.handle("terminal:write", (_event: IpcMainInvokeEvent, id: string, data: string) => {
  const term = terminals.get(assertString(id, "terminal id"));
  if (term) {
    term.write(assertStringValue(data, "terminal data"));
  }
  return true;
});

ipcMain.handle("terminal:resize", (_event: IpcMainInvokeEvent, id: string, cols: number, rows: number) => {
  const term = terminals.get(assertString(id, "terminal id"));
  if (term) {
    term.resize(cols, rows);
  }
  return true;
});

ipcMain.handle("terminal:kill", (_event: IpcMainInvokeEvent, id: string) => {
  const terminalId = assertString(id, "terminal id");
  const term = terminals.get(terminalId);
  if (term) {
    term.kill();
    terminals.delete(terminalId);
  }
  return true;
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
