# Project Map: opencode

## Overview

**OpenCode** is an open-source AI coding agent — a terminal-first (TUI) CLI tool that assists developers with code generation, editing, exploration, and task execution through natural language. It supports multiple LLM providers, has a plugin ecosystem, and ships as:
- A terminal UI (TUI) CLI (`opencode`)
- A desktop application (Electron)
- A web-based console (SolidStart)

**Tech Stack:**
- **Runtime:** Bun (primary), Node (fallback for some PTY operations)
- **Language:** TypeScript (~2,135 `.ts`/`.tsx` files across 25 packages)
- **UI Frameworks:** SolidJS (TUI via OpenTUI, Desktop, Web App), Terminal rendering via `@opentui/core/solid`
- **Functional Effects:** Effect-TS (extensively used for dependency injection, error handling, and async flows)
- **Database:** SQLite via Drizzle ORM
- **LLM Abstraction:** Vercel AI SDK (`ai` package) + custom native LLM runtime + `@opencode-ai/llm` provider abstraction
- **API Server:** Hono (HTTP REST + WebSocket)
- **Build:** Turbo monorepo, SST for cloud deployments, Vite for app builds

---

## Directory Structure

```
packages/
├── opencode/           # MAIN CLI PACKAGE (~534 source files)
│   ├── src/cli/cmd/    # CLI commands (run, tui, serve, debug, etc.)
│   ├── src/cli/cmd/tui/# Terminal UI (SolidJS components, routes, dialogs, keymaps)
│   ├── src/session/    # Session lifecycle, messages, LLM streaming, processor
│   ├── src/agent/      # Agent definitions (build, plan, explore, general, scout)
│   ├── src/tool/       # Built-in tools (edit, read, write, shell, grep, glob, etc.)
│   ├── src/server/     # HTTP API server (Hono), v1 and v2 routes, middleware
│   ├── src/provider/   # LLM provider resolution, auth, transforms
│   ├── src/plugin/     # Plugin loading (internal + external npm-based)
│   ├── src/mcp/        # Model Context Protocol integration
│   ├── src/skill/      # Skill discovery and loading (.agents/skills/ SKILL.md)
│   ├── src/config/     # Configuration system (opencode.json, opencode.jsonc)
│   ├── src/project/    # Project/workspace bootstrap, instance context
│   ├── src/control-plane/ # Workspace adapters, multi-workspace support
│   ├── src/permission/ # Permission evaluation for tools/actions
│   ├── src/pty/        # Pseudo-terminal support (Bun + Node adapters)
│   └── src/v2/         # V2 API session/event handlers
├── core/               # Shared core abstractions (schemas, models, providers, git, utils)
├── llm/                # Low-level LLM provider abstraction and protocols
│   ├── src/providers/  # Provider-specific implementations (Anthropic, OpenAI, etc.)
│   ├── src/protocols/  # Protocol adapters (OpenAI-compatible, Bedrock, Gemini)
│   └── src/route/      # LLM routing client, auth, transport (HTTP/WebSocket)
├── ui/                 # Shared UI component library (SolidJS, Kobalte, storybook)
├── plugin/             # Plugin SDK (defines tool, TUI, and hook interfaces)
├── sdk/js/             # Generated JavaScript SDK from OpenAPI spec (client + types)
├── app/                # Web application (SolidStart, shared with desktop)
├── desktop/            # Electron desktop app (wraps `@opencode-ai/app`)
├── console/            # Cloud console web app (SolidStart, auth, billing)
│   ├── app/            # Console frontend
│   ├── core/           # Console backend logic
│   ├── mail/           # Email templates
│   └── resource/       # Cloud resources
├── enterprise/         # Enterprise sharing/stats site (SolidStart)
├── web/                # Marketing/landing site (Astro)
├── stats/              # Usage statistics aggregation service
├── docs/               # Documentation site
├── containers/         # Docker images for CI/build
├── effect-drizzle-sqlite/ # Effect-TS integration for Drizzle + SQLite
├── http-recorder/      # HTTP request/response recording for tests
├── slack/              # Slack integration
├── identity/           # Auth/identity utilities
├── extensions/         # VS Code extension
├── function/           # Cloud functions
├── storybook/          # UI component stories
└── cli/                # Additional CLI utilities
```

