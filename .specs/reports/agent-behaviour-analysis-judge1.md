# Judge 1 - Minimalist Perspective

## Problem Analysis

### Problem 1: Silent Failure After Tool Calls

**Current behavior:** `_maybe_retry_empty_response()` in `@backend/src/personagent/application/use_cases/chat/streaming/_assistant.py` (lines 18-94) only retries when `not assistant_state.has_visible_output` — i.e., when the assistant produces **literally nothing** after tool execution.

**Why this is insufficient:**
- The guard at line 30 (`not assistant_state.has_visible_output`) returns `False` for stub responses like "Done.", "OK.", "Fixed.", or "I've completed the task." These have visible output but are functionally empty — they contain no analysis, no file references, no reasoning.
- The retry only fires once. If the model stubs again on the retry pass, the code falls through to `empty_model_response_notice` (lines 62-92) and emits a generic failure message to the user.
- The root cause is not "the model forgot to answer." The root cause is "the model thinks a one-word answer is sufficient after reading tools."

**Minimalist diagnosis:** The retry logic is treating the symptom (empty output) rather than the cause (the model's willingness to under-answer). You don't need 94 lines of retry scaffolding. You need the model to know that tool results are not an answer, and that stub responses are unacceptable.

---

### Problem 2: Superficial Analysis

**Current behavior:** The agent stops after 1-3 tool calls because there is no prompt-level enforcement of thoroughness. The `File Operations` section in `@backend/src/personagent/domain/prompts/sections/tools.py` (lines 34-58) gives good advice:
> "discover structure with listing/glob/search; search exact identifiers, then related terms; read the smallest high-signal file set; follow imports, callers, and tests before final architecture or behavior claims..."

**Why this doesn't work:**
- It's one paragraph in a larger prompt. Models are lazy readers. Operational instructions buried in prose get ignored.
- There's no negative reinforcement — no "if you stop early, you will be wrong."
- The model has no visibility into whether it has "enough" evidence. Humans know when to stop reading; models don't unless you tell them explicitly.

**The evidence gate response:** The team added 578 lines of `evidence_gate.py` + ~420 lines of `InvestigationState`/`TurnCoverage` in `state.py` to force the model to continue. This is the exact opposite of minimalism.

---

### Problem 3: Evidence Gate Implementation

**What exists:**

1. **`evidence_gate.py` (578 lines):**
   - 6 hardcoded regexes: `_INVESTIGATION_INTENT_RE`, `_IMPROVEMENT_RE`, `_TEST_COMMAND_RE`, `_READ_COMMAND_RE`, `_SEARCH_COMMAND_RE`
   - 6 hardcoded frozensets: `_CODEBASE_TERMS` (30 words), `_TEST_RELEVANCE_TERMS` (14), `_MANIFEST_RELEVANCE_TERMS` (10), `_SOURCE_SUFFIXES` (23 extensions), `_MANIFEST_NAMES` (21 files), `_READ_TOOL_NAMES`, `_SEARCH_TOOL_NAMES`
   - Re-parses the entire conversation from the last user message on every check (`_collect_current_turn_evidence`, lines 341-363)
   - Maintains a checklist of 13 boolean conditions (lines 243-258)
   - Duplicates path-normalization logic already present in `state.py`

2. **`state.py` (~560 lines, was ~140):**
   - `InvestigationState` dataclass (lines 102-249) duplicates the intent classification (`_INVESTIGATION_INTENT_RE`, line 41; `_IMPROVEMENT_RE`, line 49)
   - `TurnCoverage` (lines 384-483) duplicates evidence tracking
   - 7 module-level regexes/frozensets that overlap with `evidence_gate.py`
   - `refresh_coverage()` (lines 204-224) uses hardcoded surface tokens: `"route"`, `"api"`, `"main"`, `"cli"`, `"entry"`, `"controller"`, `"domain"`, `"model"`, `"service"`, `"adapter"`, `"infrastructure"`, `"repository"`, `"client"`, `"test"`, `"spec"`, `"config"`

3. **`executor.py` (lines 221-396):**
   - Has **two independent loop controllers**:
     - `turn_state.iteration >= effective_max_iterations` (line 223) — hard limit
     - `evidence_gate.should_continue_investigation()` (lines 341-366) — soft limit that can `continue` the while loop
   - When `ready_for_synthesis=True`, tools are stripped (`pass_tools = []`) and a synthesis reminder is injected (lines 248-255)
   - When evidence gate says continue, a reminder is injected and the loop iterates again (lines 243-246, 365-366)

**Why this is bad:**
- **Dual loop controllers are a bug waiting to happen.** The evidence gate can force a `continue` even when `iteration` is at `effective_max_iterations - 1`, causing the next iteration to hit the hard cap and raise `ToolLoopLimitExceededError`. The gate's `continuation_cap` (2-5) is independent of the iteration limit, creating a race condition.
- **O(N*M) re-parsing.** Every time the gate runs, it walks backward through the conversation to find the last user message, then re-parses every tool message since then. This happens on every loop iteration for active investigations.
- **Maintenance burden.** `_CODEBASE_TERMS` has 30 words. What about "microservice", "lambda", "handler", "middleware", "middlewares", "handler", "dto", "schema", "migration", "seed", "factory", "fixture"? The list is necessarily incomplete. Every new domain requires updating frozensets.
- **False positives/negatives.** A user asking "how do I configure my editor for this repo" matches `_CODEBASE_TERMS` ("config", "repo") but needs no evidence gate. A user asking "why is my asyncio task cancelling" doesn't match the regex but might need deep investigation.
- **No learning.** The frozensets are static. They don't adapt to the actual codebase structure, the user's history, or the model's observed behavior.

**The deeper architectural sin:** The evidence gate is trying to do with imperative code what should be done with a prompt. It inspects tool usage *after the fact* and forces another iteration. A prompt can shape behavior *before the fact* and avoids all the parsing, classification, and checklist maintenance.

---

## Proposed Solutions

### Solution 1: Fix Silent Failures with Prompt + Expanded Retry (not 578 lines)

**A. Prompt-level fix:** Add a single paragraph to the system prompt (in `tools.py` or the main prompt builder):

```
After executing tools, you MUST synthesize findings into a substantive answer. 
One-word responses like "Done.", "OK.", or "Fixed." are forbidden. 
Your answer must reference specific files, functions, or lines, and explain 
how the tool results support your conclusion. If evidence is insufficient, 
call more tools instead of guessing.
```

**B. Expand `_maybe_retry_empty_response` to catch stubs:**

```python
_STUB_RE = re.compile(r"^(done|ok|fixed|completed|resolved|looks good)[.!]?$", re.I)

def _is_stub_response(content: str) -> bool:
    stripped = content.strip()
    return len(stripped) < 30 or bool(_STUB_RE.match(stripped))
```

Then change the retry condition from `not has_visible_output` to `not has_visible_output or _is_stub_response(content)`.

**Cost:** ~5 lines of regex + 1 prompt paragraph. vs. 94 lines of retry logic that still fails.

---

### Solution 2: Fix Superficial Analysis with Prompt Engineering (not 1000+ lines)

**Replace the current `File Operations` paragraph with a structured checklist that the model can self-evaluate:**

```
Before giving your final answer to any codebase question, you must complete 
the following self-check. Do not answer until all items are true:

1. I have searched for or read the primary file(s) mentioned in the question.
2. I have read at least one related implementation file (followed imports/callers).
3. I have checked for relevant tests or manifest/config files.
4. I can name specific files and line numbers that support my conclusion.

If any item is false, call more tools. Never guess. Never summarize tool 
outputs without analysis.
```

**Why this works:**
- It's self-evaluating. The model is good at checking its own work when given a checklist.
- It doesn't require parsing conversation history. The model carries its own state in its context window.
- It's universal. Works for any codebase, any language, any domain. No frozensets to maintain.
- It's visible to the model on every turn. Not hidden in a service class it can't see.

---

### Solution 3: Delete the Evidence Gate (or reduce to a simple retry counter)

**Option A: Delete entirely.**
- Remove `evidence_gate.py` (578 lines)
- Remove `InvestigationState` and `TurnCoverage` from `state.py` (revert to ~140 lines)
- Remove `evidence_gate` integration from `executor.py` (lines 248-255, 341-377)
- Remove `with_synthesis_reminder` from `message_preparation.py` (lines 196-215)
- Remove `minimum_evidence_expectations` and `max_evidence_gate_continuations` from `tool_runtime.py`
- Remove `test_chat_evidence_gate.py`

**What remains:** A single while loop controlled by `effective_max_iterations`. The prompt does the work of encouraging thoroughness. The retry logic catches stubs and empties.

**Option B: Reduce to a simple "are you sure?" retry.**
If you must have code-level enforcement, replace the entire gate with:

```python
class EvidenceGateService:
    def should_continue(self, conversation) -> bool:
        # Only check: did the model use tools this turn?
        # If not, and the user asked a codebase question, remind once.
        return False  # Prompt handles it
```

Actually, even that is unnecessary. Just delete it.

---

## Evidence Gate Verdict

**Score (1-10): 2**

**Verdict: Delete**

**Rationale:**
- The evidence gate is 578 lines of regex and frozensets that duplicate what a 50-word prompt paragraph can do.
- It adds a second loop controller (`executor.py` lines 341-366) that races with the primary iteration cap (`effective_max_iterations`), creating a `ToolLoopLimitExceededError` hazard.
- It re-parses the entire conversation history on every check (`_collect_current_turn_evidence`), which is O(N) per iteration.
- It is inherently incomplete: `_CODEBASE_TERMS` will always miss domain-specific vocabulary. `_SOURCE_SUFFIXES` will miss new languages. `_MANIFEST_NAMES` will miss new build systems.
- The `InvestigationState` and `TurnCoverage` in `state.py` duplicate the same logic, adding another ~420 lines. That's ~1000 lines of heuristic code to solve a prompting problem.
- The gate does not generalize. A prompt generalizes to any repo, any language, any framework.
- The tests (`test_chat_evidence_gate.py`) are tautological: they verify that the frozensets match the frozensets.

**What to keep:**
- `TurnCoverage.to_metadata()` is useful for telemetry/logging. Extract it to a 30-line telemetry helper.
- The `effective_max_iterations` cap is a necessary safety rail. Keep it.

---

## Overall Recommendation

1. **Delete `evidence_gate.py` entirely.** Remove from `executor.py`, `tool_runtime.py`, `message_preparation.py`, and tests.
2. **Revert `state.py` to ~140 lines.** Remove `InvestigationState`, `TurnCoverage`, and their regex/frozenset dependencies. Keep `AssistantStreamState`, `StreamingTurnState`, `PromptPackage`, `PromptPreparation`, `MemoryRecallResult`.
3. **Add a self-checklist to the system prompt.** Replace the current `File Operations` prose with a structured "before you answer" checklist that the model evaluates itself against.
4. **Expand empty-response retry to catch stubs.** Change `_maybe_retry_empty_response` to trigger on stub patterns ("Done.", "OK.", <30 chars) in addition to completely empty output.
5. **Keep the single iteration cap.** `effective_max_iterations` is sufficient loop control. One cap, not two.

**Expected outcome:**
- ~1000 lines deleted.
- No behavioral regression on thoroughness (prompt handles it).
- No behavioral regression on silent failures (prompt + expanded retry handles it).
- Simpler mental model: one loop, one cap, one prompt.
- Faster execution: no conversation re-parsing, no regex classification on every iteration.

**The minimalist credo:** If you find yourself writing 578 lines of regex to make a model use tools more, you have a prompt problem, not a code problem.
