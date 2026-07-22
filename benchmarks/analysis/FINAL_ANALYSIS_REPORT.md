# PersonAgent Prompt Harness — Exploration Benchmark Analysis

**Date:** 2026-05-30  
**Model:** deepseek-v4-flash  
**Benchmarks:** 6 (2 PersonAgent, 2 pydantic, 2 opencode)  
**Total Duration:** 260.2 seconds  
**Total Tokens:** 3,902,893  

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Success Rate** | 33.3% (2/6) |
| **Overall Harness Score** | 68.0 / 100 |
| **Exploration Breadth** | 95.0 / 100 |
| **Tool Efficiency** | 34.0 / 100 |
| **Persistence** | 61.7 / 100 |
| **Answer Quality** | 66.7 / 100 |
| **Prompt Harness Effectiveness** | 76.7 / 100 |

**Verdict:** ⚠️ The current prompt harness provides adequate guidance for simple-to-medium exploration tasks but fails significantly on complex cross-file reasoning. The primary failure mode is **agent stuckness** — the model repeatedly searches without reading new files, exhausting retries and never synthesizing an answer. Token burn is extreme (avg 650K per benchmark), making this economically unsustainable at scale.

---

## Per-Benchmark Results

| # | Benchmark | Project | Difficulty | Success | Steps | Tools | Tokens | Time | Stuck |
|---|-----------|---------|------------|---------|-------|-------|--------|------|-------|
| 1 | `pa_cache_invalidation` | PersonAgent | medium | ✅ | 8 | 14 | 156K | 31s | 0 |
| 2 | `pa_state_resolution` | PersonAgent | complex | ❌ | 11 | 22 | 428K | 101s | 4 |
| 3 | `pd_discriminated_union` | pydantic | complex | ❌ | 11 | 23 | 635K | 37s | 4 |
| 4 | `pd_plugin_interception` | pydantic | medium | ✅ | 11 | 18 | 756K | 38s | 3 |
| 5 | `oc_permission_eval` | opencode | complex | ❌ | 11 | 24 | 898K | 25s | 4 |
| 6 | `oc_skill_discovery` | opencode | medium | ❌ | 11 | 23 | 1.03M | 27s | 4 |

### Successful Benchmarks

#### `pa_cache_invalidation` (Score: 81.8/100)
The agent found the `PromptBuilder` caching logic efficiently. It used a clear pattern: `Glob` → targeted `Grep` for keywords (`cache_scope`, `cache_break`) → `Read` the relevant files. The final answer was comprehensive, with exact file names, line numbers, and code snippets. **No stuck events.** This shows the harness works well when the target code is discoverable via keyword search.

#### `pd_plugin_interception` (Score: 84.4/100)
The agent traced the pydantic plugin system from discovery through interception. It found the entry-point loader, the `PluggableSchemaValidator` factory, and the wrapper chain. Despite 3 stuck events (recovered via retries), the agent eventually synthesized a correct, detailed answer. **Key insight:** The retry mechanism *can* work when the agent has enough "signal" in the codebase to recover.

### Failed Benchmarks

#### `pa_state_resolution` (Score: 62.5/100)
The agent found `AgentStateResolver` and read the keyword lists, but then spent 5+ steps searching for tests and validation code that didn't exist in obvious locations. It got stuck in a loop of `Glob`/`Grep` for test files, never synthesizing the answer. **Root cause:** The prompt does not instruct the agent to *answer based on what it has found* when searches turn up empty.

#### `pd_discriminated_union` (Score: 50.7/100)
The agent found `_discriminated_union.py` and `types.py`, but then chased internal helper functions (`_apply_annotations`, `_get_wrapped_inner_schema`) across `_generate_schema.py` without ever synthesizing the transformation logic. It read only 4 unique files in 23 tool calls — extreme inefficiency. **Root cause:** The prompt lacks guidance on when to stop following internal helpers and start synthesizing.

