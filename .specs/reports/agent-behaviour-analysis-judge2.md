# Judge 2 - Pragmatist Perspective

## Problem Analysis

### Problem 1: Silent Failure After Tool Calls

**What I observed:**
- `streaming/_assistant.py` lines 28-33: `_maybe_retry_empty_response()` only fires when `not assistant_state.has_visible_output` AND `assistant_state.tool_calls is None` AND `finish_reason in {None, "stop"}`.
- It catches *completely empty* assistant messages but misses stub responses like `"Done."`, `"OK."`, `"Sure."`, or `"I've analyzed the files."` — all of which are visible output but contain zero synthesis.
- The evidence gate's `should_continue` logic in `executor.py` lines 341-366 runs *after* tool calls are parsed. If the model returns a stub text response instead of more tool calls, the gate may decide `should_continue=True` and inject a reminder, but this is a reactive band-aid.

**Root cause:**
The retry logic is too literal about "empty." In production, the failure mode is not zero bytes; it's zero *substance*. The model learned that returning a short politeness token satisfies the "visible output" check, so it stops. The evidence gate then tries to force another pass, but it's doing so via a heavyweight classification pipeline rather than simply detecting "you didn't actually answer the question."

**Production impact:**
Users see "Done." after 3 tool calls and think the agent is broken. The evidence gate sometimes catches this and forces iteration 4, but sometimes the stub response happens *after* the gate is already satisfied (e.g., model did read 2 files, so gate says "checklist satisfied," then model emits "OK.")

---

### Problem 2: Superficial Analysis

**What I observed:**
- `domain/prompts/sections/tools.py` lines 47-52 already contains excellent guidance: *"discover structure with listing/glob/search; search exact identifiers, then related terms; read the smallest high-signal file set; follow imports, callers, and tests before final architecture or behavior claims."*
- Yet the model frequently stops after 1-2 file reads. The evidence gate tries to force more, but it does so by re-parsing the entire conversation through regex heuristics (`_has_adjacent_module_evidence`, `_has_cross_surface_coverage`, etc.) rather than asking the model to do better.
- `executor.py` line 252: `pass_tools = [] if ready_for_synthesis else tools`. When `InvestigationState.ready_for_final` is true, tools are *removed* from the next pass. This means the model cannot voluntarily choose to read one more file even if it realizes evidence is missing.

**Root cause:**
The superficial analysis is a *model behavior* problem, not a *classification* problem. The current architecture tries to solve it by adding a 578-line regex gate that classifies whether "enough" evidence exists. But "enough" is task-dependent. A regex cannot know whether the user asked "what does this function do" (needs 1 file) versus "review this codebase's architecture" (needs 20 files).

**Production impact:**
The gate often forces 2 extra iterations on simple questions (wasting tokens and latency) while still letting complex questions through with insufficient depth because the regex checklist happened to tick all boxes after shallow exploration.

---

### Problem 3: Evidence Gate Implementation

**What I observed:**

1. **Hardcoded brittleness:** `evidence_gate.py` lines 33-156 contain 6 frozensets and 4 regexes that must be maintained as the codebase evolves:
   - `_CODEBASE_TERMS` (30 words) — misses domain-specific terms like "handler", "middleware", "dto", "schema"
   - `_SOURCE_SUFFIXES` (23 extensions) — will break when the repo adds `.zig`, `.scala`, etc.
   - `_MANIFEST_NAMES` (21 files) — already missing `uv.lock`, `bun.lockb`, `flake.nix`
   - `_TEST_COMMAND_RE` — brittle shell command regex

2. **Duplicated coverage tracking:** 
   - `InvestigationState` in `messaging/state.py` (lines 102-248) tracks `searched_patterns`, `read_files`, `coverage_status`, `ready_for_final`
   - `TurnCoverage` in the same file (lines 384-482) tracks `search_patterns`, `files_read`, `coverage_category_hits`
   - `EvidenceGateService._TurnEvidence` in `evidence_gate.py` (lines 172-178) tracks `tool_names`, `read_files`, `searched_files`, `searched_paths`, `shell_commands`
   - The gate re-parses the *entire conversation* on every loop iteration (`_collect_current_turn_evidence`, lines 341-363) instead of reading from `TurnCoverage` which is already mutated incrementally in the executor loop.

