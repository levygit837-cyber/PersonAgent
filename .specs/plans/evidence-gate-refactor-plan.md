# Evidence Gate Refactoring Plan

## Overview

Refactor the evidence gate and investigation system to:
1. Remove hardcoded regex/frozenset classification
2. Let the model decide investigation depth
3. Simplify the gate to objective fact-checking only
4. Unify loop controllers and coverage tracking
5. Add prompt-level prevention (synthesis mandate, exploration protocol, self-checklist)
6. Expand empty-response retry detection
7. Make messages immutable

---

## Branch

`refactor/evidence-gate-simplification`

---

## Phase 1: Prompt Engineering (Preventive)

### 1.1 Add Post-Tool Synthesis Mandate
**File:** `domain/prompts/prompt.py` — `core_system_prompt_sections()`

Add new section `post_tool_synthesis_mandate()`:
- After tool results appear, the model MUST synthesize them into a substantive final answer
- One-word responses ("Done.", "OK.", "Fixed.") are never acceptable after tool use
- Answer must reference specific files, functions, or evidence from tool results

### 1.2 Add Exploration Self-Checklist
**File:** `domain/prompts/prompt.py` — `core_system_prompt_sections()`

Add new section `exploration_self_checklist()`:
- Before every final answer, the model evaluates:
  - [ ] Read file(s) directly related to the question
  - [ ] Searched for callers, usages, or related implementations
  - [ ] Checked tests or manifests that validate understanding
  - [ ] Can name specific files and line numbers as evidence
- Do not answer until all items are checked. If unchecked, call more tools.

### 1.3 Add Response Quality Minimum
**File:** `domain/prompts/prompt.py` — `core_system_prompt_sections()`

Add new section `response_quality_minimum()`:
- After tool execution, response must contain:
  - At least one specific file reference
  - At least one function, class, or line number reference
  - A synthesis explaining how evidence answers the user's question
- If minimum cannot be met, call more tools instead of responding

### 1.4 Add Exploration Protocol
**File:** `domain/prompts/prompt.py` — `core_system_prompt_sections()`

Add new section `exploration_protocol()`:
```
# Exploration Protocol

Before finalizing your answer:
1. Identify the entrypoints relevant to the user's question
2. Search for usages and callers of key functions
3. Read the implementation, not just the interface
4. Check tests for expected behavior and edge cases
5. Verify your understanding by tracing at least one complete call chain
6. Only then synthesize your answer
```

---

## Phase 2: Extract Investigation Code from state.py

### 2.1 Create `application/use_cases/chat/investigation/__init__.py`
Re-export `InvestigationState`, `TurnCoverage` for backward compatibility.

### 2.2 Create `application/use_cases/chat/investigation/state.py`
Move from `messaging/state.py`:
- `InvestigationState` dataclass
- `InvestigationDepth`, `InvestigationPhase` type aliases
- All regexes/frozensets (for removal in Phase 3)
- All helper functions (`_unique_append`, `_tool_call_name`, `_json_dict`, `_path_value`, `_paths_from_shell_command`)
- `TurnCoverage` dataclass
- `_DEFAULT_REQUIRED_SURFACES`
- `_INVESTIGATION_PHASES`

### 2.3 Clean `messaging/state.py`
Revert to ~140 lines:
- Keep `StreamingTurnState`, `AssistantStreamState`, `PromptPackage`
- Remove `InvestigationState`, `TurnCoverage`, `InvestigationDepth`, `InvestigationPhase`
- Import from `investigation` module

---

## Phase 3: Simplify EvidenceGateService

### 3.1 Rewrite `application/use_cases/chat/evidence_gate.py`

**Remove:**
- All regexes (`_INVESTIGATION_INTENT_RE`, `_IMPROVEMENT_RE`, `_TEST_COMMAND_RE`, `_READ_COMMAND_RE`, `_SEARCH_COMMAND_RE`)
- All frozensets (`_CODEBASE_TERMS`, `_TEST_RELEVANCE_TERMS`, `_MANIFEST_RELEVANCE_TERMS`, `_SOURCE_SUFFIXES`, `_MANIFEST_NAMES`, `_READ_TOOL_NAMES`, `_SEARCH_TOOL_NAMES`)
- `_TurnEvidence` dataclass (replaced by `TurnCoverage`)
- `_collect_current_turn_evidence()` (no more re-parsing)
- `_is_codebase_analysis_request()` (no more regex classification)
- `_needs_tests()`, `_needs_manifests()`, `_has_test_evidence()`, `_has_manifest_evidence()`, `_has_core_implementation_file()`, `_has_caller_or_symbol_search()`, `_has_adjacent_module_evidence()`, `_has_broad_symbol_search()`, `_has_cross_surface_coverage()`
- `max_evidence_gate_continuations` logic from `tool_runtime.py`