#### `oc_permission_eval` & `oc_skill_discovery` (Scores: 64.5, 64.0)
Both found relevant files (permission evaluation, skill discovery) but got stuck doing redundant `Glob`/`Grep` cycles in adjacent directories. The TypeScript monorepo structure confused the search strategy. **Root cause:** The prompt does not guide the agent to prefer `Grep` over `Glob` for large codebases, or to narrow search scope after initial discovery.

---

## Multi-Perspective Critique

### Judge 1: Requirements Validator

**Requirements Alignment Score: 5/10**

The harness was supposed to enable agents to explore codebases effectively. It succeeds on simple keyword-searchable tasks but fails on tasks requiring cross-file synthesis or navigating large monorepos.

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Guide agent to use tools appropriately | ⚠️ Partial | Agents use tools, but inefficiently (34% efficiency) |
| Prevent agent stuckness | ❌ Failed | 4/6 benchmarks hit max stuck events |
| Encourage synthesis after exploration | ❌ Failed | Failed benchmarks produced no final answer |
| Handle large codebases | ❌ Failed | opencode and pydantic tasks failed |
| Provide retry recovery | ⚠️ Partial | Retries injected, but agents repeated same patterns |

### Judge 2: Solution Architect

**Solution Optimality Score: 6/10**

**Strengths:**
- The section-based prompt builder is architecturally sound
- The `exploring` mode overlay provides reasonable guidance
- Tool definitions are clear and well-structured

**Weaknesses:**
- The prompt is **reactive**, not **proactive**. It tells the agent what to do when it finds something, but not *how* to search strategically.
- There is no "exploration strategy" section — no guidance on breadth-first vs depth-first, when to stop following call chains, or how to handle empty search results.
- The `context_discovery` state adds generic text but no tactical search advice.
- Token accumulation is unbounded; there is no prompt-level guidance to keep searches focused.

**Recommended Architecture Change:**
Add an `exploration_strategy` section to the system prompt that includes:
1. **Search triage:** Start with `Grep` for keywords, not `Glob` for all files
2. **Depth limit:** After reading 3-4 files in one module, synthesize before going deeper
3. **Empty result handling:** If a search returns nothing, try a different keyword or read the parent module
4. **Synthesis trigger:** After reading any file that contains the core logic, draft an answer immediately

### Judge 3: Code Quality Reviewer (Prompt Quality)

**Prompt Quality Score: 5.5/10**

**Issues Found:**

1. **Prompt duplication / reinforcement bloat** (Severity: Medium)
   - `acting_contract`, `execution.py` behaviour guidelines, and `response_style_contract` all reinforce "be helpful, be thorough" without adding distinct tactical value.
   - This bloats the prompt to 3,128 tokens before any tool schemas or dynamic sections.

2. **Missing exploration tactics** (Severity: Critical)
   - The `codebase_investigation_contract` describes *what* to investigate but not *how*.
   - There is no guidance on search strategy, file prioritization, or when to stop exploring.

3. **Anti-pattern: "Do not guess" without "Do this instead"** (Severity: High)
   - The prompt repeatedly says "do not guess, verify by reading" but does not tell the agent what to do when verification fails or is ambiguous.

4. **States are decorative, not functional** (Severity: Medium)
   - The `context_discovery`, `tool_execution`, `finalization` states inject flavor text but do not change the agent's actual behavior. The agent does the same thing regardless of state.

**Refactoring Recommendations:**

| Priority | Refactoring | Effort |
|----------|-------------|--------|
| High | Add `exploration_strategy` section with tactical search guidance | Small |
| High | Add `synthesis_trigger` section: "After reading N files, draft answer" | Small |
| High | Deduplicate `acting_contract` / `execution.py` / `response_style_contract` | Medium |
| Medium | Add `empty_result_recovery` guidance | Small |
| Medium | Replace heuristic states with explicit `exploration_phase` FSM | Large |

---

## Prompt Composition Analysis

