# Decomposition Playbooks

This directory exists so any agent (human or LLM) can pick up
the work of breaking PersonAgent's god files into smaller,
coherent, testable modules **without losing behavior** and
**without needing the original author's context.**

If you're an agent that landed here, read this file first,
then `_protocol.md`, then the playbook for whatever file you
were asked to decompose.

## When to use these playbooks

Use them when you've been asked to:

- Reduce the line count of a specific file.
- Split a class with too many responsibilities.
- Make a god file testable in isolation.
- Continue the decomposition started in Phase 1 (PRs #7–#11
  for `chat_completion.py`).

Do **not** use them when:

- You're adding a new feature (the playbook is about
  reorganizing existing code, not adding new behavior).
- You're fixing a bug (extraction PRs preserve behavior
  verbatim).
- The file in question isn't listed below (different files
  may need different patterns).

## Files in this directory

| File                        | Purpose                                  |
| --------------------------- | ---------------------------------------- |
| `README.md`                 | This file. Index + when to use what.     |
| `_protocol.md`              | **Shared rules.** Read first. Every playbook below extends it. |
| `god-files-master-plan.md`  | **Master plan.** Full inventory, ASCII tree, priority, rules. |
| **Backend — already decomposed** | |
| `chat_completion.md`        | ✅ `chat_completion.py` (2,742 → 483 L, −82%) |
| `team_chat_orchestrator.md` | ✅ `team_chat/orchestrator.py` (3,097 → 127 L, −96%) |
| **Backend — in progress** | |
| `lightpanda.md`             | 🔄 `browser/lightpanda.py` (5,735 → 1,469 L, slices 1–14 done, Phase 3 needed) |
| **Backend — planned** | |
| `browser_tools.md`          | ✅ `tools/browser_tools/factories.py` (2,786 → 61 L, −98%) |
| `operational_memory_repository.md` | ✅ `persistence/operational_memory_repository.py` (1,938 → 251 L, −87%) |
| `routes_chat.md`            | 🔄 `api/routes/chat/__init__.py` (1,905 → 612 L, 6 slices merged) |
| `routes_workspace.md`       | ✅ `api/routes/workspace/` (1,576 → 30 L, −98%) |
| `routes_sessions.md`        | ✅ `api/routes/sessions/` (1,471 → 166 L, −89%) |
| `browser_cooperation.md`    | ✅ `services/browser_cooperation/` (1,292 → 35 L, −97%) |
| `blackboard.md`             | ⏳ `team_chat/blackboard.py` (1,091 L) |
| `operational_memory_service.md` | ⏳ `services/operational_memory.py` (1,075 L) |
| `llm_adapters.md`           | 🔄 `llm/vertex_ai` ✅ (1,064 → 31 L); `codex` ⏳ (944 L); `kimi` ⏳ (892 L) |
| `session_panel_service.md`  | ⏳ `services/session_panel.py` (976 L) |
| `persistence_models.md`     | ⏳ `persistence/models.py` (919 L, 31 ORM classes) |
| `session_titles.md`         | ⏳ `services/session_titles.py` (848 L) |
| `filesystem_tools.md`       | ⏳ `tools/filesystem_tools.py` (810 L) |
| **Frontend — planned** | |
| `session_panel.md`          | ⏳ `chat/session-panel.tsx` (3,960 L) |
| `chat_store.md`             | ⏳ `stores/chat-store.ts` (3,307 L) |
| `input_dock.md`             | ⏳ `chat/input-dock.tsx` (1,976 L) |
| `agent_message.md`          | ⏳ `chat/agent-message.tsx` (1,419 L) |
| `open_pr_workspace.md`      | ⏳ `open-pr/open-pr-workspace.tsx` (1,350 L) |
| `browser_mirror.md`         | ⏳ `session-panel/browser-mirror.ts` (1,261 L) |
| `api_client.md`             | ⏳ `api/client.ts` (1,231 L) |
| `file_viewer_panel.md`      | ⏳ `chat/file-viewer-panel.tsx` (1,079 L) |
| `tool_block.md`             | ⏳ `chat/tool-block.tsx` (919 L) |
| `chat_types.md`             | ⏳ `types/chat.ts` (887 L, 71 exports) |