---

## Key Architectural Components

### 1. CLI / Terminal UI (`packages/opencode/src/cli/cmd/tui/`)
The primary user interface is a terminal application built with **SolidJS** rendered via **OpenTUI**. It has:
- **Routes:** `home`, `session`, and plugin-defined routes
- **Dialogs:** Model picker, agent switcher, session list, MCP toggle, workspace manager, etc.
- **Keymap system:** Extensible keyboard binding system with modes
- **Context providers:** SDK, sync, theme, project, route, local state, prompt history
- **Plugin runtime:** TUI plugins can register routes, commands, and UI slots

### 2. Session & Message System (`packages/opencode/src/session/`)
- **Session**: SQLite-backed entity with metadata (cost, tokens, title, agent, permissions)
- **MessageV2**: Typed message parts (text, tool, reasoning, step-start/finish, patch, snapshot, file, compaction)
- **Processor** (`processor.ts`): Core event loop that consumes LLM streams, handles tool calls, tracks snapshots, and manages doom-loop detection
- **LLM** (`llm.ts`): Streaming abstraction supporting both **AI SDK** and **native runtime** paths
- **Compaction**: Automatic context window management via a dedicated compaction agent

### 3. Agent System (`packages/opencode/src/agent/`)
- **build**: Default full-access agent for development
- **plan**: Read-only agent for exploration and planning
- **general**: Subagent for multi-step parallel research
- **explore**: Fast codebase exploration agent (grep/glob/read only)
- **scout**: Documentation/dependency research agent
- Agents define **permission rulesets** that govern tool access

### 4. Tool System (`packages/opencode/src/tool/`)
- ~20 built-in tools: `read`, `write`, `edit`, `shell`, `grep`, `glob`, `lsp`, `websearch`, `webfetch`, `repo_clone`, `repo_overview`, `question`, `plan`, `todo`, `task`, `skill`, `apply_patch`, etc.
- Tools are defined with Effect-TS schemas, have truncation logic, and emit structured results
- Tool registry (`registry.ts`) collects tools from built-ins, plugins, and MCP servers

### 5. Plugin System (`packages/opencode/src/plugin/`)
- **Internal plugins**: Hardcoded (Codex, Copilot, GitLab, Poe, Cloudflare, Azure, etc.)
- **External plugins**: Loaded from npm packages via `PluginLoader`
- Plugins receive a `PluginInput` with SDK client, project info, and server URL
- Hook-based architecture: `trigger(name, input, output)` allows plugins to intercept events

### 6. LLM Provider Abstraction (`packages/llm/` + `packages/opencode/src/provider/`)
- Supports 15+ providers via AI SDK (Anthropic, OpenAI, Google, Azure, Bedrock, Groq, Mistral, XAI, Cohere, etc.)
- Custom providers: OpenRouter, GitHub Copilot, GitLab Workflow
- `@opencode-ai/llm` provides low-level protocol adapters and routing
- Provider transforms handle message formatting, header injection, and SSE timeouts

### 7. Server / API (`packages/opencode/src/server/`)
- Hono-based HTTP server running on port 4096 (default)
- **V1 API**: Session, message, file, project, provider, MCP, PTY, sync, workspace routes
- **V2 API**: Newer event-driven API with different schema shapes (v2 session, message, location, model handlers)
- WebSocket support for real-time events
- Authentication via `ServerAuth` with token-based middleware

### 8. Control Plane / Workspaces (`packages/opencode/src/control-plane/`)
- Experimental multi-workspace support
- Workspace adapters (`worktree.ts`) for different workspace types
- Workspace context and routing middleware

### 9. Desktop & Web Apps (`packages/desktop/`, `packages/app/`)
- Desktop: Electron app loading the shared `@opencode-ai/app` bundle
- App: SolidStart-based SPA consumed by both desktop and web console
- Shared UI components from `@opencode-ai/ui`

