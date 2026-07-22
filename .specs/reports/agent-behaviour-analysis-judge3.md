# Judge 3 - Systems Architect Perspective

## Problem Analysis

### Problem 1: Silent Failure After Tool Calls

**Root cause:** The empty-response safety net is too narrow and lives in the wrong abstraction.

In `@backend/src/personagent/application/use_cases/chat/streaming/_assistant.py` (lines 28-33), `_maybe_retry_empty_response()` only fires when:

```python
turn_state.executed_tools
and not assistant_state.has_visible_output
and assistant_state.tool_calls is None
and assistant_state.finish_reason in {None, "stop"}
```

`has_visible_output` is defined in `@backend/src/personagent/application/use_cases/chat/messaging/state.py` (line 515-516) as:

```python
@property
def has_visible_output(self) -> bool:
    return bool(self.content or self.images)
```

This means a response of `"Done."`, `"OK."`, or `"Finished."` passes the gate because `bool("Done.")` is `True`. The model has satisfied the "visible output" check while providing zero analytical value. The loop then terminates, and the user sees a useless stub.

**Architectural issue:** Response-quality validation is conflated with "empty content retry." There is no domain concept of "minimum response value." The evidence gate (`evidence_gate.py`) tries to force another iteration, but it only cares about *tool evidence*, not *response quality*. If the model produces a stub response *after* satisfying the evidence checklist, the gate lets it through.

The executor (`@backend/src/personagent/application/use_cases/chat/streaming/executor.py`, lines 377-378) breaks out of the loop when there are no tool calls and the evidence gate says `should_continue=False`. It never asks: "Is the assistant message actually worth delivering?"

---

### Problem 2: Superficial Analysis

**Root cause:** The system tells the model *what* to do (good prompt) but enforces compliance with *action checklists* rather than *outcome quality*.

The prompt in `@backend/src/personagent/domain/prompts/sections/tools.py` (lines 47-52) contains excellent guidance:

> "discover structure with listing/glob/search; search exact identifiers, then related terms; read the smallest high-signal file set; follow imports, callers, and tests before final architecture or behavior claims"

However, the enforcement mechanism in `@backend/src/personagent/application/use_cases/chat/evidence_gate.py` translates this into a checklist of regex matches and file-path suffixes:

- `_CODEBASE_TERMS` (30 words, lines 33-62)
- `_TEST_RELEVANCE_TERMS` (14 words, lines 63-81)
- `_SOURCE_SUFFIXES` (23 extensions, lines 102-123)
- `_MANIFEST_NAMES` (21 files, lines 124-147)
- `_TEST_COMMAND_RE`, `_READ_COMMAND_RE`, `_SEARCH_COMMAND_RE` (lines 148-156)
- `_is_test_path()`, `_is_manifest_path()`, `_looks_like_symbol_search()` (lines 535-567)

This is *action theater*: the gate counts whether the model touched a test file or ran grep, but it does not evaluate whether the model *understood* what it read. Two regex-heavy state trackers—`InvestigationState` and `TurnCoverage`—both try to track tool usage but with different heuristics, leading to inconsistent coverage reporting.

**Duplication:** `InvestigationState.refresh_coverage()` in `state.py` (lines 204-224) and `EvidenceGateService.should_continue_investigation()` in `evidence_gate.py` (lines 191-278) both parse conversation messages to count files and searches. The gate even re-parses from scratch on every call (`_collect_current_turn_evidence`, lines 341-363), ignoring the `TurnCoverage` object already accumulated in `StreamingTurnState`.

---

### Problem 3: Evidence Gate Architecture

**Root cause:** The evidence gate was bolted onto the side of the loop without integrating into the loop control abstraction.

In `@backend/src/personagent/application/use_cases/chat/streaming/executor.py` (lines 222-396), there are **two independent loop controllers**:

1. **Hard iteration cap** (lines 223-231):
   ```python
   if turn_state.iteration >= effective_max_iterations:
       raise ToolLoopLimitExceededError(...)
   ```

2. **Evidence gate override** (lines 341-366):
   ```python
   decision = self._evidence_gate.should_continue_investigation(...)
   if decision.should_continue and tool_context:
       turn_state.evidence_gate_continuations += 1
       evidence_gate_reminder = decision.reminder
       continue
   ```

The first controller counts `turn_state.iteration`. The second counts `turn_state.evidence_gate_continuations`. They are incremented at different moments and checked in different branches. The gate can force a `continue` even when the model explicitly chose to stop (no tool calls), which contradicts the normal loop semantics.

**Leaky abstractions:**

