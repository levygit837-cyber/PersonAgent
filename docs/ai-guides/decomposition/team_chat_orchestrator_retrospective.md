# Retrospective: Team Chat Orchestrator Decomposition

**Date:** 2026-05-23
**Author:** Devin agent
**Scope:** Slices 4–6 of `team_chat/orchestrator.py` decomposition

This document records the real errors, failures, and fixes encountered during
extraction. It exists so future agents (human or LLM) can avoid the same
traps and understand why certain decisions were made.

---

## Slice 4 — Extract `ConsensusPhase`

### Error 1: Missing `import json` in new module

**Symptom:**
```
F821 Undefined name `json`
  --> consensus_phase.py:277:57
```

**Root cause:** `_vote_messages` uses `json.dumps()` inside an f-string.
When moved from `orchestrator.py` (which had `import json` at module top) to
`consensus_phase.py`, the import was not copied.

**Fix:** Added `import json` to `consensus_phase.py`.

**Lesson:** Always audit imports used *inside* the methods being moved —
not just the ones at the top of the god file.

---

### Error 2: Backward-compat import break

**Symptom:**
```
ImportError: cannot import name '_parse_vote_payload'
  from 'personagent.application.team_chat.orchestrator'
```

**Root cause:** Existing test imports `_parse_vote_payload` directly from
`orchestrator`. When the function moved to `consensus_phase.py`, the test
broke.

**Fix:** Added a re-export in `orchestrator.py`:
```python
from personagent.application.team_chat.consensus_phase import _parse_vote_payload
```

**Lesson:** Before deleting any function from the god file, `grep` every
name in `tests/` to find direct imports. Re-export with `# noqa: F401`.

---

### Error 3: Mypy "Returning Any" on lazy imports

**Symptom:**
```
error: Returning Any from function declared to return "dict[str, Any]"
error: Returning Any from function declared to return "float | None"
```

**Root cause:** `_parse_vote_payload` and `_regex_number` used lazy imports
(`from personagent.application.team_chat.blackboard import _parse_json_object`)
inside the function body. Mypy cannot infer types from lazy imports.

**Fix:** Moved `_parse_json_object` and `_clamp_float` to top-level imports
in `consensus_phase.py`. No circular import risk because `blackboard.py`
does not import from `consensus_phase.py`.

**Lesson:** Lazy imports inside methods break mypy inference. Only use lazy
imports when there is a genuine circular-import risk. Verify with
`python -c "import module"`.

---

### Error 4: Dead code `_should_vote`

**Discovery:** While mapping the consensus surface, found `_should_vote` —
a top-level function that was never called by the orchestrator or the
blackboard (`blackboard.vote_triggers` has its own logic).

**Decision:** Removed it entirely. This is the *only* behavior change across
all slices — strictly dead-code elimination.

**Lesson:** Use `grep -r "_should_vote" src/ tests/` before assuming a
function is part of the public contract.

---

## Slice 5 — Extract `CoordinatorPhase`

### Error 5: StrReplaceFile failed on large blocks

**Symptom:** `StrReplaceFile` repeatedly failed to match `_execution_contract_messages`
and `_coordinator_planning_messages`.

**Root cause:** The text blocks were ~80 lines each with nested quotes and
f-strings. Subtle whitespace or quote-escaping differences prevented exact
string matching.

**Fix:** Fell back to a Python script that found methods by `def` line and
deleted by line indices:
```python
for i, line in enumerate(lines):
    if '    def _execution_contract_messages(' in line:
        start_idx = i
```

**Lesson:** For large method removals (>50 lines), programmatic line-based
deletion is more reliable than string replacement.

---

### Error 6: Ruff auto-removed "unused" imports that were actually used

**Symptom:** After `ruff check --fix`, imports like `_coordinator_focus_assignments`
were stripped from `orchestrator.py`.

**Root cause:** The functions were referenced inside `_run_execution_contract`
and `_run_coordinator_planning` — but those methods were deleted *before* ruff
ran. Ruff saw no remaining references and removed the imports.

**Fix:** Let ruff clean up, then verify the remaining file compiles. The
extracted module (`coordinator_phase.py`) has its own imports.

**Lesson:** Run ruff *after* deletion, not before. Expect to lose imports
that were only referenced by deleted code.

---

### Error 7: Mypy error count dropped from 6 → 4

**Unexpected positive:** Moving `_coverage_matrix_from_payload` and
`_normalize_subproblems` out of `orchestrator.py` eliminated 2 mypy errors.
The remaining 4 errors are in `_tool_use_context_from_request` and
`_turn_coherency_score` — unrelated to the coordinator surface.

**Lesson:** Extraction can *improve* type-checking by isolating functions
that had ambiguous inference in the large file.

---

## Slice 6 — Extract `FinalSynthesis`

