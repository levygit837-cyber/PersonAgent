# Decomposition Checklist: agent-message.tsx

## Baseline
- Typecheck: pass
- Tests: 6 passed

## Slice 1 — Content Blocks (`agent-message/content-blocks.tsx`)
- [x] Create module with MarkdownContent, GeneratedImageContent, ChatExecutionStatus, renderToolBlocks, compactToolKindFor, remarkBreakTags helpers
- [x] Wire into agent-message.tsx (import + re-exports)
- [x] Delete originals from agent-message.tsx
- [x] Write content-blocks.test.tsx (25 cases)
- [x] Validation: typecheck pass, 31 tests passed (was 6)
- [ ] Commit and open PR

## Slice 2 — Actions (`agent-message/actions.tsx`)
- [ ] Create module with AgentMessageActions, TooltipIconButton, MemoryTraceBadge, MemoryTraceInspector + subcomponents, memory helpers
- [ ] Wire into agent-message.tsx
- [ ] Delete originals from agent-message.tsx
- [ ] Write actions.test.tsx (10+ cases)
- [ ] Validation: typecheck pass, tests >= baseline + new
- [ ] Commit and open PR

## Slice 3 — Thinking Blocks (`agent-message/thinking-block.tsx`)
- [ ] Create module with thinking blocks orchestration component
- [ ] Wire into agent-message.tsx
- [ ] Delete originals from agent-message.tsx
- [ ] Write thinking-block.test.tsx (5+ cases)
- [ ] Validation: typecheck pass, tests >= baseline + new
- [ ] Commit and open PR