- `StreamingTurnState` in `state.py` (line 558) gained `evidence_gate_continuations: int = 0`, polluting a generic turn-state carrier with feature-specific accounting.
- `MessagePreparer` in `message_preparation.py` (lines 196-207) grew `with_synthesis_reminder()` and `_format_evidence_summary()`, which know about investigation-state keys (`"coverage_status"`, `"read_files"`, `"missing"`). A generic message renderer should not be formatting domain-specific evidence summaries.
- `InvestigationState` (560 lines in `state.py`) contains 7 module-level regexes/frozensets, path categorization logic (`_path_category`, lines 331-358), and hardcoded surface definitions (`_DEFAULT_REQUIRED_SURFACES`, line 40). This leaked into the generic messaging state module.

**Layer violation:** `EvidenceGateService` lives in `application/use_cases/chat/evidence_gate.py`, but it encodes domain knowledge about what constitutes sufficient evidence for a codebase analysis. Domain policies should live in the domain layer; the application layer should only *execute* them.

---

## Proposed Architectural Changes

### 1. Unified Loop Controller (Single Source of Truth)

Replace the two independent caps with one `TurnLoopPolicy` abstraction.

```python
# domain/investigation/models.py
@dataclass(frozen=True)
class LoopDirective:
    action: Literal["continue", "break", "retry_with_reminder"]
    reason: str
    reminder: str | None = None
```

The executor loop becomes:

```python
while True:
    directive = loop_policy.directive(turn_state, evidence_collection)
    if directive.action == "break":
        break
    if directive.action == "retry_with_reminder":
        messages = message_preparer.with_system_reminder(messages, directive.reminder)
        # run another assistant pass without tools
        continue
    # normal tool pass
```

This removes the `evidence_gate_continuations` field from `StreamingTurnState` and eliminates the dual-controller race condition.

### 2. Extract Domain Policy for Evidence Sufficiency

Move `InvestigationDepthPolicy` and the evidence sufficiency rules from `tool_runtime.py` and `evidence_gate.py` into the domain layer.

```python
# domain/investigation/policy.py
class ExplorationPolicy(Protocol):
    def required_surfaces(self, request: ChatRequestDTO) -> list[Surface]: ...
    def max_iterations(self) -> int: ...
    def sufficient(self, evidence: EvidenceCollection) -> bool: ...
```

Depth strings ("light", "standard", "deep", "exhaustive") become policy factory keys, not hardcoded lookup tables scattered across modules.

### 3. Incremental Evidence Collection (No Re-parsing)

Replace `_collect_current_turn_evidence()` (which walks `conversation.messages` from the last user index on every gate invocation) with an `EvidenceCollection` builder that is updated incrementally as tool results stream in.

```python
# application/use_cases/chat/investigation/tracker.py
class EvidenceTracker:
    def record_tool_call(self, call: dict) -> None: ...
    def record_tool_result(self, result: dict) -> None: ...
    def to_collection(self) -> EvidenceCollection: ...
```

`TurnCoverage` in `messaging/state.py` should be reduced to a generic telemetry carrier. Path categorization (`_path_category`, `_looks_like_config`) moves to the investigation tracker or to a pluggable `SurfaceClassifier`.

### 4. Response Quality as a First-Class Policy

Fix the silent-failure problem by introducing a `ResponseQualityPolicy` that participates in the unified `LoopDirective`:

```python
class ResponseQualityPolicy:
    def assess(self, assistant_state: AssistantStreamState, executed_tools: bool) -> LoopDirective:
        if not executed_tools:
            return LoopDirective(action="break")
        if self._is_stub_response(assistant_state.content):
            return LoopDirective(
                action="retry_with_reminder",
                reminder="...",
                reason="stub response after tool calls"
            )
        return LoopDirective(action="break")
```

This removes the responsibility from `_assistant.py` and makes it an explicit loop-control concern.

### 5. Feature Isolation (Stop Leaking Into General Modules)

- **`messaging/state.py`** should contain only generic types: `StreamingTurnState`, `AssistantStreamState`, `PromptPackage`, `MemoryRecallResult`. Remove `InvestigationState`, `TurnCoverage` path categories, and all regex/frozenset constants.
- **`message_preparation.py`** should not know about evidence summaries. If the investigation layer needs to inject a synthesis reminder, it should do so via a decorator or pre-processor, not by embedding `_format_evidence_summary` into the generic preparer.
- **`executor.py`** should not contain conditionals like `if investigation_state.active:` (currently at lines 238-243, 248-255, 333-335, 392-394). Instead, the `LoopPolicy` should optionally attach an `InvestigationContext` to the turn state. If the context is present, the policy uses it; otherwise, the default loop runs.

### 6. Replace Regex Soup with Pluggable Classifiers

