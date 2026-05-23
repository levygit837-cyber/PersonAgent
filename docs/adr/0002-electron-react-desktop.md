# ADR 0002: Electron 41 + React 19 + Vite 8 Desktop Shell

Date: 2025-06-10
Status: Accepted

## Context

PersonAgent needs a desktop client that runs locally, has full filesystem access, embeds a terminal, and communicates with the local Python backend. A browser-based SPA cannot grant workspace filesystem access or spawn PTY terminals securely.

## Decision

Build the desktop client with Electron 41 as the shell, React 19 for the renderer, and Vite 8 for the build toolchain.

**Process architecture**
- **Main** (`electron/main.ts`): Node.js process owning window management, local auth token storage, workspace grants, action-approval HMAC signing, PTY terminals via `node-pty`, and IPC handlers.
- **Preload** (`electron/preload.ts`): contextBridge exposing a typed `window.personAgent` API to the renderer. Preload is transpiled to CJS so Electron can load it with `contextIsolation: true` and `sandbox: true`.
- **Renderer** (`src/main.tsx`, `src/App.tsx`): React 19 + TanStack Query + Zustand stores + TailwindCSS + Radix/shadcn primitives. Strict-port dev server at `127.0.0.1:5176`.

**Security choices**
- `nodeIntegration: false`, `contextIsolation: true`, `sandbox: true` in all `BrowserWindow` instances.
- All filesystem and shell access is gated through IPC in the main process, with workspace-grant validation (`resolveGrantedWorkspace`).
- Local auth token is read from `~/.cache/personagent/local_auth_token` or `.env`; never shipped in the renderer bundle.

## Consequences

- **Easier**: native window chrome, PTY terminals, local file dialogs, secure action approvals with HMAC-SHA256 + TTL.
- **Harder**: Electron upgrades require main/preload/renderer compatibility checks; binary size grows.
- **Risk**: preload script must remain minimal; adding Node APIs directly to the renderer breaks the sandbox model.
- **Out of scope**: mobile apps, web-only distribution, or third-party plugin stores.

## Alternatives Considered

- **Tauri**: smaller binary, but no mature PTY story and Rust ecosystem mismatch with the existing Python backend team.
- **Browser SPA with File System Access API**: insufficient for terminal integration and workspace-grant security model.

## Validation

- Desktop starts with `npm run dev` on Linux (AppImage target) and macOS (dmg target).
- `@desktop-electron/test-artifacts/` contains screenshots of key UI states (chat refactor, features, open-pr).