**Keep/Add:**
- `EvidenceGateDecision` dataclass (simplified)
- `EvidenceGateService` class:
  - Accepts `TurnCoverage` directly (not `Conversation`)
  - No iteration cap (removed `max_continuations`)
  - Checks objective facts only:
    - `files_read` count
    - `searches_made` count
    - `tool_calls` presence
  - Returns reminder if insufficient evidence
  - Does NOT force `continue` — only returns a decision + optional reminder

**New simplified logic:**
```python
def should_continue(
    self,
    request: ChatRequestDTO,
    coverage: TurnCoverage,
) -> EvidenceGateDecision:
    files_read = coverage.files_read or []
    searches_made = coverage.searches_made or []

    if not files_read and not searches_made:
        return EvidenceGateDecision(
            should_continue=True,
            reason="no evidence gathered",
            reminder="You have not yet used any tools. Read or search the codebase before answering.",
        )
    if len(files_read) < 2:
        return EvidenceGateDecision(
            should_continue=True,
            reason="insufficient file reads",
            reminder="You have only read one file. Consider searching for callers, tests, and related modules before answering.",
        )
    return EvidenceGateDecision(False, "sufficient evidence")
```

---

## Phase 4: Fix Shadow Loop

### 4.1 Update `streaming/executor.py`

**Current problem:** Two independent controllers:
- `effective_max_tool_iterations` hard cap
- `evidence_gate` can force `continue` independently

**Fix:**
- Remove `evidence_gate_continuations` from `StreamingTurnState`
- Gate returns `should_continue` + `reminder` only
- Executor decides whether to loop based on:
  1. `turn_state.iteration >= effective_max_iterations` → raise `ToolLoopLimitExceededError`
  2. If gate says `should_continue=True` AND `iteration < max - 1` → inject reminder and continue
  3. Otherwise break
- No separate gate iteration counter

### 4.2 Update `tool_runtime.py`

Remove `max_evidence_gate_continuations` from:
- `InvestigationDepthPolicy` dataclass
- `INVESTIGATION_DEPTH_POLICIES` entries
- `max_evidence_gate_continuations()` function

---

## Phase 5: Expand Empty-Response Retry

### 5.1 Update `streaming/_assistant.py`