---

## Dependency Map

### Internal Package Dependencies (simplified)

```
opencode (main CLI)
  ├─► @opencode-ai/core        (schemas, utils, models, git, npm, global paths)
  ├─► @opencode-ai/llm         (provider protocols, routing, transport)
  ├─► @opencode-ai/plugin      (plugin SDK interfaces)
  ├─► @opencode-ai/sdk         (generated HTTP client for self-calls)
  ├─► @opencode-ai/ui          (shared SolidJS components)
  ├─► @opencode-ai/script      (build scripts)
  └─► effect-drizzle-sqlite    (DB layer integration)

@opencode-ai/app (web app)
  ├─► @opencode-ai/core
  ├─► @opencode-ai/ui
  └─► @opencode-ai/sdk

@opencode-ai/desktop
  └─► @opencode-ai/app, @opencode-ai/ui

@opencode-ai/llm
  └─► (standalone, only effect + smithy/aws deps)

@opencode-ai/ui
  ├─► @opencode-ai/sdk, @opencode-ai/core
  └─► Kobalte, SolidJS, Shiki, Tailwind

@opencode-ai/console-app
  ├─► @opencode-ai/ui
  ├─► @opencode-ai/console-core/mail/resource
  └─► SolidStart, OpenAuth, Stripe
```

### Key External Dependencies
- `effect` — Functional programming, DI, error handling, streams
- `ai` / `@ai-sdk/*` — Vercel AI SDK for LLM interactions
- `solid-js` / `@solidjs/*` — Reactive UI framework
- `@opentui/*` — Terminal UI rendering engine
- `drizzle-orm` — SQLite ORM
- `hono` — HTTP server framework
- `zod` / `schema` — Schema validation (both Zod and Effect Schema used)
- `remeda` — Functional utilities

---

## Informational Goals (Benchmark Candidates)

### Goal 1: Message Flow from TUI Prompt to Tool Execution
- **Question**: When a user types a message in the TUI and presses Enter, what is the complete path that message takes through the codebase until a tool (e.g., `edit`) is executed and its result is streamed back to the terminal?
- **Why it's hard**: This spans the TUI (SolidJS context + SDK client), HTTP API server (Hono routes), session creation, LLM streaming (dual runtime paths), the processor event loop, tool registry lookup, tool execution with Effect-TS, and delta updates back through the sync system to the TUI.
- **Expected findings**: The agent should trace: `prompt/index.tsx` → `sdk.client` → `server/routes/instance/httpapi/handlers/session.ts` → `session/llm.ts` → `processor.ts` → `tool/registry.ts` → `tool/edit.ts` → bus events → `sync` context → TUI re-render.
- **Complexity**: very complex
- **Key files involved**: `packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`, `packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts`, `packages/opencode/src/session/llm.ts`, `packages/opencode/src/session/processor.ts`, `packages/opencode/src/tool/registry.ts`, `packages/opencode/src/tool/edit.ts`, `packages/opencode/src/cli/cmd/tui/context/sync.tsx`

### Goal 2: Permission Evaluation for Tool Approval
- **Question**: How does the system decide whether a specific tool call (e.g., `shell`) requires user approval ("ask"), is auto-allowed, or auto-denied? How do agent permissions, user config, session-level overrides, and wildcard patterns interact?
- **Why it's hard**: Permission resolution involves merging multiple rulesets (agent defaults, user config, session overrides), wildcard pattern matching, special cases (doom_loop, .env files, external_directory), and integration with the `Permission` service and `Question` system.
- **Expected findings**: The agent should discover that permissions are merged via `Permission.merge()` in `agent/agent.ts`, evaluated via `Permission.evaluate()` using wildcard matching, and that the `doom_loop` threshold (3 repeated calls) triggers an explicit ask regardless of base permissions.
- **Complexity**: complex
- **Key files involved**: `packages/opencode/src/agent/agent.ts`, `packages/opencode/src/permission/`, `packages/opencode/src/session/processor.ts` (doom_loop check), `packages/opencode/src/tool/tool.ts`