## How a playbook works

Each per-file playbook contains:

1. **Status table** — which slices are already merged.
2. **Public contract** — methods/exports that cannot change.
3. **Proposed slices in order** — concrete extraction plan.
   Each slice has:
   - What moves out (with line ranges).
   - Collaborators to inject.
   - Test plan (minimum cases).
   - Risk assessment.
   - Why this slice is right *now* (vs later).
4. **Anti-patterns** specific to that file.
5. **Validation gates** — exact commands to run.

Each slice → one PR → one merge → next slice. Never bundle.

## How to use a playbook end-to-end

1. **Pick the playbook.** Match it to the file the user named.
2. **Read `_protocol.md`.** This is the shared contract for
   every playbook. Skipping it produces non-reviewable PRs.
3. **Read the playbook's status table.** Find the first
   "next" slice.
4. **Run the pre-condition validation gates.** Record the
   green test count. If anything fails before you start, fix
   the baseline first (file an issue if you can't).
5. **Execute the slice** by following the steps in
   `_protocol.md` Section "Extraction pattern":
   - Map the surface.
   - Create the module.
   - Wire into the parent.
   - Delete the originals.
   - Write the tests.
   - Run all validation gates.
6. **Open the PR** using `fetch_pr_template` →
   `git_create_pr`. Use the commit / PR templates at the bottom
   of `_protocol.md`.
7. **Wait for CI** with `wait_mode="all"`. Fix any failures.
8. **Update the playbook's status table** in a follow-up
   commit (or include it in the same PR).
9. **Stop.** Do not start the next slice — let a human review
   and merge first. The chain integrity matters more than
   throughput.

## How to decide if a new file deserves a playbook

If the file is:

- Over **800 lines** (1,500+ is severe), **and**
- Mixing **more than one responsibility**, **and**
- **Hot path** (called from multiple places, with multiple
  collaborators),

then it likely deserves a playbook. Write a new one in this
directory following the structure of the existing playbooks:

1. Why this file is hard.
2. Public contract.
3. Proposed slices (in priority order, low-risk → high-risk).
4. Anti-patterns specific to the file.
5. Validation gates.

## How this directory was built

These playbooks were created in May 2025 after executing five
slices on `chat_completion.py` (PRs #7–#11) and discovering
that the same pattern would apply to four other god files. The
playbooks codify what worked so future agents don't have to
rediscover it.

PR chain so far (Phase 1.2):

- #7 — Helpers + state dataclasses
- #8 — `ConversationCompactor`
- #9 — `OperationalMemoryCapture`
- #10 — `MemoryRecallCoordinator`
- #11 — `PromptSurfacePreparer`
- #13 — `PromptPackageBuilder`
- #14 — `ToolResultHandler`
- #16 — `MessagePreparer`
- #17 — `ToolContextBuilder`
- #19 — `AfterTurnCoordinator`
- #20 — `MediaPolicyHandler`
- #21 — `ConversationLifecycleHandler`
- #23 — `StreamChunkNormalizer`
- #24 — `StreamingTurnState` dataclass (prep)
- #25 — `AssistantPassRunner`
- #28 — `StreamingTurnExecutor`
- #29 — `ToolRuntime` + `TurnContextResolver` + `schedule_background`

Cumulative reduction on `chat_completion.py`: 2,742 → 483
lines (**–82%**), zero behavior changes, 325+ new unit tests.

## Frequently-asked questions

**Q: Should I rename the methods I extract?**
No. Keep the verb. Class name carries the noun. See
`_protocol.md` § "Anti-patterns".

**Q: What if I find a bug while extracting?**
Land the extraction PR with the bug preserved verbatim. File
a follow-up to fix. See `_protocol.md` § "When you discover a
behavior bug mid-extraction".

**Q: What if a slice ends up bigger than expected?**
Split it. Two smaller PRs are always better than one big PR.

**Q: What if the playbook's status table is wrong?**
Update it in the same PR as the slice you just landed. The
playbook is a living document.

**Q: Can I do two slices in one PR?**
No. One slice = one PR. Period.

**Q: Can I skip writing the tests?**
No. New code needs tests. See `_protocol.md` § "Validation
gates".
