# Dynamic Prompt Builder — Implementation Plan

> **ADR**: [0023-dynamic-prompt-builder](../../adr/0023-dynamic-prompt-builder.md)
> **Status**: Ready for implementation
> **Slices**: 4 PRs, ordered by dependency

---

## Architecture Overview

```
User Query (or Tool Loop iteration)
    │
    ▼
[0ms] Layer 1: Check `_phase` from assistant_state.metadata
    │
    ├── Valid phase found → use directly
    │
    └── Missing → [0.05ms] Layer 2: FSM transition from runtime signals
            │
            ├── Event detected → transition in state graph
            │
            └── No event → sticky (keep current phase)
    │
    ▼
[0.01ms] Load pre-compiled phase prompt from PromptTemplateCache
    │
    ▼
[0.1ms] Swap dynamic layer in prompt_package (if phase changed)
    │
    ▼
Agent executes with phase-optimized prompt
    │
    ▼
Agent emits `_phase` in response metadata → feeds next iteration
```

---

## Slice 1 — Domain Models & Phase Constants

**Files:**
- `domain/prompts/models.py` — Add `AgentPhase` and `PhaseEvent` enums
- `domain/prompts/sections/phases.py` — New: phase-specific prompt constants + `PromptTemplateCache`
- `tests/unit/test_phase_prompt_sections.py` — New: tests for constants and cache

### 1.1 `AgentPhase` Enum

Add to `domain/prompts/models.py` alongside existing `AgentState`:

```python
AgentPhase = Literal[
    "intake",
    "exploring",
    "planning",
    "writing",
    "testing",
    "using_browser",
    "debugging",
    "finalizing",
]
```

### 1.2 `PhaseEvent` Enum

```python
PhaseEvent = Literal[
    "turn_start",
    "read_action",
    "code_edit_detected",
    "test_run",
    "browser_action",
    "plan_requested",
    "error_detected",
    "final_response",
]
```

### 1.3 Phase Prompt Constants (`phases.py`)

Each phase gets a pre-rendered prompt block (~200-800 chars). These are string constants, not `SystemPromptSection` compute callables — they never need async resolution.

```python
PHASE_PROMPTS: dict[AgentPhase, str] = {
    "intake": """## Active Phase: Intake
Convert the latest input into a concrete objective. Identify outcome,
constraints, and risk level before deep work.""",

    "exploring": """## Active Phase: Context Discovery
You are actively reading code and building understanding. Use targeted
search and read tools. Stop when the objective and impacted surfaces
are clear enough to act.""",

    "planning": """## Active Phase: Planning
Structure your execution path. Order steps by dependency: discover,
decide, edit, validate, report. Use TodoWrite to track.""",

    "writing": """## Active Phase: Implementation
You are actively writing code. Keep edits narrow and behavior-driven.
Follow existing conventions. Do not call this phase complete until
validation has been attempted.""",

    "testing": """## Active Phase: Validation
You are running tests, lint, or build commands. Focus on verifying
correctness. If tests fail, diagnose the root cause before changing
test code.""",

    "using_browser": """## Active Phase: Browser Research
You are actively browsing the web. Extract the information you need
efficiently. Avoid unnecessary page loads.""",

    "debugging": """## Active Phase: Debug Recovery
An error occurred in the previous step. Isolate the root cause before
applying fixes. Read error messages carefully. Test hypotheses.""",

    "finalizing": """## Active Phase: Finalization
You are producing the final response. Be direct, lead with the outcome.
Include evidence and next actions as needed.""",
}
```

### 1.4 `PromptTemplateCache`

```python
class PromptTemplateCache:
    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._precompile()

    def get(self, phase: AgentPhase) -> str:
        return self._cache.get(phase, PHASE_PROMPTS.get(phase, ""))

    def _precompile(self) -> None:
        for phase, prompt in PHASE_PROMPTS.items():
            self._cache[phase] = prompt
```

### 1.5 State Declaration Protocol Prompt

A constant added to the dynamic layer instructing the agent to declare phase:

```python
STATE_DECLARATION_PROTOCOL = """## State Declaration Protocol

At the end of each response, include in your metadata:
- `_phase`: your current execution phase (one of: exploring, writing, testing, planning, debugging, using_browser, finalizing)
- `_next_phase`: your predicted next phase

This enables instant prompt optimization for your next turn."""
```

**Tests (15+ cases):**
- Verify all `AgentPhase` values have corresponding `PHASE_PROMPTS` entries
- Verify `PromptTemplateCache.get()` returns correct content for each phase
- Verify cache miss returns empty string gracefully
- Verify `STATE_DECLARATION_PROTOCOL` is a non-empty string
- Verify `PhaseEvent` values are all valid strings

---

## Slice 2 — Phase Classifier (`AgentPhaseMachine`)