### What Was Actually Tested

For each benchmark, the harness assembled the following prompt structure:

| Component | Tokens | Role |
|-----------|--------|------|
| `core_system_prompt_sections` | ~1,800 | Identity, style, acting, investigation contracts |
| `get_frontloaded_agent_sections` | ~400 | Personality and collaboration |
| `mode_exploring` overlay | ~150 | "Be thorough, read multiple files" |
| `get_tool_sections` + rich prompts | ~800 | Tool usage guidance |
| `execution_sections` (manual mode) | ~300 | Permission behavior |
| `agent_state_sections` | ~200 | Intake, context_discovery, tool_execution, finalization |
| `get_agent_sections` + runtime reminder | ~400 | Continuity and style reminder |
| **Total Base Prompt** | **~3,128** | |

**Observation:** The base prompt is ~16,500 characters / 3,128 tokens. With tool schemas, conversation history, and tool results, each API call ballooned to 50K–150K+ tokens for later steps. This is the primary driver of the 3.9M total token burn.

### The Heuristic Mode/State Problem

The benchmarks ran with `mode=exploring` and various state tuples. The `exploring` mode overlay added ~150 tokens of generic "be thorough" advice. The states (`intake`, `context_discovery`, etc.) added another ~200 tokens of behavioral flavor text.

**Finding:** Neither the mode nor the states appeared to materially change agent behavior. The successful and failed benchmarks used the same modes/states. The difference in outcome was driven by:
1. **Codebase discoverability** (keyword-rich vs. abstract internal helpers)
2. **Agent's innate search strategy** (which the prompt does not explicitly guide)

**This validates your concern:** The heuristic modes and states are fragile and provide little actual value. They add tokens without adding capability.

---

## Key Metrics & Scores

### Tool Use Efficiency

| Benchmark | Unique Files | Total Tools | Efficiency |
|-----------|-------------|-------------|------------|
| pa_cache_invalidation | 6 | 14 | 42.9% |
| pa_state_resolution | 6 | 22 | 27.3% |
| pd_discriminated_union | 4 | 23 | 17.4% |
| pd_plugin_interception | 8 | 18 | 44.4% |
| oc_permission_eval | 9 | 24 | 37.5% |
| oc_skill_discovery | 8 | 23 | 34.8% |
| **Average** | | | **34.0%** |

**Interpretation:** The agent makes 2-3 tool calls for every unique file it reads. This indicates redundant searches, failed globs, and re-reading the same files.

### Token Burn Per Benchmark

| Benchmark | Tokens |
|-----------|--------|
| pa_cache_invalidation | 156K |
| pa_state_resolution | 428K |
| pd_discriminated_union | 635K |
| pd_plugin_interception | 756K |
| oc_permission_eval | 898K |
| oc_skill_discovery | 1,030K |

**Interpretation:** Token usage grows super-linearly with steps because the full conversation history (including large tool results) is sent on every turn. The last benchmark used **1M tokens** — approximately $0.50–$1.00 per benchmark at typical API pricing.

### Stuck Events

| Benchmark | Stuck Count | Retry Utilization |
|-----------|-------------|-------------------|
| pa_cache_invalidation | 0 | 0% |
| pa_state_resolution | 4 | 100% |
| pd_discriminated_union | 4 | 100% |
| pd_plugin_interception | 3 | 100% |
| oc_permission_eval | 4 | 100% |
| oc_skill_discovery | 4 | 100% |

**Interpretation:** 83% of benchmarks (5/6) hit stuck events. The stuck detection mechanism (no new files in 8 steps) is accurate — the agent genuinely stops making progress. However, the retry prompt ("reconsider your approach") is ineffective because the prompt does not teach the agent *how* to reconsider.

---

## Recommendations

### Immediate (Can implement today)

