import { execFile } from "node:child_process";
import { readFile, readlink } from "node:fs/promises";
import net from "node:net";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const PORT = Number(process.env.PERSONAGENT_DESKTOP_DEV_PORT ?? 5176);
const HOST = process.env.PERSONAGENT_DESKTOP_DEV_HOST ?? "127.0.0.1";
const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const APP_ROOT = resolve(SCRIPT_DIR, "..");

async function isPortOpen() {
  return new Promise((resolvePortState) => {
    const socket = net.createConnection({ host: HOST, port: PORT });
    let settled = false;

    function finish(open) {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolvePortState(open);
    }

    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
    socket.setTimeout(750, () => finish(false));
  });
}

async function findLinuxListenerPids() {
  if (process.platform !== "linux") return [];

  try {
    const { stdout } = await execFileAsync("ss", ["-ltnp"]);
    const pids = new Set();

    for (const line of stdout.split("\n")) {
      if (!line.includes(`:${PORT}`)) continue;

      for (const match of line.matchAll(/pid=(\d+)/g)) {
        pids.add(Number(match[1]));
      }
    }

    return [...pids];
  } catch {
    return [];
  }
}

async function describePid(pid) {
  const [cmdline, cwd] = await Promise.all([
    readFile(`/proc/${pid}/cmdline`, "utf8")
      .then((raw) => raw.replaceAll("\0", " ").trim())
      .catch(() => ""),
    readlink(`/proc/${pid}/cwd`).catch(() => ""),
  ]);

  return { pid, cmdline, cwd };
}

function isInsideAppRoot(path) {
  if (!path) return false;

  const resolvedPath = resolve(path);
  return resolvedPath === APP_ROOT || resolvedPath.startsWith(`${APP_ROOT}/`);
}

function isAppOwnedViteProcess(processInfo) {
  const command = processInfo.cmdline.toLowerCase();
  return command.includes("vite") && isInsideAppRoot(processInfo.cwd);
}

async function waitForPortToClose() {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (!(await isPortOpen())) return true;
    await delay(100);
  }

  return false;
}

if (!(await isPortOpen())) {
  process.exit(0);
}

const listenerPids = await findLinuxListenerPids();
const listenerDetails = await Promise.all(listenerPids.map((pid) => describePid(pid)));
const staleViteProcesses = listenerDetails.filter(isAppOwnedViteProcess);

for (const processInfo of staleViteProcesses) {
  console.log(`[dev] Stopping stale Vite listener on ${HOST}:${PORT} (pid ${processInfo.pid}).`);
  try {
    process.kill(processInfo.pid, "SIGTERM");
  } catch {
    // The process may have exited between detection and termination.
  }
}

if (staleViteProcesses.length > 0 && (await waitForPortToClose())) {
  process.exit(0);
}

const details = listenerDetails
  .map((processInfo) => {
    const command = processInfo.cmdline || "unknown command";
    const cwd = processInfo.cwd ? ` cwd=${processInfo.cwd}` : "";
    return `pid ${processInfo.pid}: ${command}${cwd}`;
  })
  .join("\n");

console.error(`[dev] Port ${HOST}:${PORT} is already in use.`);
if (details) {
  console.error(details);
}
console.error("[dev] Refusing to launch Electron against an existing server.");
process.exit(1);