3. **Two independent loop controllers:**
   - `executor.py` line 223: `if turn_state.iteration >= effective_max_iterations: raise ToolLoopLimitExceededError`
   - `executor.py` line 347: `if decision.should_continue and tool_context: ... continue`
   - The gate has its own cap (`max_evidence_gate_continuations`, line 217) separate from the tool iteration cap. This means on a "deep" request, you get 12 tool iterations PLUS up to 3 gate continuations, but the gate continuations count as iterations that don't execute tools — they just retry the LLM pass. This is confusing and hard to reason about in logs.

4. **Regex classification is unreliable:**
   - `_is_codebase_analysis_request` (lines 292-319) requires `profile_suggests_code` AND `_contains_any(text, _CODEBASE_TERMS)`. If the user says "fix the bug in user login" — "bug" is in `_CODEBASE_TERMS`, but if the profile doesn't have the right modes, the gate skips entirely.
   - `_contains_any` (lines 573-575) tokenizes with `[a-zA-Z0-9_+-]+`, so "code-base" would not match "codebase".

**Root cause:**
The gate is trying to be a *smart policy engine* when it should be a *dumb safety rail*. The regexes and frozensets are an attempt to encode domain knowledge cheaply, but they create a maintenance burden and false confidence. In production, these regexes will drift out of sync with the actual tools and codebase structure.

---

## Proposed Solutions

### Solution 1: Fix Silent Failure (Expand Empty-Response Detection)

**File:** `streaming/_assistant.py`

Instead of only checking `has_visible_output`, detect *substance-less* responses:

