"""Scale benchmark for GPT OSS 120B operational-memory recall.

The benchmark creates 50 distinct but related agent-system topics, runs one
initial GPT OSS 120B session per topic, runs follow-up turns in the same
conversations, then probes scoped and project-wide recall.

Example:

    uv run python scripts/gpt_oss_120b_memory_scale_benchmark.py \
        --repo-url https://github.com/levygit837-cyber/test-repo.git \
        --repo-root /home/levybonito/Projetos/test-repo \
        --session-count 50 \
        --followups-per-session 1 \
        --rpm-limit 35 \
        --max-tool-iterations 40
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.services.operational_memory import project_slug_from_workspace
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.infrastructure.config.settings import get_project_root
from personagent.infrastructure.persistence.database import AsyncSessionLocal, init_db
from personagent.infrastructure.persistence.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from personagent.interfaces.config.di_container import get_container

PROJECT_ROOT = get_project_root()
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "@backend" / ".benchmarks" / "gpt_oss_120b_memory_scale"
DEFAULT_REPO_URL = "https://github.com/levygit837-cyber/test-repo.git"
DEFAULT_REPO_ROOT = Path.home() / "Projetos" / "test-repo"
WORKTREE_NAME = "test-repo-gpt-oss-120b-scale"
WORKTREE_BRANCH = "codex/bench-gpt-oss-120b-scale"
PROJECT_NAME = "HelixAgent Runtime Knowledge Base"
PROJECT_KEY = "HELIXAGENT-GPTOSS120B-SCALE"


@dataclass(frozen=True, slots=True)
class ScaleTopic:
    index: int
    topic_id: str
    title: str
    layer: str
    problem: str
    decision: str
    relation: str
    validation: str
    canary: str
    terms: tuple[str, ...]


@dataclass(slots=True)
class TurnResult:
    phase: str
    status: str
    latency_ms: int
    content_chars: int = 0
    reasoning_chars: int = 0
    tool_events: int = 0
    tool_results: int = 0
    finish_reason: str | None = None
    failure: str | None = None


@dataclass(slots=True)
class SessionResult:
    topic_id: str
    title: str
    conversation_id: str | None
    artifact_path: str
    turns: list[TurnResult] = field(default_factory=list)
    status: str = "pending"


@dataclass(slots=True)
class RecallProbeResult:
    probe_id: str
    scenario: str
    topic_id: str
    latency_ms: int
    items: int
    budget_used: int
    omitted_count: int
    hit: bool
    leakage_hint: bool


class JsonlLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")

    def log(self, event: str, **payload: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(), "event": event, **payload}
        self._file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class RequestRateLimiter:
    def __init__(self, rpm_limit: int, logger: JsonlLogger) -> None:
        self.interval_seconds = 60.0 / max(1, rpm_limit)
        self._logger = logger
        self._last_request_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            wait_seconds = max(0.0, self.interval_seconds - elapsed)
            if wait_seconds > 0:
                self._logger.log("rate_limit_wait", wait_seconds=round(wait_seconds, 3))
                await asyncio.sleep(wait_seconds)
            self._last_request_at = time.monotonic()


class GptOss120bMemoryScaleBenchmark:
    def __init__(
        self,
        *,
        repo_url: str,
        repo_root: Path,
        output_dir: Path,
        session_count: int,
        followups_per_session: int,
        rpm_limit: int,
        max_tool_iterations: int,
        max_tokens: int,
        context_window_tokens: int,
        recall_probe_count: int,
        concurrency: int,
        dry_run: bool,
        start_embedding: bool,
        retries: int,
    ) -> None:
        self.repo_url = repo_url
        self.repo_root = repo_root.expanduser().resolve()
        self.output_dir = output_dir.expanduser().resolve()
        self.session_count = max(1, min(50, session_count))
        self.followups_per_session = max(0, followups_per_session)
        self.rpm_limit = max(1, rpm_limit)
        self.max_tool_iterations = max(1, max_tool_iterations)
        self.max_tokens = max(256, max_tokens)
        self.context_window_tokens = max(8_000, context_window_tokens)
        self.recall_probe_count = max(1, recall_probe_count)
        self.concurrency = max(1, min(8, concurrency))
        self.dry_run = dry_run
        self.start_embedding = start_embedding
        self.retries = max(0, retries)
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.run_dir = self.output_dir / self.run_id
        self.logger = JsonlLogger(self.run_dir / "scale_memory_stream.jsonl")
        self.rate_limiter = RequestRateLimiter(self.rpm_limit, self.logger)
        self.container = get_container()
        self.memory_service = self.container.get_operational_memory_service()
        if self.memory_service is None:
            raise RuntimeError("Operational memory is disabled")
        self.model = self.container.settings.nvidia_default_model or "openai/gpt-oss-120b"
        self.provider = "nvidia"
        self.worktree = self.repo_root.parent / WORKTREE_NAME
        self.project_slug = project_slug_from_workspace(str(self.worktree))
        self.topics = build_topics()[: self.session_count]

    async def run(self) -> tuple[list[SessionResult], list[RecallProbeResult]]:
        try:
            await init_db()
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.logger.log(
                "benchmark_started",
                project=PROJECT_NAME,
                project_key=PROJECT_KEY,
                repo_url=self.repo_url,
                repo_root=str(self.repo_root),
                worktree=str(self.worktree),
                project_slug=self.project_slug,
                provider=self.provider,
                model=self.model,
                session_count=self.session_count,
                followups_per_session=self.followups_per_session,
                rpm_limit=self.rpm_limit,
                max_tool_iterations=self.max_tool_iterations,
                concurrency=self.concurrency,
                dry_run=self.dry_run,
            )
            self._prepare_repo()
            self._prepare_worktree()
            self._write_topic_docs()
            await self._prepare_embedding_runtime()
            health = await self._provider_health()
            self.logger.log("provider_health", health=health)

            sessions = await self._run_topic_sessions()

            await self.memory_service.backfill_structured_memory(self.project_slug, limit=100_000)
            probes = await self._run_recall_probes(sessions)
            self._write_report(sessions, probes, health)
            self.logger.log("benchmark_finished", report=str(self.run_dir / "report.md"))
            return sessions, probes
        finally:
            if self.start_embedding:
                self.container.get_embedding_process_manager().stop()
            self.logger.close()

    def _prepare_repo(self) -> None:
        if not self.repo_root.exists():
            self._run(["git", "clone", self.repo_url, str(self.repo_root)], cwd=PROJECT_ROOT)
        if not self._has_commit(self.repo_root):
            (self.repo_root / "README.md").write_text(
                f"# {PROJECT_NAME}\n\nSeed repository for {PROJECT_KEY}.\n",
                encoding="utf-8",
            )
            self._run(["git", "add", "README.md"], cwd=self.repo_root)
            self._run(
                [
                    "git",
                    "-c",
                    "user.name=PersonAgent Benchmark",
                    "-c",
                    "user.email=bench@personagent.local",
                    "commit",
                    "-m",
                    "Initial GPT OSS memory scale scaffold",
                ],
                cwd=self.repo_root,
            )

    def _prepare_worktree(self) -> None:
        if not self.worktree.exists():
            self._run(
                ["git", "worktree", "add", "-B", WORKTREE_BRANCH, str(self.worktree), "main"],
                cwd=self.repo_root,
            )
        self.logger.log(
            "worktree_ready",
            path=str(self.worktree.resolve()),
            branch=WORKTREE_BRANCH,
            status=self._run(["git", "status", "--short"], cwd=self.worktree, check=False).stdout,
        )

    def _write_topic_docs(self) -> None:
        topic_dir = self.worktree / "docs" / "scale-topics"
        topic_dir.mkdir(parents=True, exist_ok=True)
        for topic in self.topics:
            path = topic_dir / f"{topic.topic_id}.md"
            path.write_text(topic_document(topic), encoding="utf-8")
        (self.worktree / "docs" / "scale-runs").mkdir(parents=True, exist_ok=True)
        self.logger.log("topic_docs_written", count=len(self.topics), topic_dir=str(topic_dir))

    async def _prepare_embedding_runtime(self) -> None:
        if self.start_embedding:
            manager = self.container.get_embedding_process_manager()
            started = await manager.start()
            self.logger.log("embedding_runtime", started=started, runtime=manager.runtime_status())
            return
        available = await self._embedding_server_available()
        if not available:
            self.memory_service._embeddings_enabled = False
        manager = self.container.get_embedding_process_manager()
        self.logger.log(
            "embedding_runtime",
            started=False,
            available=available,
            disabled_for_benchmark=not available,
            runtime=manager.runtime_status(),
        )

    async def _embedding_server_available(self) -> bool:
        url = self.container.settings.embedding_server_url.rstrip("/") + "/models"
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                response = await client.get(url)
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def _provider_health(self) -> dict[str, Any]:
        try:
            backend = self.container.get_llm_backend(self.provider)
            status = _sanitize_provider_status(await backend.health_check())
            catalog = await backend.list_models(capability="reasoning_chat")
            ids = [item.get("id") for item in catalog.get("data", [])]
            return {
                "status": status,
                "model_available": self.model in ids,
                "reasoning_chat_models": ids[:30],
            }
        except Exception as exc:
            return {"status": {"status": "unhealthy", "error": str(exc)}}

    async def _run_topic_session(self, topic: ScaleTopic) -> SessionResult:
        artifact_path = f"docs/scale-runs/{topic.topic_id}-session.md"
        session = SessionResult(
            topic_id=topic.topic_id,
            title=topic.title,
            conversation_id=None,
            artifact_path=artifact_path,
        )
        if self.dry_run:
            session.conversation_id = f"dry-run-{topic.topic_id}"
            session.status = "skipped"
            await self.memory_service.capture_turn_summary(
                project_slug=self.project_slug,
                workspace_root=str(self.worktree),
                conversation_id=session.conversation_id,
                summary=topic_document(topic),
                metadata={"benchmark": "gpt_oss_scale", "topic_id": topic.topic_id, "dry_run": True},
            )
            self.logger.log("session_result", result=asdict(session))
            return session

        initial = await self._run_turn_with_retries(
            topic=topic,
            phase="initial",
            conversation_id=None,
            message=initial_prompt(topic, self.worktree, artifact_path),
        )
        session.conversation_id = initial[0]
        session.turns.append(initial[1])

        for followup_index in range(self.followups_per_session):
            if not session.conversation_id:
                break
            followup = await self._run_turn_with_retries(
                topic=topic,
                phase=f"followup_{followup_index + 1}",
                conversation_id=session.conversation_id,
                message=followup_prompt(topic, self.worktree, artifact_path, followup_index),
            )
            session.conversation_id = followup[0] or session.conversation_id
            session.turns.append(followup[1])

        session.status = "completed" if session.turns and all(turn.status == "completed" for turn in session.turns) else "partial"
        self.logger.log("session_result", result=asdict(session))
        return session

    async def _run_topic_sessions(self) -> list[SessionResult]:
        if self.concurrency <= 1:
            sessions: list[SessionResult] = []
            for topic in self.topics:
                result = await self._run_topic_session(topic)
                sessions.append(result)
                self._write_partial_results(sessions, [])
            return sessions

        sessions_by_topic: dict[str, SessionResult] = {}
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(topic: ScaleTopic) -> SessionResult:
            async with semaphore:
                return await self._run_topic_session(topic)

        tasks = [asyncio.create_task(run_one(topic)) for topic in self.topics]
        for completed in asyncio.as_completed(tasks):
            result = await completed
            sessions_by_topic[result.topic_id] = result
            ordered = [
                sessions_by_topic[topic.topic_id]
                for topic in self.topics
                if topic.topic_id in sessions_by_topic
            ]
            self._write_partial_results(ordered, [])
        return [
            sessions_by_topic[topic.topic_id]
            for topic in self.topics
            if topic.topic_id in sessions_by_topic
        ]

    async def _run_turn_with_retries(
        self,
        *,
        topic: ScaleTopic,
        phase: str,
        conversation_id: str | None,
        message: str,
    ) -> tuple[str | None, TurnResult]:
        last_conversation_id = conversation_id
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            if attempt > 1:
                wait_seconds = min(90, 10 * attempt)
                self.logger.log("turn_retry_wait", topic_id=topic.topic_id, phase=phase, attempt=attempt, wait_seconds=wait_seconds)
                await asyncio.sleep(wait_seconds)
            await self.rate_limiter.wait()
            next_conversation_id, result = await self._run_turn(
                topic=topic,
                phase=phase,
                conversation_id=last_conversation_id,
                message=message,
                attempt=attempt,
            )
            last_conversation_id = next_conversation_id or last_conversation_id
            if result.status == "completed":
                return last_conversation_id, result
            if not _looks_retryable(result.failure):
                return last_conversation_id, result
        return last_conversation_id, result

    async def _run_turn(
        self,
        *,
        topic: ScaleTopic,
        phase: str,
        conversation_id: str | None,
        message: str,
        attempt: int,
    ) -> tuple[str | None, TurnResult]:
        started = time.perf_counter()
        content_chars = 0
        reasoning_chars = 0
        tool_events = 0
        tool_results = 0
        finish_reason: str | None = None
        active_conversation_id = conversation_id
        failure: str | None = None
        self.logger.log(
            "turn_started",
            topic_id=topic.topic_id,
            phase=phase,
            attempt=attempt,
            conversation_id=conversation_id,
            prompt_preview=message[:2_000],
        )
        try:
            async with AsyncSessionLocal() as session:
                use_case = self._create_use_case(session)
                request = ChatRequestDTO(
                    conversation_id=UUID(conversation_id) if conversation_id else None,
                    message=message,
                    stream=True,
                    temperature=0.2,
                    max_tokens=self.max_tokens,
                    provider=self.provider,
                    model=self.model,
                    prompt_mode="exploring",
                    reasoning_level="medium",
                    reasoning_budget_tokens=2048,
                    tools_enabled=True,
                    allowed_tools=["Glob", "Grep", "Read", "Write", "Edit", "TodoWrite"],
                    tool_context={
                        "workspace_root": str(self.worktree),
                        "cwd": str(self.worktree),
                        "allowed_roots": [str(self.worktree)],
                    },
                    max_tool_iterations=self.max_tool_iterations,
                    metadata={
                        "benchmark": "gpt_oss_120b_memory_scale",
                        "topic_id": topic.topic_id,
                        "phase": phase,
                    },
                )
                async for chunk in use_case.execute_stream(request):
                    metadata = dict(chunk.metadata)
                    event = str(metadata.get("event") or "")
                    if event == "conversation" and metadata.get("conversation_id"):
                        active_conversation_id = str(metadata["conversation_id"])
                    if chunk.content:
                        content_chars += len(chunk.content)
                    if chunk.reasoning_content:
                        reasoning_chars += len(chunk.reasoning_content)
                    if event.startswith("tool_") or metadata.get("tool_name"):
                        tool_events += 1
                        if metadata.get("tool_result") is not None:
                            tool_results += 1
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
                    self.logger.log(
                        "agent_stream",
                        topic_id=topic.topic_id,
                        phase=phase,
                        stream_event=event or None,
                        content_chars=len(chunk.content or ""),
                        reasoning_chars=len(chunk.reasoning_content or ""),
                        metadata=_compact_metadata(metadata),
                    )
        except Exception as exc:
            failure = str(exc)
            self.logger.log("turn_failed", topic_id=topic.topic_id, phase=phase, attempt=attempt, error=failure)

        status = "failed" if failure else "completed"
        result = TurnResult(
            phase=phase,
            status=status,
            latency_ms=int((time.perf_counter() - started) * 1000),
            content_chars=content_chars,
            reasoning_chars=reasoning_chars,
            tool_events=tool_events,
            tool_results=tool_results,
            finish_reason=finish_reason,
            failure=failure,
        )
        self.logger.log(
            "turn_result",
            topic_id=topic.topic_id,
            conversation_id=active_conversation_id,
            result=asdict(result),
        )
        return active_conversation_id, result

    def _create_use_case(self, session: AsyncSession) -> ChatCompletionUseCase:
        llm_backend = self.container.get_llm_backend(self.provider)
        return ChatCompletionUseCase(
            conversation_repo=PostgresConversationRepository(session),
            llm_backend=llm_backend,
            tool_registry=self.container.get_tool_registry(),
            tool_runtime_config=self.container.get_tool_runtime_config(),
            build_context_use_case=self.container.create_build_context_use_case(str(self.worktree)),
            prompt_builder=self.container.get_prompt_builder(),
            prompt_context_analyzer=self.container.create_prompt_context_analyzer(llm_backend),
            command_registry=self.container.create_command_registry(),
            session_memory_service=self.container.create_session_memory_service(llm_backend),
            next_step_suggestion_service=None,
            session_title_service=getattr(self.container, "get_session_title_service", lambda: None)(),
            recall_memory_use_case=None,
            memory_repository=self.container.get_memory_repository(),
            operational_memory_service=self.memory_service,
            context_window_tokens=self.context_window_tokens,
            default_output_tokens=self.max_tokens,
        )

    async def _run_recall_probes(self, sessions: list[SessionResult]) -> list[RecallProbeResult]:
        probes: list[RecallProbeResult] = []
        candidates = [session for session in sessions if session.conversation_id]
        if not candidates:
            return probes
        for index, session in enumerate(candidates[: self.recall_probe_count]):
            topic = self.topics[index % len(self.topics)]
            scenario = ["conversation_scoped", "workspace_project", "file_path", "latest_active", "relation"][index % 5]
            query, kwargs = self._probe_query(topic, session, scenario)
            package = await self.memory_service.recall_package_for_prompt(
                project_slug=self.project_slug,
                query=query,
                provider=self.provider,
                model=self.model,
                top_k=8,
                context_window_tokens=self.context_window_tokens,
                **kwargs,
            )
            payload = self._memory_package_payload(package)
            recall_text = _recall_items_text(payload)
            hit = topic.canary.lower() in recall_text or topic.topic_id.lower() in recall_text
            leakage_hint = scenario == "conversation_scoped" and any(
                other.topic_id.lower() in recall_text
                for other in self.topics
                if other.topic_id != topic.topic_id
            )
            result = RecallProbeResult(
                probe_id=f"probe-{index + 1:03d}",
                scenario=scenario,
                topic_id=topic.topic_id,
                latency_ms=package.latency_ms,
                items=len(package.items),
                budget_used=package.budget_used,
                omitted_count=package.omitted_count,
                hit=hit,
                leakage_hint=leakage_hint,
            )
            probes.append(result)
            self.logger.log(
                "recall_probe",
                result=asdict(result),
                query=query,
                filters=kwargs,
                package=payload,
            )
        return probes

    def _probe_query(
        self,
        topic: ScaleTopic,
        session: SessionResult,
        scenario: str,
    ) -> tuple[str, dict[str, Any]]:
        base = (
            f"{PROJECT_KEY} recall memory for {topic.topic_id} {topic.title}. "
            f"Find canary {topic.canary}, decision {topic.decision}, and validation {topic.validation}."
        )
        if scenario == "conversation_scoped":
            return base, {
                "conversation_id": session.conversation_id,
                "workspace_root": str(self.worktree),
                "active_only": True,
            }
        if scenario == "file_path":
            return f"{base} Use the generated artifact path {session.artifact_path}.", {
                "workspace_root": str(self.worktree),
                "file_paths": [session.artifact_path],
                "active_only": True,
            }
        if scenario == "latest_active":
            return f"{base} Return latest active state and avoid superseded decisions.", {
                "workspace_root": str(self.worktree),
                "latest_only": True,
                "active_only": True,
            }
        if scenario == "relation":
            return f"{base} Relate this topic to: {topic.relation}.", {
                "workspace_root": str(self.worktree),
                "active_only": True,
            }
        return base, {"workspace_root": str(self.worktree), "active_only": True}

    def _memory_package_payload(self, package: Any) -> dict[str, Any]:
        return {
            "latency_ms": package.latency_ms,
            "budget_tokens": package.budget_tokens,
            "budget_used": package.budget_used,
            "omitted_count": package.omitted_count,
            "filters_applied": package.filters_applied,
            "formatted_preview": package.formatted[:4_000],
            "items": [
                {
                    "type": item.type.value,
                    "summary": item.summary,
                    "evidence": item.evidence,
                    "paths": item.paths,
                    "source_ids": item.source_ids,
                    "score": item.score,
                    "status": item.status,
                    "event_types": item.event_types,
                }
                for item in package.items
            ],
        }

    def _write_partial_results(
        self,
        sessions: list[SessionResult],
        probes: list[RecallProbeResult],
    ) -> None:
        (self.run_dir / "results.json").write_text(
            json.dumps(
                {
                    "sessions": [asdict(session) for session in sessions],
                    "recall_probes": [asdict(probe) for probe in probes],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_report(
        self,
        sessions: list[SessionResult],
        probes: list[RecallProbeResult],
        health: dict[str, Any],
    ) -> None:
        self._write_partial_results(sessions, probes)
        completed_sessions = [session for session in sessions if session.status == "completed"]
        failed_turns = [
            turn
            for session in sessions
            for turn in session.turns
            if turn.status != "completed"
        ]
        total_turns = sum(len(session.turns) for session in sessions)
        total_tool_results = sum(turn.tool_results for session in sessions for turn in session.turns)
        hit_count = sum(1 for probe in probes if probe.hit)
        leakage_count = sum(1 for probe in probes if probe.leakage_hint)
        avg_latency = round(sum(probe.latency_ms for probe in probes) / len(probes), 2) if probes else 0
        lines = [
            f"# GPT OSS 120B Memory Scale Benchmark - {PROJECT_NAME}",
            "",
            f"- Run: `{self.run_id}`",
            f"- Project key: `{PROJECT_KEY}`",
            f"- Provider/model: `{self.provider}/{self.model}`",
            f"- Worktree: `{self.worktree}`",
            f"- Project slug: `{self.project_slug}`",
            f"- Stream log: `{self.logger.path}`",
            f"- Sessions requested: `{self.session_count}`",
            f"- Follow-ups per session: `{self.followups_per_session}`",
            f"- RPM limit: `{self.rpm_limit}`",
            f"- Max tool iterations requested: `{self.max_tool_iterations}`",
            f"- Concurrency: `{self.concurrency}`",
            "",
            "## Summary",
            "",
            f"- Completed sessions: `{len(completed_sessions)}/{len(sessions)}`",
            f"- Total model turns: `{total_turns}`",
            f"- Tool results observed: `{total_tool_results}`",
            f"- Failed turns: `{len(failed_turns)}`",
            f"- Recall probes: `{len(probes)}`",
            f"- Recall hit rate: `{hit_count}/{len(probes) if probes else 0}`",
            f"- Conversation-scoped leakage hints: `{leakage_count}`",
            f"- Recall average latency: `{avg_latency} ms`",
            "",
            "## Provider Health",
            "",
            "```json",
            json.dumps(health, ensure_ascii=False, indent=2, default=str),
            "```",
            "",
            "## Sessions",
            "",
            "| Topic | Status | Conversation | Turns | Tool results | Artifact |",
            "|---|---|---|---:|---:|---|",
        ]
        for session in sessions:
            lines.append(
                "| "
                + " | ".join(
                    [
                        session.topic_id,
                        session.status,
                        session.conversation_id or "-",
                        str(len(session.turns)),
                        str(sum(turn.tool_results for turn in session.turns)),
                        session.artifact_path,
                    ]
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "## Recall Probes",
                "",
                "| Probe | Scenario | Topic | Latency ms | Items | Budget | Hit | Leakage hint |",
                "|---|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for probe in probes:
            lines.append(
                "| "
                + " | ".join(
                    [
                        probe.probe_id,
                        probe.scenario,
                        probe.topic_id,
                        str(probe.latency_ms),
                        str(probe.items),
                        str(probe.budget_used),
                        "yes" if probe.hit else "no",
                        "yes" if probe.leakage_hint else "no",
                    ]
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "## Direct Analysis",
                "",
                self._direct_analysis(sessions, probes),
            ]
        )
        (self.run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    def _direct_analysis(
        self,
        sessions: list[SessionResult],
        probes: list[RecallProbeResult],
    ) -> str:
        if not sessions:
            return "No sessions ran."
        completed = sum(1 for session in sessions if session.status == "completed")
        hit_count = sum(1 for probe in probes if probe.hit)
        leakage_count = sum(1 for probe in probes if probe.leakage_hint)
        return (
            f"GPT OSS 120B completed {completed}/{len(sessions)} sessions. "
            f"Recall hit {hit_count}/{len(probes)} probes with {leakage_count} scoped leakage hints. "
            "The important measurement is not only whether ANN retrieves something fast; it is "
            "whether conversation-scoped recall returns the right canary without importing adjacent "
            "session state. Project-wide recall should intentionally connect related topics, while "
            "conversation/file-path probes should be narrow. Any leakage hint in those scoped probes "
            "is a candidate bug for long-session agent work."
        )

    def _has_commit(self, root: Path) -> bool:
        return self._run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, check=False).returncode == 0

    def _run(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=False,
        )
        self.logger.log(
            "command",
            cwd=str(cwd),
            command=cmd,
            returncode=result.returncode,
            stdout=result.stdout[-4_000:],
            stderr=result.stderr[-4_000:],
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
        return result


def build_topics() -> list[ScaleTopic]:
    blueprints = [
        ("context-budget-ledger", "Context Budget Ledger", "memory budgeting", "Agents need deterministic context allocation across raw context, structured memory, tools, and final answer reserve.", "Reserve 3 percent of context for operational memory and enforce layer quotas before prompt assembly.", "paired with retrieval packaging and prompt surface telemetry", "Verify prompt metadata records budget used, injected items, omitted items, and evidence caps.", ("context budget", "layer quota", "prompt metadata")),
        ("structured-ingestion-layers", "Structured Ingestion Layers", "memory ingestion", "Raw tool chunks are too noisy for direct model injection in long sessions.", "Derive facts, decisions, latest state, file state, command results, and error solutions during ingestion.", "paired with backfill taxonomy and active/latest status", "Verify prompt context contains structured summaries instead of raw chunks.", ("structured memory", "fact", "decision")),
        ("ann-prefilter-contract", "ANN Prefilter Contract", "vector retrieval", "Project-wide ANN over all embeddings returns semantically close but operationally wrong sessions.", "Apply project, workspace, conversation, session, source type, file path, temporal, active, and latest filters before ANN.", "paired with leakage probes and project-wide recall", "Verify conversation-scoped queries do not return adjacent topic canaries.", ("ANN", "prefilter", "conversation_id")),
        ("latest-state-register", "Latest State Register", "state management", "Long sessions accumulate superseded plans and stale facts.", "Store active/latest state separately and mark superseded decisions inactive before recall.", "paired with temporal windows and decision lifecycle", "Verify latest_only ignores superseded state while project recall can audit history.", ("latest state", "superseded", "active")),
        ("evidence-caps", "Evidence Caps", "prompt packaging", "Large evidence snippets silently consume context and crowd out decisions.", "Limit evidence per item to 350 characters and prefer source ids plus paths over full body text.", "paired with context budget ledger and citation integrity", "Verify each returned item contains short evidence and stable source ids.", ("evidence", "source ids", "350 characters")),
        ("tool-result-normalization", "Tool Result Normalization", "tool memory", "Tool outputs arrive as heterogeneous blobs from shell, read, write, browser, and MCP tools.", "Normalize tool results into command_result, file_state, error_solution, and fact records.", "paired with structured ingestion layers and UI trace rendering", "Verify Read/Write/Edit results produce path-aware structured items.", ("tool result", "file state", "command result")),
        ("agent-trace-visibility", "Agent Trace Visibility", "frontend runtime", "Persisted assistant tool-call messages with no content produce blank agent shells.", "Suppress non-streaming empty assistant shells and keep live streaming shells visible before the first chunk.", "paired with reasoning/output separation and persisted history cleanup", "Verify empty persisted assistant messages do not render PersonAgent headings.", ("agent trace", "empty assistant", "streaming shell")),
        ("reasoning-output-split", "Reasoning Output Split", "adapter contract", "Some providers mix thinking tags, reasoning_content, content, and tool-call deltas.", "Normalize reasoning into reasoning blocks and visible content into answer blocks without promoting one into the other.", "paired with model adapters and UI stream ordering", "Verify reasoning tokens do not become final visible answer text.", ("reasoning_content", "visible content", "thinking tags")),
        ("provider-rate-governor", "Provider Rate Governor", "provider operations", "NVIDIA NIM rate limits can interrupt large benchmark runs around 40 RPM.", "Throttle requests below the provider ceiling and log wait intervals, retries, and retryable failures.", "paired with long-session benchmark and provider health", "Verify benchmark logs contain rate_limit_wait and retry events when needed.", ("NVIDIA", "rate limit", "RPM")),
        ("conversation-scope-canaries", "Conversation Scope Canaries", "evaluation", "Recall quality is hard to measure when topics are similar.", "Embed deterministic per-topic canaries and score probes by canary and topic-id hits.", "paired with ANN prefilter contract and relation probes", "Verify scoped probes hit only the expected canary.", ("canary", "recall probe", "topic id")),
        ("workspace-root-partition", "Workspace Root Partition", "storage partitioning", "Worktrees for the same repo can contaminate each other's operational memory.", "Treat workspace_root as a first-class filter and persist it on every event and structured item.", "paired with project_slug and file-path filters", "Verify scale worktree recall excludes previous multi-model worktrees unless project-wide mode asks for them.", ("workspace_root", "worktree", "partition")),
        ("file-path-recall", "File Path Recall", "file memory", "Agents often ask about the latest state of one file rather than the whole project.", "Index file paths on structured items and support file_path filters before ANN.", "paired with Write/Edit tool normalization and artifact probes", "Verify recall by docs/scale-runs artifact returns the matching topic.", ("file_path", "artifact", "file state")),
        ("session-summary-rollup", "Session Summary Rollup", "summarization", "Long conversations exceed prompt context before the agent finishes the task.", "Generate session summaries after turns and store them as a separate structured layer.", "paired with turn capture and latest state register", "Verify summaries preserve decisions, risks, and validation tasks without raw transcript replay.", ("session summary", "rollup", "long conversation")),
        ("temporal-recall-window", "Temporal Recall Window", "time filtering", "Older decisions may be correct historically but wrong for current execution.", "Expose created_after and created_before filters and combine them with active/latest flags.", "paired with latest state register and audit mode", "Verify temporal probes can isolate recent follow-up turns.", ("temporal window", "created_after", "created_before")),
        ("cross-agent-handoff", "Cross-Agent Handoff", "multi-agent coordination", "Parallel agents need shared state but not every private scratchpad from other agents.", "Use project-wide recall for handoffs and scoped recall for execution details.", "paired with blackboard summaries and role-scoped prompts", "Verify relation probes return adjacent decisions while scoped probes stay narrow.", ("handoff", "project-wide", "scoped recall")),
        ("blackboard-memory", "Blackboard Memory", "coordination state", "Team Mode needs durable coordination state across rounds and resumptions.", "Persist claims, decisions, blockers, coverage, and tool evidence as structured memory.", "paired with cross-agent handoff and trace visibility", "Verify blackboard facts can be recalled without replaying every agent delta.", ("blackboard", "claims", "coverage")),
        ("command-result-index", "Command Result Index", "tool evidence", "Shell command outputs contain decisive facts but are expensive to replay.", "Convert command exits, stdout summaries, stderr, and cwd into command_result items.", "paired with tool-result normalization and evidence caps", "Verify command_result recall returns status and short output evidence.", ("command_result", "stderr", "cwd")),
        ("error-solution-bank", "Error Solution Bank", "debug memory", "Repeated failures are rediscovered when fixes are not indexed semantically.", "Store error signatures and successful solution attempts in an error_solution layer.", "paired with command result index and latest state register", "Verify a query for a known error returns the latest successful fix.", ("error_solution", "failure", "fix")),
        ("decision-lifecycle", "Decision Lifecycle", "governance", "Decisions must be active, superseded, or rejected instead of flat notes.", "Persist decision status and prefer active decisions in prompt recall.", "paired with latest state register and audit history", "Verify project-wide audit can show superseded decisions but prompt default cannot.", ("decision", "active", "superseded")),
        ("memory-prompt-metadata", "Memory Prompt Metadata", "observability", "A model-visible prompt without recall metadata cannot be debugged.", "Record memory_budget_tokens, memory_budget_used, injected item count, and omitted count on prompt metadata.", "paired with context budget ledger and benchmark logs", "Verify prompt_context chunks include memory metadata.", ("memory metadata", "budget_used", "omitted_count")),
        ("provider-adapter-catalog", "Provider Adapter Catalog", "provider routing", "Model catalog availability and direct execution can disagree.", "Log catalog status separately from execution health and classify provider 400s by model contract.", "paired with Vertex hardening and NVIDIA rate governance", "Verify benchmark report separates model_available from turn execution status.", ("model catalog", "provider 400", "execution health")),
        ("sse-stream-order", "SSE Stream Order", "frontend streaming", "Tool, reasoning, image, and content chunks lose meaning if grouped by type after the fact.", "Preserve stream order with parts that reference reasoning blocks, tool blocks, images, and content.", "paired with agent trace visibility and reasoning split", "Verify UI displays tool calls in the order the model produced them.", ("SSE", "stream order", "parts")),
        ("tool-loop-limit", "Tool Loop Limit", "agent runtime", "Long benchmark tasks may need many model-tool cycles.", "Keep a conservative default but allow explicit runs to request up to 60 tool iterations.", "paired with provider rate governor and task prompts", "Verify explicit max_tool_iterations above 20 is accepted and logged.", ("tool loop", "max_tool_iterations", "hard cap")),
        ("db-only-ranking", "DB Only Ranking", "database retrieval", "Loading 4096-d embeddings into Python during recall adds avoidable latency.", "Return chunk ids, structured content, metadata, and vector distance directly from PostgreSQL.", "paired with ANN prefilter contract and candidate limits", "Verify recall path does not materialize embeddings in Python.", ("pgvector", "DB ranking", "embedding")),
        ("candidate-limit-policy", "Candidate Limit Policy", "retrieval tuning", "Huge candidate pools make rerank latency unpredictable.", "Default semantic candidates to 80, recent candidates to 40, and final top_k to 6.", "paired with DB-only ranking and context budget", "Verify logs expose semantic_candidate_limit and recent_candidate_limit.", ("candidate limit", "top_k", "recent")),
        ("raw-chunk-audit-mode", "Raw Chunk Audit Mode", "auditability", "Raw chunks are necessary for debugging but dangerous as default prompt input.", "Keep raw chunks persisted for audit and backfill, but exclude them from prompt recall by default.", "paired with structured ingestion and evidence caps", "Verify include_raw_chunks is false in normal recall payloads.", ("raw chunk", "audit", "include_raw_chunks")),
        ("backfill-taxonomy", "Backfill Taxonomy", "migration", "Existing operational events need structured records without blocking startup.", "Run backfill as a job over events and chunks to derive structured memory layers.", "paired with structured ingestion and session summary rollup", "Verify backfill creates structured items for existing events.", ("backfill", "structured item", "migration")),
        ("retrieval-package-contract", "Retrieval Package Contract", "API contract", "Prompt injection needs a stable package, not an arbitrary list of chunks.", "Return formatted context, structured items, applied filters, budget used, omitted count, and latency.", "paired with memory prompt metadata and benchmark logging", "Verify /operational/recall and internal recall_package expose the same fields.", ("retrieval package", "filters_applied", "latency_ms")),
        ("active-session-router", "Active Session Router", "session routing", "A user may switch workspaces while async requests are still resolving.", "Pass conversation_id and workspace_root from the active request through recall and tool context.", "paired with workspace partition and UI session mapping", "Verify stale workspace panel data does not affect memory recall.", ("active session", "conversation_id", "workspace_root")),
        ("memory-quality-score", "Memory Quality Score", "evaluation", "Latency alone says nothing about whether memory changed the model's work.", "Score influence from final content and changed file artifacts, not only stream text.", "paired with changed_file_snapshot and canary probes", "Verify generated artifact text includes retrieved anchors.", ("influence score", "changed file", "artifact")),
        ("artifact-snapshot-log", "Artifact Snapshot Log", "benchmark evidence", "Tool-created docs may contain the real answer while final stream text is short.", "Read changed files after each run and log bounded excerpts for influence analysis.", "paired with memory-quality-score and agent trace visibility", "Verify JSONL contains changed_file_snapshot events.", ("artifact snapshot", "changed_file_snapshot", "evidence")),
        ("conversation-followup-probe", "Conversation Follow-up Probe", "long session testing", "Single-turn benchmarks do not test whether memory persists across a session.", "Run follow-up turns in the same conversation and ask for previous canaries and decisions.", "paired with session summary rollup and temporal recall", "Verify follow-up turns can reference initial topic state.", ("follow-up", "same conversation", "canary")),
        ("synthetic-distractor-bank", "Synthetic Distractor Bank", "evaluation dataset", "Related topics create false positives unless distractors are intentional.", "Use 50 related topics with distinct canaries and overlapping vocabulary.", "paired with conversation-scope canaries and leakage probes", "Verify scoped probes resist distractors.", ("distractor", "overlap", "false positive")),
        ("source-type-filter", "Source Type Filter", "retrieval filters", "A task may need only file states or only command results.", "Expose source_type filters and map operational event types to structured memory types.", "paired with tool normalization and command result index", "Verify source_type probes exclude unrelated summaries.", ("source_type", "event type", "structured type")),
        ("memory-latency-envelope", "Memory Latency Envelope", "performance", "Recall must stay below model-visible interaction latency at scale.", "Track DB-only and end-to-end recall latencies separately in benchmark logs.", "paired with provider rate governor and DB ranking", "Verify p50/p95 are computed by scenario.", ("latency", "p50", "p95")),
        ("embedding-context-fallback", "Embedding Context Fallback", "embedding runtime", "A 32K embedding target may fail on 8GB GPUs.", "Expose target_ctx_size, actual_ctx_size, fallback_used, and startup_error.", "paired with benchmark labels and hardware capacity", "Verify reports label fallback runs as 8K when actual_ctx_size is 8192.", ("embedding ctx", "fallback", "actual_ctx_size")),
        ("project-slug-isolation", "Project Slug Isolation", "tenant partitioning", "Two repos with similar docs should not share memory unless explicitly requested.", "Make project_slug mandatory on recall and persistence.", "paired with workspace-root partition and multi-tenant storage", "Verify recall cannot run without project_slug.", ("project_slug", "tenant", "isolation")),
        ("file-state-currentness", "File State Currentness", "code awareness", "Agents need the latest file state, not every edit history chunk.", "Persist latest file_state per path and mark older edits superseded.", "paired with file-path recall and latest state register", "Verify a file query returns the newest artifact section.", ("file_state", "current", "path")),
        ("tool-error-ui-feedback", "Tool Error UI Feedback", "frontend diagnostics", "Tool errors must be visible but not dominate successful context.", "Render failed tool rows with concise error text and keep detailed output collapsible.", "paired with agent trace visibility and error-solution bank", "Verify failed tool events create visible rows and memory error_solution items.", ("tool error", "UI feedback", "collapsible")),
        ("mcp-resource-memory", "MCP Resource Memory", "external context", "MCP resource reads can become important session state.", "Capture MCP resource URI, server, and summarized content as structured facts.", "paired with source-type filter and audit mode", "Verify MCP facts cite server and URI.", ("MCP", "resource", "URI")),
        ("security-redaction-boundary", "Security Redaction Boundary", "safety", "Operational memory may capture secrets from tool output or config files.", "Redact sensitive keys before event capture, embedding, logging, or prompt formatting.", "paired with raw chunk audit mode and provider data boundary", "Verify API keys never appear in JSONL benchmark logs.", ("redaction", "secret", "provider boundary")),
        ("prompt-surface-ledger", "Prompt Surface Ledger", "prompt architecture", "Large agent prompts need traceability of dynamic sections and commands.", "Record prompt_sections_used, prompt_surfaces_used, dynamic_sections_used, and provider boundary.", "paired with memory prompt metadata and command context", "Verify prompt preview exposes section and surface counts.", ("prompt surface", "dynamic section", "ledger")),
        ("command-context-attachments", "Command Context Attachments", "composer context", "User-invoked commands should inject structured context without changing visible text.", "Attach command_context and file annotations as structured prompt attachments.", "paired with prompt surface ledger and memory filters", "Verify context_attachments metadata survives request/resume paths.", ("context attachment", "command_context", "annotation")),
        ("session-title-backfill", "Session Title Backfill", "session UX", "Long benchmark runs create many sessions that need unique titles.", "Use LLM titles with deterministic fallback and uniqueness repair.", "paired with conversation persistence and session panel refresh", "Verify 50 saved sessions have distinct usable titles.", ("session title", "backfill", "unique")),
        ("recall-debug-endpoint", "Recall Debug Endpoint", "API diagnostics", "Operators need to inspect exact memory items returned for a query.", "Expose recall preview with formatted context, items, filters, budget, omitted count, and latency.", "paired with retrieval package contract and benchmark JSONL", "Verify endpoint and script logs agree on filters_applied.", ("debug endpoint", "preview", "items")),
        ("memory-capacity-planning", "Memory Capacity Planning", "scale planning", "50 sessions times 1M context can create thousands of chunks and distractors.", "Partition before ANN, derive structured layers, cap candidates, and benchmark recall envelopes.", "paired with memory latency envelope and synthetic distractor bank", "Verify candidate count does not grow linearly with total chunks.", ("capacity", "1M context", "partition")),
        ("quality-gate-rubric", "Quality Gate Rubric", "evaluation", "Recall can be fast and still harmful if it injects stale or conflicting facts.", "Gate memory by hit, leakage, active/latest correctness, source ids, and model artifact influence.", "paired with memory quality score and decision lifecycle", "Verify report separates performance, precision, and influence.", ("quality gate", "leakage", "influence")),
        ("agent-task-contract", "Agent Task Contract", "agent orchestration", "Parallel agents need explicit role, scope, deliverable, and memory expectations.", "Write each agent task with project key, topic id, required tools, artifact path, and canary.", "paired with conversation follow-up and artifact snapshot log", "Verify every session prompt contains structured task fields.", ("agent task", "artifact path", "required tools")),
        ("long-context-resume", "Long Context Resume", "session continuity", "Very long sessions need compact resume points rather than full transcript replay.", "Use session summaries plus latest state and artifact paths as resume anchors.", "paired with session summary rollup and context budget ledger", "Verify follow-up prompts retrieve resume anchors before editing artifacts.", ("resume", "long context", "anchor")),
        ("retrieval-conflict-resolution", "Retrieval Conflict Resolution", "semantic precision", "Related sessions can contain conflicting decisions about the same subsystem.", "Prefer scoped active/latest decisions and surface conflicts only in project-wide analysis mode.", "paired with decision lifecycle and cross-agent handoff", "Verify scoped recall does not merge conflicting adjacent decisions.", ("conflict", "scoped", "project-wide")),
    ]
    topics: list[ScaleTopic] = []
    for index, blueprint in enumerate(blueprints, start=1):
        slug, title, layer, problem, decision, relation, validation, terms = blueprint
        topic_id = f"T{index:03d}-{slug}"
        canary = f"{PROJECT_KEY}-CANARY-{index:03d}"
        topics.append(
            ScaleTopic(
                index=index,
                topic_id=topic_id,
                title=title,
                layer=layer,
                problem=problem,
                decision=decision,
                relation=relation,
                validation=validation,
                canary=canary,
                terms=terms,
            )
        )
    return topics


def topic_document(topic: ScaleTopic) -> str:
    return f"""# {topic.title}

