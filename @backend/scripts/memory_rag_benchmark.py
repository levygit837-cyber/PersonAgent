"""Benchmark persistent operational RAG memory.

Run from @backend:
    uv run python scripts/memory_rag_benchmark.py --project memory_rag_bench

Hard/live examples:
    uv run python scripts/memory_rag_benchmark.py --project memory_rag_hard --live-chat
    uv run python scripts/memory_rag_benchmark.py --project memory_rag_hard \
        --live-chat --live-provider vertex --live-model gemini-3.1-flash-lite-preview

The benchmark writes JSONL and Markdown reports under @backend/.benchmarks by
default. It intentionally includes deterministic index tests and optional live
chat tests because a memory system must be useful even when providers are
temporarily unavailable.
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
from sqlalchemy import text

from personagent.application.services.operational_memory import project_slug_from_workspace
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolResult, ToolUseContext
from personagent.infrastructure.config.settings import get_project_root
from personagent.infrastructure.persistence.database import AsyncSessionLocal, init_db
from personagent.interfaces.config.di_container import DIContainer, get_container

PROJECT_ROOT = get_project_root()
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "@backend" / ".benchmarks" / "memory_rag"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_PROVIDER = "nvidia"
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
        live_provider: str,
        live_model: str,
        long_context_chars: int,
        long_session_turns: int,
        distractor_count: int,
    ) -> None:
        self.project_slug = project_slug
        self.output_dir = output_dir
        self.backend_url = backend_url.rstrip("/")
        self.live_chat = live_chat
        self.live_provider = live_provider
        self.live_model = live_model
        self.long_context_chars = max(50_000, long_context_chars)
        self.long_session_turns = max(12, long_session_turns)
        self.distractor_count = max(20, distractor_count)
        self.workspace = PROJECT_ROOT
        self.container = get_container()
        self.service = self.container.get_operational_memory_service()
        if self.service is None:
            raise RuntimeError("Operational memory is disabled")

        self.run_id = datetime.now(UTC).strftime("%H%M%S") + "-" + uuid4().hex[:8]
        self.synthetic_app = f"AuroraOps-{self.run_id}"
        self.synthetic_root = f"bench/{self.run_id}/auroraops"
        self.live_project_root = self.output_dir / "live_projects" / self.run_id
        self._fullstack_seeded = False
        self._long_context_seeded = False
        self._distractors_seeded = False
        self._temporal_seeded = False
        self._error_chain_seeded = False
        self._live_long_context_seeded = False
        self._live_project_memory_conversation_id = str(uuid4())
        self._live_long_context_memory_conversation_id = str(uuid4())

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
            # Harder operational-memory benchmarks added after the first pass.
            await self.multi_turn_fullstack_project_recall(),
            await self.sequential_followup_query_coherence(),
            await self.semantic_paraphrase_embedding_advantage(),
            await self.distractor_collision_precision_at_k(),
            await self.long_context_pressure_recall(),
            await self.superseded_decision_conflict_recall(),
            await self.temporal_latest_state_after_edits(),
            await self.error_solution_chain_reconstruction(),
            await self.dependency_runtime_repro_recall(),
            await self.agent_handoff_state_recovery(),
            await self.live_iterative_project_chat_rag_delta(),
            await self.live_long_context_dynamic_rag_delta(),
            await self.live_tool_project_build_quality(),
        ]
        self.write_reports(results)
        return results

    async def run_single_session_live(self) -> list[BenchmarkResult]:
        await init_db()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = [await self.live_single_session_persistent_rag()]
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
            findings = await self._recall_findings(
                "timeout retry orchestrator planner executor tool dispatch registry abstraction",
                top_k=5,
            )
            hit_rank = _rank_of(findings, "orchestrator", "timeout")
            return {
                "retrieved": len(findings),
                "hit_rank": hit_rank,
                "mrr": 0.0 if hit_rank is None else round(1.0 / hit_rank, 4),
            }

        return await self._measure("recall_at_k_mrr", "Recall@k and MRR", run)

    async def ndcg_relevance(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            findings = await self._recall_findings(
                "registry already contains tool dispatch abstraction",
                top_k=5,
            )
            gains = [3 if "registry" in _finding_text(finding).lower() else 1 for finding in findings]
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
            fresh_container = DIContainer()
            service = fresh_container.get_operational_memory_service()
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
            return {
                "ttft_no_rag_ms": no_rag_ms,
                "ttft_rag_ms": rag_ms,
                "overhead_ms": rag_ms - no_rag_ms,
                "quality_score": 1.0 if rag_ms - no_rag_ms < 2_000 else 0.5,
            }

        return await self._measure("ttft_overhead_gpt_oss_120b", "TTFT overhead live chat", run)

    async def multi_turn_fullstack_project_recall(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_fullstack_project_session()
            expectations = [
                (
                    "Qual backend entrypoint o agente criou para o projeto fullstack?",
                    ("backend/app/main.py", "FastAPI"),
                ),
                (
                    "Onde esta o console React de incidentes que deve consumir o backend?",
                    ("frontend/src/features/incidents/IncidentConsole.tsx", "React"),
                ),
                (
                    "Qual contrato foi definido para streaming de incidentes?",
                    ("GET /api/incidents/stream", "SSE"),
                ),
                (
                    "Qual decisao de autenticacao ficou ativa para o app?",
                    ("httpOnly", "SameSite=Lax"),
                ),
                (
                    "Qual protecao evita mutacoes duplicadas no frontend?",
                    ("X-Request-Fingerprint", "idempotency"),
                ),
            ]
            hits = 0
            ranks: list[int] = []
            for query, terms in expectations:
                findings = await self._recall_findings(f"{query} {self.synthetic_app}", top_k=8)
                rank = _rank_of(findings, *terms)
                if rank is not None:
                    hits += 1
                    ranks.append(rank)
            return {
                "queries": len(expectations),
                "hits": hits,
                "avg_rank": round(statistics.mean(ranks), 2) if ranks else None,
                "quality_score": round(hits / len(expectations), 4),
            }

        return await self._measure(
            "hard_multi_turn_fullstack_project",
            "Hard: multi-turn fullstack project recall",
            run,
        )

    async def sequential_followup_query_coherence(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_fullstack_project_session()
            first = await self._recall_findings(
                f"No {self.synthetic_app}, qual arquivo contem o fetch wrapper do frontend?",
                top_k=6,
            )
            first_path = _first_path(first) or "arquivo desconhecido"
            second_query = (
                f"Com base no arquivo {first_path}, qual header foi escolhido para idempotencia?"
            )
            second = await self._recall_findings(second_query, top_k=6)
            second_text = _joined_findings(second)
            third_query = (
                "Depois dessa resposta, qual endpoint backend deve respeitar esse mesmo contrato?"
            )
            third = await self._recall_findings(f"{third_query} {second_text[:500]}", top_k=6)
            return {
                "first_has_api_file": "frontend/src/lib/api.ts" in _joined_findings(first),
                "second_has_header": "X-Request-Fingerprint" in second_text,
                "third_has_endpoint": "POST /api/incidents" in _joined_findings(third),
                "followup_queries": 3,
            }

        return await self._measure(
            "hard_sequential_followup_query_coherence",
            "Hard: sequential follow-up query coherence",
            run,
        )

    async def semantic_paraphrase_embedding_advantage(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_fullstack_project_session()
            query = (
                "Quando a rede repetir o envio do formulario, que mecanismo impede criar "
                "dois incidentes iguais sem usar as palavras do codigo?"
            )
            lexical = await self._recall_findings(query, top_k=8, use_embedding=False)
            hybrid = await self._recall_findings(query, top_k=8, use_embedding=True)
            lexical_rank = _rank_of(lexical, "X-Request-Fingerprint")
            hybrid_rank = _rank_of(hybrid, "X-Request-Fingerprint")
            improved = hybrid_rank is not None and (
                lexical_rank is None or hybrid_rank <= lexical_rank
            )
            return {
                "lexical_rank": lexical_rank,
                "hybrid_rank": hybrid_rank,
                "embedding_helped": improved,
                "quality_score": 1.0 if hybrid_rank == 1 and improved else 0.5 if improved else 0.0,
            }

        return await self._measure(
            "hard_semantic_paraphrase_embedding_advantage",
            "Hard: semantic paraphrase embedding advantage",
            run,
        )

    async def distractor_collision_precision_at_k(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_fullstack_project_session()
            await self._seed_distractor_memories()
            findings = await self._recall_findings(
                (
                    "No projeto certo, onde ficou o console de incidentes com SSE, "
                    f"credenciais e idempotencia para {self.synthetic_app}?"
                ),
                top_k=10,
            )
            text = _joined_findings(findings)
            target_rank = _rank_of(findings, self.synthetic_app, "IncidentConsole.tsx")
            wrong_top = bool(findings and "Legacy" in _finding_text(findings[0]))
            precision_terms = sum(
                1
                for finding in findings[:5]
                if self.synthetic_app in _finding_text(finding)
                or self.synthetic_root in _finding_text(finding)
            )
            return {
                "distractors": self.distractor_count,
                "target_rank": target_rank,
                "wrong_project_top": wrong_top,
                "precision_at_5": round(precision_terms / 5, 4),
                "has_target_path": "IncidentConsole.tsx" in text,
                "quality_score": 1.0 if target_rank == 1 and not wrong_top else 0.5 if target_rank else 0.0,
            }

        return await self._measure(
            "hard_distractor_collision_precision_at_k",
            "Hard: distractor collision precision@k",
            run,
        )

    async def long_context_pressure_recall(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_long_context_pressure()
            queries = [
                (
                    f"No contexto longo do {self.synthetic_app}, recupere o marcador inicial de arquitetura.",
                    ("EARLY_CANARY", "TenantBoundary"),
                ),
                (
                    f"No contexto longo do {self.synthetic_app}, qual decisao de meio da sessao controla backpressure?",
                    ("MID_CANARY", "bounded queue"),
                ),
                (
                    f"No contexto longo do {self.synthetic_app}, qual foi a ultima cautela antes de encerrar?",
                    ("LATE_CANARY", "do not remove retry budget"),
                ),
            ]
            hits = 0
            ranks: list[int] = []
            for query, terms in queries:
                findings = await self._recall_findings(query, top_k=8)
                rank = _rank_of(findings, *terms)
                if rank is not None:
                    hits += 1
                    ranks.append(rank)
            return {
                "target_chars": self.long_context_chars,
                "queries": len(queries),
                "hits": hits,
                "avg_rank": round(statistics.mean(ranks), 2) if ranks else None,
                "quality_score": round(hits / len(queries), 4),
            }

        return await self._measure(
            "hard_long_context_pressure_recall",
            "Hard: long context pressure recall",
            run,
        )

    async def superseded_decision_conflict_recall(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_fullstack_project_session()
            findings = await self._recall_findings(
                f"Qual decisao atual de fila/eventos para {self.synthetic_app}, ignorando alternativas antigas?",
                top_k=6,
            )
            text = _joined_findings(findings)
            active = "PostgreSQL outbox" in text and "active" in text.lower()
            stale = "in-memory queue" in text and "superseded" not in text.lower()
            return {
                "active_decision_found": active,
                "unstated_stale_decision_leaked": stale,
                "quality_score": 1.0 if active and not stale else 0.5 if active else 0.0,
            }

        return await self._measure(
            "hard_superseded_decision_conflict",
            "Hard: superseded decision conflict recall",
            run,
        )

    async def temporal_latest_state_after_edits(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_temporal_edits()
            findings = await self._recall_findings(
                f"Qual e o endpoint canonical atual de importacao em lote no {self.synthetic_app}?",
                top_k=6,
            )
            text = _joined_findings(findings)
            latest_rank = _rank_of(findings, "/api/incidents/bulk-import-v3", "canonical")
            old_version_top = bool(
                findings
                and any(old in _finding_text(findings[0]) for old in ("bulk-import-v1", "bulk-import-v2"))
            )
            return {
                "latest_rank": latest_rank,
                "old_version_top": old_version_top,
                "quality_score": 1.0 if latest_rank == 1 and not old_version_top else 0.5 if latest_rank else 0.0,
                "has_latest": "/api/incidents/bulk-import-v3" in text,
            }

        return await self._measure(
            "hard_temporal_latest_state_after_edits",
            "Hard: temporal latest state after edits",
            run,
        )

    async def error_solution_chain_reconstruction(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_error_solution_chain()
            findings = await self._recall_findings(
                f"Reconstrua a cadeia de erro e solucao do teste SSE do {self.synthetic_app}.",
                top_k=8,
            )
            text = _joined_findings(findings)
            return {
                "has_initial_error": "EventSource credentials were omitted" in text,
                "has_failed_attempt": "retrying without credentials did not fix" in text,
                "has_final_solution": "withCredentials adapter and cookie session" in text,
                "quality_score": _fraction(
                    [
                        "EventSource credentials were omitted" in text,
                        "retrying without credentials did not fix" in text,
                        "withCredentials adapter and cookie session" in text,
                    ]
                ),
            }

        return await self._measure(
            "hard_error_solution_chain_reconstruction",
            "Hard: error and solution chain reconstruction",
            run,
        )

    async def dependency_runtime_repro_recall(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_fullstack_project_session()
            findings = await self._recall_findings(
                f"Como reproduzir localmente o {self.synthetic_app}, incluindo dependencias e comandos?",
                top_k=8,
            )
            text = _joined_findings(findings)
            checks = [
                "uv add fastapi sqlalchemy asyncpg pgvector" in text,
                "pnpm add react zod @tanstack/react-query" in text,
                "uvicorn backend.app.main:app --reload" in text,
                "pnpm dev --filter web" in text,
            ]
            return {
                "dependency_hits": sum(checks),
                "expected": len(checks),
                "quality_score": _fraction(checks),
            }

        return await self._measure(
            "hard_dependency_runtime_repro",
            "Hard: dependency and runtime repro recall",
            run,
        )

    async def agent_handoff_state_recovery(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            await self._seed_fullstack_project_session()
            findings = await self._recall_findings(
                f"Se outro agente assumir o {self.synthetic_app}, qual e o proximo passo seguro?",
                top_k=8,
            )
            text = _joined_findings(findings)
            checks = [
                "Executor owns backend/app/routers/incidents.py" in text,
                "Reviewer must verify CORS credentials" in text,
                "Do not rewrite frontend/src/lib/api.ts" in text,
            ]
            return {
                "handoff_hits": sum(checks),
                "expected": len(checks),
                "quality_score": _fraction(checks),
            }

        return await self._measure(
            "hard_agent_handoff_state_recovery",
            "Hard: agent handoff state recovery",
            run,
        )

    async def live_iterative_project_chat_rag_delta(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            if not self.live_chat:
                return {"skipped": True, "reason": "pass --live-chat to call backend"}
            await self._seed_live_project_memory()
            questions = [
                "Qual arquivo frontend deve ser preservado porque ja contem o fetch wrapper?",
                "Qual header foi escolhido para evitar duplicar incidentes em retries?",
                "Qual decisao ativa substituiu JWT no localStorage?",
            ]
            expected = [
                "frontend/src/lib/api.ts",
                "X-Request-Fingerprint",
                "httpOnly",
            ]
            without_hits = 0
            with_hits = 0
            without_conversation_id: str | None = None
            rag_conversation_id: str | None = None
            question_results: list[dict[str, Any]] = []
            for question, term in zip(questions, expected, strict=True):
                without, without_conversation_id = await self._chat_turn(
                    question,
                    rag=False,
                    conversation_id=without_conversation_id,
                )
                with_rag, rag_conversation_id = await self._chat_turn(
                    question,
                    rag=True,
                    conversation_id=rag_conversation_id,
                )
                without_hit = _contains_expected(without, term)
                with_hit = _contains_expected(with_rag, term)
                without_hits += int(without_hit)
                with_hits += int(with_hit)
                question_results.append(
                    {
                        "question": question,
                        "expected_any": [term],
                        "without_hit": without_hit,
                        "with_rag_hit": with_hit,
                        "without_answer": without[:300],
                        "with_rag_answer": with_rag[:500],
                    }
                )
            return {
                "provider": self.live_provider,
                "model": self.live_model,
                "turns": len(questions),
                "without_conversation_id": without_conversation_id,
                "rag_conversation_id": rag_conversation_id,
                "persistent_conversations": bool(without_conversation_id and rag_conversation_id),
                "without_hits": without_hits,
                "with_rag_hits": with_hits,
                "delta": with_hits - without_hits,
                "quality_score": 1.0 if with_hits > without_hits and with_hits >= 2 else 0.5 if with_hits else 0.0,
                "question_results": question_results,
            }

        return await self._measure(
            "hard_live_iterative_project_chat_rag_delta",
            "Hard: live iterative project chat RAG delta",
            run,
        )

    async def live_long_context_dynamic_rag_delta(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            if not self.live_chat:
                return {"skipped": True, "reason": "pass --live-chat to call backend"}
            await self._seed_live_long_context_memory()
            questions = [
                (
                    "No historico enorme desta sessao, qual marcador identifica a regra inicial de isolamento entre tenant, project_slug e conversation_id?",
                    ("LIVE_EARLY_CANARY",),
                ),
                (
                    "Depois dos eventos intermediarios, qual decisao controla backpressure no stream de incidentes?",
                    ("LIVE_MID_CANARY", "bounded queue"),
                ),
                (
                    "Na ultima cautela operacional, qual regra de retry nao pode ser removida?",
                    (
                        "LIVE_LATE_CANARY",
                        "retry budget",
                        "PostgreSQL outbox stream processor",
                    ),
                ),
            ]
            without_hits = 0
            with_hits = 0
            rag_chars: list[int] = []
            question_results: list[dict[str, Any]] = []
            without_conversation_id: str | None = None
            rag_conversation_id: str | None = None
            for question, expected_terms in questions:
                without, without_conversation_id = await self._chat_turn(
                    question,
                    rag=False,
                    conversation_id=without_conversation_id,
                )
                with_rag, rag_conversation_id = await self._chat_turn(
                    question,
                    rag=True,
                    conversation_id=rag_conversation_id,
                )
                without_hit = _contains_expected(without, expected_terms)
                with_hit = _contains_expected(with_rag, expected_terms)
                without_hits += int(without_hit)
                with_hits += int(with_hit)
                rag_chars.append(len(with_rag))
                question_results.append(
                    {
                        "question": question,
                        "expected_any": list(expected_terms),
                        "without_hit": without_hit,
                        "with_rag_hit": with_hit,
                        "without_answer": without[:300],
                        "with_rag_answer": with_rag[:500],
                    }
                )
            return {
                "provider": self.live_provider,
                "model": self.live_model,
                "target_context_chars": self.long_context_chars,
                "queries": len(questions),
                "without_conversation_id": without_conversation_id,
                "rag_conversation_id": rag_conversation_id,
                "seed_memory_conversation_id": self._live_long_context_memory_conversation_id,
                "persistent_conversations": bool(without_conversation_id and rag_conversation_id),
                "without_hits": without_hits,
                "with_rag_hits": with_hits,
                "delta": with_hits - without_hits,
                "avg_rag_answer_chars": round(statistics.mean(rag_chars), 2) if rag_chars else 0,
                "quality_score": 1.0 if with_hits == len(questions) and without_hits == 0 else with_hits / len(questions),
                "question_results": question_results,
            }

        return await self._measure(
            "hard_live_long_context_dynamic_rag_delta",
            "Hard: live 1M-context dynamic RAG delta",
            run,
        )

    async def live_single_session_persistent_rag(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            if not self.live_chat:
                return {"skipped": True, "reason": "pass --live-chat to call backend"}

            started_at = datetime.now(UTC)
            marker = f"SINGLE_SESSION_RAG_{self.run_id}"
            bootstrap, conversation_id = await self._chat_turn(
                (
                    f"[{marker}] Inicie uma unica sessao persistente de benchmark. "
                    "Responda apenas READY."
                ),
                rag=True,
                workspace_root=self.workspace,
                conversation_id=None,
            )
            if not conversation_id:
                raise RuntimeError("backend did not return conversation_id for single-session run")
            await asyncio.sleep(2)

            await self._seed_live_project_memory(
                conversation_id=conversation_id,
                benchmark="single_session_live_project_memory",
            )
            await self._seed_live_long_context_memory(
                conversation_id=conversation_id,
                benchmark="single_session_live_long_context",
            )

            work_turns = [
                "Registre que o objetivo da sessao e construir um console fullstack de incidentes. Responda em uma frase.",
                "Prepare uma verificacao final de memoria operacional, sem revelar respostas ainda.",
            ]
            for index, turn in enumerate(work_turns, start=1):
                _, returned_id = await self._chat_turn(
                    f"[{marker}] Etapa {index}: {turn}",
                    rag=True,
                    workspace_root=self.workspace,
                    conversation_id=conversation_id,
                )
                if returned_id != conversation_id:
                    raise RuntimeError(
                        f"conversation_id drifted during work turn {index}: {returned_id}"
                    )
                await asyncio.sleep(2)

            await self._chat_with_tools(
                (
                    f"[{marker}] Use uma ferramenta de leitura ou shell read-only para verificar "
                    "que @backend/scripts/memory_rag_benchmark.py existe. Responda curto."
                ),
                workspace=self.workspace,
                conversation_id=conversation_id,
            )
            await asyncio.sleep(2)

            questions: list[tuple[str, tuple[str, ...]]] = [
                (
                    "Qual arquivo frontend deve ser preservado porque ja contem o fetch wrapper?",
                    ("frontend/src/lib/api.ts",),
                ),
                (
                    "Qual header foi escolhido para evitar duplicar incidentes em retries?",
                    ("X-Request-Fingerprint",),
                ),
                (
                    "Qual decisao ativa substituiu JWT no localStorage?",
                    ("httpOnly", "SameSite=Lax"),
                ),
                (
                    "No historico enorme desta sessao, qual marcador identifica a regra inicial de isolamento entre tenant, project_slug e conversation_id?",
                    ("LIVE_EARLY_CANARY",),
                ),
                (
                    "Depois dos eventos intermediarios, qual decisao controla backpressure no stream de incidentes?",
                    ("LIVE_MID_CANARY", "bounded queue"),
                ),
                (
                    "Na ultima cautela operacional, qual regra de retry nao pode ser removida?",
                    (
                        "LIVE_LATE_CANARY",
                        "retry budget",
                        "PostgreSQL outbox stream processor",
                    ),
                ),
            ]
            hits = 0
            question_results: list[dict[str, Any]] = []
            for question, expected_terms in questions:
                answer, returned_id = await self._chat_turn(
                    question,
                    rag=True,
                    workspace_root=self.workspace,
                    conversation_id=conversation_id,
                )
                if returned_id != conversation_id:
                    raise RuntimeError(f"conversation_id drifted during recall query: {returned_id}")
                hit = _contains_expected(answer, expected_terms)
                hits += int(hit)
                question_results.append(
                    {
                        "question": question,
                        "expected_any": list(expected_terms),
                        "hit": hit,
                        "answer": answer[:600],
                    }
                )
                await asyncio.sleep(2)

            ended_at = datetime.now(UTC)
            audit = await self._audit_single_session(
                conversation_id=conversation_id,
                started_at=started_at,
                ended_at=ended_at,
                marker=marker,
            )
            single_session_ok = (
                audit["marker_conversations"] == 1
                and audit["memory_event_conversations"] == 1
                and audit["conversation_id"] == conversation_id
            )
            return {
                "provider": self.live_provider,
                "model": self.live_model,
                "conversation_id": conversation_id,
                "bootstrap_answer": bootstrap[:120],
                "single_session_ok": single_session_ok,
                "hits": hits,
                "expected": len(questions),
                "quality_score": hits / len(questions),
                "question_results": question_results,
                **audit,
            }

        return await self._measure(
            "hard_live_single_session_persistent_rag",
            "Hard: live single-session persistent RAG",
            run,
        )

    async def live_tool_project_build_quality(self) -> BenchmarkResult:
        async def run() -> dict[str, Any]:
            if not self.live_chat:
                return {"skipped": True, "reason": "pass --live-chat to call backend"}
            workspace = self.live_project_root
            workspace.mkdir(parents=True, exist_ok=True)
            await self._seed_live_workspace_project_memory(workspace)
            prompt = (
                "Construa um projeto fullstack real neste workspace usando ferramentas de escrita. "
                "Nao apenas descreva. Crie estes arquivos: backend/app/main.py, "
                "backend/app/routers/incidents.py, backend/app/services/memory_recall.py, "
                "frontend/src/lib/api.ts, frontend/src/features/incidents/IncidentConsole.tsx, "
                "frontend/src/features/incidents/useIncidentStream.ts, README.md. "
                "O sistema deve ter backend FastAPI, frontend React, SSE de incidentes, "
                "cookie httpOnly SameSite=Lax, header X-Request-Fingerprint para idempotencia, "
                "divisao clara em routers/services/frontend features, e notas de execucao. "
                "Depois de escrever os arquivos, responda com um resumo curto."
            )
            response = ""
            tool_error = None
            try:
                response = await self._chat_with_tools(prompt, workspace=workspace)
            except Exception as exc:
                tool_error = _format_exception(exc)
            files = {
                "backend_main": workspace / "backend/app/main.py",
                "backend_router": workspace / "backend/app/routers/incidents.py",
                "memory_service": workspace / "backend/app/services/memory_recall.py",
                "api_client": workspace / "frontend/src/lib/api.ts",
                "incident_console": workspace / "frontend/src/features/incidents/IncidentConsole.tsx",
                "stream_hook": workspace / "frontend/src/features/incidents/useIncidentStream.ts",
                "readme": workspace / "README.md",
            }
            existing = {name: path.exists() for name, path in files.items()}
            contents = {
                name: path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
                for name, path in files.items()
            }
            quality_checks = {
                "created_all_expected_files": all(existing.values()),
                "backend_uses_fastapi": "FastAPI" in contents["backend_main"],
                "router_has_sse": "/api/incidents/stream" in contents["backend_router"] or "EventSourceResponse" in contents["backend_router"],
                "api_client_has_credentials": "credentials" in contents["api_client"] and "include" in contents["api_client"],
                "idempotency_header_present": "X-Request-Fingerprint" in "\n".join(contents.values()),
                "frontend_component_uses_stream": "useIncidentStream" in contents["incident_console"],
                "memory_service_is_separate_module": "class" in contents["memory_service"] or "def " in contents["memory_service"],
                "readme_has_run_commands": "uvicorn" in contents["readme"] and ("pnpm" in contents["readme"] or "npm" in contents["readme"]),
            }
            followups = [
                ("Qual arquivo contem o hook de SSE?", "useIncidentStream.ts"),
                ("Qual header evita mutacoes duplicadas?", "X-Request-Fingerprint"),
                ("Qual modulo backend isola recall de memoria?", "memory_recall.py"),
            ]
            followup_hits = 0
            followup_errors: list[str] = []
            for question, expected in followups:
                try:
                    answer = await self._chat(question, rag=True, workspace_root=workspace)
                    followup_hits += int(expected in answer)
                except Exception as exc:
                    followup_errors.append(_format_exception(exc))
            return {
                "provider": self.live_provider,
                "model": self.live_model,
                "workspace": str(workspace),
                "tool_error": tool_error,
                "response_chars": len(response),
                "files_created": sum(1 for value in existing.values() if value),
                "expected_files": len(files),
                "quality_checks": quality_checks,
                "quality_hits": sum(1 for value in quality_checks.values() if value),
                "followup_hits": followup_hits,
                "followup_expected": len(followups),
                "followup_errors": followup_errors,
                "quality_score": round(
                    (
                        _fraction(list(quality_checks.values()))
                        + (followup_hits / len(followups))
                    )
                    / 2,
                    4,
                ),
            }

        return await self._measure(
            "hard_live_tool_project_build_quality",
            "Hard: live tool project build and code quality",
            run,
        )

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

    async def _seed_fullstack_project_session(self) -> None:
        if self._fullstack_seeded:
            return
        conversation_id = str(uuid4())
        await self.service.capture_user_message(
            project_slug=self.project_slug,
            workspace_root=str(self.workspace),
            conversation_id=conversation_id,
            message=(
                f"Crie o projeto {self.synthetic_app}: um sistema fullstack com backend FastAPI, "
                "frontend React, streaming SSE de incidentes, autenticacao por cookie e memoria RAG."
            ),
            metadata={"benchmark": "hard_fullstack_project", "turn": 1},
        )
        await self.service.capture_assistant_message(
            project_slug=self.project_slug,
            workspace_root=str(self.workspace),
            conversation_id=conversation_id,
            content=(
                f"Plano para {self.synthetic_app}: criar backend/app/main.py, "
                "backend/app/routers/incidents.py, frontend/src/lib/api.ts e "
                "frontend/src/features/incidents/IncidentConsole.tsx."
            ),
            provider="benchmark",
            model="synthetic-agent",
        )
        await self._capture_tool(
            conversation_id,
            "Write",
            {
                "type": "file_write",
                "created": True,
                "path": f"{self.synthetic_root}/backend/app/main.py",
                "content": (
                    "from fastapi import FastAPI\n"
                    "from backend.app.routers.incidents import router as incidents_router\n"
                    f"APP_NAME = '{self.synthetic_app}'\n"
                    "app = FastAPI(title=APP_NAME)\n"
                    "app.include_router(incidents_router, prefix='/api')\n"
                    "CORS_POLICY = 'configured origins only; allow_credentials=True'\n"
                    "RUN = 'uvicorn backend.app.main:app --reload'\n"
                ),
            },
            "Created FastAPI entrypoint with configured CORS and incidents router.",
            task="Create backend entrypoint",
        )
        await self._capture_tool(
            conversation_id,
            "Write",
            {
                "type": "file_write",
                "created": True,
                "path": f"{self.synthetic_root}/backend/app/routers/incidents.py",
                "content": (
                    "POST /api/incidents creates incidents with idempotency guard.\n"
                    "GET /api/incidents/stream opens SSE updates for the React console.\n"
                    "The endpoint must honor X-Request-Fingerprint from the frontend.\n"
                ),
            },
            "Created incidents router with POST /api/incidents and GET /api/incidents/stream SSE.",
            task="Create backend API routes",
        )
        await self._capture_tool(
            conversation_id,
            "Write",
            {
                "type": "file_write",
                "created": True,
                "path": f"{self.synthetic_root}/backend/app/db/schema.py",
                "content": (
                    "Tables: Incident, AgentRun, MemoryRecallLog, OutboxEvent.\n"
                    "PostgreSQL outbox stores event delivery state and retry budget.\n"
                    "pgvector is optional for production search; JSONB fallback remains available.\n"
                ),
            },
            "Created database schema with Incident, AgentRun, MemoryRecallLog and OutboxEvent.",
            task="Create backend schema",
        )
        await self._capture_tool(
            conversation_id,
            "Write",
            {
                "type": "file_write",
                "created": True,
                "path": f"{self.synthetic_root}/frontend/src/lib/api.ts",
                "content": (
                    "export const api = createFetchClient({ credentials: 'include' });\n"
                    "api.beforeRequest((request) => request.headers.set('X-Request-Fingerprint', stableFingerprint(request)));\n"
                    "Do not rewrite frontend/src/lib/api.ts; extend it because it centralizes auth and idempotency.\n"
                    "DEV = 'pnpm dev --filter web'\n"
                ),
            },
            "Created fetch wrapper with credentials include and X-Request-Fingerprint.",
            task="Create frontend API client",
        )
        await self._capture_tool(
            conversation_id,
            "Write",
            {
                "type": "file_write",
                "created": True,
                "path": f"{self.synthetic_root}/frontend/src/features/incidents/IncidentConsole.tsx",
                "content": (
                    "React IncidentConsole uses useIncidentStream('/api/incidents/stream').\n"
                    "It renders incident timeline, retry state, and memory citations.\n"
                    f"Component is scoped to {self.synthetic_app} and must use frontend/src/lib/api.ts.\n"
                ),
            },
            "Created React IncidentConsole consuming SSE and the shared API client.",
            task="Create frontend incident console",
        )
        await self._capture_tool(
            conversation_id,
            "shell",
            {
                "type": "shell",
                "command": "uv add fastapi sqlalchemy asyncpg pgvector && pnpm add react zod @tanstack/react-query",
                "return_code": 0,
                "stdout": (
                    "Installed backend deps: uv add fastapi sqlalchemy asyncpg pgvector. "
                    "Installed frontend deps: pnpm add react zod @tanstack/react-query."
                ),
            },
            "Installed backend and frontend dependencies for the fullstack project.",
            task="Install dependencies",
        )
        await self._capture_tool(
            conversation_id,
            "shell",
            {
                "type": "shell",
                "command": "uvicorn backend.app.main:app --reload",
                "return_code": 0,
                "stdout": "Runtime command validated: uvicorn backend.app.main:app --reload",
            },
            "Validated backend runtime command.",
            task="Validate backend runtime",
        )
        await self._capture_tool(
            conversation_id,
            "shell",
            {
                "type": "shell",
                "command": "pnpm dev --filter web",
                "return_code": 0,
                "stdout": "Runtime command validated: pnpm dev --filter web",
            },
            "Validated frontend runtime command.",
            task="Validate frontend runtime",
        )
        await self._capture_tool(
            conversation_id,
            "shell",
            {
                "type": "shell",
                "command": "pnpm test e2e:sse",
                "return_code": 1,
                "stderr": "CORS preflight failed because wildcard origin cannot be used with credentials.",
                "stdout": "Fix required: configured origins only and allow_credentials=True.",
            },
            "CORS preflight failed because wildcard origin cannot be used with credentials.",
            status=ToolExecutionStatus.ERROR,
            is_error=True,
            task="Run SSE E2E test",
        )
        await self._capture_tool(
            conversation_id,
            "Edit",
            {
                "type": "file_edit",
                "path": f"{self.synthetic_root}/backend/app/main.py",
                "diff": "@@ replace wildcard CORS with configured origins and allow_credentials=True",
                "content": "Decision: CORS must use configured origins only; allow_credentials=True.",
            },
            "Applied CORS fix for credentialed SSE and cookie auth.",
            task="Fix CORS credentials",
        )
        await self._capture_tool(
            conversation_id,
            "Edit",
            {
                "type": "file_edit",
                "path": f"{self.synthetic_root}/docs/architecture.md",
                "decision": (
                    "Decision active: use httpOnly SameSite=Lax session cookie for browser auth. "
                    "JWT in localStorage is rejected for this project."
                ),
                "content": "Authentication architecture decision.",
            },
            "Decision active: use httpOnly SameSite=Lax session cookie; reject JWT localStorage.",
            task="Record auth decision",
        )
        await self._capture_tool(
            conversation_id,
            "Edit",
            {
                "type": "file_edit",
                "path": f"{self.synthetic_root}/docs/architecture.md",
                "decision": (
                    "Decision superseded: in-memory queue for incident event delivery was replaced "
                    "by PostgreSQL outbox because restarts lost pending events."
                ),
                "content": "Superseded queue decision.",
            },
            "Decision superseded: in-memory queue replaced by PostgreSQL outbox.",
            task="Record superseded event decision",
        )
        await self._capture_tool(
            conversation_id,
            "Edit",
            {
                "type": "file_edit",
                "path": f"{self.synthetic_root}/docs/architecture.md",
                "decision": (
                    "Decision active: PostgreSQL outbox is the current event delivery architecture "
                    "with bounded queue backpressure and retry budget."
                ),
                "content": "Active outbox decision.",
            },
            "Decision active: PostgreSQL outbox with bounded queue backpressure and retry budget.",
            task="Record active event decision",
        )
        await self._capture_tool(
            conversation_id,
            "Task",
            {
                "type": "agent_state",
                "agent": "Planner",
                "task": (
                    "Executor owns backend/app/routers/incidents.py. Reviewer must verify CORS credentials. "
                    "Do not rewrite frontend/src/lib/api.ts because it already centralizes auth and idempotency."
                ),
            },
            (
                "Agent handoff: Executor owns backend/app/routers/incidents.py; "
                "Reviewer must verify CORS credentials; Do not rewrite frontend/src/lib/api.ts."
            ),
            task="Record agent handoff state",
        )
        for turn in range(max(0, self.long_session_turns - 12)):
            await self.service.capture_turn_summary(
                project_slug=self.project_slug,
                workspace_root=str(self.workspace),
                conversation_id=conversation_id,
                summary=(
                    f"Continuation turn {turn} for {self.synthetic_app}: keep React frontend and FastAPI backend coherent. "
                    "Preserve SSE, httpOnly cookie auth, X-Request-Fingerprint idempotency, and PostgreSQL outbox."
                ),
                metadata={"benchmark": "hard_fullstack_project", "turn": turn + 12},
            )
        self._fullstack_seeded = True

    async def _seed_distractor_memories(self) -> None:
        if self._distractors_seeded:
            return
        for index in range(self.distractor_count):
            app = f"AuroraOpsLegacy-{index}" if index % 2 == 0 else f"BorealOps-{index}"
            await self.service.capture_turn_summary(
                project_slug=self.project_slug,
                workspace_root=str(self.workspace),
                conversation_id=str(uuid4()),
                summary=(
                    f"Distractor project {app}: contains IncidentConsole.tsx, SSE notes, FastAPI router, "
                    "credentials include and idempotency, but it is not the requested benchmark project. "
                    f"Wrong path: bench/distractors/{app}/frontend/src/features/incidents/IncidentConsole.tsx."
                ),
                metadata={"benchmark": "hard_distractors", "index": index},
            )
        self._distractors_seeded = True

    async def _seed_long_context_pressure(self) -> None:
        if self._long_context_seeded:
            return
        await self._seed_fullstack_project_session()
        block = (
            f"{self.synthetic_app} operational log filler: frontend React, backend FastAPI, "
            "tool outputs, dependency notes, code review comments, retry decisions, memory recall evidence. "
        )
        target = self.long_context_chars
        block_size = 6_000
        total = 0
        index = 0
        while total < target:
            filler = (block * ((block_size // len(block)) + 2))[:block_size]
            if index == 2:
                filler += (
                    " EARLY_CANARY TenantBoundary: workspace isolation must separate tenant_id, "
                    "project_slug and conversation_id before any recall injection."
                )
            if total < target // 2 <= total + block_size:
                filler += (
                    " MID_CANARY: bounded queue backpressure protects SSE delivery when the outbox "
                    "replayer is slower than incident writes."
                )
            if total + block_size >= target:
                filler += (
                    " LATE_CANARY final caution: do not remove retry budget from the PostgreSQL outbox "
                    "when refactoring the incident stream."
                )
            await self.service.capture_turn_summary(
                project_slug=self.project_slug,
                workspace_root=str(self.workspace),
                conversation_id=str(uuid4()),
                summary=filler,
                metadata={"benchmark": "hard_long_context", "index": index},
            )
            total += len(filler)
            index += 1
        self._long_context_seeded = True

    async def _seed_temporal_edits(self) -> None:
        if self._temporal_seeded:
            return
        await self._seed_fullstack_project_session()
        conversation_id = str(uuid4())
        versions = [
            ("v1", "/api/incidents/bulk-import-v1", "deprecated first draft"),
            ("v2", "/api/incidents/bulk-import-v2", "deprecated validation draft"),
            ("v3", "/api/incidents/bulk-import-v3", "current canonical endpoint"),
        ]
        for version, endpoint, note in versions:
            await self._capture_tool(
                conversation_id,
                "Edit",
                {
                    "type": "file_edit",
                    "path": f"{self.synthetic_root}/backend/app/routers/incidents.py",
                    "diff": f"@@ set bulk import endpoint to {endpoint}",
                    "content": (
                        f"Temporal edit {version}: {endpoint}. {note}. "
                        f"For {self.synthetic_app}, canonical means the latest active endpoint."
                    ),
                },
                f"Temporal edit {version}: {endpoint} is {note}.",
                task="Update bulk import endpoint",
            )
        self._temporal_seeded = True

    async def _seed_error_solution_chain(self) -> None:
        if self._error_chain_seeded:
            return
        await self._seed_fullstack_project_session()
        conversation_id = str(uuid4())
        events = [
            (
                "shell",
                {
                    "type": "shell",
                    "command": "pnpm test sse-credentials",
                    "return_code": 1,
                    "stderr": "EventSource credentials were omitted; cookie session never reached backend.",
                },
                "EventSource credentials were omitted; cookie session never reached backend.",
                ToolExecutionStatus.ERROR,
                True,
            ),
            (
                "shell",
                {
                    "type": "shell",
                    "command": "pnpm test sse-credentials --retry-no-credentials",
                    "return_code": 1,
                    "stderr": "retrying without credentials did not fix authenticated stream.",
                },
                "retrying without credentials did not fix authenticated stream.",
                ToolExecutionStatus.ERROR,
                True,
            ),
            (
                "Edit",
                {
                    "type": "file_edit",
                    "path": f"{self.synthetic_root}/frontend/src/features/incidents/useIncidentStream.ts",
                    "diff": "@@ add withCredentials adapter and cookie session support for SSE",
                    "content": "Final solution: withCredentials adapter and cookie session for SSE stream.",
                },
                "Final solution: withCredentials adapter and cookie session.",
                ToolExecutionStatus.COMPLETED,
                False,
            ),
        ]
        for name, data, content, status, is_error in events:
            await self._capture_tool(
                conversation_id,
                name,
                data,
                content,
                status=status,
                is_error=is_error,
                task="Debug SSE credential chain",
            )
        self._error_chain_seeded = True

    async def _seed_live_project_memory(
        self,
        *,
        conversation_id: str | None = None,
        benchmark: str = "hard_live_project_memory",
    ) -> None:
        live_project_slug = project_slug_from_workspace(str(self.workspace))
        memory_conversation_id = conversation_id or self._live_project_memory_conversation_id
        await self.service.capture_turn_summary(
            project_slug=live_project_slug,
            workspace_root=str(self.workspace),
            conversation_id=memory_conversation_id,
            summary=(
                "Live hard RAG benchmark memory: in the created fullstack project, "
                "frontend/src/lib/api.ts must be preserved because it contains the fetch wrapper. "
                "The idempotency header is X-Request-Fingerprint. "
                "The active auth decision is httpOnly SameSite=Lax cookie, replacing JWT in localStorage."
            ),
            metadata={"benchmark": benchmark, "run_id": self.run_id},
        )

    async def _seed_live_long_context_memory(
        self,
        *,
        conversation_id: str | None = None,
        benchmark: str = "hard_live_long_context",
    ) -> None:
        if self._live_long_context_seeded:
            return
        live_project_slug = project_slug_from_workspace(str(self.workspace))
        memory_conversation_id = conversation_id or self._live_long_context_memory_conversation_id
        block = (
            "Live 1M benchmark operational filler: agent builds a fullstack incident console, "
            "captures diffs, tool outputs, architecture decisions, errors, dependency installs, "
            "and recall evidence across sessions. "
        )
        block_size = 6_000
        total = 0
        index = 0
        while total < self.long_context_chars:
            content = (block * ((block_size // len(block)) + 2))[:block_size]
            if index == 2:
                content += (
                    " LIVE_EARLY_CANARY TenantBoundary: isolate tenant_id, project_slug, "
                    "workspace_root, and conversation_id before recall injection."
                )
            if total < self.long_context_chars // 2 <= total + block_size:
                content += (
                    " LIVE_MID_CANARY bounded queue backpressure controls incident SSE delivery "
                    "when the outbox replayer falls behind."
                )
            if total + block_size >= self.long_context_chars:
                content += (
                    " LIVE_LATE_CANARY final caution: do not remove retry budget from the "
                    "PostgreSQL outbox stream processor."
                )
            await self.service.capture_turn_summary(
                project_slug=live_project_slug,
                workspace_root=str(self.workspace),
                conversation_id=memory_conversation_id,
                summary=content,
                metadata={
                    "benchmark": benchmark,
                    "run_id": self.run_id,
                    "index": index,
                    "session_scope": memory_conversation_id,
                },
            )
            total += len(content)
            index += 1
        self._live_long_context_seeded = True

    async def _seed_live_workspace_project_memory(self, workspace: Path) -> None:
        await self.service.capture_turn_summary(
            project_slug=project_slug_from_workspace(str(workspace)),
            workspace_root=str(workspace),
            conversation_id=str(uuid4()),
            summary=(
                "Live tool-build benchmark memory: build a modular fullstack incident console. "
                "Architecture decision active: backend FastAPI routers delegate memory recall to "
                "backend/app/services/memory_recall.py. Frontend must keep all fetch behavior in "
                "frontend/src/lib/api.ts with credentials='include' and X-Request-Fingerprint. "
                "Use SSE endpoint /api/incidents/stream. Auth is httpOnly SameSite=Lax cookie. "
                "Avoid monolithic files; create feature modules."
            ),
            metadata={"benchmark": "hard_live_tool_project_memory", "run_id": self.run_id},
        )

    async def _capture_tool(
        self,
        conversation_id: str,
        name: str,
        data: dict[str, Any],
        content: str,
        *,
        status: ToolExecutionStatus = ToolExecutionStatus.COMPLETED,
        is_error: bool = False,
        task: str | None = None,
    ) -> None:
        call = ToolCall(
            id=f"bench-{name.lower()}-{uuid4().hex[:8]}",
            name=name,
            arguments={
                key: value
                for key, value in {
                    "path": data.get("path"),
                    "command": data.get("command"),
                    "task": task,
                }.items()
                if value
            },
        )
        result = ToolResult(
            tool_call_id=call.id,
            tool_name=name,
            content=content,
            status=status,
            is_error=is_error,
            data=data,
        )
        await self.service.capture_tool_result(
            project_slug=self.project_slug,
            workspace_root=str(self.workspace),
            conversation_id=conversation_id,
            call=call,
            result=result,
            context=self._tool_context(conversation_id),
            task=task,
        )

    async def _recall_findings(
        self,
        query: str,
        *,
        top_k: int = 6,
        use_embedding: bool = True,
    ):
        query_embedding = await self._query_embedding(query) if use_embedding else None
        return await self.service.repository.recall(
            project_slug=self.project_slug,
            query=query,
            query_embedding=query_embedding,
            top_k=top_k,
            filters={"candidate_limit": 2_500},
            provider=self.live_provider if self.live_chat else None,
            model=self.live_model if self.live_chat else None,
        )

    async def _query_embedding(self, query: str) -> list[float] | None:
        adapter = self.container.get_embedding_adapter()
        if adapter is None:
            return None
        vectors = await adapter.embed([query])
        return vectors[0] if vectors else None

    def _tool_context(self, conversation_id: str) -> ToolUseContext:
        return ToolUseContext(
            conversation_id=conversation_id,
            workspace_root=self.workspace,
            cwd=self.workspace,
            allowed_roots=(self.workspace,),
        )

    async def _chat(
        self,
        message: str,
        *,
        rag: bool,
        workspace_root: Path | None = None,
        conversation_id: str | None = None,
    ) -> str:
        content, _ = await self._chat_turn(
            message,
            rag=rag,
            workspace_root=workspace_root,
            conversation_id=conversation_id,
        )
        return content

    async def _chat_turn(
        self,
        message: str,
        *,
        rag: bool,
        workspace_root: Path | None = None,
        conversation_id: str | None = None,
    ) -> tuple[str, str | None]:
        memory_workspace = workspace_root or self.workspace
        resolved_workspace = (
            str(memory_workspace)
            if rag
            else str(self.workspace / ".benchmarks" / "no_memory_workspace")
        )
        payload = {
            "message": message,
            "provider": self.live_provider,
            "model": self.live_model,
            "stream": False,
            "temperature": 0,
            "max_tokens": 1200,
            "prompt_mode": "exploring",
            "tools_enabled": False,
            "workspace_root": resolved_workspace,
            "tool_context": {"workspace_root": resolved_workspace},
            "system_prompt": (
                "Use persisted operational memory when provided and answer with exact strings."
                if rag
                else "You do not have persisted project memory. Answer only from the current question."
            ),
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        async with httpx.AsyncClient(timeout=240.0) as client:
            response = await client.post(f"{self.backend_url}/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            return str(body.get("content") or ""), body.get("conversation_id")

    async def _chat_with_tools(
        self,
        message: str,
        *,
        workspace: Path,
        conversation_id: str | None = None,
    ) -> str:
        payload = {
            "message": message,
            "provider": self.live_provider,
            "model": self.live_model,
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 1800,
            "prompt_mode": "exploring",
            "tools_enabled": True,
            "allowed_tools": ["Read", "shell"],
            "workspace_root": str(workspace),
            "tool_context": {
                "workspace_root": str(workspace),
                "cwd": str(workspace),
                "allowed_roots": [str(workspace)],
            },
            "max_tool_iterations": 12,
            "system_prompt": (
                "You are a coding agent. Use the provided read-only tools to inspect the "
                "workspace. Prefer concrete evidence from tools over unsupported claims. "
                "After tool work, summarize what was checked."
            ),
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        async with httpx.AsyncClient(timeout=360.0) as client:
            response = await client.post(f"{self.backend_url}/chat/completions", json=payload)
            response.raise_for_status()
            return str(response.json().get("content") or "")

    async def _audit_single_session(
        self,
        *,
        conversation_id: str,
        started_at: datetime,
        ended_at: datetime,
        marker: str,
    ) -> dict[str, Any]:
        workspace_root = str(self.workspace)
        async with AsyncSessionLocal() as session:
            marker_rows = (
                await session.execute(
                    text(
                        """
                        SELECT DISTINCT conversation_id
                        FROM messages
                        WHERE content LIKE :marker
                        ORDER BY conversation_id
                        """
                    ),
                    {"marker": f"%{marker}%"},
                )
            ).all()
            window_message_conversations = (
                await session.execute(
                    text(
                        """
                        SELECT DISTINCT conversation_id
                        FROM messages
                        WHERE timestamp >= :started_at
                          AND timestamp <= :ended_at
                          AND content LIKE :marker
                        ORDER BY conversation_id
                        """
                    ),
                    {
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "marker": f"%{marker}%",
                    },
                )
            ).all()
            message_counts = (
                await session.execute(
                    text(
                        """
                        SELECT
                            count(*) AS total,
                            count(*) FILTER (WHERE role = 'user') AS users,
                            count(*) FILTER (WHERE role = 'assistant') AS assistants,
                            count(*) FILTER (WHERE role = 'tool') AS tool_messages,
                            count(*) FILTER (
                                WHERE role = 'assistant'
                                  AND tool_calls IS NOT NULL
                                  AND tool_calls <> '[]'::jsonb
                            ) AS assistant_tool_call_messages
                        FROM messages
                        WHERE conversation_id = CAST(:conversation_id AS uuid)
                        """
                    ),
                    {"conversation_id": conversation_id},
                )
            ).one()
            marker_conversations = len(marker_rows)
            memory_event_conversations = await session.scalar(
                text(
                    """
                    SELECT count(DISTINCT conversation_id)
                    FROM memory_events
                    WHERE metadata ->> 'run_id' = :run_id
                      AND metadata ->> 'benchmark' LIKE 'single_session_%'
                    """
                ),
                {"run_id": self.run_id},
            )
            memory_events = await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM memory_events
                    WHERE conversation_id = CAST(:conversation_id AS uuid)
                      AND metadata ->> 'run_id' = :run_id
                    """
                ),
                {"conversation_id": conversation_id, "run_id": self.run_id},
            )
            recall_logs = await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM memory_recall_logs
                    WHERE project_slug = :project_slug
                      AND created_at >= :started_at
                      AND created_at <= :ended_at
                    """
                ),
                {
                    "project_slug": project_slug_from_workspace(workspace_root),
                    "started_at": started_at,
                    "ended_at": ended_at,
                },
            )
        return {
            "conversation_id": conversation_id,
            "new_conversations_in_window": len(window_message_conversations),
            "new_conversation_ids_in_window": [
                str(row[0]) for row in window_message_conversations
            ],
            "marker_conversations": int(marker_conversations),
            "marker_conversation_ids": [str(row[0]) for row in marker_rows],
            "memory_event_conversations": int(memory_event_conversations or 0),
            "memory_events_for_conversation": int(memory_events or 0),
            "message_count": int(message_counts.total or 0),
            "user_message_count": int(message_counts.users or 0),
            "assistant_message_count": int(message_counts.assistants or 0),
            "tool_message_count": int(message_counts.tool_messages or 0),
            "assistant_tool_call_message_count": int(
                message_counts.assistant_tool_call_messages or 0
            ),
            "recall_logs_in_window": int(recall_logs or 0),
        }

    async def _stream_first_event_ms(self, *, rag: bool) -> int:
        workspace_root = str(self.workspace) if rag else str(self.workspace / ".benchmarks" / "no_memory_workspace")
        payload = {
            "message": "Responda em uma frase: qual cautela existe sobre tool dispatch?",
            "provider": self.live_provider,
            "model": self.live_model,
            "stream": True,
            "tools_enabled": False,
            "tool_context": {"workspace_root": workspace_root},
            "system_prompt": (
                "Use persisted operational memory when provided."
                if rag
                else "You do not have persisted project memory."
            ),
        }
        started = time.perf_counter()
        async with (
            httpx.AsyncClient(timeout=240.0) as client,
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
            status = _status_for_score(metrics, score)
            failure = None
            if status == "failed":
                failure = f"quality score {score} below threshold"
            return BenchmarkResult(scenario_id, name, status, latency_ms, score, metrics, failure)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return BenchmarkResult(scenario_id, name, "failed", latency_ms, 0.0, {}, _format_exception(exc))

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
            f"- Synthetic app: `{self.synthetic_app}`",
            f"- Generated: `{timestamp}`",
            f"- Provider/model: `{self.live_provider}` / `{self.live_model}`",
            f"- Long context target chars: `{self.long_context_chars}`",
            f"- Distractors: `{self.distractor_count}`",
            f"- Passed: `{sum(1 for r in results if r.status == 'passed')}/{len(results)}`",
            f"- Median latency: `{statistics.median(latencies) if latencies else 0} ms`",
            "",
            "Scores are scenario-specific. `1.0` is perfect for normalized quality checks; "
            "throughput scenarios use items/sec or events/sec.",
            "",
            "| Scenario | Status | Latency ms | Score | Failure |",
            "|---|---:|---:|---:|---|",
        ]
        for result in results:
            lines.append(
                f"| {result.name} | {result.status} | {result.latency_ms} | "
                f"{result.score if result.score is not None else ''} | {result.failure or ''} |"
            )
        lines.extend(["", "## Metrics", ""])
        for result in results:
            lines.extend(
                [
                    f"### {result.name}",
                    "",
                    "```json",
                    json.dumps(result.metrics or {}, ensure_ascii=False, indent=2, sort_keys=True),
                    "```",
                    "",
                ]
            )
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {jsonl_path}")
        print(f"Wrote {md_path}")


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__


def _score_metrics(metrics: dict[str, Any]) -> float:
    if metrics.get("skipped"):
        return 0.0
    if isinstance(metrics.get("quality_score"), int | float):
        return round(float(metrics["quality_score"]), 4)
    booleans = [value for value in metrics.values() if isinstance(value, bool)]
    if booleans:
        return round(sum(1 for value in booleans if value) / len(booleans), 4)
    for key in ("mrr", "ndcg", "events_per_second", "items_per_second"):
        if key in metrics and isinstance(metrics[key], int | float):
            return round(float(metrics[key]), 4)
    return 1.0


def _status_for_score(metrics: dict[str, Any], score: float) -> str:
    if metrics.get("skipped"):
        return "skipped"
    if "quality_score" in metrics or any(isinstance(value, bool) for value in metrics.values()):
        return "passed" if score >= 0.8 else "failed"
    if "mrr" in metrics or "ndcg" in metrics:
        return "passed" if score >= 0.8 else "failed"
    if "events_per_second" in metrics or "items_per_second" in metrics:
        return "passed" if score > 0 else "failed"
    return "passed"


def _fraction(values: list[bool]) -> float:
    return round(sum(1 for value in values if value) / max(1, len(values)), 4)


def _contains_expected(answer: str, expected: str | tuple[str, ...]) -> bool:
    expected_terms = (expected,) if isinstance(expected, str) else expected
    answer_lower = answer.lower()
    return any(term.lower() in answer_lower for term in expected_terms)


def _rank_of(findings: list[Any], *terms: str) -> int | None:
    lowered_terms = [term.lower() for term in terms]
    for index, finding in enumerate(findings, start=1):
        text = _finding_text(finding).lower()
        if all(term in text for term in lowered_terms):
            return index
    return None


def _finding_text(finding: Any) -> str:
    return " ".join(
        [
            str(getattr(finding, "finding", "")),
            " ".join(str(item) for item in getattr(finding, "evidence", []) or []),
            " ".join(str(item) for item in getattr(finding, "paths", []) or []),
            " ".join(str(item) for item in getattr(finding, "decisions", []) or []),
            " ".join(str(item) for item in getattr(finding, "cautions", []) or []),
        ]
    )


def _joined_findings(findings: list[Any]) -> str:
    return "\n".join(_finding_text(finding) for finding in findings)


def _first_path(findings: list[Any]) -> str | None:
    for finding in findings:
        paths = getattr(finding, "paths", []) or []
        if paths:
            return str(paths[0])
    return None


def _log2(value: int) -> float:
    import math

    return math.log2(max(2, value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="memory_rag_bench")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--live-chat", action="store_true")
    parser.add_argument("--live-provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--live-model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--long-context-chars",
        type=int,
        default=1_000_000,
        help="Synthetic operational memory volume used by the long-context pressure scenario.",
    )
    parser.add_argument(
        "--long-session-turns",
        type=int,
        default=48,
        help="Synthetic multi-turn work session length for the fullstack project scenario.",
    )
    parser.add_argument(
        "--distractors",
        type=int,
        default=120,
        help="Number of similar-but-wrong memories used by collision benchmarks.",
    )
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="Write the report and exit 0 even when quality scenarios fail.",
    )
    parser.add_argument(
        "--single-session-only",
        action="store_true",
        help="Run only the live benchmark that proves all chat turns use one conversation_id.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    runner = MemoryRagBenchmark(
        project_slug=args.project,
        output_dir=args.output_dir,
        backend_url=args.backend_url,
        live_chat=args.live_chat,
        live_provider=args.live_provider,
        live_model=args.live_model,
        long_context_chars=args.long_context_chars,
        long_session_turns=args.long_session_turns,
        distractor_count=args.distractors,
    )
    results = await runner.run_single_session_live() if args.single_session_only else await runner.run()
    failed = [result for result in results if result.status == "failed"]
    if failed and not args.allow_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