**Files:**
- `domain/prompts/services/phase_classifier.py` — New: FSM + event detection + Layer 1/2 pipeline
- `tests/unit/test_phase_classifier.py` — New: tests for all transitions

### 2.1 Tool Category Sets

```python
BROWSER_TOOLS = frozenset({
    "BrowserOpen", "BrowserExtractContent", "BrowserClick",
    "BrowserSearch", "BrowserType", "BrowserScreenshot",
    "BrowserListTabs", "BrowserGetHtml", "BrowserGetElementMap",
    "BrowserScroll", "BrowserReload", "BrowserCloseTab",
    "BrowserSwitchTab", "BrowserScript", "BrowserAct",
    "BrowserReadContentChunk", "BrowserHistory", "BrowserWait",
    "BrowserReadConsole",
})

WRITE_TOOLS = frozenset({
    "EditFile", "WriteFile", "CreateFile", "MultiEdit",
    "ReplaceInFile", "DeleteFile",
})

TEST_TOOLS = frozenset({"ShellExec"})
# ShellExec classified as testing only when command matches test heuristic

PLANNING_TOOLS = frozenset({"TodoWrite", "PlanMode"})

READ_TOOLS = frozenset({
    "ReadFile", "Search", "Grep", "ListFiles", "FileSearch",
    "FindFiles", "ReadDirectory",
})
```

### 2.2 Event Detection

```python
def detect_event(
    tool_names: Sequence[str],
    tool_statuses: Sequence[ToolExecutionStatus],
    has_content: bool,
    has_tool_calls: bool,
    iteration: int,
) -> PhaseEvent:
    if iteration == 0:
        return "turn_start"

    tool_set = frozenset(tool_names)

    if any(s == ToolExecutionStatus.ERROR for s in tool_statuses):
        return "error_detected"
    if tool_set & BROWSER_TOOLS:
        return "browser_action"
    if tool_set & WRITE_TOOLS:
        return "code_edit_detected"
    if tool_set & TEST_TOOLS:
        return "test_run"
    if tool_set & PLANNING_TOOLS:
        return "plan_requested"
    if tool_set & READ_TOOLS:
        return "read_action"
    if not has_tool_calls and has_content:
        return "final_response"

    return "read_action"  # safe default
```

### 2.3 Transition Table

```python
TRANSITIONS: dict[AgentPhase, dict[PhaseEvent, AgentPhase]] = {
    "intake": {
        "turn_start": "intake",
        "read_action": "exploring",
        "code_edit_detected": "writing",
        "test_run": "testing",
        "browser_action": "using_browser",
        "plan_requested": "planning",
        "error_detected": "debugging",
        "final_response": "finalizing",
    },
    "exploring": {
        "read_action": "exploring",
        "code_edit_detected": "writing",
        "test_run": "testing",
        "browser_action": "using_browser",
        "plan_requested": "planning",
        "error_detected": "debugging",
        "final_response": "finalizing",
    },
    "planning": {
        "read_action": "exploring",
        "code_edit_detected": "writing",
        "test_run": "testing",
        "browser_action": "using_browser",
        "plan_requested": "planning",
        "error_detected": "debugging",
        "final_response": "finalizing",
    },
    "writing": {
        "read_action": "exploring",
        "code_edit_detected": "writing",
        "test_run": "testing",
        "browser_action": "using_browser",
        "error_detected": "debugging",
        "final_response": "finalizing",
    },
    "testing": {
        "read_action": "exploring",
        "code_edit_detected": "writing",
        "test_run": "testing",
        "error_detected": "debugging",
        "final_response": "finalizing",
    },
    "using_browser": {
        "read_action": "exploring",
        "code_edit_detected": "writing",
        "browser_action": "using_browser",
        "error_detected": "debugging",
        "final_response": "finalizing",
    },
    "debugging": {
        "read_action": "exploring",
        "code_edit_detected": "writing",
        "test_run": "testing",
        "browser_action": "using_browser",
        "error_detected": "debugging",
        "final_response": "finalizing",
    },
    "finalizing": {
        "read_action": "exploring",
        "code_edit_detected": "writing",
        "final_response": "finalizing",
    },
}
```

### 2.4 `AgentPhaseMachine`