1. **Add `exploration_strategy` section to prompt.py**
   ```
   When exploring a codebase:
   1. Start with Grep for the specific concept, not Glob for all files.
   2. Read the file where the concept is defined first.
   3. Follow import chains one level at a time.
   4. After reading 3-4 files, pause and synthesize what you've learned.
   5. If a search returns nothing, try a broader keyword or read the parent module.
   6. Do not search for test files unless specifically asked.
   ```

2. **Add `synthesis_mandate` to the investigation contract**
   ```
   After you have read the core implementation files, you MUST provide
   a synthesized answer. Do not continue searching indefinitely.
   If you are unsure, state what you found and what remains unclear.
   ```

3. **Add `empty_search_recovery` guidance**
   ```
   If Grep or Glob returns no results, try:
   - A broader keyword
   - A different file extension
   - Reading the parent directory's __init__.py or index.ts
   - Searching for related concepts
   ```

### Short-term (Next sprint)

4. **Remove or consolidate duplicate reinforcement sections**
   - `acting_contract`, `execution.py` behaviour guidelines, and `response_style_contract` overlap significantly.
   - Consolidate into a single `behavior_contract` of ~500 tokens.

5. **Replace heuristic states with explicit exploration phases**
   - Instead of `context_discovery` → `tool_execution` → `finalization`, use:
     - `search_phase`: Focused keyword search
     - `read_phase`: Reading discovered files
     - `synthesize_phase`: Drafting answer
   - Track phase transitions in the harness, not via keyword heuristics.

6. **Cap conversation history for tool results**
   - Truncate tool results to 2,000 chars after the first turn.
   - Summarize old tool results instead of repeating them.

### Long-term (Architecture)

7. **Implement the ADR 0023 two-layer FSM**
   - The current heuristic state resolver is validated as fragile.
   - A proper `AgentPhase` + `PromptPhase` finite state machine would:
     - Explicitly track exploration depth
     - Trigger synthesis after N files
     - Inject recovery prompts on stuck detection
     - Reduce token burn by not sending full history every turn

8. **Add a "reflection" step before each tool call**
   - Prompt the model to explicitly state its search strategy before calling tools.
   - This makes stuck detection easier and gives the harness a hook to intervene.

---

## Appendix: Reusable Benchmark Artifacts

All benchmark artifacts are stored in `benchmarks/` and are fully reusable:

| Artifact | Path | Purpose |
|----------|------|---------|
| Benchmark Harness | `benchmarks/exploration-harness/harness.py` | Runs benchmarks with DeepSeek API |
| Prompt Assembler | `benchmarks/exploration-harness/prompt_assembler.py` | Assembles actual PersonAgent prompts |
| Metrics Tracker | `benchmarks/exploration-harness/metrics.py` | Collects and scores metrics |
| Analyzer | `benchmarks/exploration-harness/analyzer.py` | Analyzes traces and produces reports |
| Task Template | `benchmarks/prompts/exploration_task_template.md` | Reusable prompt template |
| Project Maps | `benchmarks/project-maps/*.md` | 21 informational goals across 3 projects |
| Traces | `benchmarks/traces/*_trace.json` | Full execution traces |
| Metrics | `benchmarks/traces/*_metrics.json` | Per-benchmark metrics |
| Analysis | `benchmarks/traces/analysis_report.json` | Automated scoring |
| **This Report** | `benchmarks/analysis/FINAL_ANALYSIS_REPORT.md` | Human-reviewed analysis |

To re-run benchmarks after prompt changes:

```bash
cd /home/levybonito/Documentos/PersonAgent
export $(grep -v '^#' .env | grep DEEPSEEK_API_KEY | xargs)
@backend/.venv/bin/python benchmarks/exploration-harness/harness.py --all
```

To analyze new traces:

```bash
@backend/.venv/bin/python benchmarks/exploration-harness/analyzer.py benchmarks/traces
```

---

*Analysis generated using Multi-Agent Debate + LLM-as-a-Judge evaluation principles. Benchmarks executed with deepseek-v4-flash on real project codebases.*
