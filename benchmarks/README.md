# PersonAgent Exploration Benchmarks

Reusable benchmark suite for evaluating agent exploration depth, tool usage efficiency,
and information synthesis quality across real-world codebases.

## Directory Structure

```
benchmarks/
  prompts/
    benchmark_agent_prompt.md      # Prompt template for benchmark runs
    retry_prompts.md               # Stuck/incorrect answer recovery prompts
  evals/
    project_goals.yaml             # Informational goals per project (easy/medium/hard)
    metrics.yaml                   # Metric definitions and scoring rubrics
    difficulty_matrix.yaml         # Project complexity scores and rationale
  traces/
    {run_id}/                      # Per-run execution traces (JSONL)
  results/
    {run_id}_results.json          # Aggregated metrics per run
    {run_id}_report.md             # Human-readable report
  analysis/
    critiques/                     # Per-run critique analyses
    aggregations/                # Cross-run comparative analyses
  scripts/
    run_benchmark.py             # Main benchmark runner
    evaluate_trace.py            # Trace scoring and metric extraction
    aggregate.py               # Multi-run aggregation
```

## Quick Start

```bash
# 1. Ensure DEEPSEEK_API_KEY is set
export DEEPSEEK_API_KEY=$(grep DEEPSEEK_API_KEY /home/levybonito/Documentos/PersonAgent/.env | cut -d= -f2)

# 2. Run a single benchmark
python benchmarks/scripts/run_benchmark.py \
  --project OrchestraOS \
  --goal medium \
  --provider deepseek \
  --model deepseek-v4-flash \
  --max-retries 2

# 3. Evaluate the trace
python benchmarks/scripts/evaluate_trace.py \
  --trace benchmarks/traces/orchestraos_medium_*.jsonl \
  --output benchmarks/results/orchestraos_medium_results.json

# 4. Run full suite
python benchmarks/scripts/run_benchmark.py --suite full --provider deepseek --model deepseek-v4-flash
```

## Metrics

| Metric | Unit | Target | Description |
|--------|------|--------|-------------|
| exploration_score | % | > 70 | Did the agent read sufficient files to answer? |
| tool_efficiency | % | > 60 | Correct tools chosen vs. total tool calls |
| synthesis_quality | % | > 75 | Did the final answer reference specific files/evidence? |
| success_rate | % | > 80 | Did the agent reach a correct answer without hints? |
| token_efficiency | tokens/step | < 800 | Avg tokens consumed per tool loop step |
| time_to_first_evidence | s | < 30 | Time until first relevant file read |
| stuck_count | count | 0 | Times the agent got stuck and needed retry |
| retry_success_rate | % | > 50 | Success rate after retry injection |
| hallucination_detected | bool | false | Did the agent fabricate files/paths? |

## Projects Evaluated

| Project | Language | Complexity | GH Visibility |
|---------|----------|------------|---------------|
| OrchestraOS | Go | 7/10 | Public |
| gitbook | TS/Next.js monorepo | 9/10 | Public |
| reor | TS/Electron | 8/10 | Public |
| Nemity | Astro | 3/10 | Private |
| SiteThalita | Astro | 5/10 | Public |
| accounts | Go (tiny) | 2/10 | Private |
