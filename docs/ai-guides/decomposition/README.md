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
| `_protocol.md`              | **Shared rules.** Read first. Every     |
|                             | playbook below extends it.               |
| `chat_completion.md`        | Backend: `chat_completion.py` (1,938 L) |
| `team_chat_orchestrator.md` | Backend: `team_chat/orchestrator.py` (3,097 L) |
| `lightpanda.md`             | Backend: `infrastructure/browser/lightpanda.py` (5,735 L) |
| `session_panel.md`          | Frontend: `chat/session-panel.tsx` (3,960 L) |
| `chat_store.md`             | Frontend: `stores/chat-store.ts` (3,307 L) |

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

- Over 1,500 lines, **and**
- Mixing more than one responsibility, **and**
- Hot path (called from multiple places, with multiple
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

Cumulative reduction on `chat_completion.py`: 2,742 → 1,098
lines (**–60%**), zero behavior changes, 195+ new unit tests.

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