### Goal 3: Native LLM Runtime vs AI SDK Fallback
- **Question**: Under what conditions does the LLM streaming system use the "native" runtime (`@opencode-ai/llm`) instead of the Vercel AI SDK default path? What are the differences in how tool calls are handled between these two paths?
- **Why it's hard**: The choice is gated by `RuntimeFlags.experimentalNativeLlm`, but the native runtime itself is an opt-in adapter with provider-specific support detection. The two paths converge back to a unified `LLMEvent` stream, but the tool execution mechanics differ (AI SDK owns tool dispatch; native returns raw streams).
- **Expected findings**: The agent should find `LLMNativeRuntime.stream()` in `session/llm/native-runtime.ts`, the `type: "native" | "ai-sdk"` branching in `session/llm.ts`, and how `LLMAISDK.toLLMEvents()` normalizes AI SDK events into the shared event format.
- **Complexity**: complex
- **Key files involved**: `packages/opencode/src/session/llm.ts`, `packages/opencode/src/session/llm/native-runtime.ts`, `packages/opencode/src/session/llm/native-request.ts`, `packages/opencode/src/session/llm/ai-sdk.ts`, `packages/llm/src/route/executor.ts`

### Goal 4: Plugin Loading and Hook Execution Lifecycle
- **Question**: How are external npm-based plugins discovered, installed, loaded, and initialized at runtime? And when a plugin hook (e.g., `experimental.chat.system.transform`) is triggered, how does the system route the call to the correct plugin function?
- **Why it's hard**: Plugin loading involves npm package resolution, compatibility checks, entrypoint detection (CJS/ESM, server vs client), dynamic imports, and a hook registry that is instance-scoped via Effect-TS. The trigger pattern `(name, input, output) => Effect<Output>` is non-obvious.
- **Expected findings**: The agent should trace: `plugin/index.ts` → `PluginLoader.loadExternal()` → `plugin/loader.ts` → `plugin/shared.ts` (resolve entry) → dynamic import → `applyPlugin()` → hook registration in `state.hooks`. Triggers iterate hooks by name in `Plugin.trigger()`.
- **Complexity**: complex
- **Key files involved**: `packages/opencode/src/plugin/index.ts`, `packages/opencode/src/plugin/loader.ts`, `packages/opencode/src/plugin/shared.ts`, `packages/opencode/src/plugin/install.ts`

### Goal 5: V2 Event Bridge and Backwards Compatibility
- **Question**: How does the experimental v2 event system coexist with the legacy sync event system? Specifically, when a tool is called during a session, what events are emitted on each system, and how does the v2 `EventV2Bridge` interact with the legacy `Bus`/`SyncEvent` infrastructure?
- **Why it's hard**: The codebase has explicit "TODO(v2): Temporary dual-write" comments scattered through `processor.ts`. Understanding the relationship requires reading both legacy event definitions in `session/session.ts`/`bus/` and v2 definitions in `@opencode-ai/core/session-event`, plus the bridge implementation.
- **Expected findings**: The agent should identify that `flags.experimentalEventSystem` gates v2 event emission, that `EventV2Bridge` publishes to a separate channel, and that many operations (tool start/end, reasoning, step start/end) emit on BOTH systems simultaneously during the migration period.
- **Complexity**: complex
- **Key files involved**: `packages/opencode/src/session/processor.ts`, `packages/opencode/src/event-v2-bridge.ts`, `packages/opencode/src/bus/`, `packages/opencode/src/sync.ts`, `packages/core/src/session-event.ts`, `packages/opencode/src/v2/session.ts`

