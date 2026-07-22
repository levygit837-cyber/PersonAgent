# Agent Behaviour Comprehensive Analysis

## Executive Summary

This document is the result of a multi-step reasoning process (thought-based-reasoning, reflection, judge-with-debate, critique, and context-engineering/prompt-engineering analysis) applied to three interconnected problems in the PersonAgent codebase:

1. **Silent Failure After Tool Calls:** The agent occasionally stops without synthesizing a final answer after executing tools.
2. **Superficial Analysis:** When the agent does answer, it often performs minimal exploration (few tool calls, no tracing of callers/tests/related files).
3. **Evidence Gate Over-Engineering:** A recently added "Evidence Gate" (578 lines of hardcoded regex/frozensets) attempts to solve problems #1 and #2 but introduces significant architectural debt.

**Verdict:** The Evidence Gate concept is sound ("ensure sufficient evidence before answering") but the implementation is fundamentally flawed. The correct approach shifts primary enforcement to the **prompt** (preventive) with a **lightweight code safety net** (reactive).

---

## Methodology

This analysis was produced through:

1. **Thought-Based-Reasoning:** Each of 12 distinct problems was analyzed individually with chain-of-thought reasoning, keeping contexts separate.
2. **Reflection:** For each problem, 2-4 alternative solutions were simulated and evaluated against the primary approach.
3. **Judge-With-Debate:** Three independent judge agents (Minimalist, Pragmatist, Systems Architect) evaluated the problems and proposed solutions independently.
4. **Critique:** The three perspectives were synthesized, finding consensus on diagnosis and disagreement on remedy scope.
5. **Context-Engineering + Prompt-Engineering:** The problems were analyzed through the lens of what the model sees in context at each decision point.

---

## Problem Diagnosis

### Problem 1: Silent Failure After Tool Calls

**Symptom:** The model executes tools, receives results, then returns `finish_reason="stop"` with no substantive content. The user sees nothing or a generic stub like "Done."

**Root Cause:** The safety net `_maybe_retry_empty_response()` in `streaming/_assistant.py` is too narrow:

```python
# Current condition (too literal)
if (
    turn_state.executed_tools
    and not assistant_state.has_visible_output  # Only catches ZERO content
    and assistant_state.tool_calls is None
    and assistant_state.finish_reason in {None, "stop"}
):
```

`has_visible_output` returns `bool(self.content or self.images)`. A response of `"Done."` passes this check because `bool("Done.")` is `True`. The loop terminates and the user sees a useless stub.

**Why it happens:**
- The system prompt has no explicit instruction: *"After tool results appear, you must synthesize them into a final answer."*
- The model sees its own `tool_calls` message followed by raw tool result messages. Some models (especially local/quantized) struggle with the transition from "tool execution phase" to "synthesis phase."
- The `_maybe_retry_empty_response()` only fires when content is completely empty, missing stub responses entirely.

---

### Problem 2: Superficial Analysis

**Symptom:** The agent reads 1-2 files and immediately answers, without exploring callers, tests, related implementations, or configuration.

**Root Cause:** The prompt contains excellent guidance in `domain/prompts/sections/tools.py` (the `File Operations` section), but it is:
- **Passive:** It describes what thorough analysis looks like, but doesn't give the model a procedure to follow.
- **Not self-evaluating:** The model has no checklist to verify whether it has explored enough before answering.
- **No negative reinforcement:** There's no "if you stop early, you will be wrong" signal.

The evidence gate tried to solve this programmatically by checking whether the model had read files from different "surfaces" (entrypoints, domain, adapters, tests, config). But this is action theater — the gate counts whether the model touched a test file, not whether the model *understood* what it read.

---

### Problem 3: Evidence Gate Over-Engineering

**The evidence gate (`evidence_gate.py`, 578 lines) suffers from five critical flaws:**

#### 3a. Regex Cathedral

