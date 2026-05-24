# ADR 0023: Intra-Turn Dynamic Prompt Builder via Layered State Resolution

Date: 2025-05-24
Status: Accepted

## Context

ADR 0007 introduced the modular prompt system with `PromptContextAnalyzer` (LLM-based, pre-turn) and `AgentStateResolver` (heuristic, pre-turn). Both resolve state **once before the turn starts**. During the tool loop (`StreamingTurnExecutor.run`), the system prompt remains static across all iterations.

This creates a mismatch: an agent that starts a turn exploring code and transitions to writing code mid-loop continues receiving explorer-optimized prompts. The system has no mechanism to adapt prompt guidance as the agent's execution phase shifts within a single turn.

The core constraint is latency. Any intra-loop classification must complete in sub-millisecond time — LLM calls (2–12 s) and embedding lookups (5–50 ms) are too slow for a hot path that runs on every tool-loop iteration.

### Current Gaps in `AgentStateResolver`

The existing resolver already runs in < 0.1ms and resolves 12 states, but:
1. Only uses keyword heuristics from the user message — not runtime signals
2. Has no memory of transitions (does not know "was in state X last iteration")
3. Does not incorporate signals from tool execution results or agent output
4. Runs once pre-turn, never re-evaluates during the tool loop

## Decision

Replace the single-pass pre-turn state resolution with a **two-layer intra-turn pipeline** that resolves execution phase at every tool-loop iteration and hot-swaps only the dynamic prompt layer on phase transitions.

### Phase Enum

A new `AgentPhase` enum represents the agent's observable execution behavior:

```
intake · exploring · planning · writing · testing · using_browser · debugging · finalizing
```

`AgentPhase` captures intra-turn runtime observation (what the agent *is doing*), complementing `AgentState` (pre-turn intent heuristic) and `PromptMode` (user intent classification).

### Two-Layer Resolution Pipeline

```
┌────────────────────────────────────────────────────────┐
│               DYNAMIC STATE PIPELINE                    │
├────────────────────────────────────────────────────────┤
│                                                        │
│  Layer 1: Agent Self-Declaration (0ms)                 │
│  ──────────────────────────────────                    │
│  The agent emits `_phase` in response metadata.        │
│  If present and valid → use directly. Skip Layer 2.    │
│                                                        │
│  Layer 2: Deterministic FSM (< 0.05ms)                 │
│  ──────────────────────────────────                    │
│  If Layer 1 unavailable (1st iteration, missing tag):  │
│  → Classify from runtime signals (tool names, errors,  │
│    iteration count, finish reason)                     │
│  → Transition in state graph with history tracking     │
│                                                        │
│  [Fallback]: Current AgentStateResolver (< 0.1ms)      │
│                                                        │
├────────────────────────────────────────────────────────┤
│                                                        │
│  PRE-COMPILED PROMPT CACHE                             │
│  ──────────────────────────────────                    │
│  dict[str, str] mapping phase → pre-rendered block     │
│  Common combinations pre-compiled at startup           │
│  Load from memory: < 0.01ms                            │
│                                                        │
└────────────────────────────────────────────────────────┘
```

**Why two layers, not three:** The external analysis proposed a Micro-Classifier (Layer 3, sklearn/numpy) for ambiguous cases. We reject this because: (a) it adds a numpy/sklearn dependency, (b) requires training data we don't have yet, (c) the FSM + self-declaration already covers ~95% of cases, and (d) the fallback to `AgentStateResolver` handles the remaining ~5% adequately. If future telemetry shows the FSM is insufficient, a micro-classifier can be added later without architectural changes.

**Why not the Micro-Agent (ONNX/TinyBERT):** Training and maintaining a dedicated ML model for state classification is disproportionate to the problem. The signals are deterministic — if the agent just called `EditFile`, it is implementing. ML inference adds latency, dependency, and maintenance overhead for marginal precision gain over a well-tuned FSM.

### Layer 1 — Agent Self-Declaration

The agent declares its execution phase in response metadata:

```python
# In agent response metadata:
{
    "_phase": "writing",
    "_next_phase": "testing",
}
```

Cost: ~10 output tokens per response. The system prompt includes a brief instruction block asking the agent to declare phase. When `_phase` is present and maps to a valid `AgentPhase`, the pipeline uses it directly (0ms classification).

Expected coverage: ~85% of iterations after the first turn.

### Layer 2 — Deterministic FSM with Transition History

A state machine with explicit transitions and a bounded history deque:

```python
class AgentPhaseMachine:
    current_phase: AgentPhase = "intake"
    history: deque[AgentPhase]  # maxlen=10

    def transition(self, event: PhaseEvent) -> AgentPhase:
        next_phase = TRANSITIONS[self.current_phase].get(event)
        if next_phase and next_phase != self.current_phase:
            self.history.append(self.current_phase)
            self.current_phase = next_phase
        return self.current_phase
```

Events are derived from signals already in memory at each loop iteration:

| Signal | Source | I/O Cost |
|--------|--------|----------|
| Last tool names executed | `tool_calls` / `results_by_id` | 0 |
| Tool result statuses | `ToolResult.status` | 0 |
| Iteration count | `turn_state.iteration` | 0 |
| Finish reason | `assistant_state.finish_reason` | 0 |
| Has visible content | `assistant_state.content` | 0 |
| Has pending tool calls | `assistant_state.tool_calls` | 0 |

Event detection rules (ordered by priority):