Project: {PROJECT_NAME}
Project key: {PROJECT_KEY}
Topic id: {topic.topic_id}
Layer: {topic.layer}
Canary: {topic.canary}

## Problem
{topic.problem}

## Decision
{topic.decision}

## Related Context
{topic.relation}.

## Validation Target
{topic.validation}

## Retrieval Anchors
- {topic.terms[0]}
- {topic.terms[1]}
- {topic.terms[2]}
- {topic.canary}
"""


def initial_prompt(topic: ScaleTopic, worktree: Path, artifact_path: str) -> str:
    return f"""# GPT OSS 120B Memory Scale Session

You are running inside PersonAgent as a benchmark agent for {PROJECT_NAME}.

Structured task:
- project_key: {PROJECT_KEY}
- topic_id: {topic.topic_id}
- title: {topic.title}
- layer: {topic.layer}
- canary: {topic.canary}
- worktree: {worktree}
- topic_doc: docs/scale-topics/{topic.topic_id}.md
- artifact_path: {artifact_path}

You must use tools and perform multiple concrete actions:
1. Use Glob to inspect docs/scale-topics.
2. Use Read on docs/scale-topics/{topic.topic_id}.md.
3. Create or overwrite {artifact_path} with a precise design note.
4. The artifact must include sections: Problem, Decision, Memory Retrieval Contract, Failure Mode, Validation Query, and Canary.
5. Include the exact canary {topic.canary} and the exact project key {PROJECT_KEY}.

