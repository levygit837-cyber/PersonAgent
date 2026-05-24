# Playbook: Decompose `team_chat/orchestrator.py`

**Target file:** `@backend/src/personagent/application/team_chat/orchestrator.py`
(3,097 lines)

**Target package:** `@backend/src/personagent/application/team_chat/`
(extend the existing package; the file currently lives alongside
`contracts.py`)

**Test file (existing, big!):** `@backend/tests/test_team_chat_orchestrator.py`

Read `_protocol.md` first. The rules in this file extend that
protocol; they don't replace it.

## Why this file is hard

Team Mode is the most stateful subsystem we have. The orchestrator
coordinates:

1. Multiple agents executing turns in parallel.
2. A shared `_Blackboard` that records claims, evidence,
   blockers, and coverage between rounds.
3. A coordinator/judge agent that publishes execution contracts
   and guidance after each round.
4. A voting phase that produces a chosen plan / chosen path.
5. A final-synthesis phase that produces the user-facing answer.

A naive extraction risks breaking subtle invariants like
"coverage matrix is recomputed after every turn" or "the
coordinator only sees turns published before its own". Take the
extraction slowly. Land one slice at a time. Pin every observable
side effect with a test before extracting.

## Public contract that must be preserved

The orchestrator is consumed by:

- `interfaces/api/team_chat_routes.py`
- `interfaces/websocket/team_chat_streaming.py`

Public entry points:

- `TeamChatOrchestrator.__init__(...)`
- `async def execute(request: TeamChatRequest) -> TeamChatResponse`

Constructor kwargs must keep their names. The dataclass-flavored
data types (`_TurnResult`, `_Vote`, `_CoordinatorGuidance`,
`_ExecutionContract`, `_ToolAudit`, `_BlackboardEntry`,
`_QueuedTurnItem`) are private but consumed by tests — when
extracting, expose them through `team_chat/__init__.py` so test
imports don't break.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract dataclasses + types to `team_chat/types.py` | ✅ Merged | — | 76 lines removed from orchestrator.py |
| 2 — Extract `_Blackboard` to `team_chat/blackboard.py` | ✅ Merged | — | 1,042 lines removed from orchestrator.py |
| 3 — Extract `AgentTurnRunner` | ✅ Merged | #21 | 405 lines removed from orchestrator.py |
| 4 — Extract `ConsensusPhase` | ✅ Merged | #26 | 230 lines removed from orchestrator.py |
| 5 — Extract `CoordinatorPhase` | ✅ Ready | #27 | 279 lines removed from orchestrator.py |
| 6 — Extract `FinalSynthesis` | ⏳ Pending | — | |
| 7 — Extract `MessageBuilders` to `team_chat/messages.py` | ⏳ Pending | — | |
| 8 — Inline what remains (the outer phase loop) | ⏳ Pending | — | |

## Proposed slices (in order; never reorder without justification)

### Slice 1 — Extract dataclasses + types to `team_chat/types.py`

**What moves out:**

- `_TurnResult` (62–80)
- `_Vote` (81–92)
- `_CoordinatorGuidance` (93–103)
- `_ExecutionContract` (104–116)
- `_ToolAudit` (117–123)
- `_BlackboardEntry` (124–147)
- `_QueuedTurnItem` (148–155)

**Why first:** No methods, no behavior. This is the cheapest
de-risking move and lets later slices reference the types
without circular imports. Underscore-prefix aliases stay in
`orchestrator.py` for backward compat with the existing test
file.

**Risk:** Negligible.

**Tests to add:** None (pure types). Existing test file must
still pass.

### Slice 2 — Extract `_Blackboard` to `team_chat/blackboard.py`

**What moves out:**

- `_Blackboard` class (156–875) — ~720 lines

This is a self-contained class with no use-case dependencies. It
owns:
- the list of `_BlackboardEntry` items
- the coverage matrix
- claim normalization / claim-node building
- delta-guard text generation
- vote-trigger detection
- ballot text rendering

**Public methods that must not change:**

- `publish_execution_contract`
- `publish_turn`
- `publish_coordinator_guidance`
- `snapshot`, `snapshot_text`
- `latest_focus_for(agent_id)`, `latest_lane_for(agent_id)`
- `delta_guard_text(agent_id)`
- `claim_delta_for(entry)`
- `coverage_matrix`, `coherency_summary`
- `novelty_by_agent`, `coverage_ratio`
- `has_real_blocker`, `has_conflict`, `has_mutating_proposal`
- `should_skip_debate`, `fast_vote_ready`
- `vote_triggers(round_index, team)`
- `ballot_text`, `memory_snapshot`

**Tests required (new file `tests/unit/test_team_chat_blackboard.py`):**

Minimum 25 cases — this is a core stateful object.

- Empty blackboard reports `coverage_ratio == 0.0` and no
  blockers.
- `publish_turn` appends an entry and updates the coverage
  matrix.
- `publish_execution_contract` records the contract once and
  ignores duplicates (verify by checking entry count).
- `claim_delta_for` returns the same shape across two turns when
  the agent didn't change claims (zero delta).
- `delta_guard_text(agent_id)` produces guidance referencing the
  agent's own previous claims when they've published before, and
  a "no prior turn" message otherwise.
- `should_skip_debate` returns True when the coverage ratio
  passes the configured threshold and there are no blockers.
- `fast_vote_ready` returns True when:
  - coverage threshold passed
  - all agents have published at least one turn
  - no real blocker
- `vote_triggers(round_index, team)` produces a non-empty list
  when fast-vote criteria are met and an empty list otherwise.