```python
@dataclass(slots=True)
class PhaseResolution:
    phase: AgentPhase
    source: str  # "self_declared" | "fsm" | "fallback"
    previous_phase: AgentPhase | None
    event: PhaseEvent | None
    changed: bool

class AgentPhaseMachine:
    def __init__(self) -> None:
        self._current: AgentPhase = "intake"
        self._history: deque[AgentPhase] = deque(maxlen=10)

    @property
    def current_phase(self) -> AgentPhase:
        return self._current

    @property
    def history(self) -> tuple[AgentPhase, ...]:
        return tuple(self._history)

    def resolve(
        self,
        *,
        declared_phase: str | None = None,
        tool_names: Sequence[str] = (),
        tool_statuses: Sequence[ToolExecutionStatus] = (),
        has_content: bool = False,
        has_tool_calls: bool = False,
        iteration: int = 0,
    ) -> PhaseResolution:
        previous = self._current

        # Layer 1: Self-declaration
        if declared_phase and declared_phase in VALID_PHASES:
            return self._transition_to(declared_phase, previous, source="self_declared")

        # Layer 2: FSM
        event = detect_event(tool_names, tool_statuses, has_content, has_tool_calls, iteration)
        next_phase = TRANSITIONS.get(self._current, {}).get(event)

        if next_phase:
            return self._transition_to(next_phase, previous, source="fsm", event=event)

        # Sticky: no valid transition, keep current
        return PhaseResolution(
            phase=self._current,
            source="fsm",
            previous_phase=previous,
            event=event,
            changed=False,
        )

    def _transition_to(
        self, phase: AgentPhase, previous: AgentPhase,
        source: str, event: PhaseEvent | None = None,
    ) -> PhaseResolution:
        changed = phase != previous
        if changed:
            self._history.append(previous)
        self._current = phase
        return PhaseResolution(
            phase=phase, source=source, previous_phase=previous,
            event=event, changed=changed,
        )

    def reset(self) -> None:
        self._current = "intake"
        self._history.clear()
```

**Tests (25+ cases):**
- `detect_event` returns correct event for each tool category
- `detect_event` prioritizes error over browser over write
- FSM transitions correctly for all phase×event combinations
- Sticky state: unrecognized event keeps current phase
- History tracks previous phases (maxlen=10)
- Layer 1 (self-declaration) overrides Layer 2 (FSM)
- Invalid `declared_phase` falls through to Layer 2
- `reset()` returns to intake and clears history
- `PhaseResolution.changed` is True only on actual transitions

---

## Slice 3 — Prompt Package Rebuild & StreamingTurnState

**Files:**
- `application/use_cases/chat/state.py` — Add phase fields to `StreamingTurnState`
- `application/use_cases/chat/prompt_package.py` — Add `rebuild_dynamic()` method
- `domain/prompts/services/prompt_builder.py` — Add `rebuild_dynamic_layer()` method
- `tests/unit/test_prompt_package_rebuild.py` — New: tests for partial rebuild

### 3.1 StreamingTurnState Changes

Add to `StreamingTurnState`:

```python
@dataclass(slots=True)
class StreamingTurnState:
    # ... existing fields ...

    # Phase tracking (ADR 0023)
    current_phase: AgentPhase = "intake"
    last_tool_names: list[str] = field(default_factory=list)
    last_tool_statuses: list[ToolExecutionStatus] = field(default_factory=list)
    declared_phase: str | None = None
```

### 3.2 `PromptPackageBuilder.rebuild_dynamic()`

```python
def rebuild_dynamic(
    self,
    package: PromptPackage,
    phase: AgentPhase,
    phase_cache: PromptTemplateCache,
) -> PromptPackage:
    """Hot-swap the dynamic prompt layer for a new phase.

    Replaces only the phase block in the system prompt, keeping
    the static layer intact. Cost: ~0.1ms (string replace).
    """
    phase_block = phase_cache.get(phase)
    # The system prompt has a marker separating static/dynamic
    static, _, _ = package.system_prompt.partition(PHASE_MARKER)
    new_prompt = f"{static}{PHASE_MARKER}\n\n{phase_block}"

    return PromptPackage(
        system_prompt=new_prompt,
        user_context_message=package.user_context_message,
        metadata={**package.metadata, "current_phase": phase},
    )
```

### 3.3 Phase Marker in `PromptBuilder`

Add a constant marker that separates static and dynamic layers:

```python
PHASE_MARKER = "<!-- DYNAMIC_PHASE_LAYER -->"
```

`PromptBuilder.build()` inserts this marker after the static sections, before the dynamic phase section. This allows `rebuild_dynamic()` to do a simple `partition()` + concatenation without re-resolving all sections.

### 3.4 Initial Phase Injection

In `PromptBuilder.build()`, after assembling all sections, append:

```python
phase_block = phase_cache.get("intake")  # default for first iteration
content = f"{content}\n\n{PHASE_MARKER}\n\n{phase_block}"
```

**Tests (10+ cases):**
- `rebuild_dynamic` replaces only the dynamic layer
- `rebuild_dynamic` preserves static layer content verbatim
- `rebuild_dynamic` updates metadata with `current_phase`
- `PHASE_MARKER` is correctly inserted by `PromptBuilder.build()`
- `partition()` handles missing marker gracefully (full prompt treated as static)

