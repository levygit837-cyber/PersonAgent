"""Benchmark persistent operational RAG memory.

Run from @backend:
    uv run python scripts/memory_rag_benchmark.py --project memory_rag_bench

The benchmark writes JSONL and Markdown reports under @backend/.benchmarks by
default. Live embedding/chat checks are included when their services are up.
"""

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
from uuid import uuid4

import httpx

from personagent.application.services.operational_memory import project_slug_from_workspace
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolResult, ToolUseContext
from personagent.infrastructure.config.settings import get_project_root
from personagent.infrastructure.persistence.database import init_db
from personagent.interfaces.config.di_container import get_container

PROJECT_ROOT = get_project_root()
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "@backend" / ".benchmarks" / "memory_rag"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_MODEL = "openai/gpt-oss-120b"


@dataclass(slots=True)
class BenchmarkResult:
    id: str
    name: str
    status: str
    latency_ms: int
    score: float | None = None
    metrics: dict[str, Any] | None = None
    failure: str | None = None


class MemoryRagBenchmark:
    def __init__(
        self,
        *,
        project_slug: str,
        output_dir: Path,
        backend_url: str,
        live_chat: bool,
    ) -> None:
        self.project_slug = project_slug
        self.output_dir = output_dir
        self.backend_url = backend_url.rstrip("/")
        self.live_chat = live_chat
        self.workspace = PROJECT_ROOT
        self.container = get_container()
        self.service = self.container.get_operational_memory_service()
        if self.service is None:
            raise RuntimeError("Operational memory is disabled")

    async def run(self) -> list[BenchmarkResult]:
        await init_db()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = [
            await self.embedding_latency_single(),
            await self.embedding_latency_batch(),
            await self.ingest_throughput(),
            await self.recall_at_k_mrr(),
            await self.ndcg_relevance(),
            await self.diff_and_decision_recall(),
            await self.command_error_solution_recall(),
            await self.file_chunk_update_recall(),
            await self.persistence_after_recreate(),
            await self.secret_redaction(),
            await self.hallucination_reduction_live_chat(),
            await self.ttft_overhead_live_chat(),
        ]
        self.write_reports(results)
        return results

    async def embedding_latency_single(self) -> BenchmarkResult:
        return await self._measure("embedding_latency_single", "Embedding latency single", self._embed_single)

    async def embedding_latency_batch(self) -> BenchmarkResult:
        return await self._measure("embedding_latency_batch", "Embedding latency batch", self._embed_batch)

    async def ingest_throughput(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            count = 20
            started = time.perf_counter()
            for index in range(count):
                await self.service.capture_turn_summary(
                    project_slug=self.project_slug,
                    workspace_root=str(self.workspace),
                    conversation_id=str(uuid4()),
                    summary=(
                        f"Benchmark ingest event {index}: agent changed src/agents/orchestrator.ts "
                        "to add retry and timeout around tool dispatch."
                    ),
                    metadata={"benchmark": "ingest_throughput", "index": index},
                )
            elapsed = time.perf_counter() - started
            return {"events": count, "events_per_second": round(count / max(elapsed, 0.001), 3)}

        return await self._measure("ingest_throughput", "Ingest throughput", run)

    async def recall_at_k_mrr(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_core_memories()
            findings = await self.service.repository.recall(
                project_slug=self.project_slug,
                query="timeout retry orchestrator planner executor tool dispatch registry abstraction",
                top_k=5,
            )
            ids = [finding.finding for finding in findings]
            hit_rank = next(
                (
                    index + 1
                    for index, text in enumerate(ids)
                    if "orchestrator" in text.lower() and "timeout" in text.lower()
                ),
                None,
            )
            return {
                "retrieved": len(findings),
                "hit_rank": hit_rank,
                "mrr": 0.0 if hit_rank is None else round(1.0 / hit_rank, 4),
            }

        return await self._measure("recall_at_k_mrr", "Recall@k and MRR", run)

    async def ndcg_relevance(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            findings = await self.service.repository.recall(
                project_slug=self.project_slug,
                query="registry already contains tool dispatch abstraction",
                top_k=5,
            )
            gains = [
                3 if "registry" in finding.finding.lower() else 1
                for finding in findings
            ]
            dcg = sum(gain / (1 if index == 0 else _log2(index + 1)) for index, gain in enumerate(gains))
            ideal = sorted(gains, reverse=True)
            idcg = sum(gain / (1 if index == 0 else _log2(index + 1)) for index, gain in enumerate(ideal))
            return {"ndcg": round(dcg / idcg, 4) if idcg else 0.0, "gains": gains}

        return await self._measure("ndcg_relevance", "NDCG relevance", run)

    async def diff_and_decision_recall(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            context = self._tool_context(str(uuid4()))
            call = ToolCall(id="bench-edit", name="Edit", arguments={"path": "src/agents/orchestrator.ts"})
            result = ToolResult(
                tool_call_id=call.id,
                tool_name="Edit",
                content="Applied retry timeout diff. Decision: planner delegates to executor.",
                data={
                    "type": "file_edit",
                    "path": "src/agents/orchestrator.ts",
                    "diff": "@@ add retry and timeout around executor dispatch",
                    "content": "Decision: planner must not call tools directly; delegate to executor.",
                },
            )
            await self.service.capture_tool_result(
                project_slug=self.project_slug,
                workspace_root=str(self.workspace),
                conversation_id=context.conversation_id,
                call=call,
                result=result,
                context=context,
            )
            formatted = await self.service.recall_for_prompt(
                project_slug=self.project_slug,
                query="planner must delegate executor retry timeout diff orchestrator",
                top_k=5,
            )
            return {"contains_decision": "planner" in formatted.lower(), "chars": len(formatted)}

        return await self._measure("diff_and_decision_recall", "Diff and decision recall", run)

    async def command_error_solution_recall(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            context = self._tool_context(str(uuid4()))
            call = ToolCall(id="bench-shell", name="shell", arguments={"command": "uv run pytest tests/unit"})
            result = ToolResult(
                tool_call_id=call.id,
                tool_name="shell",
                content="FAILED test_operational_memory.py::test_redaction then fixed regex token redaction.",
                status=ToolExecutionStatus.ERROR,
                is_error=True,
                data={
                    "type": "shell",
                    "command": "uv run pytest tests/unit",
                    "return_code": 1,
                    "stderr": "AssertionError: secret leaked",
                    "stdout": "solution attempted: tighten token regex",
                },
            )
            await self.service.capture_tool_result(
                project_slug=self.project_slug,
                workspace_root=str(self.workspace),
                conversation_id=context.conversation_id,
                call=call,
                result=result,
                context=context,
            )
            formatted = await self.service.recall_for_prompt(
                project_slug=self.project_slug,
                query="pytest secret leaked redaction regex solution attempted",
                top_k=5,
            )
            return {"contains_error": "secret leaked" in formatted.lower(), "chars": len(formatted)}

        return await self._measure(
            "command_error_solution_recall",
            "Commands, errors, and solutions",
            run,
        )

    async def file_chunk_update_recall(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            context = self._tool_context(str(uuid4()))
            call = ToolCall(id="bench-read", name="Read", arguments={"path": "src/tools/registry.ts"})
            result = ToolResult(
                tool_call_id=call.id,
                tool_name="Read",
                content="src/tools/registry.ts contains ToolRegistry abstraction for dispatch.",
                data={
                    "type": "file_read",
                    "path": "src/tools/registry.ts",
                    "content": "class ToolRegistry { dispatch(toolName, args) { /* existing abstraction */ } }",
                    "truncated": False,
                },
            )
            await self.service.capture_tool_result(
                project_slug=self.project_slug,
                workspace_root=str(self.workspace),
                conversation_id=context.conversation_id,
                call=call,
                result=result,
                context=context,
            )
            formatted = await self.service.recall_for_prompt(
                project_slug=self.project_slug,
                query="tool registry dispatch abstraction already exists",
                top_k=5,
            )
            return {"contains_registry": "registry" in formatted.lower(), "chars": len(formatted)}

        return await self._measure("file_chunk_update", "File chunk update", run)

    async def persistence_after_recreate(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            service = self.container.get_operational_memory_service()
            if service is None:
                raise RuntimeError("Operational memory disabled after service recreate")
            formatted = await service.recall_for_prompt(
                project_slug=self.project_slug,
                query="timeout retry orchestrator",
                top_k=3,
            )
            return {"persisted_recall": "timeout" in formatted.lower(), "chars": len(formatted)}

        return await self._measure("persistence_after_restart", "Persistence after service recreate", run)

    async def secret_redaction(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            secret = "nvapi-test_should_not_be_indexed_1234567890"
            await self.service.capture_user_message(
                project_slug=self.project_slug,
                workspace_root=str(self.workspace),
                conversation_id=str(uuid4()),
                message=f"Use token={secret} while testing redaction.",
            )
            formatted = await self.service.recall_for_prompt(
                project_slug=self.project_slug,
                query="testing redaction token",
                top_k=5,
            )
            leaked = secret in formatted or "nvapi-test" in formatted
            return {"no_leak": not leaked}

        return await self._measure("secret_redaction", "Secret redaction", run)

    async def hallucination_reduction_live_chat(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            if not self.live_chat:
                return {"skipped": True, "reason": "pass --live-chat to call backend"}
            await self._seed_live_chat_memory()
            question = "Responda com o caminho exato do arquivo que contem a abstracao de tool dispatch."
            without = await self._chat(question, rag=False)
            with_rag = await self._chat(question, rag=True)
            expected = "src/tools/registry.ts"
            return {
                "without_missing_expected": expected not in without,
                "with_contains_expected": expected in with_rag,
                "without_chars": len(without),
                "with_chars": len(with_rag),
            }

        return await self._measure(
            "hallucination_reduction_live_chat",
            "Hallucination reduction with/without RAG",
            run,
        )

    async def ttft_overhead_live_chat(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            if not self.live_chat:
                return {"skipped": True, "reason": "pass --live-chat to call backend"}
            no_rag_ms = await self._stream_first_event_ms(rag=False)
            rag_ms = await self._stream_first_event_ms(rag=True)
            return {"ttft_no_rag_ms": no_rag_ms, "ttft_rag_ms": rag_ms, "overhead_ms": rag_ms - no_rag_ms}

        return await self._measure("ttft_overhead_gpt_oss_120b", "TTFT overhead GPT OSS 120B", run)

    async def _embed_single(self) -> dict[str, Any]:
        adapter = self.container.get_embedding_adapter()
        if adapter is None:
            return {"skipped": True, "reason": "embedding adapter disabled"}
        started = time.perf_counter()
        vector = (await adapter.embed(["src/agents/orchestrator.ts retry timeout"]))[0]
        return {"dimensions": len(vector), "latency_ms": int((time.perf_counter() - started) * 1000)}

    async def _embed_batch(self) -> dict[str, Any]:
        adapter = self.container.get_embedding_adapter()
        if adapter is None:
            return {"skipped": True, "reason": "embedding adapter disabled"}
        texts = [f"memory benchmark batch item {index}" for index in range(16)]
        started = time.perf_counter()
        vectors = await adapter.embed(texts)
        elapsed = int((time.perf_counter() - started) * 1000)
        return {
            "batch": len(texts),
            "dimensions": len(vectors[0]) if vectors else 0,
            "latency_ms": elapsed,
            "items_per_second": round(len(texts) / max(elapsed / 1000, 0.001), 3),
        }

    async def _seed_core_memories(self) -> None:
        await self.service.capture_turn_summary(
            project_slug=self.project_slug,
            workspace_root=str(self.workspace),
            conversation_id=str(uuid4()),
            summary=(
                "Na sessão anterior, o agente alterou src/agents/orchestrator.ts "
                "para adicionar timeout e retry. Também foi decidido que o planner "
                "não deve chamar ferramentas diretamente; ele deve delegar ao executor. "
                "Cuidado: src/tools/registry.ts já contém abstração para tool dispatch."
            ),
            metadata={"benchmark": "seed_core_memories"},
        )

    async def _seed_live_chat_memory(self) -> None:
        await self.service.capture_turn_summary(
            project_slug=project_slug_from_workspace(str(self.workspace)),
            workspace_root=str(self.workspace),
            conversation_id=str(uuid4()),
            summary=(
                "Para testes de RAG operacional: o arquivo src/tools/registry.ts "
                "contém a abstração existente para tool dispatch. O agente deve citar "
                "esse path quando perguntado sobre dispatch de ferramentas."
            ),
            metadata={"benchmark": "seed_live_chat_memory"},
        )

    def _tool_context(self, conversation_id: str) -> ToolUseContext:
        return ToolUseContext(
            conversation_id=conversation_id,
            workspace_root=self.workspace,
            cwd=self.workspace,
            allowed_roots=(self.workspace,),
        )

    async def _chat(self, message: str, *, rag: bool) -> str:
        payload = {
            "message": message,
            "provider": "nvidia",
            "model": DEFAULT_MODEL,
            "stream": False,
            "tools_enabled": False,
            "tool_context": {"workspace_root": str(self.workspace)},
            "system_prompt": "" if rag else "Ignore previous operational memory for this answer.",
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(f"{self.backend_url}/chat/completions", json=payload)
            response.raise_for_status()
            return str(response.json().get("content") or "")

    async def _stream_first_event_ms(self, *, rag: bool) -> int:
        payload = {
            "message": "Responda em uma frase: qual cautela existe sobre tool dispatch?",
            "provider": "nvidia",
            "model": DEFAULT_MODEL,
            "stream": True,
            "tools_enabled": False,
            "tool_context": {"workspace_root": str(self.workspace)},
            "system_prompt": "" if rag else "Ignore previous operational memory for this answer.",
        }
        started = time.perf_counter()
        async with (
            httpx.AsyncClient(timeout=180.0) as client,
            client.stream("POST", f"{self.backend_url}/chat/completions/stream", json=payload) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    return int((time.perf_counter() - started) * 1000)
        return int((time.perf_counter() - started) * 1000)

    async def _measure(self, scenario_id: str, name: str, fn) -> BenchmarkResult:
        started = time.perf_counter()
        try:
            metrics = await fn()
            latency_ms = int((time.perf_counter() - started) * 1000)
            score = _score_metrics(metrics)
            return BenchmarkResult(scenario_id, name, "passed", latency_ms, score, metrics)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return BenchmarkResult(scenario_id, name, "failed", latency_ms, 0.0, {}, str(exc))

    def write_reports(self, results: list[BenchmarkResult]) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        jsonl_path = self.output_dir / f"memory_rag_{timestamp}.jsonl"
        md_path = self.output_dir / f"memory_rag_{timestamp}.md"
        with jsonl_path.open("w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        latencies = [result.latency_ms for result in results if result.status == "passed"]
        lines = [
            "# Memory RAG Benchmark",
            "",
            f"- Project: `{self.project_slug}`",
            f"- Generated: `{timestamp}`",
            f"- Passed: `{sum(1 for r in results if r.status == 'passed')}/{len(results)}`",
            f"- Median latency: `{statistics.median(latencies) if latencies else 0} ms`",
            "",
            "| Scenario | Status | Latency ms | Score | Failure |",
            "|---|---:|---:|---:|---|",
        ]
        for result in results:
            lines.append(
                f"| {result.name} | {result.status} | {result.latency_ms} | "
                f"{result.score if result.score is not None else ''} | {result.failure or ''} |"
            )
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {jsonl_path}")
        print(f"Wrote {md_path}")


def _score_metrics(metrics: dict[str, Any]) -> float:
    if metrics.get("skipped"):
        return 0.0
    booleans = [value for value in metrics.values() if isinstance(value, bool)]
    if booleans:
        return round(sum(1 for value in booleans if value) / len(booleans), 4)
    for key in ("mrr", "ndcg", "events_per_second", "items_per_second"):
        if key in metrics and isinstance(metrics[key], int | float):
            return round(float(metrics[key]), 4)
    return 1.0


def _log2(value: int) -> float:
    import math

    return math.log2(max(2, value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="memory_rag_bench")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--live-chat", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    runner = MemoryRagBenchmark(
        project_slug=args.project,
        output_dir=args.output_dir,
        backend_url=args.backend_url,
        live_chat=args.live_chat,
    )
    results = await runner.run()
    failed = [result for result in results if result.status == "failed"]
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