The file contains:
- 6 hardcoded regexes: `_INVESTIGATION_INTENT_RE`, `_IMPROVEMENT_RE`, `_TEST_COMMAND_RE`, `_READ_COMMAND_RE`, `_SEARCH_COMMAND_RE`
- 6 hardcoded frozensets: `_CODEBASE_TERMS` (30 words), `_TEST_RELEVANCE_TERMS` (14), `_MANIFEST_RELEVANCE_TERMS` (10), `_SOURCE_SUFFIXES` (23 extensions), `_MANIFEST_NAMES` (21 files), `_READ_TOOL_NAMES`, `_SEARCH_TOOL_NAMES`

These are necessarily incomplete. Every new language (`.zig`, `.scala`), every new package manager (`uv.lock`, `bun.lockb`), every new domain term ("middleware", "handler", "DTO") requires a code change. The classification is brittle:
- "How do I configure my editor?" matches "config" and "repo" → false positive (classified as investigation)
- "Why does my user_service.py crash?" doesn't match keywords unless "bug" or "debug" is present → false negative

#### 3b. Duplicated Coverage Tracking

Evidence tracking exists in THREE places:
1. `InvestigationState` in `messaging/state.py` (tracks `searched_patterns`, `read_files`, `coverage_status`)
2. `TurnCoverage` in `messaging/state.py` (tracks `search_patterns`, `files_read`, `coverage_category_hits`)
3. `_TurnEvidence` in `evidence_gate.py` (tracks `tool_names`, `read_files`, `searched_files`, `searched_paths`, `shell_commands`)

The gate even re-parses the entire conversation from the last user message on every check (`_collect_current_turn_evidence`), ignoring the already-accumulated `TurnCoverage` in `StreamingTurnState`.

#### 3c. Shadow Loop (Two Independent Controllers)

In `streaming/executor.py`:
```python
# Controller 1: Hard iteration cap
if turn_state.iteration >= effective_max_iterations:
    raise ToolLoopLimitExceededError

# Controller 2: Evidence gate override
if evidence_gate_decision.should_continue:
    continue  # forces another iteration
```

The gate has its own cap (`max_evidence_gate_continuations`, 2-5 depending on depth) separate from the tool iteration cap. The gate can force a `continue` even when `iteration` is at `max - 1`, causing the next iteration to hit the hard cap and raise `ToolLoopLimitExceededError`. This is confusing and hard to debug.

#### 3d. `messaging/state.py` Bloat

The file grew from ~140 lines to ~560 lines by adding:
- `InvestigationState` with 10 methods
- `TurnCoverage` with tracking methods
- 7 module-level regexes/frozensets
- 5 helper functions (`_unique_append`, `_tool_call_name`, `_json_dict`, `_path_value`, `_paths_from_shell_command`)

This breaks the single-responsibility boundary. A file that owned "in-flight state carriers" now owns "heuristic conversation classification and evidence tracking."

#### 3d. Feature Logic Leaking Into General Modules

- `MessagePreparer` in `message_preparation.py` grew `with_synthesis_reminder()` and `_format_evidence_summary()` — investigation-domain logic in a generic message renderer.
- `StreamingTurnState` gained `evidence_gate_continuations: int = 0` — a feature-specific counter polluting a generic turn-state carrier.
- `InvestigationState` hardcodes surface definitions (`_DEFAULT_REQUIRED_SURFACES = ["entrypoints", "domain", "adapters", "tests", "config"]`) in the messaging layer.

---

## Judge Consensus

Three independent judges (Minimalist, Pragmatist, Architect) were asked to evaluate the problems. Their scores and verdicts:

| Judge | Score | Verdict |
|-------|-------|---------|
| Minimalist | 2/10 | **Delete the gate entirely** |
| Pragmatist | 4/10 | **Keep the concept, simplify to ~80 lines** |
| Architect | 3/10 | **Refactor into clean abstractions** |

**Consensus on diagnosis:** All three judges independently identified the same root causes.
**Disagreement on remedy:** The Minimalist wants to delete everything and rely on prompt engineering. The Pragmatist wants a lightweight gate. The Architect wants a principled abstraction layer.

**Synthesis:** The Pragmatist's approach best aligns with the user's stated preference: *"I think it's a good way if we keep with the Evidence Gate, but we need to do some improvements in the logic."*

---

## Recommended Solution

### Phase 1: Prompt Engineering (Preventive — Addresses Root Cause)