---

## Slice 4 — Hook into StreamingTurnExecutor

**Files:**
- `application/use_cases/chat/streaming_turn.py` — Phase resolution hook in the tool loop
- `interfaces/config/di_container.py` — Wire `AgentPhaseMachine` + `PromptTemplateCache`
- `tests/unit/test_streaming_turn_phase.py` — New: integration-style tests

### 4.1 StreamingTurnExecutor Changes

Add `phase_machine: AgentPhaseMachine` and `phase_cache: PromptTemplateCache` to constructor.

In the tool loop, **between message preparation and assistant pass** (line ~205 current):

```python
# Phase classification (ADR 0023)
resolution = self._phase_machine.resolve(
    declared_phase=turn_state.declared_phase,
    tool_names=turn_state.last_tool_names,
    tool_statuses=turn_state.last_tool_statuses,
    has_content=bool(assistant_state.content) if turn_state.iteration > 0 else False,
    has_tool_calls=bool(assistant_state.tool_calls) if turn_state.iteration > 0 else True,
    iteration=turn_state.iteration,
)
turn_state.current_phase = resolution.phase
if resolution.changed:
    prompt_package = self._prompt_package_builder.rebuild_dynamic(
        prompt_package, resolution.phase, self._phase_cache,
    )
    yield StreamChunk(
        metadata={
            "event": "phase_transition",
            "from_phase": resolution.previous_phase,
            "to_phase": resolution.phase,
            "source": resolution.source,
            "trigger_event": resolution.event,
            "iteration": turn_state.iteration,
        }
    )
```

After tool execution, capture signals for next iteration:

```python
# Capture phase signals for next iteration
turn_state.last_tool_names = [call.name for call in tool_calls]
turn_state.last_tool_statuses = [
    results_by_id[call.id].status
    for call in tool_calls
    if call.id in results_by_id
]
# Capture self-declared phase from assistant metadata
turn_state.declared_phase = (
    assistant_state.metadata.get("_phase")
    if isinstance(assistant_state.metadata.get("_phase"), str)
    else None
)
```

### 4.2 DI Container Wiring

In `di_container.py`, create singletons:

```python
phase_cache = PromptTemplateCache()
# AgentPhaseMachine is per-turn (not singleton) — created in StreamingTurnExecutor.run
```

The `AgentPhaseMachine` is created fresh for each turn (stateful per-turn, not per-request).

### 4.3 Phase Machine Reset

At the start of each `StreamingTurnExecutor.run()`, the phase machine resets to `intake`:

```python
self._phase_machine.reset()
```

**Tests (10+ cases):**
- Phase transition emits `StreamChunk` with correct metadata
- Phase stays sticky when no transition occurs (no StreamChunk emitted)
- `declared_phase` is captured from assistant metadata
- `last_tool_names` and `last_tool_statuses` are captured after tool execution
- Phase machine resets at start of each turn
- Full loop simulation: intake → exploring → writing → testing → finalizing

---

## Execution Order & Dependencies

```
Slice 1 (models + constants)
    │
    ▼
Slice 2 (FSM classifier)  ← depends on Slice 1 for AgentPhase/PhaseEvent
    │
    ▼
Slice 3 (prompt rebuild)  ← depends on Slice 1 for constants, Slice 2 for PhaseResolution
    │
    ▼
Slice 4 (hook + wiring)   ← depends on all previous slices
```

Each slice is one PR. No behavioral changes to existing code until Slice 4 (which is the integration point).

---

## Validation Checklist

- [ ] All existing tests pass (regression: 1680+ passed)
- [ ] Phase classifier tests cover all 8 phases × 8 events = 64 transition combinations
- [ ] Self-declaration (Layer 1) correctly overrides FSM (Layer 2)
- [ ] `rebuild_dynamic` preserves static layer byte-for-byte
- [ ] Phase transition events appear in StreamChunk metadata
- [ ] Latency benchmark: classify + swap < 1ms (target: < 0.2ms)
- [ ] No new external dependencies (no numpy, sklearn, onnx)
- [ ] State Declaration Protocol prompt is included in dynamic layer

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Model ignores `_phase` self-declaration | Layer 2 FSM handles 100% of cases independently |
| `ShellExec` misclassified (testing vs writing) | Command content heuristic: check for "test", "pytest", "lint", "build" in arguments |
| New tools added without updating category sets | Tool category sets are `frozenset` constants — ruff/CI won't catch missing entries. Add a lint rule or test that verifies all registered tools are categorized |
| Prompt swap confuses model mid-conversation | Only ~500-2000 chars change; static layer (identity, rules, tools) stays constant |
| `PHASE_MARKER` appears in user content | Use HTML comment syntax `<!-- DYNAMIC_PHASE_LAYER -->` — unlikely in natural text |