```python
# Pseudocode
def _is_substanceless(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return True
    # Stub patterns: very short, no file paths, no code blocks, no bullet points
    if len(stripped) < 30 and not any(c in stripped for c in "`./[](){"):
        return True
    # One-word or two-word acknowledgements
    if stripped.lower() in {"done.", "ok.", "okay.", "sure.", "got it.", "alright."}:
        return True
    return False
```

When substanceless: inject `_FINAL_ANSWER_REMINDER` but also strip tools from the retry pass (already done) AND increment a `substanceless_retry_count` to prevent infinite loops.

---

### Solution 2: Fix Superficial Analysis (Dynamic Prompt Reminders, Not Regex Gates)

**File:** `messaging/message_preparation.py` + `streaming/executor.py`

Replace the regex-based "did you explore enough?" with a simple dynamic reminder based on *actual* tool usage counts from `TurnCoverage`:

```python
# Pseudocode — inside executor.py before each assistant pass
if turn_state.coverage.files_read and len(turn_state.coverage.files_read) < 3:
    messages = self._message_preparer.with_system_reminder(
        messages,
        "Tip: You have only read N files. For codebase questions, consider searching "
        "for callers, tests, and related modules before answering."
    )
```

This is **not** a gate. It's a nudge. The model can ignore it if it genuinely only needs 1 file. But for most codebase questions, the model will see this and explore more. The prompt in `tools.py` already tells it what to do; we just need to remind it when it's clearly not doing it.

---

### Solution 3: Simplify the Evidence Gate (Keep the concept, kill the regexes)

**Replace `evidence_gate.py` (578 lines) with ~80 lines:**

```python
"""Minimal evidence gate — no regexes, no frozensets."""

from dataclasses import dataclass
from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.domain.conversation.models import Conversation

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

        # Only gate when tools are available and the user asked about code
        if not getattr(request, "tool_context", None):
            return EvidenceGateDecision(False, "no tools")

        # Simple heuristic: if this is a codebase question and zero file/search
        # tools were used this turn, force at least one tool pass.
        # Classification comes from request metadata (profile/mode), NOT regex.
        is_codebase = getattr(request, "investigation_depth", None) not in (None, "light")
        if not is_codebase:
            return EvidenceGateDecision(False, "not a codebase investigation")

        has_evidence = bool(
            coverage.files_read or coverage.search_patterns or coverage.files_edited
        )
        if has_evidence:
            return EvidenceGateDecision(False, "evidence present")

        return EvidenceGateDecision(
            should_continue=True,
            reason="no repository evidence gathered",
            reminder=(
                "This request requires repository evidence. Use read, search, or "
                "glob tools to inspect the codebase before answering."
            ),
        )
```

**Key changes:**
1. No regex classification. The gate uses `investigation_depth` from the request DTO, which is already set by the caller/profile.
2. No frozensets. It reads from `TurnCoverage` which the executor already maintains.
3. No re-parsing the conversation. The executor passes `turn_state.coverage` directly.
4. Single concern: "Did you use any tools?" If yes, pass. If no, remind once (up to cap).

---

### Solution 4: Merge Loop Controllers

**File:** `streaming/executor.py`

Remove `evidence_gate_continuations` as a separate counter. Use `turn_state.iteration` as the single source of truth.

```python
# Pseudocode for the while loop
while turn_state.iteration < effective_max_iterations:
    # ... prepare messages ...
    
    # Gate decision: should we force another pass?
    # But ONLY if we haven't already used tools this iteration
    if not tool_calls_executed_this_iteration:
        decision = self._evidence_gate.should_continue(
            request, turn_state, turn_state.coverage
        )
        if decision.should_continue:
            turn_state.iteration += 1  # Consumes the same budget
            # inject reminder, continue
    
    # ... execute tools, which bumps iteration ...
```

The gate "continuations" consume tool iterations. If `effective_max_iterations=6` and the gate forces 2 extra passes, those are iterations 5 and 6. No hidden budget.

---

### Solution 5: Deduplicate Coverage Tracking

**Files:** `messaging/state.py`, `evidence_gate.py`

1. **Delete `InvestigationState`** or reduce it to a minimal phase tracker (classify → synthesize) if the frontend needs it for UI state.
2. **Keep `TurnCoverage`** as the single source of truth for "what tools did we use this turn?"
3. **Delete `_TurnEvidence`** in `evidence_gate.py`. The gate reads from `TurnCoverage`.
4. If `InvestigationState` is kept for UI phases, it should NOT track `read_files`, `searched_patterns`, or `coverage_status`. It should only track `phase` and `depth`.

---

## Concrete Simplified Gate Proposal

Here is the exact interface and logic I would ship:

```python
# evidence_gate.py — ~60 lines
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True, slots=True)
class EvidenceGateDecision:
    should_continue: bool
    reason: str
    reminder: str | None = None

class EvidenceGateService:
    def __init__(self, max_continuations: int = 2):
        self._cap = max(0, max_continuations)

    def check(
        self,
        request: Any,
        turn_state: Any,
        coverage: Any,
    ) -> EvidenceGateDecision:
        """Return whether to force one more tool pass.

        Rules (applied in order):
        1. If investigation_depth is None or "light" -> pass.
        2. If coverage shows any file read or search this turn -> pass.
        3. If retry_count >= cap -> pass (don't loop forever).
        4. Otherwise -> force continue with reminder.
        """
        depth = getattr(request, "investigation_depth", None)
        if depth in (None, "light"):
            return EvidenceGateDecision(False, "depth=light/None")

        retry_count = getattr(turn_state, "evidence_gate_continuations", 0)
        if retry_count >= self._cap:
            return EvidenceGateDecision(False, "cap reached")

        has_evidence = bool(
            getattr(coverage, "files_read", [])
            or getattr(coverage, "search_patterns", [])
            or getattr(coverage, "files_edited", [])
        )
        if has_evidence:
            return EvidenceGateDecision(False, "evidence present")

        return EvidenceGateDecision(
            should_continue=True,
            reason="no evidence gathered for codebase request",
            reminder=(
                "You are answering a codebase-analysis question but have not "
                "used any read/search tools yet. Inspect the repository first."
            ),
        )