1. **any tool status == ERROR** → `error_detected`
2. **tool set ∩ browser_tools ≠ ∅** → `browser_action`
3. **tool set ∩ write_tools ≠ ∅** → `code_edit_detected`
4. **tool set ∩ test_tools ≠ ∅** → `test_run` (with ShellExec command heuristic)
5. **tool set ∩ planning_tools ≠ ∅** → `plan_requested`
6. **tool set ∩ read_tools ≠ ∅** → `read_action`
7. **no tool calls + has content** → `final_response`
8. **iteration == 0** → `turn_start`

Transition table defines valid transitions per current phase and event. Invalid or unrecognized events leave the phase unchanged (sticky state). History enables "return to previous phase" patterns (e.g., debugging → return to writing).

### Prompt Layering

The system prompt is split into two layers:

```
┌──────────────────────────────────┐
│ STATIC LAYER (cached per turn)   │  Built once by PromptBuilder.build()
│ - Identity, rules, style         │
│ - Tool definitions & schemas     │
│ - Execution policy               │
│ - Provider boundary              │
│ - Memory, skills, commands       │
├──────────────────────────────────┤
│ DYNAMIC LAYER (per iteration)    │  Hot-swapped on phase transition
│ - Phase-specific instructions    │
│ - Runtime reminders              │
│ - State Declaration Protocol     │
└──────────────────────────────────┘
```

Phase-specific prompt blocks are pre-rendered string constants (~500–2000 chars each). A `PromptTemplateCache` pre-compiles the ~15 most common phase combinations at startup. On a phase transition, only the dynamic layer is replaced via dict lookup + string concatenation.

### Hook Point

Inside `StreamingTurnExecutor.run`, between message preparation and the assistant pass:

```
while True:
    messages, context = prepare(...)
    ┌── resolve_phase(declared_state, turn_state signals)
    │   if phase changed → rebuild_dynamic(prompt_package, new_phase)
    │   emit StreamChunk(metadata={"event": "phase_transition", ...})
    └── assistant_pass_runner.run(messages, tools)
    ... tool execution ...
    capture declared_state from assistant_state.metadata["_phase"]
    turn_state.iteration += 1
```

### Latency Budget

| Scenario | Latency | Expected % |
|----------|---------|------------|
| Agent declared phase (Layer 1) | ~0ms | ~85% |
| FSM resolves from signals (Layer 2) | < 0.05ms | ~10% |
| Fallback to AgentStateResolver | < 0.1ms | ~5% |
| Prompt template cache hit | < 0.01ms | ~100% |
| **Worst case total per iteration** | **< 0.2ms** | — |

### Files Changed

| File | Change |
|------|--------|
| `domain/prompts/models.py` | Add `AgentPhase` enum, `PhaseEvent` enum |
| `domain/prompts/services/phase_classifier.py` | New: `AgentPhaseMachine`, event detection, Layer 1+2 pipeline |
| `domain/prompts/sections/phases.py` | New: phase-specific prompt constants, `PromptTemplateCache` |
| `application/use_cases/chat/state.py` | Add `current_phase`, `phase_history`, `last_tool_names`, `last_tool_statuses` to `StreamingTurnState` |
| `application/use_cases/chat/streaming_turn.py` | Phase resolution hook in the loop, phase transition events |
| `application/use_cases/chat/prompt_package.py` | `rebuild_dynamic()` method for partial prompt rebuild |
| `domain/prompts/services/prompt_builder.py` | Support for two-layer build (static once, dynamic per iteration) |

## Consequences

- **Easier**: agent prompts adapt mid-turn as execution context shifts; phase transitions are logged as StreamChunk events for telemetry; phase-specific instructions can be tuned independently; self-declaration creates a feedback loop where the agent participates in its own optimization.
- **Harder**: two overlapping state concepts (`AgentState` pre-turn + `AgentPhase` intra-turn) that must stay coherent; tool-set classification rules need maintenance when new tools are added; self-declaration adds ~10 tokens per response.
- **Risk**: model may not reliably emit `_phase` metadata (mitigation: Layer 2 FSM always available as fallback); prompt swap mid-conversation may confuse models that track instruction consistency (mitigation: only the dynamic layer changes, static layer is stable); FSM transition table may have gaps for edge cases (mitigation: sticky state + AgentStateResolver fallback).
- **Out of scope**: ML-based intra-turn classification (deferred pending telemetry data); automatic prompt compression; per-phase tool filtering (tools remain constant within a turn); cross-turn phase persistence (phase resets to `intake` each new turn).

## Alternatives Considered

- **LLM-based intra-turn classifier**: rejected because even the fastest providers add 1–2 s latency per iteration.
- **Embedding centroid match**: rejected because cosine similarity is imprecise (~0.65) for execution states and adds 2–8 ms latency.
- **Micro-classifier (sklearn/numpy)**: rejected for now — adds dependency and requires training data. Can be added as Layer 3 later if telemetry shows FSM insufficient.
- **Fine-tuned ONNX TinyBERT**: rejected — disproportionate maintenance overhead for marginal precision gain.
- **Extend AgentStateResolver to run intra-turn**: rejected because the resolver uses message-level keyword heuristics that don't capture tool-execution signals; extending it would conflate two distinct concerns.

## Validation

- `phase_classifier.py` must have unit tests covering all FSM transitions with mock tool-call data.
- Integration test: a multi-iteration tool loop with mixed tool types must produce the expected phase sequence.
- Self-declaration test: verify that `_phase` metadata is read from assistant response and correctly overrides FSM.
- Regression: existing `test_prompt_builder.py` and tool test suites must remain green (phase classification is additive).
- Observability: phase transitions emitted as `StreamChunk` metadata events (`event: "phase_transition"`) for telemetry.
- Latency benchmark: classification + swap must stay under 1 ms per iteration.