Add three new prompt sections to `domain/prompts/prompt.py` or `domain/prompts/sections/tools.py`:

**Section A: Post-Tool Synthesis Mandate**
```
After Tool Execution

When tool results appear in the conversation after your previous tool_calls 
message, you must use those results to produce a substantive final answer. 
Do not stop without answering. One-word responses like "Done.", "OK.", or 
"Fixed." are never acceptable after tool use. Your answer must reference 
specific files, functions, or evidence from the tool results.
```

**Section B: Exploration Self-Checklist**
```
Exploration Checklist (evaluate before every final answer)

For any question involving code, files, or repository structure:
- [ ] I have read the file(s) most directly related to the question.
- [ ] I have searched for callers, usages, or related implementations.
- [ ] I have checked tests or manifests that validate my understanding.
- [ ] I can name specific files and line numbers as evidence.

Do not answer until all items are checked. If unchecked, call more tools.
```

**Section C: Response Quality Minimum**
```
Response Quality Minimum

After tool execution, your response must contain:
- At least one specific file reference (path or filename)
- At least one function, class, or line number reference
- A synthesis explaining how the evidence answers the user's question

If you cannot meet this minimum, call more tools instead of responding.
```

**Why this works:**
- The model evaluates the checklist against its own message history (which it can see in context).
- No external code needs to parse the conversation.
- Universal: applies to all tool-using conversations, not just regex-classified "investigations."
- Models reliably follow self-evaluation checklists when they appear in the system prompt.

---

### Phase 2: Simplify the Evidence Gate (Lightweight Safety Net)

Replace `evidence_gate.py` (578 lines) with a ~80-line implementation:

```python
"""Minimal evidence gate — no regexes, no frozensets."""

from dataclasses import dataclass
from typing import Any

from personagent.application.dto import ChatRequestDTO

@dataclass(frozen=True, slots=True)
class EvidenceGateDecision:
    should_continue: bool
    reason: str
    reminder: str | None = None

class EvidenceGateService:
    def __init__(self, *, max_continuations: int = 2) -> None:
        self._max_continuations = max(0, max_continuations)

    def should_continue(
        self,
        request: ChatRequestDTO,
        turn_state: Any,
        coverage: Any,  # TurnCoverage
    ) -> EvidenceGateDecision:
        retry_count = getattr(turn_state, "evidence_gate_continuations", 0)
        if retry_count >= self._max_continuations:
            return EvidenceGateDecision(False, "cap reached")

        files_read = getattr(coverage, "files_read", [])
        searches_made = getattr(coverage, "searches_made", [])

        # If no tools were used at all, nudge once
        if not files_read and not searches_made:
            return EvidenceGateDecision(
                should_continue=True,
                reason="no evidence gathered",
                reminder="You have not yet used any tools. Read or search the codebase before answering.",
            )

        # If only 1 file was read, suggest exploring more
        if len(files_read) < 2:
            return EvidenceGateDecision(
                should_continue=True,
                reason="insufficient file reads",
                reminder="You have only read one file. Consider searching for callers, tests, and related modules before answering.",
            )

        return EvidenceGateDecision(False, "sufficient evidence")
```

**Key changes:**
- **No regexes.** No `_INVESTIGATION_INTENT_RE`, no `_CODEBASE_TERMS`, no frozensets.
- **No re-parsing.** Consumes `TurnCoverage` directly.
- **Unified budget.** The gate's `max_continuations` is checked against the same `turn_state.iteration` counter — no shadow loop. The gate injects a reminder, it does NOT force `continue`.
- **No classification.** The gate checks objective facts (how many files read, how many searches) rather than classifying user intent.

---

### Phase 3: Expand Empty-Response Retry (Reactive Safety Net)

In `streaming/_assistant.py`, expand `_maybe_retry_empty_response()`:

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

Change the retry condition from:
```python
and not assistant_state.has_visible_output
```
to:
```python
and (
    not assistant_state.has_visible_output
    or _is_substanceless(assistant_state.content)
)
```

**Also remove the `turn_state.executed_tools` guard** so the retry fires even on the first pass if the model returns empty/stop with no content and no tool calls.