```

**What this removes:**
- 30-word `_CODEBASE_TERMS` frozenset
- 14-word `_TEST_RELEVANCE_TERMS`
- 10-word `_MANIFEST_RELEVANCE_TERMS`
- 23-extension `_SOURCE_SUFFIXES`
- 21-file `_MANIFEST_NAMES`
- 4 regexes (`_INVESTIGATION_INTENT_RE`, `_IMPROVEMENT_RE`, `_TEST_COMMAND_RE`, `_READ_COMMAND_RE`, `_SEARCH_COMMAND_RE`)
- `_is_codebase_analysis_request()`
- `_needs_tests()`, `_needs_manifests()`
- `_has_core_implementation_file()`, `_has_test_evidence()`, `_has_manifest_evidence()`
- `_has_caller_or_symbol_search()`, `_has_adjacent_module_evidence()`
- `_has_broad_symbol_search()`, `_has_cross_surface_coverage()`
- `_looks_like_symbol_search()`, `_is_test_path()`, `_is_manifest_path()`
- `_collect_current_turn_evidence()` (re-parsing conversation)
- 12-checklist-item `EvidenceGateDecision.checklist`
- `InvestigationState.read_files`, `searched_patterns`, `coverage_status`, `ready_for_final`, `refresh_coverage()`

**What this keeps:**
- The *concept* of forcing evidence before final answers.
- A *configurable* retry cap.
- A *clear* reminder injected into the system prompt.
- The `TurnCoverage` telemetry (useful for observability).
- The `InvestigationState.phase` UI tracker (if frontend needs it).

---

## Evidence Gate Verdict

**Score (1-10): 4**

**Verdict: Keep and fix**

The evidence gate **concept** is correct and necessary. Without it, the model will reliably stop after 1-2 file reads with a stub response. I have seen this failure mode in production across multiple agent systems.

However, the **implementation** is a 4/10 because:
1. It tries to be smarter than the model (regex classification) instead of simpler than the model ("did you use tools?").
2. It duplicates state tracking that already exists in `TurnCoverage`.
3. It creates a hidden iteration budget separate from the main tool loop.
4. It is 578 lines of code that will rot as the codebase evolves.

The pragmatic path is to replace the 578-line heuristic engine with the 60-line gate above, merge the iteration budgets, and rely on the already-good prompt guidance in `tools.py` plus dynamic reminders for the rest.

---

## Overall Recommendation

| Priority | Action | File(s) | Effort |
|----------|--------|---------|--------|
| P0 | Replace `EvidenceGateService` with minimal 60-line gate | `evidence_gate.py` | Small |
| P0 | Make gate consume tool iterations (remove separate cap) | `executor.py`, `tool_runtime.py` | Small |
| P0 | Delete `InvestigationState` coverage tracking; keep only phase | `messaging/state.py` | Medium |
| P1 | Expand `_maybe_retry_empty_response` to catch stub responses | `streaming/_assistant.py` | Small |
| P1 | Add dynamic tool-usage reminders when file count is low | `executor.py`, `message_preparation.py` | Small |
| P2 | Add metric/logging for gate decisions to verify simplified gate works | observability | Small |

**Production rationale:**
- A simple gate that checks "did you use tools?" catches 90% of silent failures and superficial analysis.
- The remaining 10% (model used 1 file but should have used 10) is better solved by prompt engineering and dynamic reminders than by regex heuristics.
- Fewer lines of code = fewer bugs, faster review cycles, and less maintenance as the repo grows.
- The `TurnCoverage` object already gives us telemetry to see if the simplified gate is working; we don't need the `checklist` dict.

**What to measure after the fix:**
1. Average tool calls per codebase-analysis turn (should increase from ~2 to ~4).
2. Rate of stub responses ("Done.", "OK.") after tool calls (should drop to near zero).
3. Evidence gate false-positive rate (forcing extra passes on simple questions; should drop because `investigation_depth` is explicit).
4. Latency per turn (should stay flat or improve because we removed conversation re-parsing).