The hardcoded regexes in `evidence_gate.py` (`_INVESTIGATION_INTENT_RE`, `_IMPROVEMENT_RE`, `_CODEBASE_TERMS`, etc.) should be encapsulated behind a `RequestClassifier` protocol:

```python
class RequestClassifier(Protocol):
    def classify(self, request: ChatRequestDTO, conversation: Conversation) -> InvestigationContext | None: ...
```

A default `KeywordRequestClassifier` can keep the current heuristic behavior for backward compatibility, but it becomes swappable. This isolates the heuristic mess to one replaceable component.

---

## Proposed Directory Structure

```
backend/src/personagent/
├── domain/
│   └── investigation/
│       ├── __init__.py
│       ├── models.py              # EvidenceCollection, Surface, LoopDirective, EvidenceSpec
│       └── policy.py              # ExplorationPolicy (protocol), ResponseQualityPolicy (protocol)
│
├── application/
│   └── use_cases/
│       └── chat/
│           ├── investigation/
│           │   ├── __init__.py
│           │   ├── state.py       # InvestigationState (moved from messaging/state.py)
│           │   ├── tracker.py     # EvidenceTracker (incremental, replaces _collect_current_turn_evidence)
│           │   ├── classifier.py  # KeywordRequestClassifier (replaces regex soup)
│           │   └── arbiter.py     # TurnLoopArbiter: composes policies into a single LoopDirective
│           │
│           ├── messaging/
│           │   ├── state.py       # StreamingTurnState, AssistantStreamState, PromptPackage (generic only)
│           │   └── message_preparation.py  # Stripped of evidence/synthesis specifics
│           │
│           ├── streaming/
│           │   ├── executor.py    # Single loop controller; delegates to arbiter
│           │   ├── _assistant.py  # Retry mixin removed; response quality handled by arbiter
│           │   └── ...
│           │
│           └── tooling/
│               └── tool_runtime.py  # Remove InvestigationDepthPolicy; keep tool orchestration only
```

**Migration path:**
1. Create `domain/investigation/` and move policy protocols.
2. Create `application/use_cases/chat/investigation/` and move `InvestigationState`, tracker, and classifier.
3. Introduce `TurnLoopArbiter` in `investigation/arbiter.py`; make `executor.py` use it.
4. Strip `messaging/state.py` and `message_preparation.py` of investigation-specific code.
5. Delete `evidence_gate.py` once its logic is distributed into the tracker, classifier, and arbiter.

---

## Evidence Gate Verdict

**Score (1-10): 3**

**Verdict: Refactor into clean abstractions.**

The evidence gate is *architecturally unsound* but *functionally necessary*. Deleting it would remove the only mechanism forcing deeper exploration, which would make Problems 1 and 2 worse. However, keeping it in its current form guarantees technical debt accretion:

- **Duplication:** It re-parses conversation history that other trackers already processed.
- **Leakage:** It injected feature-specific fields into generic state carriers (`StreamingTurnState.evidence_gate_continuations`).
- **Fragility:** Regexes and frozensets will rot as tool names evolve, new languages are added, or the prompt profile schema changes.
- **Dual control:** Two loop controllers create a non-deterministic execution path that is hard to reason about and nearly impossible to unit test comprehensively.

The correct path is to *dissolve* the monolithic gate into three well-separated concerns:
1. **Classification** (should this request trigger deep exploration?)
2. **Tracking** (what has the model actually done?)
3. **Arbitration** (should the loop continue, break, or retry?)

Each of these should be a replaceable policy, not a 578-line imperative script.

---

## Overall Recommendation

1. **Stop the bleeding:** Do not add more regexes or frozensets to `evidence_gate.py` or `state.py`. Any new heuristic makes the refactor harder.
2. **Extract first:** Move `InvestigationState` and the evidence collection logic out of `messaging/state.py` immediately. A 560-line state carrier is a code smell.
3. **Unify loop control:** Replace the `iteration >= max` + `evidence_gate.should_continue` duality with a single `TurnLoopArbiter` that composes iteration-limit, evidence-sufficiency, and response-quality policies.
4. **Fix silent failure:** Make response-quality assessment a first-class loop policy. Do not rely on `has_visible_output` alone; treat known stub patterns as retry triggers.
5. **Make depth pluggable:** Replace `INVESTIGATION_DEPTH_POLICIES` (the hardcoded dict in `tool_runtime.py`) with a factory registry. This allows depth policies to be tested in isolation and extended without touching the executor.

The root cause is not that developers wrote bad regexes. The root cause is that the architectural boundary between "loop control" and "domain policy" was never drawn, so every new requirement (force more tools, track coverage, detect empty responses) got welded onto the existing loop as a new conditional. The fix is to draw that boundary explicitly: **the executor decides when to iterate; policies decide whether the current iteration was good enough.**