### Error 8: `FinalSynthesis` import never reached `orchestrator.py`

**Symptom:**
```
F821 Undefined name `FinalSynthesis`
```

**Root cause:** The `StrReplaceFile` for adding the import block failed
silently (old string did not match). The call-site replacement succeeded,
but the import was missing.

**Fix:** Added the import manually after verifying the exact text around
line 43.

**Lesson:** After any `StrReplaceFile`, always grep for the new symbol in
the target file to confirm the import landed.

---

### Error 9: `FrozenInstanceError` on `TeamChatRequest`

**Symptom:**
```
dataclasses.FrozenInstanceError: cannot assign to field 'max_tokens'
```

**Root cause:** Test tried to mutate `request.max_tokens = 500` after
creation. `TeamChatRequest` is a `@dataclass(frozen=True)`.

**Fix:** Changed the test helper to accept `max_tokens` as a constructor
argument:
```python
def _request(message="Hello", max_tokens=-1):
    return TeamChatRequest(..., max_tokens=max_tokens)
```

**Lesson:** Always check if dataclasses are frozen before mutating them in
tests. Prefer constructor arguments over post-creation mutation.

---

### Error 10: `_votes_text` import path changed

**Symptom:**
```
F401 `_votes_text` imported but unused
```

**Root cause:** `_votes_text` was originally in `orchestrator.py`. After
Slice 4 it moved to `consensus_phase.py`. The orchestrator still imported it
for `_final_messages` — but after Slice 6, `_final_messages` also moved.

**Fix:** Removed the now-unused import from `orchestrator.py`.
`final_synthesis.py` imports `_votes_text` directly from `consensus_phase.py`.

**Lesson:** Track function migrations across slices. A function's "home"
changes, and downstream consumers need updated imports.

---

## Cross-cutting patterns

### Circular import mitigation

All three new modules (`consensus_phase`, `coordinator_phase`, `final_synthesis`)
use lazy imports for shared helpers still living in `orchestrator.py`:

```python
from personagent.application.team_chat.orchestrator import (
    _agent_tool_context,
    _duration_ms,
    _runtime_context,
    _team_policy_overlay,
)
```

These are imported *inside* methods, not at module top. This avoids:
- `orchestrator.py` → `new_module.py` (constructor + call sites)
- `new_module.py` → `orchestrator.py` (lazy import of helpers)

**When to use lazy vs top-level:**
- Top-level is safe when the target module does *not* import back.
- Lazy is required when there is a mutual dependency.
- After Slice 8 (inline outer loop), these helpers should move to a shared
  `team_chat/_helpers.py` and all lazy imports become top-level.

---

### Test count tracking

| Slice | New tests | Total team_chat tests | Regression total |
|-------|-----------|----------------------|------------------|
| 3 (AgentTurnRunner) | 13 | 58 | 561 |
| 4 (ConsensusPhase) | 26 | 84 | 687 |
| 5 (CoordinatorPhase) | 18 | 102 | 759 |
| 6 (FinalSynthesis) | 6 | 108 | 765 |

**Pattern:** Each slice adds 6–26 tests. The baseline (11 orchestrator tests)
never decreases. Regression grows as unit tests accumulate.

---

## Uncorrected errors (mypy)

These errors existed **before** the decomposition started and were
**preserved verbatim** per the protocol ("no behavior changes"). They
should be fixed in dedicated follow-up PRs, not extraction PRs.

### 1. `agent_turn_runner.py:278` — `Returning Any` from `_tool_schemas_for_agent`

```python
def _tool_schemas_for_agent(...) -> list[dict[str, Any]]:
    ...
    return self._tool_registry.openai_schemas(...)  # <-- returns Any
```

**Why:** `ToolRegistry.openai_schemas()` has no return type annotation.
**Fix:** Add `-> list[dict[str, Any]]` to `ToolRegistry.openai_schemas()`.

---

### 2. `blackboard.py:661` — Incompatible type assignment

```python
extra = {}  # mypy infers dict[str, list[str]] from next line
extra["coverage"] = self._infer_coverage_for_claim(...)  # list[str]
extra["coverage_inferred"] = True   # <-- bool into dict[str, list[str]]
```

**Why:** `_infer_coverage_for_claim` returns `list[str]`, so mypy narrows
`extra` to `dict[str, list[str]]`. Then assigning `bool` fails.

**Fix:** Annotate `extra: dict[str, Any] = {}` explicitly.

---

### 3. `blackboard.py:663` — Incompatible type assignment

```python
extra["mutating"] = True   # <-- bool into dict[str, list[str]]
```

**Same root cause as #2.**

**Fix:** Same fix — annotate `extra: dict[str, Any] = {}`.

---

### 4. `consensus_phase.py:105` — `Returning Any` from `_parse_vote_payload`

