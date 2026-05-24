# Playbook: Decompose `session-panel.tsx`

**Target file:** `@desktop-electron/src/components/chat/session-panel.tsx`
(3,960 lines — largest frontend god file)

**Target directory:** `@desktop-electron/src/components/chat/session-panel/`
(directory already exists with `browser-mirror.ts` and `cache.ts`;
new modules go here)

**Test files:**
- `@desktop-electron/src/components/chat/session-panel.test.tsx`

Read `_protocol.md` first.

## Why this file is hard

`SessionPanel` is a single React component that owns:

1. **Session state queries** — backend session metadata, browser
   tabs, memory recall, recent usage.
2. **Browser tab strip** — the user-facing tabs for active
   browsers and pages, with synchronization to backend tab state.
3. **Browser tracing panel** — live event timeline for browser
   tool calls.
4. **Memory / files / sources / project panels** — the right-rail
   detail tabs.
5. **Browser cooperation overlay** — proposal acceptance UI.

Inside the component there are **11 `useState` hooks, 16
`useEffect` hooks, 16 `useMemo` hooks** plus refs and store
subscriptions. The component is the inside-out version of a
mini-app.

## Public contract that must be preserved

`SessionPanel` is rendered by exactly one parent (search for
`<SessionPanel`). The signature `function SessionPanel({ ... }:
SessionPanelProps)` must keep its props shape. The component's
exported subcomponents (`BrowserTabStrip`, etc.) are also imported
by their tests — keep the exports.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract helpers to `helpers.ts` | ✅ Merged | — | 19 functions + 7 types + 8 constants; `helpers.ts`; 40 new tests |
| 2 — Extract `useSessionPanelState` hook | ✅ Merged | — | hook + `mergeUsage`; `use-session-panel-state.ts`; 8 new tests |
| 3 — Extract `useBrowserTabs` hook | ⏳ Pending | — | |
| 4 — Extract leaf components | ⏳ Pending | — | |
| 5 — Extract `BrowserTabContent` | ⏳ Pending | — | |
| 6 — Extract right-rail detail sections | ⏳ Pending | — | |
| 7 — Inline what remains | ⏳ Pending | — | |

## Proposed slices (in order)

The frontend uses different decomposition primitives than the
Python backend:

| Backend pattern             | Frontend equivalent                       |
| --------------------------- | ----------------------------------------- |
| Extract a class             | Extract a sub-component                   |
| Extract a module function   | Extract a custom hook                     |
| Extract a dataclass         | Extract a `type` + helper functions       |

### Slice 1 — Extract pure helper functions to `session-panel/helpers.ts`

**What moves out:** the ~25 standalone functions defined at the
top of the file (lines 197–425):

- `createEmptyBrowserState`, `browserPanelTabId`,
  `browserPagePanelTabId`, `isBrowserTab`,
  `browserTabsRepresentSamePage`, `browserTabPageIds`,
  `browserTabComparableUrl`, `browserPreferredSyncedView`,
  `browserViewComparableUrl`, `browserViewIsPlaceholder`,
  `browserCooperationFromView`, `browserRenderCacheKey`,
  `browserRenderUrlCacheKey`, `browserRenderCacheKeyFromView`,
  `rememberBrowserRenderView`, `compactBrowserViewForMemory`,
  `resolveBackendUrlPath`, `readBrowserRenderCache`,
  `isBrowserCooperationEvent`
- Constants: `SESSION_PANEL_*`, `BROWSER_LOADING_MESSAGES`,
  `BROWSER_RENDER_CACHE_LIMIT`, `BROWSER_TOOL_VIEW_SETTLE_MS`,
  `BROWSER_TOOL_HYDRATE_NAMES`, `BROWSER_TOOL_PASSIVE_VIEW_NAMES`,
  `BROWSER_TOOL_NAVIGATION_VIEW_NAMES`

**Why first:** Pure functions. No render dependencies. Test by
unit-testing the helpers in a new
`session-panel/helpers.test.ts`. The component just imports
them from the helpers module.

**Risk:** Negligible.

**Tests:** ~15 cases. Most helpers are 1-liners; cover the
non-trivial ones (`browserPreferredSyncedView`,
`compactBrowserViewForMemory`,
`browserTabsRepresentSamePage`).

### Slice 2 — Extract `SessionPanelStateProvider` (custom hook for session data)

**What moves out:** the React Query hooks + state derivations
that pull session/usage/memory/files data from the backend.

**New file:** `session-panel/use-session-panel-state.ts`.

Hook signature:

```ts
export function useSessionPanelState(conversationId: string | undefined) {
  return {
    sessionQuery,
    memoryQuery,
    filesQuery,
    sourcesQuery,
    isStreaming,
    liveUsage,
    /* ... */
  };
}
```

**Why now:** Most of the data-loading logic is independent of
the render tree. Lifting it into a hook makes the component
test in isolation.

**Risk:** Low if you preserve the dependency arrays exactly.
Subtle bugs come from re-keying queries or changing the
`enabled` predicate. Use `git diff` to audit every hook.

**Tests:** Use `@testing-library/react` + `vitest`. Mock the
backend client and assert the hook's outputs for each
combination of `(conversationId is null, query is loading,
query has data, query errored)`.

### Slice 3 — Extract `useBrowserTabs` custom hook (~400 lines of effects)

**What moves out:**

