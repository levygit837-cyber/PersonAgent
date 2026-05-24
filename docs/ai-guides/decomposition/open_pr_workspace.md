# Playbook: Decompose `open-pr-workspace.tsx`

**Target file:** `@desktop-electron/src/components/open-pr/open-pr-workspace.tsx`
(1,350 lines)

**Target directory:** `@desktop-electron/src/components/open-pr/open-pr-workspace/`

**Tests:**
- `@desktop-electron/src/components/open-pr/open-pr-workspace.test.tsx`

Read `_protocol.md` first.

## Why this file is hard

`OpenPrWorkspace` handles the entire PR creation flow:

1. **Diff viewer** — displaying file changes with syntax highlighting.
2. **Review form** — title, description, reviewer selection.
3. **Branch management** — base/head branch selection and validation.
4. **State management** — multi-step wizard with validation at each step.

## Public contract that must be preserved

Props interface must remain identical.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract helpers + types | ⏳ Pending | — | |
| 2 — Extract diff viewer | ⏳ Pending | — | |
| 3 — Extract review form | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract helpers to `open-pr-workspace/helpers.ts`

**What moves out:** Pure functions, constants, type definitions.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 2 — Extract diff viewer to `open-pr-workspace/diff-viewer.tsx`

**What moves out:** File diff display component.

**Risk:** Medium.

**Tests:** 10+ cases.

### Slice 3 — Extract review form to `open-pr-workspace/review-form.tsx`

**What moves out:** PR form fields, validation, submission.

**Risk:** Medium.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @desktop-electron
npm run typecheck
npm test -- --testPathPattern open-pr-workspace
```