---

### Phase 4: Extract Investigation Code From `messaging/state.py`

Move `InvestigationState`, `TurnCoverage`, and all associated regex/frozenset/helpers to a dedicated module:

```
backend/src/personagent/application/use_cases/chat/investigation/
  __init__.py
  state.py          # InvestigationState, TurnCoverage
  coverage.py       # Coverage tracking helpers
```

Revert `messaging/state.py` to ~140 lines of clean dataclasses.

---

### Phase 5: Fix Coverage Metadata Mutation Timing

In `streaming/executor.py`, when creating the assistant `Message`, pass coverage metadata at construction time:

```python
conversation.add_message(
    Message(
        role=Role.ASSISTANT,
        content=assistant_state.content,
        tool_calls=assistant_state.tool_calls,
        metadata={
            # ... existing metadata ...
            "tool_coverage": turn_state.coverage.to_metadata(),
        },
    )
)
```

Remove the post-hoc mutation in `streaming/_tools.py`.

---

### Phase 6: Extract System Message Augmentation

In `messaging/message_preparation.py`, the `with_final_answer_reminder()`, `with_synthesis_reminder()`, and `with_evidence_gate_reminder()` methods all do the same thing: append text to the system message. Extract them to a dedicated helper:

```python
# backend/src/personagent/application/use_cases/chat/messaging/system_reminders.py

def with_final_answer_reminder(messages: list[dict]) -> list[dict]: ...
def with_synthesis_reminder(messages: list[dict], evidence_summary: Any) -> list[dict]: ...
def with_evidence_gate_reminder(messages: list[dict], reminder: str) -> list[dict]: ...
```

`MessagePreparer` keeps only `prepare()`, `with_prompt()`, and compaction logic.

---

### Phase 7: Unified Surface Taxonomy

Create a single source of truth for investigation surfaces:

```python
# backend/src/personagent/domain/investigation/taxonomy.py

from dataclasses import dataclass
from typing import Literal

InvestigationDepth = Literal["light", "standard", "deep", "exhaustive"]

SURFACES = ["entrypoints", "domain", "adapters", "tests", "config"]

@dataclass(frozen=True)
class DepthPolicy:
    min_files_read: int
    min_searches: int
    max_continuations: int
    required_surfaces: tuple[str, ...]

DEPTH_POLICIES: dict[InvestigationDepth, DepthPolicy] = {
    "light": DepthPolicy(0, 0, 0, ()),
    "standard": DepthPolicy(2, 1, 1, ("domain", "tests")),
    "deep": DepthPolicy(4, 2, 3, ("entrypoints", "domain", "adapters", "tests")),
    "exhaustive": DepthPolicy(8, 4, 5, tuple(SURFACES)),
}
```

All other modules (`tool_runtime.py`, `evidence_gate.py`, `state.py`) reference this module.

---

## Files to Modify

| File | Change | Lines Impact |
|------|--------|-------------|
| `domain/prompts/prompt.py` | Add Post-Tool Synthesis + Exploration Checklist + Response Quality Minimum sections | +40 lines |
| `domain/prompts/sections/tools.py` | Optionally add reference to new sections | Minimal |
| `application/use_cases/chat/evidence_gate.py` | Replace 578-line regex cathedral with ~80-line simplified gate | -500 lines |
| `application/use_cases/chat/messaging/state.py` | Extract `InvestigationState`/`TurnCoverage` to `investigation/` | -420 lines |
| `application/use_cases/chat/investigation/` | **New package** containing extracted state + coverage logic | +200 lines |
| `application/use_cases/chat/streaming/executor.py` | Remove shadow `continue`; gate injects reminder only; unify budget | -30 lines |
| `application/use_cases/chat/streaming/_assistant.py` | Expand retry to catch stub responses; remove `executed_tools` guard | +10 lines |
| `application/use_cases/chat/streaming/_tools.py` | Remove post-hoc metadata mutation | -5 lines |
| `application/use_cases/chat/messaging/message_preparation.py` | Extract reminder methods to `system_reminders.py` | -30 lines |
| `application/use_cases/chat/messaging/system_reminders.py` | **New file** for system message augmentation | +30 lines |
| `application/use_cases/chat/tooling/tool_runtime.py` | Reference `taxonomy.py` instead of hardcoded policies | -20 lines |
| `domain/investigation/taxonomy.py` | **New file** single source of truth for surfaces and depth policies | +30 lines |
| `tests/unit/test_chat_evidence_gate.py` | Update tests for simplified gate | Rewrite |
| `tests/unit/test_chat_streaming_turn.py` | Add tests for stub-response retry | +40 lines |
| `tests/unit/test_prompt_builder.py` | Update tests for new prompt sections | +20 lines |

