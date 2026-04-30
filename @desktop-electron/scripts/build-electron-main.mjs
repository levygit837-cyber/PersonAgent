import { readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const tsc = process.platform === "win32" ? join(root, "node_modules", ".bin", "tsc.cmd") : join(root, "node_modules", ".bin", "tsc");

execFileSync(tsc, ["-p", "tsconfig.node.json"], {
  cwd: root,
  stdio: "inherit",
});

const preloadSource = readFileSync(join(root, "electron", "preload.ts"), "utf8");
const preloadOutput = ts.transpileModule(preloadSource, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS,
    esModuleInterop: true,
  },
  fileName: "preload.ts",
});

writeFileSync(join(root, "dist-electron", "preload.cjs"), preloadOutput.outputText, "utf8");