**Add stub detection:**
```python
_STUB_RE = re.compile(r"^(done|ok|fixed|completed|resolved|looks good)[.!]?$", re.I)

def _is_substanceless(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return True
    if len(stripped) < 30 and not any(c in stripped for c in "`./[](){"):
        return True
    if _STUB_RE.match(stripped):
        return True
    return False
```

**Expand retry condition:**
- Change from `not assistant_state.has_visible_output` to `_is_substanceless(assistant_state.content)`
- Remove `turn_state.executed_tools` guard so retry fires even on first pass with empty/stop

**Add tool-result-as-response detection:**
- If the last message in the conversation is a `tool` role message, and the assistant response is empty/stop, treat as substanceless and retry

**Add `finish_reason="length"` recovery:**
- If `assistant_state.finish_reason == "length"`, inject reminder: "Your previous response was truncated. Continue from where you left off."

---

## Phase 6: Fix Coverage Metadata Mutation

### 6.1 Update `streaming/_tools.py`

**Remove:**
```python
last_assistant = next(
    (message for message in reversed(conversation.messages) if message.role == Role.ASSISTANT),
    None,
)
if last_assistant is not None:
    last_assistant.metadata["tool_coverage"] = turn_state.coverage.to_metadata()
```

### 6.2 Update `streaming/executor.py`

**At assistant message creation time, pass coverage:**
```python
conversation.add_message(
    Message(
        role=Role.ASSISTANT,
        content=assistant_state.content,
        tool_calls=assistant_state.tool_calls,
        metadata={
            "provider": assistant_state.provider,
            "model": assistant_state.model,
            "finish_reason": assistant_state.finish_reason,
            "tool_coverage": turn_state.coverage.to_metadata(),
        },
    )
)
```

---

## Phase 7: Extract System Reminders

### 7.1 Create `application/use_cases/chat/messaging/system_reminders.py`

Extract from `MessagePreparer`:
- `with_final_answer_reminder()` → `with_final_answer_reminder()`
- `with_synthesis_reminder()` → `with_synthesis_reminder()`
- `with_system_reminder()` → `with_system_reminder()`
- `_format_evidence_summary()` → `_format_evidence_summary()`

### 7.2 Update `messaging/message_preparation.py`

- Remove extracted methods
- Delegate to `system_reminders` module
- Keep `prepare()`, `with_prompt()` only

---

## Phase 8: Unified Investigation Taxonomy

### 8.1 Create `domain/prompts/investigation_taxonomy.py`

Single source of truth:
```python
from typing import Literal

InvestigationDepth = Literal["light", "standard", "deep", "exhaustive"]

SURFACES = ["entrypoints", "domain", "adapters", "tests", "config"]

DEPTH_POLICIES: dict[InvestigationDepth, dict[str, Any]] = {
    "light": {"max_tool_iterations": 3, "required_surfaces": ()},
    "standard": {"max_tool_iterations": 6, "required_surfaces": ("domain", "tests")},
    "deep": {"max_tool_iterations": 12, "required_surfaces": ("entrypoints", "domain", "adapters", "tests")},
    "exhaustive": {"max_tool_iterations": 24, "required_surfaces": tuple(SURFACES)},
}
```

### 8.2 Update all references
- `tool_runtime.py` references `taxonomy.py`
- `investigation/state.py` references `taxonomy.py`
- Remove duplicated surface definitions

---

## Phase 9: Model-Driven Depth + ready_for_final

### 9.1 Remove regex classification from `InvestigationState.classify()`

**New default:**
```python
@classmethod
def classify(cls, request: ChatRequestDTO) -> InvestigationState:
    # Default: active when tools enabled, depth="light"
    # Model will reclassify on first interaction
    active = request.tools_enabled
    depth = request.investigation_depth or "light"
    return cls(
        depth=depth,
        objective=request.message.strip(),
        active=active,
        phase="discover" if active else "classify",
    )
```

### 9.2 Model declares depth on first interaction

The model will include a depth declaration in its first response. The executor will parse this and update `investigation_state.depth`.

### 9.3 Model declares `ready_for_final`

**In `AssistantStreamState`:**
```python
ready_for_final: bool = False
```

**In executor loop:**
- After each assistant pass, if `assistant_state.ready_for_final`:
  - Gate checks evidence
  - If sufficient → allow final answer
  - If insufficient → inject reminder, do not allow final answer
- If `not ready_for_final` and no tool calls → gate may nudge for more exploration

---

## Phase 10: Test Updates

### 10.1 Update `tests/unit/test_chat_evidence_gate.py`
- Rewrite for simplified gate (no regex, no frozensets)
- Test with `TurnCoverage` input directly
- Test stub detection logic

### 10.2 Update `tests/unit/test_chat_streaming_turn.py`
- Add tests for:
  - Tool-result-as-response retry
  - `finish_reason="length"` recovery
  - Stub message detection ("Done.", "OK.")
  - Short content detection (< 30 chars)

### 10.3 Update `tests/unit/test_prompt_builder.py`
- Add tests for new prompt sections
- Verify sections appear in correct order

### 10.4 Add `tests/unit/test_investigation_state.py`
- Test `InvestigationState` extraction
- Test `TurnCoverage` behavior
- Test taxonomy module

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `domain/prompts/prompt.py` | Modify | Add 4 new prompt sections |
| `application/use_cases/chat/evidence_gate.py` | Rewrite | 578 lines → ~80 lines |
| `application/use_cases/chat/messaging/state.py` | Clean | Extract investigation code |
| `application/use_cases/chat/investigation/__init__.py` | **New** | Package init |
| `application/use_cases/chat/investigation/state.py` | **New** | InvestigationState + TurnCoverage |
| `application/use_cases/chat/streaming/executor.py` | Modify | Fix shadow loop, unified budget, ready_for_final |
| `application/use_cases/chat/streaming/_assistant.py` | Modify | Expand retry, stub detection |
| `application/use_cases/chat/streaming/_tools.py` | Modify | Remove metadata mutation |
| `application/use_cases/chat/messaging/message_preparation.py` | Modify | Extract reminders |
| `application/use_cases/chat/messaging/system_reminders.py` | **New** | Reminder functions |
| `application/use_cases/chat/tooling/tool_runtime.py` | Modify | Remove gate continuations |
| `domain/prompts/investigation_taxonomy.py` | **New** | Single source of truth |
| `tests/unit/test_chat_evidence_gate.py` | Rewrite | Simplified gate tests |
| `tests/unit/test_chat_streaming_turn.py` | Modify | New retry tests |
| `tests/unit/test_prompt_builder.py` | Modify | New section tests |
| `tests/unit/test_investigation_state.py` | **New** | Extracted state tests |

---

## Rollback Strategy

- Branch isolation: all changes on `refactor/evidence-gate-simplification`
- If critical bug found: revert branch, cherry-pick prompt-only changes (Phase 1) as hotfix

---

## Verification

1. All unit tests pass
2. Integration test: chat with tools → verify synthesis occurs
3. Integration test: stub response → verify retry fires
4. Integration test: tool result without synthesis → verify retry fires
5. Prompt builder test: verify all 4 new sections appear

---

*Plan created based on user specification dated 2026-05-29.*
