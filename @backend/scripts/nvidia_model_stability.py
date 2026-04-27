"""Benchmark NVIDIA NIM models for reasoning and long code-analysis stability."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from personagent.infrastructure.config.settings import Settings
from personagent.infrastructure.llm.nvidia_nim_adapter import NvidiaNimAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "@backend" / ".benchmarks" / "nvidia"
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"

CANDIDATE_TERMS = (
    "thinking",
    "reason",
    "deepseek",
    "qwen3",
    "nemotron",
    "kimi",
    "minimax",
    "large",
    "405b",
    "gpt-oss",
    "glm5",
    "glm-5",
)

CODE_ANALYSIS_FILES = (
    PROJECT_ROOT / "@backend/src/personagent/infrastructure/llm/nvidia_nim_adapter.py",
    PROJECT_ROOT / "@backend/src/personagent/application/use_cases/chat_completion.py",
    PROJECT_ROOT / "@desktop-electron/src/stores/chat-store.ts",
)


@dataclass
class ModelRun:
    model: str
    stage: str
    status: str
    stable: bool
    reason: str
    started_at: str
    duration_s: float
    first_signal_s: float | None
    first_content_s: float | None
    chunk_count: int
    content_chars: int
    reasoning_chars: int
    approx_output_tokens: int
    approx_content_tokens: int
    total_tokens_per_s: float
    content_tokens_per_s: float
    max_gap_s: float | None
    p95_gap_s: float | None
    reasoning_present: bool
    content_present: bool
    finish_reason: str | None
    usage: dict[str, Any] | None
    error_type: str | None = None
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe NVIDIA NIM models and benchmark long code-analysis streaming."
    )
    parser.add_argument(
        "--stage",
        choices=("catalog", "probe", "long", "full"),
        default="full",
        help="catalog only, short reasoning probe, long benchmark, or probe+long.",
    )
    parser.add_argument(
        "--model-scope",
        choices=("reasoning", "candidates", "all"),
        default="reasoning",
        help="Which catalog subset to test.",
    )
    parser.add_argument(
        "--models",
        help="Comma-separated model ids. Overrides --model-scope.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max models to test.")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=240.0, help="Per-model wall timeout.")
    parser.add_argument("--stream-read-timeout", type=float, default=45.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--probe-max-tokens", type=int, default=768)
    parser.add_argument("--reasoning-budget", type=int, default=2048)
    parser.add_argument(
        "--force-thinking-template",
        action="store_true",
        help="Send chat_template_kwargs.enable_thinking=true to every tested model.",
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--min-tps", type=float, default=30.0)
    parser.add_argument("--min-output-tokens", type=int, default=600)
    parser.add_argument("--max-first-signal-s", type=float, default=20.0)
    parser.add_argument("--max-p95-gap-s", type=float, default=6.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def elapsed_since(start: float, current: float | None) -> float | None:
    if current is None:
        return None
    return round(current - start, 3)


def metric_rate(tokens: int, duration_s: float | None) -> float:
    if not duration_s or duration_s <= 0:
        return 0.0
    return round(tokens / duration_s, 2)


def classify_run(
    *,
    status: str,
    first_signal_s: float | None,
    p95_gap_s: float | None,
    approx_output_tokens: int,
    total_tokens_per_s: float,
    content_present: bool,
    min_tps: float,
    min_output_tokens: int,
    max_first_signal_s: float,
    max_p95_gap_s: float,
) -> tuple[bool, str]:
    if status != "ok":
        return False, status
    if not content_present:
        return False, "no final content"
    if first_signal_s is None or first_signal_s > max_first_signal_s:
        return False, f"first signal > {max_first_signal_s:.0f}s"
    if p95_gap_s is not None and p95_gap_s > max_p95_gap_s:
        return False, f"p95 stream gap > {max_p95_gap_s:.0f}s"
    if approx_output_tokens < min_output_tokens:
        return False, f"output < {min_output_tokens} approx tokens"
    if total_tokens_per_s < min_tps:
        return False, f"throughput < {min_tps:.0f} tok/s"
    return True, "meets latency and volume thresholds"


async def load_catalog(adapter: NvidiaNimAdapter) -> dict[str, Any]:
    catalog = await adapter.list_models(refresh=True)
    all_models = list(catalog.get("data") or [])
    reasoning = await adapter.list_models(capability="reasoning_chat", refresh=False)
    reasoning_ids = {model["id"] for model in reasoning.get("data", [])}
    candidates = []
    for model in all_models:
        model_id = model["id"]
        lower = model_id.lower()
        if model_id in reasoning_ids or any(term in lower for term in CANDIDATE_TERMS):
            candidates.append(model)
    return {
        "provider": catalog.get("provider"),
        "total_models": len(all_models),
        "all_models": all_models,
        "reasoning_models": [model for model in all_models if model["id"] in reasoning_ids],
        "candidate_models": candidates,
    }


def select_models(catalog: dict[str, Any], args: argparse.Namespace) -> list[str]:
    if args.models:
        selected = [item.strip() for item in args.models.split(",") if item.strip()]
    elif args.model_scope == "all":
        selected = [model["id"] for model in catalog["all_models"]]
    elif args.model_scope == "candidates":
        selected = [model["id"] for model in catalog["candidate_models"]]
    else:
        selected = [model["id"] for model in catalog["reasoning_models"]]

    if args.limit and args.limit > 0:
        return selected[: args.limit]
    return selected


def build_probe_messages() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Voce e um engenheiro senior. Responda em portugues. "
                "Se o modelo suportar reasoning separado, use esse canal; "
                "na resposta final, seja direto."
            ),
        },
        {
            "role": "user",
            "content": (
                "Teste de thinking: analise o risco de um stream SSE que mistura "
                "reasoning_content, content e tool_calls. Depois entregue uma resposta "
                "final com exatamente 3 bullets: risco, evidencia, mitigacao."
            ),
        },
    ]


def build_long_messages() -> list[dict[str, str]]:
    excerpts = "\n\n".join(load_code_excerpt(path) for path in CODE_ANALYSIS_FILES)
    return [
        {
            "role": "system",
            "content": (
                "Voce e um engenheiro senior fazendo revisao tecnica de runtime de LLM. "
                "Use reasoning separado se o provedor disponibilizar, mas mantenha a "
                "resposta final em Markdown tecnico, objetiva e acionavel."
            ),
        },
        {
            "role": "user",
            "content": (
                "Analise os arquivos abaixo como se voce fosse decidir se este chat aguenta "
                "sessoes longas com modelos hosted. Esta e uma tarefa longa de analise de codigo.\n\n"
                "Entregue no minimo 8 achados tecnicos, cobrindo streaming, parsing de reasoning, "
                "tratamento de timeouts, persistencia da conversa, UI store e riscos de regressao. "
                "Para cada achado, inclua severidade, evidencias do codigo e uma correcao concreta. "
                "Finalize com uma matriz de recomendacao para modelos lentos/instaveis. "
                "A resposta final deve ter volume suficiente para avaliarmos throughput real.\n\n"
                f"{excerpts}"
            ),
        },
    ]


def load_code_excerpt(path: Path, max_chars: int = 9000) -> str:
    if not path.exists():
        return f"## {path.relative_to(PROJECT_ROOT)}\nArquivo nao encontrado."
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    numbered = [f"{idx:04d}: {line}" for idx, line in enumerate(lines, start=1)]
    text = "\n".join(numbered)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [excerpt truncated for benchmark prompt]"
    return f"## {path.relative_to(PROJECT_ROOT)}\n```text\n{text}\n```"


async def run_model(
    *,
    adapter: NvidiaNimAdapter,
    model: str,
    stage: str,
    messages: list[dict[str, str]],
    args: argparse.Namespace,
) -> ModelRun:
    start_wall = datetime.now(UTC).isoformat()
    start = time.perf_counter()
    first_signal_at: float | None = None
    first_content_at: float | None = None
    signal_times: list[float] = []
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    chunk_count = 0

    try:
        stream = adapter.chat_completion_stream(
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.probe_max_tokens if stage == "probe" else args.max_tokens,
            model=model,
            reasoning_budget_tokens=args.reasoning_budget,
            chat_template_kwargs=(
                {"enable_thinking": True} if args.force_thinking_template else None
            ),
        )
        async for chunk in stream:
            now = time.perf_counter()
            has_signal = bool(
                chunk.content
                or chunk.reasoning_content
                or chunk.finish_reason
                or chunk.usage
                or chunk.tool_calls
            )
            if has_signal:
                chunk_count += 1
                signal_times.append(now)
                if first_signal_at is None and (chunk.content or chunk.reasoning_content):
                    first_signal_at = now
            if chunk.content:
                content_parts.append(chunk.content)
                if first_content_at is None:
                    first_content_at = now
            if chunk.reasoning_content:
                reasoning_parts.append(chunk.reasoning_content)
            if chunk.usage:
                usage = chunk.usage
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic harness.
        return build_error_run(
            model=model,
            stage=stage,
            started_at=start_wall,
            start=start,
            error_type=type(exc).__name__,
            error=str(exc),
        )

    duration = time.perf_counter() - start
    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)
    combined = content + reasoning
    approx_total_tokens = int((usage or {}).get("completion_tokens") or estimate_tokens(combined))
    approx_content_tokens = estimate_tokens(content)
    active_duration = max(
        0.001,
        (signal_times[-1] - first_signal_at) if signal_times and first_signal_at else duration,
    )
    gaps = [b - a for a, b in zip(signal_times, signal_times[1:], strict=False)]
    p95_gap = percentile(gaps, 95)
    first_signal_s = elapsed_since(start, first_signal_at)
    first_content_s = elapsed_since(start, first_content_at)
    total_tps = metric_rate(approx_total_tokens, active_duration)
    content_tps = metric_rate(approx_content_tokens, active_duration)
    stable, reason = classify_run(
        status="ok",
        first_signal_s=first_signal_s,
        p95_gap_s=p95_gap,
        approx_output_tokens=approx_total_tokens,
        total_tokens_per_s=total_tps,
        content_present=bool(content.strip()),
        min_tps=args.min_tps,
        min_output_tokens=80 if stage == "probe" else args.min_output_tokens,
        max_first_signal_s=args.max_first_signal_s,
        max_p95_gap_s=args.max_p95_gap_s,
    )

    return ModelRun(
        model=model,
        stage=stage,
        status="ok",
        stable=stable,
        reason=reason,
        started_at=start_wall,
        duration_s=round(duration, 3),
        first_signal_s=first_signal_s,
        first_content_s=first_content_s,
        chunk_count=chunk_count,
        content_chars=len(content),
        reasoning_chars=len(reasoning),
        approx_output_tokens=approx_total_tokens,
        approx_content_tokens=approx_content_tokens,
        total_tokens_per_s=total_tps,
        content_tokens_per_s=content_tps,
        max_gap_s=round(max(gaps), 3) if gaps else None,
        p95_gap_s=round(p95_gap, 3) if p95_gap is not None else None,
        reasoning_present=bool(reasoning.strip()),
        content_present=bool(content.strip()),
        finish_reason=finish_reason,
        usage=usage,
    )


def build_error_run(
    *,
    model: str,
    stage: str,
    started_at: str,
    start: float,
    error_type: str,
    error: str,
) -> ModelRun:
    duration = time.perf_counter() - start
    return ModelRun(
        model=model,
        stage=stage,
        status="error",
        stable=False,
        reason=error_type,
        started_at=started_at,
        duration_s=round(duration, 3),
        first_signal_s=None,
        first_content_s=None,
        chunk_count=0,
        content_chars=0,
        reasoning_chars=0,
        approx_output_tokens=0,
        approx_content_tokens=0,
        total_tokens_per_s=0.0,
        content_tokens_per_s=0.0,
        max_gap_s=None,
        p95_gap_s=None,
        reasoning_present=False,
        content_present=False,
        finish_reason=None,
        usage=None,
        error_type=error_type,
        error=error[:1000],
    )


async def run_with_timeout(
    *,
    adapter: NvidiaNimAdapter,
    model: str,
    stage: str,
    messages: list[dict[str, str]],
    args: argparse.Namespace,
) -> ModelRun:
    try:
        return await asyncio.wait_for(
            run_model(adapter=adapter, model=model, stage=stage, messages=messages, args=args),
            timeout=args.timeout,
        )
    except TimeoutError:
        return build_error_run(
            model=model,
            stage=stage,
            started_at=datetime.now(UTC).isoformat(),
            start=time.perf_counter() - args.timeout,
            error_type="TimeoutError",
            error=f"per-model wall timeout exceeded ({args.timeout}s)",
        )


async def run_stage(
    *,
    adapter: NvidiaNimAdapter,
    models: list[str],
    stage: str,
    args: argparse.Namespace,
) -> list[ModelRun]:
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    messages = build_probe_messages() if stage == "probe" else build_long_messages()
    results: list[ModelRun] = []

    async def worker(model: str) -> None:
        async with semaphore:
            print(f"[{stage}] start {model}", flush=True)
            result = await run_with_timeout(
                adapter=adapter,
                model=model,
                stage=stage,
                messages=messages,
                args=args,
            )
            results.append(result)
            status = "stable" if result.stable else result.reason
            print(
                f"[{stage}] done {model} status={result.status} verdict={status} "
                f"tps={result.total_tokens_per_s} first={result.first_signal_s} "
                f"tokens={result.approx_output_tokens}",
                flush=True,
            )

    await asyncio.gather(*(worker(model) for model in models))
    return sorted(results, key=lambda item: item.model)


def summarize(results: list[ModelRun]) -> dict[str, Any]:
    ok = [item for item in results if item.status == "ok"]
    stable = [item for item in ok if item.stable]
    failed = [item for item in results if not item.stable]
    tps_values = [item.total_tokens_per_s for item in ok if item.total_tokens_per_s > 0]
    first_values = [item.first_signal_s for item in ok if item.first_signal_s is not None]
    return {
        "total": len(results),
        "ok": len(ok),
        "stable": len(stable),
        "failed_or_unstable": len(failed),
        "median_tps": round(statistics.median(tps_values), 2) if tps_values else 0,
        "median_first_signal_s": round(statistics.median(first_values), 3) if first_values else None,
        "stable_models": [item.model for item in stable],
    }


def write_outputs(
    *,
    output_dir: Path,
    catalog: dict[str, Any],
    results: list[ModelRun],
    args: argparse.Namespace,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"nvidia-model-stability-{stamp}.json"
    md_path = output_dir / f"nvidia-model-stability-{stamp}.md"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            "stage": args.stage,
            "model_scope": args.model_scope,
            "concurrency": args.concurrency,
            "timeout": args.timeout,
            "stream_read_timeout": args.stream_read_timeout,
            "max_tokens": args.max_tokens,
            "probe_max_tokens": args.probe_max_tokens,
            "reasoning_budget": args.reasoning_budget,
            "force_thinking_template": args.force_thinking_template,
            "min_tps": args.min_tps,
            "min_output_tokens": args.min_output_tokens,
            "max_first_signal_s": args.max_first_signal_s,
            "max_p95_gap_s": args.max_p95_gap_s,
        },
        "catalog": {
            "provider": catalog["provider"],
            "total_models": catalog["total_models"],
            "reasoning_model_count": len(catalog["reasoning_models"]),
            "candidate_model_count": len(catalog["candidate_models"]),
            "reasoning_model_ids": [model["id"] for model in catalog["reasoning_models"]],
            "candidate_model_ids": [model["id"] for model in catalog["candidate_models"]],
        },
        "summary": summarize(results),
        "results": [asdict(item) for item in results],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return json_path, md_path


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# NVIDIA Model Stability Benchmark",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Catalog",
        "",
        f"- Total real API models: `{payload['catalog']['total_models']}`",
        f"- Reasoning-chat models mapped by backend: `{payload['catalog']['reasoning_model_count']}`",
        f"- Heuristic thinking candidates: `{payload['catalog']['candidate_model_count']}`",
        "",
        "## Criteria",
        "",
        f"- Minimum throughput: `{payload['config']['min_tps']}` approx output tokens/sec",
        f"- Minimum long-output volume: `{payload['config']['min_output_tokens']}` approx tokens",
        f"- Max first signal: `{payload['config']['max_first_signal_s']}` sec",
        f"- Max p95 streaming gap: `{payload['config']['max_p95_gap_s']}` sec",
        "",
        "## Summary",
        "",
        f"- Tested: `{payload['summary']['total']}`",
        f"- OK responses: `{payload['summary']['ok']}`",
        f"- Stable: `{payload['summary']['stable']}`",
        f"- Failed/unstable: `{payload['summary']['failed_or_unstable']}`",
        f"- Median throughput: `{payload['summary']['median_tps']}` approx tok/s",
        f"- Median first signal: `{payload['summary']['median_first_signal_s']}` sec",
        "",
        "## Stable Models",
        "",
    ]
    stable_models = payload["summary"]["stable_models"]
    if stable_models:
        lines.extend(f"- `{model}`" for model in stable_models)
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Results",
            "",
            "| Model | Stage | Verdict | Reasoning | First signal | p95 gap | Tokens | Tok/s | Duration | Error |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for result in sorted(payload["results"], key=lambda item: (item["stage"], item["model"])):
        verdict = "stable" if result["stable"] else result["reason"]
        error = (result.get("error") or "").replace("\n", " ")[:120]
        lines.append(
            "| "
            f"`{result['model']}` | "
            f"{result['stage']} | "
            f"{verdict} | "
            f"{'yes' if result['reasoning_present'] else 'no'} | "
            f"{result['first_signal_s']} | "
            f"{result['p95_gap_s']} | "
            f"{result['approx_output_tokens']} | "
            f"{result['total_tokens_per_s']} | "
            f"{result['duration_s']} | "
            f"{error} |"
        )

    lines.extend(
        [
            "",
            "## Reasoning-Chat Model IDs",
            "",
            *[f"- `{model}`" for model in payload["catalog"]["reasoning_model_ids"]],
            "",
            "## Candidate Model IDs",
            "",
            *[f"- `{model}`" for model in payload["catalog"]["candidate_model_ids"]],
            "",
        ]
    )
    return "\n".join(lines)


async def main() -> None:
    args = parse_args()
    settings = Settings.from_yaml(args.config)
    adapter = NvidiaNimAdapter(
        api_key=settings.nvidia_api_key,
        base_url=settings.nvidia_base_url,
        default_model=settings.nvidia_default_model,
        timeout=max(args.timeout, args.stream_read_timeout, 1.0),
        stream_read_timeout=args.stream_read_timeout,
        default_max_tokens=args.max_tokens,
        models_cache_ttl_seconds=0,
    )
    try:
        catalog = await load_catalog(adapter)
        selected = select_models(catalog, args)
        print(
            json.dumps(
                {
                    "provider": catalog["provider"],
                    "total_models": catalog["total_models"],
                    "reasoning_model_count": len(catalog["reasoning_models"]),
                    "candidate_model_count": len(catalog["candidate_models"]),
                    "selected_count": len(selected),
                    "selected_models": selected,
                },
                indent=2,
                ensure_ascii=False,
            ),
            flush=True,
        )

        if args.stage == "catalog":
            json_path, md_path = write_outputs(
                output_dir=args.output_dir,
                catalog=catalog,
                results=[],
                args=args,
            )
            print(f"wrote {json_path}")
            print(f"wrote {md_path}")
            return

        results: list[ModelRun] = []
        if args.stage in {"probe", "full"}:
            results.extend(
                await run_stage(adapter=adapter, models=selected, stage="probe", args=args)
            )
        if args.stage in {"long", "full"}:
            long_models = selected
            if args.stage == "full":
                long_models = [item.model for item in results if item.status == "ok"]
            results.extend(
                await run_stage(adapter=adapter, models=long_models, stage="long", args=args)
            )

        json_path, md_path = write_outputs(
            output_dir=args.output_dir,
            catalog=catalog,
            results=results,
            args=args,
        )
        print(json.dumps({"summary": summarize(results)}, indent=2, ensure_ascii=False))
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
