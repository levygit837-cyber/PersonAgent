# Playbook: Decompose `blackboard.py`

**Target file:** `@backend/src/personagent/application/team_chat/blackboard.py`
(1,091 lines — 1 class with 26 methods + 14 module-level helper functions)

**Target package:** `@backend/src/personagent/application/team_chat/blackboard/`
(new directory; `__init__.py` re-exports `_Blackboard` and all phase constants)

**Tests:**
- `@backend/tests/unit/test_team_chat_blackboard.py`
- `@backend/tests/unit/test_team_chat_consensus_phase.py` (uses `_Blackboard`)
- `@backend/tests/unit/test_team_chat_coordinator_phase.py` (uses `_Blackboard`)
- `@backend/tests/unit/test_team_chat_agent_turn_runner.py` (uses `_Blackboard`)
- `@backend/tests/unit/test_team_chat_final_synthesis.py` (uses `_Blackboard`)

Read `_protocol.md` first.

## Why this file is hard

`blackboard.py` is the shared state hub for Team Mode. It manages:

1. **Claim graph** — parsing agent responses into structured claim nodes
   (`_claim_nodes_from_turn`, `_normalize_claim_items`, `_claim_node`,
   deduplication via `_claim_signature`).
2. **Coverage tracking** — mapping claims to execution-contract matrix
   items (`_infer_coverage_for_claim`, `_update_coverage`,
   `_normalize_coverage_matrix`, `coverage_ratio`).
3. **Scoring & metrics** — coherency scoring, novelty detection, blocker
   analysis (`_coherency_score`, `_novelty_score`, `_is_real_blocker_text`,
   `_looks_mutating_text`, `_keyword_set`).
4. **Journal & snapshots** — entry publishing, snapshot serialization,
   ballot text generation, memory export (`publish_turn`, `snapshot`,
   `snapshot_text`, `ballot_text`, `memory_snapshot`).
5. **JSON parsing helpers** — fragile hand-written JSON extraction for
   LLM outputs (`_parse_json_object`, `_strip_json_fence`,
   `_parse_partial_claim_graph`, `_extract_complete_json_objects_from_array`).

The 14 module-level functions (lines 761–1091) are pure helpers that
belong in a utilities module, making the main class harder to read.

## Public contract that must be preserved

Consumed by:
- `application/team_chat/orchestrator.py` — creates `_Blackboard`, reads
  snapshots, publishes entries.
- `application/team_chat/consensus_phase.py` — reads ballot text, vote
  triggers, claim state.
- `application/team_chat/phase_loop.py` — publishes turns, reads
  coverage/blockers.
- 5 test files (listed above).

Public surface:
- `_Blackboard` class (all public methods and properties).
- Phase constants: `INDEPENDENT_PHASE`, `BLACKBOARD_PHASE`,
  `DEBATE_PHASE`, `VOTE_PHASE`, `EXECUTION_CONTRACT_PHASE`,
  `COORDINATOR_PLANNING_PHASE`, `COORDINATOR_PHASE`, `TOOL_PHASE_PLAN`,
  `TOOL_PHASE_READ`, `TOOL_PHASE_MUTATING_PROPOSAL`, `TOOL_PHASE_AUDIT`.
- `CLAIM_TYPES`, `MUTATING_TOOL_NAMES`.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract JSON parsing helpers | ⏳ Pending | — | |
| 2 — Extract claim graph analysis | ⏳ Pending | — | |
| 3 — Extract scoring & metrics | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract JSON parsing helpers to `blackboard/json_parsing.py`

**What moves out (~170 lines):**

- `_parse_json_object` (790–805)
- `_strip_json_fence` (805–813)
- `_parse_partial_claim_graph` (813–837)
- `_extract_complete_json_objects_from_array` (837–883)
- `_normalize_coverage_matrix` (883–918)
- `_turn_blackboard_payload` (761–783)
- `_digest` (783–790)

**New class:** None — these stay as module-level pure functions.

**Why first:** Pure functions with no class dependencies. Lowest risk.

**Risk:** Low. All functions are stateless; they receive input and
return output. No side effects.