- `tabs`, `activeTabId`, `setTabs`, `setActiveTabId` state.
- The 5–8 effects that synchronize backend browser tabs with
  the visible tab strip.
- The render-cache management refs.

**New file:** `session-panel/use-browser-tabs.ts`.

Hook signature:

```ts
export function useBrowserTabs(args: {
  browserToolBlocks: BrowserToolBlock[];
  isStreaming: boolean;
  conversationId: string | undefined;
}) {
  return {
    tabs,
    activeTab,
    selectTab,
    closeTab,
    /* ... */
  };
}
```

**Why now:** Tab-strip state is the most stateful piece of the
component. Lifting it makes the rest of the component
declarative (props → render).

**Risk:** Medium. Multiple effects compose; if you miss one,
tabs will flicker or stop syncing. Verify with the existing
`session-panel.test.tsx` integration assertions before commit.

**Tests:** ~12 cases covering tab insert / remove / focus
transitions when browser blocks change.

### Slice 4 — Extract `BrowserTabStrip` component (already partially extracted)

Lines 1387–1468 already define `BrowserTabStrip` inside the
file. Move it to `session-panel/browser-tab-strip.tsx`.

Same for the small leaf components defined at the bottom of the
file:

- `BrowserNavButton` (2459) → `session-panel/browser-nav-button.tsx`
- `BrowserModeButton` (2483)
- `BrowserCooperationModeMenu` (2513)
- `BrowserProposalOverlay` (2558) → grouped with `ProposalBody`
  (2632)
- `BrowserTracingPanel` (2666) → with `BrowserVisualEventList`,
  `TraceList`, `TraceRoleBadge`, `TraceJson`, `MetadataBlock`,
  `FilesBlock`, `CommitsBlock`, `MetricBand`

**Risk:** Negligible — these are leaf components rendered from
the parent with explicit props.

**Tests:** Each new sub-component file gets a small test for
the visible-state branches (loading / empty / populated).

### Slice 5 — Extract `BrowserTabContent` (line 1904) to its own file

**Lines:** 1904–2458. ~550 lines.

This is the largest sub-component inside the file. It owns the
browser-cooperation overlay rendering, the render-cache
lookup, and the click/scroll/key handlers.

**New file:** `session-panel/browser-tab-content.tsx`.

**Risk:** Medium. The component reaches into the parent's
state for render-cache. After slice 3 the parent's state is
already a hook (`useBrowserTabs`), so the new component
receives everything it needs as props.

### Slice 6 — Extract right-rail detail sections

Each of these is its own file in `session-panel/details/`:

- `SummaryContent` (1469) → `summary.tsx`
- `UsageSection` (1506) → `usage.tsx`
- `MemorySection` (1534) + `MemoryTopItemRow` (1583) →
  `memory.tsx`
- `FilesSection` (1623) → `files.tsx`
- `SourcesSection` (1667) → `sources.tsx`
- `ProjectSection` (1713) + `ProjectGroup` (1752) →
  `project.tsx`
- `DetailTabContent` (1795) → `detail-tab.tsx` (the switch
  router for the right rail)

These are read-only renderers — no state, no effects. Each
takes its data as props and renders.

**Risk:** Negligible.

### Slice 7 — Inline what remains

`SessionPanel` itself should be **under 400 lines** after the
above slices. Its body is now:

```tsx
export function SessionPanel(props: SessionPanelProps) {
  const session = useSessionPanelState(props.conversationId);
  const browser = useBrowserTabs(/* ... */);
  return (
    <PanelLayout>
      <BrowserTabStrip {...browser} />
      <BrowserTabContent {...browser} {...session} />
      <DetailTabContent {...session} />
    </PanelLayout>
  );
}
```

## Pre-condition tests

```bash
cd @desktop-electron
npm run typecheck
npm test -- session-panel
```

The existing `session-panel.test.tsx` is the primary safety
net. Run it after every slice.

## Anti-patterns specific to React decomposition

- **Do not prop-drill more than 2 levels.** If a sub-component
  needs 8 props that come from the parent's state, you've
  extracted at the wrong boundary. Re-evaluate whether the
  sub-component should accept a single context object or a
  smaller responsibility.
- **Do not extract effects without their cleanup.** A React
  effect with cleanup that depends on closure-captured state
  must move *together with* that state. Splitting the effect
  off from the state it depends on creates stale-closure bugs.
- **Do not change render order.** Effects are scheduled in
  the order they appear; moving an effect into a hook is
  fine, but reordering effects across hooks is **not**.
- **Do not use `React.memo` defensively during extraction.**
  If memo wasn't there before, adding it is a behavior
  change (different render skip rules). Add it in a separate
  PR if you decide it's needed.
- **Do not split state across multiple hooks just to be
  tidy.** If two state variables are read in the same effect,
  keep them in the same hook — otherwise the dependency array
  gets harder to reason about.

## Validation gates

```bash
cd @desktop-electron
npm run lint        # runs typecheck
npm test
```

All previously green tests must still pass. The frontend test
count must not decrease.

## Recovery from a broken extraction

If after extraction a test fails:

1. **Read the failing assertion carefully.** Frontend test
   failures usually point at the exact prop that changed.
2. **`git diff` the parent component.** Did a prop name change
   in the JSX? Did a dependency array drop a value?
3. **Revert the extraction commit and re-do it smaller.**
   Don't try to fix forward — the smaller the slice, the
   easier the diff to read.