### Goal 6: Workspace Discovery via Control Plane Adapters
- **Question**: How does the control plane discover and manage workspaces for a project? Specifically, how does the `worktree` workspace adapter map directories to workspace entities, and how is workspace routing applied in the HTTP API middleware?
- **Why it's hard**: Workspace support is behind `experimentalWorkspaces` flag. The adapter system (`control-plane/adapters/`), workspace context (`workspace-context.ts`), and routing middleware (`workspace-routing.ts`) are spread across multiple files and interact with project instance state.
- **Expected findings**: The agent should find `registerAdapter()` in `control-plane/adapters/index.ts`, the `worktree` adapter implementation, how `InstanceState` carries workspace IDs, and how `workspace-routing` middleware resolves workspace from request context.
- **Complexity**: medium
- **Key files involved**: `packages/opencode/src/control-plane/adapters/index.ts`, `packages/opencode/src/control-plane/adapters/worktree.ts`, `packages/opencode/src/control-plane/workspace-context.ts`, `packages/opencode/src/server/routes/instance/httpapi/middleware/workspace-routing.ts`, `packages/opencode/src/control-plane/workspace.ts`

### Goal 7: Skill Discovery and Injection into System Prompt
- **Question**: How are skills discovered from the filesystem (including external `.agents/skills/` and `.claude/` directories), and how do they get injected into the system prompt sent to the LLM?
- **Why it's hard**: Skill discovery scans multiple directory hierarchies (global home, project up-tree, config paths, URLs), parses markdown frontmatter, and integrates with the `Config` system. The injection point into prompts is buried in the session prompt builder.
- **Expected findings**: The agent should trace: `skill/index.ts` → `discoverSkills()` → `scan()` with glob patterns → `ConfigMarkdown.parse()` → `skill.dirs()` returning available skills → prompt builder in `session/prompt.ts` adding skill content to the system prompt.
- **Complexity**: medium
- **Key files involved**: `packages/opencode/src/skill/index.ts`, `packages/opencode/src/skill/discovery.ts`, `packages/opencode/src/session/prompt.ts`, `packages/opencode/src/config/markdown.ts`

---

## Complexity Assessment

**Overall Rating: VERY COMPLEX**

**Reasoning:**

1. **Scale**: ~2,135 TypeScript/TSX files across 25 packages in a monorepo. The main CLI package alone has ~534 source files.

2. **Architectural Sophistication**: Heavy use of **Effect-TS** for dependency injection, error handling, and concurrency. Services are wired through `Layer` compositions that can be difficult to trace. The codebase uses `Context.Service`, `Layer.effect`, `Effect.gen`, and `EffectBridge` patterns extensively.

3. **Multiple Frontends & Runtimes**: Three distinct UIs (terminal TUI, Electron desktop, web browser) share some code but have distinct build systems, routing, and state management.

4. **Dual API Versions**: The HTTP API has both v1 and v2 route groups with different schemas, handlers, and an experimental event bridge system running in parallel with legacy sync events.

5. **LLM Abstraction Depth**: Two separate LLM execution paths (AI SDK vs native), 15+ provider integrations, protocol adapters (OpenAI-compatible, Bedrock, Gemini), provider-specific transforms, and custom auth plugins.

6. **State Management Complexity**: SQLite database with Drizzle ORM, sync events, bus events, v2 events, session/message parts, snapshots, compaction, and real-time TUI reactivity — all interacting.

7. **Plugin & Extension System**: Dynamic npm package loading, hook-based interception, MCP server integration, skill markdown parsing, and workspace adapters create many extension points that an agent must understand to trace behavior.

**Most Complex Areas:**
- `packages/opencode/src/session/processor.ts` — The core event loop handling LLM streams, tool calls, reasoning, snapshots, doom loops, and dual event emission.
- `packages/opencode/src/session/llm.ts` — Runtime selection between native and AI SDK, with provider-specific wiring.
- `packages/opencode/src/cli/cmd/tui/` — The TUI is a full SolidJS application with its own routing, state, plugin system, and sync layer.
- `packages/opencode/src/provider/provider.ts` — ~1,900 lines of provider resolution, auth, caching, and transforms.
- `packages/opencode/src/server/routes/instance/httpapi/` — Large REST API surface with v1/v2 duality.