**Tests:** 15+ cases covering:
- Well-formed JSON, malformed JSON, partial JSON.
- JSON with markdown fences (triple backtick).
- Array extraction with incomplete trailing objects.
- Coverage matrix normalization (empty, single, nested).
- Digest truncation at boundary.
- Payload construction from TurnResult.

### Slice 2 — Extract claim graph analysis to `blackboard/claim_graph.py`

**What moves out (~350 lines):**

Class methods that move to a new `ClaimGraphAnalyzer` class:
- `_claim_nodes_from_turn` (485–607)
- `_normalize_claim_items` (607–676)
- `_claim_node` (676–710)
- `_infer_coverage_for_claim` (710–728)
- `_update_coverage` (729–760)

Module-level helpers:
- `_claim_signature` (940–945)
- `_novelty_score` (945–961)
- `_string_list` (1067–1080)

**Constructor:**
```python
class ClaimGraphAnalyzer:
    def __init__(
        self,
        *,
        claim_nodes: list[dict[str, Any]],
        claim_signatures: set[str],
        duplicates: list[dict[str, Any]],
        coverage_matrix: list[dict[str, Any]],
        agent_novelty_scores: dict[str, list[float]],
    ) -> None: ...
```

**Why now:** This is the largest cluster of tightly-coupled methods.
They all share `_claim_nodes`, `_claim_signatures`, `_duplicates`,
and `_coverage_matrix` state. Extracting them makes the main
`_Blackboard` class 30% smaller.

**Risk:** Medium. The claim graph methods mutate shared state
(`_claim_nodes`, `_coverage_matrix`). The `_Blackboard` class must
hold a reference to the `ClaimGraphAnalyzer` and pass state by
reference.

**Tests:** 25+ cases covering:
- Claim extraction from structured JSON vs free-text.
- Deduplication via signature matching.
- Tool result and proposal node creation.
- Coverage inference with/without coverage matrix.
- Coverage update with generic matching rules.
- Novelty scoring with empty/populated existing nodes.

### Slice 3 — Extract scoring & metrics to `blackboard/scoring.py`

**What moves out (~150 lines):**

Module-level pure functions:
- `_coherency_score` (918–940)
- `_is_real_blocker_text` (961–997)
- `_looks_mutating_text` (997–1012)
- `_keyword_set` (1012–1036)
- `_compact_workspace_memory` (1036–1067)
- `_clamp_float` (1080–1088)
- `_now_iso` (1088–1091)

**New class:** None — pure functions.

**Why now:** After slices 1 and 2, these are the remaining
module-level helpers. Extracting them leaves `_Blackboard` as a
clean coordinator with only journal/snapshot logic (~500L target).

**Risk:** Low. All stateless functions.

**Tests:** 15+ cases covering:
- Coherency score with matching/non-matching keywords.
- Blocker detection (real blockers vs soft suggestions).
- Mutating text detection patterns.
- Keyword set extraction (stopword removal, normalization).
- Workspace memory compaction edge cases.
- Float clamping at boundaries.

## Anti-patterns specific to this file

- **`dict[str, Any]` everywhere.** The claim nodes, coverage matrix
  items, and entries are all untyped dicts. During extraction, preserve
  this exactly — do not introduce dataclasses for these in the
  extraction PR. A follow-up PR can add types.
- **Underscore-prefixed class name.** `_Blackboard` is private by
  convention but imported directly in 5+ files. Keep the name as-is
  during extraction.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run mypy src/personagent/application/team_chat/
uv run pytest tests/unit/test_team_chat_blackboard.py \
             tests/unit/test_team_chat_consensus_phase.py \
             tests/unit/test_team_chat_coordinator_phase.py \
             tests/unit/test_team_chat_agent_turn_runner.py \
             tests/unit/test_team_chat_final_synthesis.py \
             tests/test_team_chat_orchestrator.py \
             -v
uv run pytest tests/unit/ -q --no-header \
             --deselect tests/unit/test_prompt_builder.py::TestPromptBuilder::test_agent_state_overlays_are_compact
```