**Net change:** Approximately -600 lines (deleting regex cathedral, duplicated tracking, shadow loop complexity) and +150 lines (new prompt sections, simplified gate, clean abstractions).

---

## Why This Approach Wins

### Compared to "Delete the Gate" (Minimalist)
- Keeps a lightweight safety net for the case where the model ignores the prompt checklist.
- Maintains the user's explicit preference to keep the evidence gate concept.
- The simplified gate is 80 lines — negligible maintenance burden.

### Compared to "Keep and Fix" (Pragmatist)
- Adds prompt-level prevention (the checklist) so the gate fires less often.
- The gate is even simpler than the pragmatist's 80-line version by removing classification entirely.
- Adds the missing "response quality" layer (stub detection).

### Compared to "Refactor Into Abstractions" (Architect)
- Achieves architectural cleanliness without introducing `LoopDirective` protocols and `ExplorationPolicy` interfaces.
- The refactored directory structure (`investigation/` package, `taxonomy.py`) satisfies the architect's concern for feature isolation without over-engineering.
- The unified budget (no shadow loop) satisfies the single-controller principle.

---

## Implementation Priority

| Priority | Phase | Impact | Effort |
|----------|-------|--------|--------|
| P0 | Phase 1: Prompt sections | High (prevents most failures) | Low (~1 hour) |
| P0 | Phase 3: Expand retry | High (catches remaining edge cases) | Low (~30 min) |
| P1 | Phase 2: Simplify gate | Medium (safety net, lighter weight) | Medium (~2 hours) |
| P1 | Phase 4: Extract from state.py | Medium (code quality) | Medium (~2 hours) |
| P2 | Phase 5: Fix metadata mutation | Low (cleanup) | Low (~15 min) |
| P2 | Phase 6: Extract reminders | Low (code quality) | Low (~30 min) |
| P2 | Phase 7: Unified taxonomy | Low (maintenance) | Low (~30 min) |

**Recommended:** Implement P0 items first. They address the user's pain directly with minimal code change. P1 items refactor the gate to be maintainable. P2 items are cleanup.

---

## Testing Strategy

1. **Test the prompt sections:** Build a prompt with the new sections and verify they appear in the expected order (before `response_style_runtime_reminder`).
2. **Test stub detection:** Mock assistant passes returning "Done.", "OK.", "", and "Here's the implementation in `user_service.py` at line 42." Verify only the first three trigger retry.
3. **Test simplified gate:** Mock `TurnCoverage` with 0 files, 1 file, and 5 files. Verify gate decisions.
4. **Test unified budget:** Verify that `evidence_gate_continuations` no longer exists and gate reminders consume the normal iteration budget.
5. **Regression test:** Existing chat streaming tests must pass. The gate should be transparent (no reminder) when coverage is sufficient.

---

## Conclusion

The agent's silent failures and superficial analysis are primarily **prompt-engineering problems**, not **code-engineering problems**. The evidence gate was an honest attempt to solve them programmatically, but it chose the wrong layer of abstraction.

The correct fix is:
1. **Tell the model what to do** (prompt sections — preventive)
2. **Catch it when it doesn't** (expanded retry — reactive)
3. **Keep a lightweight safety net** (simplified gate — backup)

This approach deletes ~600 lines of brittle heuristic code, adds ~150 lines of clean abstractions and prompt instructions, and addresses all three user-reported problems.

---

*Generated through multi-step reasoning: thought-based-reasoning, reflection, judge-with-debate, critique, and context-engineering/prompt-engineering analysis.*
