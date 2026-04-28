"""Live agentic benchmark for structured operational memory.

Run from ``@backend``:

    uv run python scripts/agentic_memory_benchmark.py \
        --repo-url https://github.com/levygit837-cyber/test-repo.git \
        --repo-root /home/levybonito/Projetos/test-repo \
        --target-context-tokens 120000

The script intentionally logs memory recall payloads, stream events, tool
activity, repo inventory, and a direct qualitative evaluation. It is designed
for live provider runs, but every provider failure is kept as benchmark data
instead of aborting the whole run.
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
from uuid import uuid4

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
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "@backend" / ".benchmarks" / "agentic_memory"
DEFAULT_REPO_URL = "https://github.com/levygit837-cyber/test-repo.git"
DEFAULT_REPO_ROOT = Path.home() / "Projetos" / "test-repo"
PROJECT_NAME = "AegisOps Control Plane"
PROJECT_KEY = "AEGISOPS-MEMORY-BENCH"


@dataclass(frozen=True, slots=True)
class AgentSpec:
    slug: str
    label: str
    provider: str
    model: str
    role: str
    branch: str
    worktree_name: str
    context_window_tokens: int
    expected_terms: tuple[str, ...]
    task_focus: str


@dataclass(slots=True)
class AgentRunResult:
    slug: str
    label: str
    provider: str
    model: str
    status: str
    conversation_id: str | None
    latency_ms: int
    content_chars: int
    reasoning_chars: int
    tool_events: int
    tool_results: int
    changed_files: list[str] = field(default_factory=list)
    changed_file_chars: int = 0
    memory_latency_ms: int | None = None
    memory_items: int = 0
    memory_budget_used: int = 0
    coherence_score: float = 0.0
    influence_score: float = 0.0
    failure: str | None = None


class JsonlLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")

    def log(self, event: str, **payload: Any) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            **payload,
        }
        self._file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class AgenticMemoryBenchmark:
    def __init__(
        self,
        *,
        repo_url: str,
        repo_root: Path,
        output_dir: Path,
        target_context_tokens: int,
        sessions_per_agent: int,
        max_agent_turns: int,
        start_embedding: bool,
        live_models: bool,
    ) -> None:
        self.repo_url = repo_url
        self.repo_root = repo_root.expanduser().resolve()
        self.output_dir = output_dir
        self.target_context_tokens = max(8_000, target_context_tokens)
        self.sessions_per_agent = max(1, sessions_per_agent)
        self.max_agent_turns = max(1, min(20, max_agent_turns))
        self.start_embedding = start_embedding
        self.live_models = live_models
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.run_dir = self.output_dir / self.run_id
        self.logger = JsonlLogger(self.run_dir / "agentic_memory_stream.jsonl")
        self.container = get_container()
        self.memory_service = self.container.get_operational_memory_service()
        if self.memory_service is None:
            raise RuntimeError("Operational memory is disabled")
        self.project_slug = project_slug_from_workspace(str(self.repo_root))
        self.agents = self._agent_specs()

    async def run(self) -> list[AgentRunResult]:
        try:
            await init_db()
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.logger.log(
                "benchmark_started",
                project=PROJECT_NAME,
                repo_url=self.repo_url,
                repo_root=str(self.repo_root),
                project_slug=self.project_slug,
                target_context_tokens=self.target_context_tokens,
                sessions_per_agent=self.sessions_per_agent,
            )
            self._prepare_repo()
            worktrees = self._prepare_worktrees()
            inventory = self._repo_inventory(self.repo_root)
            self.logger.log("repo_inventory", root=str(self.repo_root), inventory=inventory)
            await self._prepare_embedding_runtime()
            await self._seed_operational_memory(worktrees, inventory)
            health = await self._provider_health()
            self.logger.log("provider_health", health=health)

            tasks = [
                self._run_agent(agent, worktrees[agent.slug], health.get(agent.slug, {}))
                for agent in self.agents
            ]
            results = await asyncio.gather(*tasks)
            await self._run_cross_agent_memory_queries(results)
            self._write_report(results, health, inventory, worktrees)
            self.logger.log("benchmark_finished", report=str(self.run_dir / "report.md"))
            return results
        finally:
            if self.start_embedding:
                self.container.get_embedding_process_manager().stop()
            self.logger.close()

    def _agent_specs(self) -> list[AgentSpec]:
        return [
            AgentSpec(
                slug="gpt54-mini",
                label="GPT 5.4-Mini",
                provider="codex",
                model="gpt-5.4-mini",
                role="Architecture and contracts lead",
                branch="codex/bench-gpt54-mini",
                worktree_name="test-repo-gpt54-mini",
                context_window_tokens=self.container.settings.codex_context_window,
                expected_terms=("ADR", "bounded context", "event contract", PROJECT_KEY),
                task_focus=(
                    "define the architecture contract, ADRs, module boundaries, "
                    "and repo conventions for AegisOps."
                ),
            ),
            AgentSpec(
                slug="gemini31-pro",
                label="Gemini-3.1-pro-preview",
                provider="vertex",
                model="gemini-3.1-pro-preview",
                role="Backend data plane lead",
                branch="codex/bench-gemini31-pro",
                worktree_name="test-repo-gemini31-pro",
                context_window_tokens=self.container.settings.vertex_context_window,
                expected_terms=("FastAPI", "SSE", "outbox", PROJECT_KEY),
                task_focus=(
                    "design backend ingestion APIs, SSE event streaming, and "
                    "PostgreSQL outbox behavior."
                ),
            ),
            AgentSpec(
                slug="kimi-k26",
                label="Kimi K2.6",
                provider="kimi",
                model=self.container.settings.kimi_default_model,
                role="Product workflow and frontend lead",
                branch="codex/bench-kimi-k26",
                worktree_name="test-repo-kimi-k26",
                context_window_tokens=self.container.settings.kimi_context_window,
                expected_terms=("React", "incident console", "X-Request-Fingerprint", PROJECT_KEY),
                task_focus=(
                    "design the operator workflow, React incident console, and "
                    "client idempotency behavior."
                ),
            ),
            AgentSpec(
                slug="deepseek-v4-flash",
                label="DeepSeek-V4-flash",
                provider="deepseek",
                model="deepseek-v4-flash",
                role="Reliability and evaluation lead",
                branch="codex/bench-deepseek-v4-flash",
                worktree_name="test-repo-deepseek-v4-flash",
                context_window_tokens=self.container.settings.deepseek_context_window,
                expected_terms=("benchmark", "reliability", "memory recall", PROJECT_KEY),
                task_focus=(
                    "design reliability checks, memory benchmark probes, and "
                    "failure-mode analysis."
                ),
            ),
        ]

    def _prepare_repo(self) -> None:
        if not self.repo_root.exists():
            self._run(["git", "clone", self.repo_url, str(self.repo_root)], cwd=PROJECT_ROOT)
        self._run(["git", "checkout", "-B", "main"], cwd=self.repo_root, check=False)
        if not self._has_commit(self.repo_root):
            (self.repo_root / "README.md").write_text(
                f"# {PROJECT_NAME}\n\nSeed repository for {PROJECT_KEY}.\n",
                encoding="utf-8",
            )
            (self.repo_root / "docs").mkdir(exist_ok=True)
            (self.repo_root / "docs" / "project-brief.md").write_text(
                self._project_brief(),
                encoding="utf-8",
            )
            self._run(["git", "add", "README.md", "docs/project-brief.md"], cwd=self.repo_root)
            self._run(
                [
                    "git",
                    "-c",
                    "user.name=PersonAgent Benchmark",
                    "-c",
                    "user.email=bench@personagent.local",
                    "commit",
                    "-m",
                    "Initial AegisOps benchmark scaffold",
                ],
                cwd=self.repo_root,
            )
        else:
            brief = self.repo_root / "docs" / "project-brief.md"
            if not brief.exists():
                brief.parent.mkdir(exist_ok=True)
                brief.write_text(self._project_brief(), encoding="utf-8")
                self._run(["git", "add", str(brief.relative_to(self.repo_root))], cwd=self.repo_root)
                self._run(
                    [
                        "git",
                        "-c",
                        "user.name=PersonAgent Benchmark",
                        "-c",
                        "user.email=bench@personagent.local",
                        "commit",
                        "-m",
                        "Add AegisOps benchmark brief",
                    ],
                    cwd=self.repo_root,
                    check=False,
                )

    def _prepare_worktrees(self) -> dict[str, Path]:
        worktrees: dict[str, Path] = {}
        for agent in self.agents:
            path = self.repo_root.parent / agent.worktree_name
            if not path.exists():
                self._run(
                    ["git", "worktree", "add", "-B", agent.branch, str(path), "main"],
                    cwd=self.repo_root,
                )
            worktrees[agent.slug] = path.resolve()
            self.logger.log(
                "worktree_ready",
                agent=agent.slug,
                branch=agent.branch,
                path=str(path.resolve()),
            )
        return worktrees

    async def _start_embedding_server(self) -> None:
        manager = self.container.get_embedding_process_manager()
        started = await manager.start()
        self.logger.log(
            "embedding_runtime",
            started=started,
            runtime=manager.runtime_status(),
        )

    async def _prepare_embedding_runtime(self) -> None:
        if self.start_embedding:
            await self._start_embedding_server()
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

    async def _provider_health(self) -> dict[str, dict[str, Any]]:
        health: dict[str, dict[str, Any]] = {}
        for agent in self.agents:
            try:
                backend = self.container.get_llm_backend(agent.provider)
                status = _sanitize_provider_status(await backend.health_check())
                catalog = await backend.list_models(capability="reasoning_chat")
                ids = [item.get("id") for item in catalog.get("data", [])]
                health[agent.slug] = {
                    "status": status,
                    "model_available": agent.model in ids or agent.provider == "kimi",
                    "reasoning_chat_models": ids[:20],
                }
            except Exception as exc:
                health[agent.slug] = {"status": {"status": "unhealthy", "error": str(exc)}}
        return health

    async def _seed_operational_memory(
        self,
        worktrees: dict[str, Path],
        inventory: dict[str, Any],
    ) -> None:
        base_summary = self._project_brief()
        await self.memory_service.capture_turn_summary(
            project_slug=self.project_slug,
            workspace_root=str(self.repo_root),
            conversation_id=str(uuid4()),
            summary=base_summary,
            metadata={"benchmark": "agentic_memory", "kind": "project_brief"},
        )
        for agent in self.agents:
            await self._seed_agent_memory(agent, worktrees[agent.slug], inventory)
        result = await self.memory_service.backfill_structured_memory(self.project_slug, limit=50_000)
        self.logger.log("structured_backfill", result=result)

    async def _seed_agent_memory(
        self,
        agent: AgentSpec,
        worktree: Path,
        inventory: dict[str, Any],
    ) -> None:
        capped_target = min(self.target_context_tokens, max(8_000, agent.context_window_tokens - 8_000))
        chars_per_session = max(4_000, int((capped_target * 4) / self.sessions_per_agent))
        for index in range(self.sessions_per_agent):
            conversation_id = str(uuid4())
            marker = self._agent_marker(agent, index)
            summary = self._long_memory_payload(
                agent=agent,
                marker=marker,
                worktree=worktree,
                inventory=inventory,
                target_chars=chars_per_session,
            )
            await self.memory_service.capture_turn_summary(
                project_slug=self.project_slug,
                workspace_root=str(self.repo_root),
                conversation_id=conversation_id,
                summary=summary,
                metadata={
                    "benchmark": "agentic_memory",
                    "agent": agent.slug,
                    "session_index": index,
                    "target_context_tokens": capped_target,
                    "worktree": str(worktree),
                    "marker": marker,
                },
            )
        self.logger.log(
            "agent_memory_seeded",
            agent=agent.slug,
            context_window_tokens=agent.context_window_tokens,
            requested_context_tokens=self.target_context_tokens,
            capped_target_tokens=capped_target,
            sessions=self.sessions_per_agent,
        )

    async def _run_agent(
        self,
        agent: AgentSpec,
        worktree: Path,
        health: dict[str, Any],
    ) -> AgentRunResult:
        started = time.perf_counter()
        pre_query = self._dynamic_memory_query(agent)
        memory_package = await self.memory_service.recall_package_for_prompt(
            project_slug=self.project_slug,
            query=pre_query,
            provider=agent.provider,
            model=agent.model,
            workspace_root=str(self.repo_root),
            top_k=8,
            context_window_tokens=agent.context_window_tokens,
        )
        self.logger.log(
            "memory_query",
            agent=agent.slug,
            phase="pre_agent",
            query=pre_query,
            package=self._memory_package_payload(memory_package),
        )

        if not self.live_models:
            return self._skipped_result(
                agent,
                started,
                "live model execution disabled",
                memory_package=memory_package,
            )
        if str((health.get("status") or {}).get("status")) != "healthy":
            return self._skipped_result(
                agent,
                started,
                "provider health is not healthy",
                memory_package=memory_package,
            )

        conversation_id: str | None = None
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_events = 0
        tool_results = 0
        failure: str | None = None
        try:
            async with AsyncSessionLocal() as session:
                use_case = self._create_use_case(
                    session=session,
                    provider=agent.provider,
                    workspace_root=worktree,
                    context_window_tokens=agent.context_window_tokens,
                )
                request = ChatRequestDTO(
                    message=self._agent_prompt(agent, worktree, memory_package.formatted),
                    stream=True,
                    temperature=0.2,
                    max_tokens=4096,
                    provider=agent.provider,
                    model=agent.model,
                    prompt_mode="exploring",
                    reasoning_level="medium",
                    tools_enabled=True,
                    allowed_tools=["Glob", "Grep", "Read", "Write", "Edit", "TodoWrite"],
                    tool_context={
                        "workspace_root": str(worktree),
                        "cwd": str(worktree),
                        "allowed_roots": [str(worktree)],
                    },
                    max_tool_iterations=self.max_agent_turns,
                )
                async for chunk in use_case.execute_stream(request):
                    metadata = dict(chunk.metadata)
                    event = str(metadata.get("event") or "")
                    if event == "conversation":
                        conversation_id = str(metadata.get("conversation_id") or "")
                    if chunk.content:
                        content_parts.append(chunk.content)
                    if chunk.reasoning_content:
                        reasoning_parts.append(chunk.reasoning_content)
                    if event.startswith("tool_") or metadata.get("tool_name"):
                        tool_events += 1
                        if metadata.get("tool_result") is not None:
                            tool_results += 1
                    self.logger.log(
                        "agent_stream",
                        agent=agent.slug,
                        stream_event=event or None,
                        content_chars=len(chunk.content or ""),
                        reasoning_chars=len(chunk.reasoning_content or ""),
                        metadata=_compact_metadata(metadata),
                    )
        except Exception as exc:
            failure = str(exc)
            self.logger.log("agent_failed", agent=agent.slug, error=failure)

        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        changed_files = self._changed_files(worktree)
        changed_file_text = self._changed_file_text(worktree, changed_files)
        self.logger.log(
            "changed_file_snapshot",
            agent=agent.slug,
            worktree=str(worktree),
            changed_files=changed_files,
            chars=len(changed_file_text),
            excerpt=changed_file_text[:8_000],
        )
        post_package = await self.memory_service.recall_package_for_prompt(
            project_slug=self.project_slug,
            query=self._post_agent_memory_query(agent, changed_files, content, changed_file_text),
            provider=agent.provider,
            model=agent.model,
            workspace_root=str(self.repo_root),
            conversation_id=conversation_id,
            top_k=8,
            context_window_tokens=agent.context_window_tokens,
        )
        self.logger.log(
            "memory_query",
            agent=agent.slug,
            phase="post_agent",
            query=self._post_agent_memory_query(agent, changed_files, content, changed_file_text),
            package=self._memory_package_payload(post_package),
        )
        coherence = self._coherence_score(agent, content, changed_files, changed_file_text)
        influence = self._influence_score(
            agent,
            content,
            memory_package.formatted,
            changed_files,
            changed_file_text,
        )
        result = AgentRunResult(
            slug=agent.slug,
            label=agent.label,
            provider=agent.provider,
            model=agent.model,
            status="failed" if failure else "completed",
            conversation_id=conversation_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            content_chars=len(content),
            reasoning_chars=len(reasoning),
            tool_events=tool_events,
            tool_results=tool_results,
            changed_files=changed_files,
            changed_file_chars=len(changed_file_text),
            memory_latency_ms=memory_package.latency_ms,
            memory_items=len(memory_package.items),
            memory_budget_used=memory_package.budget_used,
            coherence_score=coherence,
            influence_score=influence,
            failure=failure,
        )
        self.logger.log("agent_result", result=asdict(result))
        return result

    async def _run_cross_agent_memory_queries(self, results: list[AgentRunResult]) -> None:
        queries = [
            "Quais decisões ativas do AegisOps conectam ADR, SSE, outbox e idempotência?",
            "Recupere o estado mais recente por agente e cite caminhos de arquivos criados.",
            "Quais conflitos ou lacunas apareceram entre backend, frontend e confiabilidade?",
            "Qual evidência mostra influência real da memória estruturada nas respostas?",
        ]
        for query in queries:
            package = await self.memory_service.recall_package_for_prompt(
                project_slug=self.project_slug,
                query=f"{query} {PROJECT_KEY}",
                workspace_root=str(self.repo_root),
                latest_only=False,
                top_k=10,
                context_window_tokens=1_048_576,
            )
            self.logger.log(
                "memory_query",
                agent="cross_agent",
                phase="analysis",
                query=query,
                package=self._memory_package_payload(package),
            )

    def _create_use_case(
        self,
        *,
        session: AsyncSession,
        provider: str,
        workspace_root: Path,
        context_window_tokens: int,
    ) -> ChatCompletionUseCase:
        llm_backend = self.container.get_llm_backend(provider)
        return ChatCompletionUseCase(
            conversation_repo=PostgresConversationRepository(session),
            llm_backend=llm_backend,
            tool_registry=self.container.get_tool_registry(),
            tool_runtime_config=self.container.get_tool_runtime_config(),
            build_context_use_case=self.container.create_build_context_use_case(str(workspace_root)),
            prompt_builder=self.container.get_prompt_builder(),
            prompt_context_analyzer=self.container.create_prompt_context_analyzer(llm_backend),
            command_registry=self.container.create_command_registry(),
            session_memory_service=self.container.create_session_memory_service(llm_backend),
            next_step_suggestion_service=None,
            session_title_service=getattr(self.container, "get_session_title_service", lambda: None)(),
            recall_memory_use_case=None,
            memory_repository=self.container.get_memory_repository(),
            operational_memory_service=self.memory_service,
            context_window_tokens=context_window_tokens,
            default_output_tokens=4096,
        )

    def _skipped_result(
        self,
        agent: AgentSpec,
        started: float,
        reason: str,
        *,
        memory_package: Any | None = None,
    ) -> AgentRunResult:
        result = AgentRunResult(
            slug=agent.slug,
            label=agent.label,
            provider=agent.provider,
            model=agent.model,
            status="skipped",
            conversation_id=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            content_chars=0,
            reasoning_chars=0,
            tool_events=0,
            tool_results=0,
            memory_latency_ms=getattr(memory_package, "latency_ms", None),
            memory_items=len(getattr(memory_package, "items", []) or []),
            memory_budget_used=getattr(memory_package, "budget_used", 0) or 0,
            failure=reason,
        )
        self.logger.log("agent_result", result=asdict(result))
        return result

    def _agent_prompt(
        self,
        agent: AgentSpec,
        worktree: Path,
        formatted_memory: str,
    ) -> str:
        return f"""
