# PersonAgent Exploration Benchmarks (Hybrid Approach)

Declarative YAML configs + imperative Python runners.

## Philosophy

**Stable config lives in YAML.** Goals, metrics, rubrics, and prompt templates are human-editable, version-controlled, and reusable across languages and tools.

**Dynamic execution lives in Python.** Tool dispatch, LLM streaming, retry logic, and scoring algorithms are code where they belong.

## Behavioral Benchmark Design

Traditional benchmarks ask "What does file X do?" — the agent just greps for `X`.
These benchmarks ask "How does the system handle behavior Y?" — the agent must:

1. **Infer where to look** from the behavior description
2. **Read multiple files** to understand cross-file interactions
3. **Trace data flow** across components
4. **Synthesize** the mechanism from scattered evidence

The `files_needed` and `expected_answer_brief` fields in the YAML are **only for the evaluator**.
The agent never sees them. This prevents benchmark leakage.

## Quick Start

```bash
# 1. Set API key
export DEEPSEEK_API_KEY=$(grep DEEPSEEK_API_KEY .env | cut -d= -f2)

# 2. Run a single benchmark
python benchmarks/scripts/run_benchmark.py \
  --project opencode --goal medium \
  --provider deepseek --model deepseek-v4-flash

# 3. Evaluate the trace
python benchmarks/scripts/evaluate_trace.py \
  --trace benchmarks/traces/opencode_medium_*.jsonl \
  --output benchmarks/results/opencode_medium_eval.json

# 4. Run full suite
python benchmarks/scripts/run_benchmark.py --suite full \
  --provider deepseek --model deepseek-v4-flash

# 5. Aggregate results
python benchmarks/scripts/aggregate.py \
  --input benchmarks/results/*.json \
  --output benchmarks/analysis/full_report.md
```

## Directory Structure

```
benchmarks/
  README.md                          # This file
  prompts/
    benchmark_agent_prompt.md        # System prompt template for benchmark runs
    retry_prompts.md               # Escalating retry prompts (4 levels)
  evals/
    project_goals.yaml             # 3 projects x 3 difficulties = 9 goals
    metrics.yaml                   # 9 metrics with weights and targets
  traces/
    {run_id}.jsonl                 # Per-run execution traces
  results/
    {run_id}_result.json           # Per-run aggregated results
    {run_id}_eval.json             # Scored metrics per run
  analysis/
    critiques/                     # Per-run critique analyses
    aggregations/                  # Cross-run comparative reports
  scripts/
    run_benchmark.py               # Main benchmark runner
    evaluate_trace.py              # Trace scoring and metric extraction
    aggregate.py                   # Multi-run aggregation and reporting
```

## Projects & Goals — Behavioral Design

All questions describe **cross-file behaviors in natural language**.
No directory names. No file names. No greppable keywords.

The agent must **explore** to discover WHERE the behavior is implemented.

| Project | Complexity | Easy Question Theme | Medium Question Theme | Hard Question Theme |
|---------|------------|---------------------|-----------------------|---------------------|
| opencode | 9/10 | CLI startup mode decision | Subagent delegation + permissions | Concurrent worker isolation |
| pydantic | 8/10 | Validation order (type vs custom) | Nested schema name collision | Error path construction (Python→Rust) |
| personagent | 10/10 | Tool selection for prompt context | Evidence gate acceptance criteria | Partial tool failure handling |

## Metrics

| Metric | Weight | Target | Description |
|--------|--------|--------|-------------|
| exploration_score | 25% | >= 70% | % of required surfaces covered |
| tool_efficiency | 15% | >= 60% | Useful tool calls / total calls |
| synthesis_quality | 20% | >= 75% | Evidence, file refs, reasoning |
| success_rate | 25% | >= 80% | Answer correctness |
| token_efficiency | 5% | < 800 | Tokens per step |
| time_to_first_evidence | 5% | < 30s | Wall-clock to first relevant read |
| stuck_count | 5% | 0 | Stuck/retry events |
| hallucination_detected | -10 | false | Fabricated paths penalty |

**Grade thresholds:** A >= 90, B >= 75, C >= 60, D >= 40, F < 40

## Retry Strategy

Max 2 retries per run. Retry prompts escalate:

1. **Insufficient exploration** — "Read more files, check tests/config"
2. **Hallucination suspected** — "Verify every file path you cited"
3. **Wrong conclusion** — "Re-read the functions, trace data flow carefully"
4. **Stuck / no progress** — "Try different search patterns, look at directory structure"

## Trace Format

Each run produces a JSONL file:

```jsonl
{"type":"meta","run_id":"opencode_medium_12345",...}
{"type":"step","step_number":1,"role":"assistant","content":"...","tool_calls":[...]}
{"type":"step","step_number":2,"role":"tool","tool_results":[...]}
```

This enables:
- Re-play and debugging of agent decisions
- Human review of every tool call
- A/B testing of prompt changes on the same trace
- Statistical analysis of exploration patterns

## Extending the Framework

### Add a new project:

1. Clone the repo to a local path
2. Add an entry to `evals/project_goals.yaml` with 3 goals
3. Run benchmarks — the framework auto-discovers the new project

### Add a new metric:

1. Add definition to `evals/metrics.yaml`
2. Add scoring function to `scripts/evaluate_trace.py`
3. Update `compute_final_score()` weights

### Add a new prompt template variant:

1. Create `prompts/benchmark_agent_prompt_v2.md`
2. Pass `--prompt-template v2` to `run_benchmark.py`

## Comparison with Pure `.py` Approach

| Concern | Hybrid (YAML+PY) | Pure `.py` |
|---------|-----------------|------------|
| Config editing | Anyone can edit YAML | Requires Python knowledge |
| Version control | `git diff` is readable | Code changes mixed with config |
| Cross-language | YAML is universal | Python-only |
| IDE support | YAML needs schema validation | Full autocomplete + type checking |
| Extensibility | Add goals without touching code | Must edit Python for new goals |
| Complexity | More files, separation of concerns | Fewer files, tightly coupled |

## Future Work

- [ ] Integrate actual tool execution (Read/Grep/Glob/shell) into runner
- [ ] Add LLM-as-judge for synthesis quality scoring
- [ ] Add prompt-section-level correlation analysis
- [ ] Add regression detection across harness versions
- [ ] Export to CI for automated harness validation
