# System Prompt Quality Benchmarks

These benchmarks exercise the real PersonAgent chat path against the official DeepSeek API using `deepseek-v4-flash`. They are intended for prompt-quality regression checks, not for unit-test speed.

Run from the backend so the package environment matches normal runtime:

```bash
cd /home/levybonito/Projetos/PersonAgent/@backend
DEEPSEEK_LIVE_TESTS=1 uv run python ../benchmarks/sysprompts/run_deepseek_v4_flash.py --workspace-root /home/levybonito/Projetos/PersonAgent
```

Required environment:

```bash
export DEEPSEEK_API_KEY=...
export DEEPSEEK_LIVE_TESTS=1
```

The runner uses `ChatCompletionUseCase`, `DeepSeekAdapter`, `PromptBuilder`, real workspace context, and the read-only tools `Read`, `Grep`, and `Glob` for project-reading cases. It does not use `ChatRequest.system_prompt` to inject the default personality.

Tool results are capped in the runner with `--tool-result-max-chars` (default `12000`) so the benchmark evaluates response quality and tool behavior instead of oversized provider payloads.

To validate another real project with the generic project-reading case:

```bash
DEEPSEEK_LIVE_TESTS=1 uv run python ../benchmarks/sysprompts/run_deepseek_v4_flash.py \
  --workspace-root /home/levybonito/Projetos/MindFlow \
  --case medium_real_project_concise_map
```

Outputs are separated by artifact type and ignored by git:

- `system_prompts/<run_id>/<case_id>.md`
- `results/<run_id>/summary.json`
- `results/<run_id>/<case_id>.json`
- `logs/<run_id>.log`
- `tracing/<run_id>/<case_id>.jsonl`

The cases cover low, medium, and high complexity prompts. The objective metrics track visible format, answer length, table lines, non-dash bullets, decorative markers, first-token latency when streaming produces text, total runtime, called tools, reasoning chars, content chars, and rubric scores. Absolute bullet limits are the hard gate; bullet ratio remains diagnostic so concise answers with a small allowed list do not fail just because the answer has fewer lines.