You are the {agent.role} for {PROJECT_NAME}.

Project key: {PROJECT_KEY}
Worktree: {worktree}
Branch: {agent.branch}
Focus: {agent.task_focus}

You must use the available backend tools. First inspect the repository with Glob/Read/Grep.
Then create or update at least one concrete project artifact inside your worktree. Keep
your edits scoped to your role. Do not ask for clarification.

Memory retrieved before this run:
{formatted_memory or "(no structured memory returned)"}

Deliver:
1. A concise summary of what you inspected.
2. Files you created or changed.
3. The memory facts or decisions that influenced you.
4. Gaps another agent should handle.
""".strip()

    def _project_brief(self) -> str:
        return f"""
{PROJECT_NAME} / {PROJECT_KEY}

Build a multi-tenant incident-intelligence platform for agentic operations teams.
The platform coordinates event ingestion, incident triage, policy-aware escalation,
SSE streaming, idempotent mutation APIs, and benchmark evidence for AI memory.

Hard contracts:
- Backend must expose FastAPI-style APIs and document SSE event streaming.
- Mutations use X-Request-Fingerprint for idempotency.
- Durable workflow state uses PostgreSQL outbox, not an in-memory queue.
- Frontend has an incident console with active/latest operational state.
- Reliability work must benchmark memory recall latency, precision, and influence.
""".strip()

    def _long_memory_payload(
        self,
        *,
        agent: AgentSpec,
        marker: str,
        worktree: Path,
        inventory: dict[str, Any],
        target_chars: int,
    ) -> str:
        base = f"""
{PROJECT_KEY} memory seed for {agent.label}.
Role: {agent.role}.
Worktree: {worktree}.
Marker: {marker}.
Focus: {agent.task_focus}.
Repo inventory files: {inventory.get("file_count")}; directories: {inventory.get("dir_count")}.
Required anchors: {", ".join(agent.expected_terms)}.
Active decision: PostgreSQL outbox is active; in-memory queue is superseded.
Latest state: every agent must preserve X-Request-Fingerprint and SSE contracts.
Early canary {marker}-EARLY: architecture boundary and project charter are stable.
Mid canary {marker}-MID: role-specific work must cite retrieved memory.
Late canary {marker}-LATE: do not invent another product name or repo.
""".strip()
        filler = (
            f"\n{PROJECT_KEY} {agent.slug} operational filler: "
            "retrieval must prefer structured facts, decisions, latest state, "
            "session summaries, file state, command results, and evidence snippets. "
            "Distractor projects must not override AegisOps. "
        )
        chunks = [base]
        while len("\n".join(chunks)) < target_chars:
            chunks.append(filler)
        return "\n".join(chunks)[:target_chars]

    def _dynamic_memory_query(self, agent: AgentSpec) -> str:
        return (
            f"{PROJECT_KEY} {agent.role} {agent.task_focus} "
            f"{' '.join(agent.expected_terms)} active latest decisions worktree"
        )

    def _post_agent_memory_query(
        self,
        agent: AgentSpec,
        changed_files: list[str],
        content: str,
        changed_file_text: str,
    ) -> str:
        return (
            f"{PROJECT_KEY} {agent.role} changed files {' '.join(changed_files[:12])} "
            f"{content[:500]} {changed_file_text[:500]}"
        )

    def _agent_marker(self, agent: AgentSpec, index: int) -> str:
        return f"{PROJECT_KEY}-{agent.slug.upper()}-S{index:03d}"

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

    def _coherence_score(
        self,
        agent: AgentSpec,
        content: str,
        changed_files: list[str],
        changed_file_text: str,
    ) -> float:
        score = 0.0
        text = f"{content}\n{' '.join(changed_files)}\n{changed_file_text}".lower()
        if PROJECT_KEY.lower() in text:
            score += 1.0
        if any(term.lower() in text for term in agent.expected_terms):
            score += 1.0
        if changed_files:
            score += 1.0
        if agent.role.split()[0].lower() in text or agent.task_focus.split()[0].lower() in text:
            score += 1.0
        if "aegisops" in text and "different project" not in text:
            score += 1.0
        return round(score / 5.0, 3)

    def _influence_score(
        self,
        agent: AgentSpec,
        content: str,
        formatted_memory: str,
        changed_files: list[str],
        changed_file_text: str,
    ) -> float:
        combined = " ".join([content, " ".join(changed_files), changed_file_text]).lower()
        memory_text = formatted_memory.lower()
        anchors = [term.lower() for term in agent.expected_terms if term.lower() in memory_text]
        if not anchors:
            return 0.0
        hits = sum(1 for term in anchors if term in combined)
        return round(hits / len(anchors), 3)

    def _changed_files(self, worktree: Path) -> list[str]:
        result = self._run(["git", "status", "--short"], cwd=worktree, check=False)
        files: list[str] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            path = line[3:].strip()
            if " -> " in path:
                path = path.rsplit(" -> ", maxsplit=1)[-1].strip()
            files.append(path)
        return files

    def _changed_file_text(self, worktree: Path, changed_files: list[str]) -> str:
        chunks: list[str] = []
        remaining = 32_000
        for relative in changed_files:
            if remaining <= 0:
                break
            path = (worktree / relative).resolve()
            try:
                path.relative_to(worktree.resolve())
            except ValueError:
                continue
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            snippet = text[: min(len(text), remaining)]
            chunks.append(f"\n--- {relative} ---\n{snippet}")
            remaining -= len(snippet)
        return "".join(chunks)

    def _repo_inventory(self, root: Path) -> dict[str, Any]:
        files = [
            path
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ]
        dirs = [
            path
            for path in root.rglob("*")
            if path.is_dir() and ".git" not in path.parts
        ]
        return {
            "file_count": len(files),
            "dir_count": len(dirs),
            "sample_files": [str(path.relative_to(root)) for path in files[:50]],
            "git_status": self._run(["git", "status", "--short"], cwd=root, check=False).stdout,
        }

    def _write_report(
        self,
        results: list[AgentRunResult],
        health: dict[str, dict[str, Any]],
        inventory: dict[str, Any],
        worktrees: dict[str, Path],
    ) -> None:
        report = self.run_dir / "report.md"
        lines = [
            f"# Agentic Memory Benchmark - {PROJECT_NAME}",
            "",
            f"- Run: `{self.run_id}`",
            f"- Project slug: `{self.project_slug}`",
            f"- Repo: `{self.repo_root}`",
            f"- Stream log: `{self.logger.path}`",
            f"- Target context tokens requested per agent: `{self.target_context_tokens}`",
            f"- Sessions seeded per agent: `{self.sessions_per_agent}`",
            f"- Repo files before agents: `{inventory.get('file_count')}`",
            "",
            "## Agent Results",
            "",
            "| Agent | Provider | Model | Status | Latency ms | Memory ms | Items | Coherence | Influence | Tool results | Artifact chars | Changed files |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for result in results:
            lines.append(
                "| "
                + " | ".join(
                    [
                        result.label,
                        result.provider,
                        result.model,
                        result.status,
                        str(result.latency_ms),
                        str(result.memory_latency_ms),
                        str(result.memory_items),
                        f"{result.coherence_score:.3f}",
                        f"{result.influence_score:.3f}",
                        str(result.tool_results),
                        str(result.changed_file_chars),
                        ", ".join(result.changed_files[:8]) or "-",
                    ]
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "## Provider Health",
                "",
                "```json",
                json.dumps(health, ensure_ascii=False, indent=2, default=str),
                "```",
                "",
                "## Worktrees",
                "",
            ]
        )
        for agent in self.agents:
            lines.append(f"- `{agent.label}`: `{worktrees[agent.slug]}` on `{agent.branch}`")
        lines.extend(
            [
                "",
                "## Direct Analysis",
                "",
                self._direct_analysis(results),
                "",
                "## Memory Log Contract",
                "",
                (
                    "Every `memory_query` JSONL event contains the exact query, "
                    "`filters_applied`, budget, omitted count, latency, formatted prompt "
                    "preview, and structured items with type/summary/evidence/paths/source ids/score."
                ),
            ]
        )
        report.write_text("\n".join(lines), encoding="utf-8")
        (self.run_dir / "results.json").write_text(
            json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _direct_analysis(self, results: list[AgentRunResult]) -> str:
        completed = [result for result in results if result.status == "completed"]
        if not completed:
            return (
                "No live agent completed. This is still useful: the memory layer can be "
                "benchmarked independently, but model influence cannot be judged without "
                "successful provider execution."
            )
        avg_coherence = sum(result.coherence_score for result in completed) / len(completed)
        avg_influence = sum(result.influence_score for result in completed) / len(completed)
        return (
            f"Completed agents: {len(completed)}/{len(results)}. "
            f"Average coherence: {avg_coherence:.3f}. "
            f"Average memory influence: {avg_influence:.3f}. "
            "My judgment: structured operational memory is most valuable when it "
            "surfaces durable contracts, current decisions, and file state before "
            "tool use. It reduces repeated rediscovery and lets each model enter a "
            "large project with a shared operational state. The risk is over-injection: "
            "if filters are too broad or old decisions are not marked latest/superseded, "
            "models will confidently follow stale context. The benchmark therefore "
            "treats latency and relevance as necessary but not sufficient; influence "
            "must be visible in model actions and changed files."
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


def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compact = dict(metadata)
    for key in ("tool_result", "tool_data", "tool_input"):
        if key in compact:
            compact[key] = _truncate(compact[key], 2_000)
    return compact


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


def _truncate(value: Any, limit: int) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-context-tokens", type=int, default=120_000)
    parser.add_argument("--sessions-per-agent", type=int, default=6)
    parser.add_argument("--max-agent-turns", type=int, default=8)
    parser.add_argument("--no-start-embedding", action="store_true")
    parser.add_argument("--dry-run-models", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


async def main() -> None:
    args = parse_args()
    benchmark = AgenticMemoryBenchmark(
        repo_url=args.repo_url,
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        target_context_tokens=args.target_context_tokens,
        sessions_per_agent=args.sessions_per_agent,
        max_agent_turns=args.max_agent_turns,
        start_embedding=not args.no_start_embedding,
        live_models=not args.dry_run_models,
    )
    results = await benchmark.run()
    for result in results:
        print(
            f"{result.label}: {result.status} coherence={result.coherence_score:.3f} "
            f"influence={result.influence_score:.3f} changed={len(result.changed_files)}"
        )
    print(f"Report: {benchmark.run_dir / 'report.md'}")
    print(f"JSONL: {benchmark.logger.path}")


if __name__ == "__main__":
    asyncio.run(main())