- `coverage_matrix` is invariant under permutation of
  `publish_turn` calls when the claim content is identical.
- `has_conflict` returns True when two agents publish
  contradictory claims; False otherwise.
- `coherency_summary` returns counts that match the underlying
  entries (no stale state).

**Risk:** Medium. The class is big but pure (no I/O, no async).
The risk is missing an invariant that the orchestrator depends
on. Mitigate by reading the orchestrator's calls to the
blackboard *first* and listing every method it uses — if any
public method isn't in the test plan above, add it.

### Slice 3 — Extract `AgentTurnRunner` (~400 lines)

**What moves out:**

- `_run_agent_turns_parallel` (1322–1373)
- `_run_agent_turn` (1374–1533)
- `_tool_schemas_for_agent` (1534–1546)
- `_execute_agent_tools` (1547–1672)

**Why this slice:** Per-agent turn execution is the single
biggest source of complexity inside `execute()`. Pulling it out
makes the outer phase loop (briefing → debate → consensus →
execution) readable.

**Collaborators:**

- `chat_use_case: ChatCompletionUseCase` (the agent's LLM call
  goes through the chat use case)
- `tool_registry`, `tool_runtime_config`
- `blackboard: _Blackboard` (passed per call, not stored)

**Tests:** 15+ cases covering:
- Single agent, no tools, no blackboard contention.
- Parallel agents, deterministic ordering of `_BlackboardEntry`
  writes (use an asyncio gather → record-then-publish pattern).
- Tool-execution branch: when the agent emits tool calls,
  `_execute_agent_tools` runs and the result feeds back into the
  next pass.
- Provider failures inside one agent don't crash the others.

**Risk:** Medium-high. Touches the chat use case and the tool
orchestrator. Mitigate by re-using stubs for both
collaborators (already done in
`tests/test_team_chat_orchestrator.py`).

### Slice 4 — Extract `ConsensusPhase` (~150 lines)

**What moves out:**

- `_run_vote` (1673–1719)
- `_vote_messages` (2025–2062)

**Collaborators:**

- `chat_use_case: ChatCompletionUseCase`
- `blackboard: _Blackboard`

**Tests:** 10+ cases covering the vote-tally logic, tie-breaking
rules, and message-construction for the voter prompt.

**Risk:** Low. Voting is a pure function over blackboard state +
LLM response.

### Slice 5 — Extract `CoordinatorPhase` (~200 lines)

**What moves out:**

- `_run_execution_contract` (1720–1768)
- `_run_coordinator_planning` (1769–1811)
- `_execution_contract_messages` (1945–1985)
- `_coordinator_planning_messages` (1986–2024)

**Collaborators:** same as `ConsensusPhase`.

**Tests:** 10+ cases covering contract publication, planning
guidance, and skip rules (e.g. coordinator skipped when no
mutating proposal exists).

**Risk:** Low-medium.

### Slice 6 — Extract `FinalSynthesis` (~120 lines)

**What moves out:**

- `_synthesize_final` (1812–1855)
- `_final_messages` (2063–end)

**Tests:** 8+ cases. The final-synthesis surface is small.

**Risk:** Low.

### Slice 7 — Extract `MessageBuilders` to `team_chat/messages.py` (~250 lines)

**What moves out:**

- `_agent_messages` (1884–1944)

After the previous slices, `_agent_messages` is the last
message-construction helper still on the orchestrator. Group it
with `messages.py` so all message construction lives in one
module.

**Risk:** Low.

### Slice 8 — Inline what remains (the outer phase loop)

After slices 1–7, `TeamChatOrchestrator.execute()` should be a
relatively flat function that:
1. Initializes the blackboard.
2. Runs the briefing phase.
3. Loops through debate rounds, delegating to `AgentTurnRunner`
   + `CoordinatorPhase` + checking `should_skip_debate`.
4. Runs `ConsensusPhase` to vote.
5. Runs `FinalSynthesis` to produce the user-facing answer.

At this point the file should be **under 800 lines** and
read like a high-level phase coordinator.

## Pre-condition tests

Before starting any slice, run:

```bash
cd @backend
uv run pytest tests/test_team_chat_orchestrator.py -v --no-header
```

Record the green count. **It must not decrease across slices.**

The existing test file is large and exercises Team Mode
end-to-end with stubbed LLM responses. Use it as the safety net
for every slice; add new unit tests in `tests/unit/test_team_chat_*.py`
rather than touching this file.

## Anti-patterns specific to this file

- **Do not move the dataclasses inside `_Blackboard`.** They are
  imported by tests and consumed by the use case.
- **Do not split `_Blackboard` across two files.** Its methods
  share `self._entries` and `self._coverage` heavily — a split
  would create coupling without isolation. Move it whole, or
  not at all.
- **Do not start with the phase loop.** The phase loop is the
  thing all the helpers feed into; extracting it first leaves
  nowhere to put the helpers.
- **Do not refactor the `_Vote` tie-breaking rules during
  extraction.** They are weird (look for `'tie'` literal) but
  they are tested. Preserve verbatim; file a follow-up if you
  spot a bug.

## Validation gates

```bash
cd @backend
uv run ruff check --fix src/ tests/
uv run ruff check src/ tests/
uv run mypy src/personagent/application/team_chat \
            src/personagent/application/use_cases/chat \
            src/personagent/application/state \
            src/personagent/domain/models/conversation.py
uv run pytest tests/test_team_chat_orchestrator.py tests/unit/test_team_chat_*.py \
              -q --no-header
```

Then the full regression command from `_protocol.md`.