Content requirements:
- Explain why this topic matters for long agent sessions.
- Preserve the decision: {topic.decision}
- Relate it to: {topic.relation}
- Add one validation query that future recall probes should ask.

Do not ask for clarification. Keep the final chat answer concise and list the artifact path and memory facts you used.
"""


def followup_prompt(topic: ScaleTopic, worktree: Path, artifact_path: str, index: int) -> str:
    return f"""# Follow-up Retrieval Turn {index + 1}

Continue the same saved session for {PROJECT_KEY}.

Topic:
- topic_id: {topic.topic_id}
- title: {topic.title}
- canary: {topic.canary}
- worktree: {worktree}
- artifact_path: {artifact_path}

Use tools again:
1. Grep for {topic.canary}.
2. Read {artifact_path}.
3. Update {artifact_path} by adding a section named "Follow-up Retrieval Note {index + 1}".

The new section must:
- Restate the canary {topic.canary}.
- Explain how this topic should be retrieved in a future conversation-scoped query.
- Name one related topic: {topic.relation}.
- State one risk if project-wide recall is used when conversation-scoped recall was required.

Final answer: one short paragraph with the file path, whether the canary was found, and the recall scenario this session now tests.
"""


def _sanitize_provider_status(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"account_id", "email", "auth_path", "api_key", "token"}:
                sanitized[key] = "[redacted]"
            else:
                sanitized[key] = _sanitize_provider_status(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_provider_status(item) for item in value]
    return value


def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compact = dict(metadata)
    for key in ("tool_result", "tool_data", "tool_input"):
        if key in compact:
            compact[key] = _truncate(compact[key], 2_000)
    return compact


def _recall_items_text(payload: dict[str, Any]) -> str:
    item_texts: list[str] = [str(payload.get("formatted_preview") or "")]
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_texts.append(str(item.get("summary") or ""))
        item_texts.extend(str(evidence) for evidence in item.get("evidence") or [])
        item_texts.extend(str(path) for path in item.get("paths") or [])
    return "\n".join(item_texts).lower()


def _truncate(value: Any, limit: int) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _looks_retryable(error: str | None) -> bool:
    if not error:
        return False
    lowered = error.lower()
    return "429" in lowered or "rate" in lowered or "timeout" in lowered or "temporar" in lowered


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--session-count", type=int, default=50)
    parser.add_argument("--followups-per-session", type=int, default=1)
    parser.add_argument("--rpm-limit", type=int, default=35)
    parser.add_argument("--max-tool-iterations", type=int, default=40)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--context-window-tokens", type=int, default=1_048_576)
    parser.add_argument("--recall-probe-count", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--start-embedding", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


async def main() -> None:
    args = parse_args()
    benchmark = GptOss120bMemoryScaleBenchmark(
        repo_url=args.repo_url,
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        session_count=args.session_count,
        followups_per_session=args.followups_per_session,
        rpm_limit=args.rpm_limit,
        max_tool_iterations=args.max_tool_iterations,
        max_tokens=args.max_tokens,
        context_window_tokens=args.context_window_tokens,
        recall_probe_count=args.recall_probe_count,
        concurrency=args.concurrency,
        dry_run=args.dry_run,
        start_embedding=args.start_embedding,
        retries=args.retries,
    )
    sessions, probes = await benchmark.run()
    completed = sum(1 for session in sessions if session.status == "completed")
    hits = sum(1 for probe in probes if probe.hit)
    print(f"Sessions: {completed}/{len(sessions)} completed")
    print(f"Recall probes: {hits}/{len(probes)} hit")
    print(f"Report: {benchmark.run_dir / 'report.md'}")
    print(f"JSONL: {benchmark.logger.path}")


if __name__ == "__main__":
    asyncio.run(main())
