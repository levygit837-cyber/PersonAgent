# Playbook: Decompose `tool-block.tsx`

**Target file:** `@desktop-electron/src/components/chat/tool-block.tsx`
(919 lines — 30+ components and helper functions for tool rendering)

**Target directory:** `@desktop-electron/src/components/chat/tool-block/`
(directory already exists with helper modules; main component file
will be restructured)

**Tests:**
- `@desktop-electron/src/components/chat/tool-block.test.tsx`

Read `_protocol.md` first.

## Why this file is hard

`tool-block.tsx` is the rendering hub for all tool call visualizations.
It contains:

1. **Primary components** — `ToolBlock` (router), `CompactToolGroupBlock`
   (grouped rendering).
2. **Tool-specific renderers** (~500L) — `ReadToolEvent`,
   `WriteToolEvent`, `ShellToolEvent`, `SearchToolEvent`,
   `TodoToolEvent`, `TodoToolGroupBlock`, `TodoPanel`, `TodoRow`,
   `GenericToolEvent`, `BrowserToolEvent`.
3. **Write diff rendering** (~120L) — `WriteOutputPanel`, diff
   parsing (`parseWriteOutput`, `contextRegion`), `WriteOutputRow` type.
4. **Utility functions** (~200L) — `toolBlockHasDetails`,
   `isFileMutationTool`, `isTodoTool`, `isSearchTool`,
   `isSearchShellCommand`, `shouldAutoCollapseToolGroup`,
   `compactGenericToolLabel`, `latestTodoBlock`, `todoPanelStatus`,
   `todoProgressLabel`, `todoStatusLabel`, `lineDetail`, `fileLabel`,
   `shellCommandText`, `shellOutputPreview`, `hasNonWhitespace`,
   `isRecord`, `shellCommandBase`, status helpers.

The directory already has extracted helper modules:
- `tool-block/browser-output.ts` — browser image/text normalization
- `tool-block/search-output.ts` — search result parsing
- `tool-block/todo.ts` — todo item extraction
- `tool-block/visibility.ts` — collapse/expand hook

The main file still holds all the React components and most utilities.

## Public contract that must be preserved

Consumed by:
- `components/chat/agent-message.tsx` — imports `ToolBlock`,
  `CompactToolGroupBlock`, `isBrowserToolName`, `isSearchShellCommand`,
  `isTodoTool`.

All current exports must remain available from the same import path
(`./tool-block`). Add re-exports via an updated `tool-block.tsx` or
a new `tool-block/index.tsx`.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract write/diff components | ⏳ Pending | — | |
| 2 — Extract read/shell/generic components | ⏳ Pending | — | |
| 3 — Extract todo components + flatten | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract write/diff rendering to `tool-block/write-output.tsx`

**What moves out (~200 lines):**

- `WriteOutputRow` type (13–19)
- `WriteToolEvent` component (223–398)
- `WriteOutputPanel` component (~70L)
- `parseWriteOutput` function (~60L)
- `contextRegion` helper
- `isFileMutationTool` guard function

**Why first:** Write/diff rendering is a self-contained cluster with
its own type (`WriteOutputRow`), its own parsing logic, and no
dependencies on other tool-specific components.

**Risk:** Low. Pure rendering + parsing logic.

**Tests:** 10+ cases:
- Diff parsing with adds/removes/context.
- File label display for various paths.
- Error state rendering.
- Collapsed/expanded state.

### Slice 2 — Extract read/shell/generic components to `tool-block/read-shell.tsx`

**What moves out (~250 lines):**

- `ReadToolEvent` component (87–97)
- `ShellToolEvent` component (~100L)
- `GenericToolEvent` component (~80L)
- `BrowserToolEvent` component (~50L)
- Supporting helpers: `shellCommandText`, `shellOutputPreview`,
  `shellCommandBase`, `lineDetail`, `fileLabel`

**Why now:** After slice 1, these are the remaining tool-type-specific
components. They share status helpers but are otherwise independent.

**Risk:** Low.

**Tests:** 10+ cases:
- Read tool rendering with line details.
- Shell tool with command display and output preview.
- Generic tool fallback rendering.
- Browser tool inline display.

### Slice 3 — Extract todo components to `tool-block/todo-block.tsx` + flatten utilities

**What moves out (~200 lines):**

Components:
- `TodoToolEvent` (102–105)
- `TodoToolGroupBlock` (98–101)
- `TodoPanel` (106–151)
- `TodoRow` (152–177)
- `TodoStatusDot` (178–188)

Utilities (to `tool-block/utils.ts`):
- `toolBlockHasDetails`
- `isTodoTool`, `isSearchTool`, `isSearchShellCommand`
- `shouldAutoCollapseToolGroup`, `compactGenericToolLabel`
- `latestTodoBlock`, `todoPanelStatus`, `todoProgressLabel`,
  `todoStatusLabel`
- Status helpers: `isError`, `isErrorStatus`, `isWarningStatus`,
  `statusTextClass`, `statusDotClass`, `isRunning`
- Value helpers: `stringValue`, `rawStringValue`, `numberValue`,
  `hasNonWhitespace`, `isRecord`

After this slice, the main `tool-block.tsx` (or `tool-block/index.tsx`)
becomes a thin router (~80L) that imports from sub-modules and
re-exports the public API.

**Risk:** Low.

**Tests:** 10+ cases:
- Todo panel rendering with various states.
- Status dot color mapping.
- Utility function edge cases.

## Anti-patterns specific to this file

- **CSS class names.** The file uses Tailwind utility classes
  extensively. Do not extract CSS — it stays inline in JSX.
- **Re-export everything.** After extraction, `agent-message.tsx`
  still does `import { ToolBlock, ... } from "./tool-block"`.
  The import path must not change.
- **Do not extract `CompactToolGroupBlock`.** It's the composition
  root that references all tool-type components — it stays in the
  main file as the orchestrator.

## Validation gates

```bash
cd @desktop-electron
npm run typecheck
npm test -- --testPathPattern tool-block
```