```python
def _parse_vote_payload(content: str) -> dict[str, Any]:
    parsed = _parse_json_object(content)  # returns Any
    if _looks_like_vote(parsed):
        return parsed   # <-- Any into dict[str, Any]
```

**Why:** `_parse_json_object` has return type `Any`.

**Fix:** Add proper return type to `_parse_json_object` or cast:
```python
return dict(parsed)  # type: ignore[no-any-return]
```

---

### 5. `consensus_phase.py:157` — `Returning Any` from `_regex_number`

```python
def _regex_number(...) -> float | None:
    ...
    return _clamp_float(match.group(1), 0, 1)  # _clamp_float returns Any
```

**Why:** `_clamp_float` is imported from `blackboard.py` which has no type
annotation on that function.

**Fix:** Add `-> float` to `_clamp_float` in `blackboard.py`.

---

### 6. `coordinator_phase.py:46` — `Returning Any` from `_coverage_matrix_from_payload`

```python
def _coverage_matrix_from_payload(...) -> list[dict[str, Any]]:
    matrix = _normalize_coverage_matrix(...)  # returns Any
    if matrix:
        return matrix   # <-- Any into list[dict[str, Any]]
```

**Why:** `_normalize_coverage_matrix` has no return type annotation.

**Fix:** Add `-> list[dict[str, Any]]` to `_normalize_coverage_matrix`.

---

### 7. `orchestrator.py:875` — `union-attr` on `_tool_proposal`

```python
def _tool_proposal(raw_call: dict[str, Any], *, reason: str) -> dict[str, Any]:
    function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
    name = str(function.get("name") or raw_call.get("name") or "tool")
    # ^ function is dict[str, Any] | {} — mypy sees the `else {}` branch
```

**Why:** Mypy infers `function` as `Any | dict[Any, Any] | None` because
`raw_call.get("function")` returns `Any`. The `isinstance` guard doesn't
narrow `function` enough.

**Fix:** Use a narrower type for `raw_call` or explicit cast:
```python
function = raw_call.get("function")
function_dict = function if isinstance(function, dict) else {}
```

---

### 8. `orchestrator.py:944` — `Returning Any` from `_turn_coherency_score`

```python
def _turn_coherency_score(...) -> float:
    ...
    return round(_clamp_float(raw, 0, 1), 3)  # _clamp_float returns Any
```

**Why:** `_clamp_float` has no return type.

**Fix:** Add `-> float` to `_clamp_float` in `blackboard.py`.

---

### 9. `orchestrator.py:945` — `Returning Any` from `_turn_coherency_score`

```python
    return round(_coherency_score(...), 3)  # _coherency_score returns Any
```

**Why:** `_coherency_score` in `blackboard.py` has no return type.

**Fix:** Add `-> float` to `_coherency_score` in `blackboard.py`.

---

## What to do differently next time

1. **Document errors in real-time.** Instead of reconstructing from memory,
   keep a running log file during extraction.
2. **Grep before delete.** Always search `tests/` and `src/` for every
   symbol before removing it.
3. **Prefer line-based deletion.** For methods >40 lines, use line indices
   instead of string replacement.
4. **Check frozen dataclasses early.** Verify `frozen=True` before writing
   tests that mutate objects.
5. **Run mypy on the new module in isolation.** Before wiring into the
   orchestrator, type-check the extracted module standalone to catch import
   issues early.
6. **File follow-up issues for uncorrected errors.** The 9 mypy errors above
   should each have a dedicated issue or be batched into a "type-hardening"
   PR after Slice 8 completes.

---

## Slice 7 — MessageBuilders extraction (PR #34)

### Error location changes

Three mypy errors moved from `orchestrator.py` to `messages.py` because the
underlying code was relocated verbatim:

| Old location | New location | Error |
|--------------|--------------|-------|
| `orchestrator.py:875` | `messages.py:240` | `union-attr` on `function.get("name")` |
| `orchestrator.py:944` | `messages.py:309` | `Returning Any` from `_turn_coherency_score` |
| `orchestrator.py:945` | `messages.py:310` | `Returning Any` from `_turn_coherency_score` |

The fixes remain the same as documented in the Slice 4–6 catalog above.

### Lessons

* **Re-exports for test imports:** `_parse_json_object` was imported by the
  existing integration test. Removing it from `orchestrator.py` broke test
  collection. Always grep `tests/` for every symbol before deleting.
* **Lazy-import repointing is safe but verbose:** Updating 4 modules to import
  from `messages.py` instead of `orchestrator.py` was mechanical and produced
  a clean diff. Keeping the old lazy imports would have worked too, but
  repointing removes a hidden circular dependency.
* **Ruff unused-import in tests:** Importing phase constants for "coverage"
  without using them in assertions triggers F401. Only import what the test
  actually exercises.
