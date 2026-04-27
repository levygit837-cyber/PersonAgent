"""Benchmark Team Mode cooperation, latency, and coordinator steering."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from personagent.application.team_chat import (
    TeamChatOrchestrator,
    TeamChatRequest,
    default_team_config,
)
from personagent.application.tools import ToolRegistry, ToolRuntimeConfig
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.infrastructure.config.settings import Settings
from personagent.infrastructure.llm.nvidia_nim_adapter import NvidiaNimAdapter
from personagent.infrastructure.tools import create_read_file_tool, create_write_file_tool

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "@backend" / ".benchmarks" / "team_mode_v3"
DEFAULT_MODEL = "openai/gpt-oss-120b"
BENCHMARK_FIXTURE_DIR = PROJECT_ROOT / "@backend" / ".benchmarks" / "team_mode_v3" / "fixtures"

TARGETS = {
    "first_event_ms": 2000,
    "first_token_ms": 15000,
    "tokens_per_s": 30.0,
    "standard_wall_ms": 180_000,
    "complex_wall_ms": 300_000,
    "vote_overhead_ratio": 0.25,
    "independent_overlap": 0.35,
    "overlap_reduction": 0.40,
    "coherency_score": 0.65,
    "coverage_ratio": 0.75,
    "duplicate_claim_ratio": 0.25,
    "quality_score": 80.0,
}

SYSTEM_PROMPT = (
    "Voce esta avaliando Team Mode V3. Responda em portugues, com objetividade tecnica. "
    "Cada agente deve contribuir com uma perspectiva distinta e evitar repetir outros agentes. "
    "Publique claim_graph com claims, evidence, blockers, proposals, risks, coverage e coherency_score. "
    "O Coordinator deve atuar como autoridade de fluxo, reduzir duplicacao, cobrir a matriz e sintetizar evidencias."
)


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    name: str
    messages: tuple[str, ...]
    expected_terms: tuple[str, ...]
    complex: bool = False
    multi_turn: bool = False
    requires_tools: bool = False
    requires_overlap_reduction: bool = False
    requires_memory_recall: bool = False
    min_expected_term_ratio: float = 0.4
    min_coverage_ratio: float = 0.75
    enforce_vote_overhead: bool = True


@dataclass(frozen=True, slots=True)
class RunAnalysis:
    scenario_id: str
    scenario_name: str
    turn_index: int
    status: str
    wall_ms: int
    first_event_ms: int | None
    final_chars: int
    final_excerpt: str
    agent_turn_count: int
    avg_first_token_ms: float | None
    avg_agent_tps: float
    min_agent_tps: float
    vote_overhead_ratio: float
    independent_overlap: float | None
    debate_overlap: float | None
    overlap_reduction: float | None
    coordinator_assignment_coverage: float
    coordinator_unique_focus_ratio: float
    tool_context_valid: bool
    claim_graph_nodes: int
    duplicate_claim_ratio: float
    coverage_ratio: float
    avg_coherency_score: float
    adaptive_vote_count: int
    tool_phase_count: int
    tool_result_count: int
    tool_proposal_count: int
    tool_audit_agent_count: int
    tool_latency_ms: int
    workspace_memory_present: bool
    expected_term_hits: int
    expected_term_total: int
    estimated_output_tokens: int
    hard_gate_failures: list[str]
    scores: dict[str, float]
    score: float
    verdict: str


@dataclass(frozen=True, slots=True)
class SingleAgentAnalysis:
    scenario_id: str
    scenario_name: str
    turn_index: int
    status: str
    wall_ms: int
    first_token_ms: int | None
    tokens_per_second: float
    estimated_output_tokens: int
    expected_term_hits: int
    expected_term_total: int
    quality_score: float
    final_chars: int
    final_excerpt: str


SCENARIOS = (
    Scenario(
        id="architecture_complex",
        name="Complex architecture and tradeoffs",
        complex=True,
        expected_terms=("blackboard", "latencia", "coordinator", "votacao", "ferramentas"),
        messages=(
            "Analise uma evolucao do Team Mode para resolver tarefas complexas de codigo. "
            "Inclua arquitetura, latencia, Blackboard, votacao espacada, tool guardrails, "
            "riscos e plano de validacao.",
        ),
    ),
    Scenario(
        id="multi_perspective_incident",
        name="Multi-perspective incident diagnosis",
        complex=True,
        expected_terms=("duplicacao", "latencia", "evidencia", "blocker", "coordenacao"),
        messages=(
            "O Team Mode esta lento e os agentes parecem repetir a mesma linha de pensamento. "
            "Diagnostique causas provaveis em backend, prompts, persistencia, UI e modelo. "
            "Proponha acoes priorizadas com criterio de sucesso.",
        ),
    ),
    Scenario(
        id="tool_governance",
        name="Tool context and guarded autonomy",
        expected_terms=("agent_id", "tool_context", "consenso", "destrutiva", "auditoria"),
        messages=(
            "Desenhe uma politica para multiplos agentes usarem ferramentas em paralelo: "
            "leitura autonoma, escrita/destruicao apenas com consenso, auditoria por agent_id, "
            "round e phase, e como lidar com conflitos.",
        ),
    ),
    Scenario(
        id="multi_turn_memory",
        name="Multi-turn continuity",
        multi_turn=True,
        expected_terms=("180", "custo", "destrutiva", "restricoes", "turno"),
        messages=(
            "Contexto para o proximo turno: o cliente exige resposta abaixo de 180 segundos, "
            "baixo custo operacional e nenhuma acao destrutiva sem aprovacao explicita.",
            "Agora, usando as restricoes anteriores, proponha o plano de execucao do time "
            "e a estrategia de validacao multi-agente.",
        ),
    ),
    Scenario(
        id="duplicate_redirect",
        name="Duplicate answer detection and Coordinator redirect",
        requires_overlap_reduction=True,
        expected_terms=("claim_graph", "duplicacao", "coerencia", "coverage", "coordinator"),
        messages=(
            "Force uma avaliacao de cooperacao: quatro agentes tendem a repetir a mesma resposta. "
            "Explique como o Coordinator deve detectar duplicacao no claim_graph, redirecionar focos, "
            "avaliar coerencia e garantir coverage matrix antes da resposta final.",
        ),
    ),
    Scenario(
        id="conflict_resolution",
        name="Contradictory constraints and useful conflict",
        complex=True,
        expected_terms=("conflito", "tradeoff", "risco", "decisao", "evidencia"),
        messages=(
            "Resolva um conflito de requisitos: o produto quer maxima velocidade, seguranca estrita, "
            "baixo custo e auditoria completa. Os agentes devem expor tradeoffs, contradicoes, riscos "
            "e uma decisao final coerente com evidencias.",
        ),
    ),
    Scenario(
        id="tool_read_write_audit",
        name="Real read tool plus blocked mutation proposal",
        requires_tools=True,
        expected_terms=("Read", "Write", "proposal", "agent_id", "auditoria"),
        messages=(
            "Use ferramentas para validar o arquivo de fixture do benchmark: execute Read em "
            "{fixture_path}. Depois proponha, mas nao execute, "
            "uma escrita Write em {mutating_path}. "
            "A resposta deve auditar agent_id, phase, tool_result e proposal.",
        ),
    ),
    Scenario(
        id="coverage_gap_redirect",
        name="Coordinator recovers low coverage",
        requires_overlap_reduction=True,
        expected_terms=("lacuna", "coverage", "redirecionar", "matriz", "criterio"),
        messages=(
            "A equipe recebeu uma pergunta ampla e pode ignorar areas importantes. Avalie como o Coordinator "
            "detecta lacunas de coverage matrix, redireciona agentes para subproblemas faltantes e impede uma "
            "resposta final antes da cobertura minima.",
        ),
    ),
    Scenario(
        id="evidence_grounding",
        name="Evidence-grounded claims versus unsupported opinions",
        expected_terms=("evidencia", "claim", "assumption", "risco", "grounding"),
        messages=(
            "Compare uma resposta baseada em opinioes com uma resposta baseada em evidencias. O time deve "
            "marcar claims, assumptions e risks, rejeitar afirmacoes sem evidencia e produzir uma sintese grounded.",
        ),
    ),
    Scenario(
        id="latency_vote_skip",
        name="Latency-sensitive answer with skipped debate",
        expected_terms=("latencia", "skip", "voto", "cobertura", "final"),
        messages=(
            "Responda uma tarefa simples que deve ser concluida com baixa latencia. O Team Mode deve evitar "
            "debate completo quando a cobertura estiver pronta, votar apenas na rodada final e explicar a decisao.",
        ),
    ),
    Scenario(
        id="memory_contamination_guard",
        name="Workspace memory relevance and contamination guard",
        multi_turn=True,
        requires_memory_recall=True,
        expected_terms=("memoria", "relevancia", "contaminacao", "snapshot", "decisao"),
        messages=(
            "Memoria relevante: no projeto X foi decidido que ferramentas destrutivas exigem aprovacao do Coordinator. "
            "Memoria irrelevante: no projeto Y a UI usa tema roxo. Guarde apenas a decisao relevante para governanca.",
            "Agora use a memoria relevante para definir a politica de execucao de ferramentas, evitando contaminar "
            "a resposta com detalhes irrelevantes do tema visual.",
        ),
    ),
)


class MemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}

    async def create(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        return list(self.conversations.values())[offset : offset + limit]

    async def update(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def delete(self, conversation_id: UUID) -> bool:
        return self.conversations.pop(conversation_id, None) is not None

    async def search(self, query: str, limit: int = 10) -> list[Conversation]:
        return [
            conversation
            for conversation in self.conversations.values()
            if query.lower() in conversation.title.lower()
        ][:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run live Team Mode V3 cooperation benchmarks."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--provider", default="nvidia")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--scenarios", default="all", help="Comma-separated scenario ids or all.")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--vote-every-rounds", type=int, default=2)
    parser.add_argument("--agent-max-tokens", type=int, default=768)
    parser.add_argument("--coordinator-max-tokens", type=int, default=1536)
    parser.add_argument("--request-max-tokens", type=int, default=1536)
    parser.add_argument("--reasoning-level", default="low")
    parser.add_argument("--reasoning-budget", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--stream-read-timeout", type=float, default=60.0)
    parser.add_argument(
        "--compare-single-agent",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run a single-model baseline for direct comparison.",
    )
    return parser.parse_args()


def selected_scenarios(raw: str) -> list[Scenario]:
    if raw.strip().lower() == "all":
        return list(SCENARIOS)
    wanted = {item.strip() for item in raw.split(",") if item.strip()}
    scenarios = [scenario for scenario in SCENARIOS if scenario.id in wanted]
    missing = wanted - {scenario.id for scenario in scenarios}
    if missing:
        raise ValueError(f"Unknown scenario ids: {', '.join(sorted(missing))}")
    return scenarios


def build_team(args: argparse.Namespace, scenario: Scenario):
    team = default_team_config()
    agents = tuple(
        replace(agent, max_tokens=args.agent_max_tokens, tools_enabled=scenario.requires_tools)
        for agent in team.agents
    )
    coordinator = replace(
        team.coordinator,
        max_tokens=args.coordinator_max_tokens,
        system_prompt=(
            f"{team.coordinator.system_prompt}\n"
            "Before every debate, assign distinct focus areas and explicitly reduce overlap."
            " Enforce execution_contract, claim_graph, coverage_matrix, delta-only updates, and coherency scoring."
        ),
    )
    return replace(
        team,
        agents=agents,
        execution_order=tuple(agent.id for agent in agents),
        coordinator=coordinator,
        max_rounds=args.max_rounds,
        vote_every_rounds=args.vote_every_rounds,
    )


def prepare_tool_fixture() -> None:
    BENCHMARK_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    (BENCHMARK_FIXTURE_DIR / "team_tool_fixture.md").write_text(
        "\n".join(
            [
                "# Team Tool Fixture",
                "",
                "- read_evidence: safe read tools may run autonomously.",
                "- mutation_policy: Write/Edit/Delete must become proposal until Coordinator approval.",
                "- audit_contract: every tool result must include agent_id, round, phase and tool_call_id.",
            ]
        ),
        encoding="utf-8",
    )
    output = BENCHMARK_FIXTURE_DIR / "mutating-output.md"
    if output.exists():
        output.unlink()


def scenario_message_text(scenario: Scenario, message: str) -> str:
    if not scenario.requires_tools:
        return message
    prepare_tool_fixture()
    return message.format(
        fixture_path=str((BENCHMARK_FIXTURE_DIR / "team_tool_fixture.md").resolve()),
        mutating_path=str((BENCHMARK_FIXTURE_DIR / "mutating-output.md").resolve()),
    )


def build_tool_runtime(scenario: Scenario) -> tuple[ToolRegistry | None, ToolRuntimeConfig | None]:
    if not scenario.requires_tools:
        return None, None
    prepare_tool_fixture()
    return (
        ToolRegistry([create_read_file_tool(), create_write_file_tool()]),
        ToolRuntimeConfig.from_values(workspace_root=PROJECT_ROOT),
    )


async def run_scenario(
    *,
    scenario: Scenario,
    repetition: int,
    orchestrator: TeamChatOrchestrator,
    team: Any,
    args: argparse.Namespace,
) -> dict[str, Any]:
    conversation_id: UUID | None = None
    turns: list[dict[str, Any]] = []
    for turn_index, raw_message in enumerate(scenario.messages, start=1):
        message = scenario_message_text(scenario, raw_message)
        print(
            f"[benchmark] scenario={scenario.id} rep={repetition} turn={turn_index} start",
            flush=True,
        )
        started = time.perf_counter()
        events: list[dict[str, Any]] = []
        request = TeamChatRequest(
            conversation_id=conversation_id,
            message=message,
            system_prompt=SYSTEM_PROMPT,
            provider=args.provider,
            model=args.model,
            max_tokens=args.request_max_tokens,
            reasoning_level=args.reasoning_level,
            reasoning_budget_tokens=args.reasoning_budget,
            workspace_root=str(PROJECT_ROOT),
            tool_context={"benchmark_id": scenario.id, "repetition": repetition},
            allowed_tools=["Read", "Write"] if scenario.requires_tools else None,
        )
        try:
            async for event in orchestrator.execute(request=request, team=team):
                offset_ms = int((time.perf_counter() - started) * 1000)
                enriched = dict(event)
                enriched["_offset_ms"] = offset_ms
                events.append(enriched)
                if event.get("conversation_id"):
                    conversation_id = UUID(str(event["conversation_id"]))
        except Exception as exc:  # noqa: BLE001 - benchmark must continue remaining scenarios.
            events.append(
                {
                    "event": "benchmark_error",
                    "error": str(exc),
                    "_offset_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        wall_ms = int((time.perf_counter() - started) * 1000)
        analysis = analyze_events(
            scenario=scenario,
            turn_index=turn_index,
            events=events,
            wall_ms=wall_ms,
        )
        print(
            f"[benchmark] scenario={scenario.id} rep={repetition} turn={turn_index} "
            f"status={analysis.status} score={analysis.score:.1f} wall_ms={wall_ms}",
            flush=True,
        )
        turns.append(
            {
                "turn_index": turn_index,
                "message": message,
                "events": events,
                "analysis": asdict(analysis),
            }
        )
    return {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "repetition": repetition,
        "multi_turn": scenario.multi_turn,
        "turns": turns,
        "summary": summarize_scenario(turns),
    }


async def run_single_agent_scenario(
    *,
    scenario: Scenario,
    repetition: int,
    adapter: NvidiaNimAdapter,
    args: argparse.Namespace,
) -> dict[str, Any]:
    history: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "Voce e um unico agente baseline. Responda em portugues com objetividade tecnica. "
                "Resolva a tarefa sem ajuda de outros agentes e inclua decisoes, evidencias, riscos e lacunas."
            ),
        }
    ]
    turns: list[dict[str, Any]] = []
    for turn_index, raw_message in enumerate(scenario.messages, start=1):
        message = scenario_message_text(scenario, raw_message)
        print(
            f"[baseline] scenario={scenario.id} rep={repetition} turn={turn_index} start",
            flush=True,
        )
        started = time.perf_counter()
        first_token_at: float | None = None
        content_parts: list[str] = []
        usage: dict[str, Any] | None = None
        status = "completed"
        try:
            async for chunk in adapter.chat_completion_stream(
                messages=[*history, {"role": "user", "content": message}],
                temperature=0.3,
                max_tokens=args.request_max_tokens,
                model=args.model,
                provider=args.provider,
                reasoning_level=args.reasoning_level,
                reasoning_budget_tokens=args.reasoning_budget,
            ):
                if first_token_at is None and (chunk.content or chunk.reasoning_content):
                    first_token_at = time.perf_counter()
                if chunk.content:
                    content_parts.append(chunk.content)
                if chunk.usage:
                    usage = chunk.usage
        except Exception as exc:  # noqa: BLE001 - benchmark should capture provider failures.
            status = f"error:{exc}"
        wall_ms = int((time.perf_counter() - started) * 1000)
        content = "".join(content_parts)
        output_tokens = output_tokens_from_usage(usage) or estimate_tokens(content)
        tokens_per_second = output_tokens / max(0.001, wall_ms / 1000)
        expected_text = metric_text(content)
        hits = sum(1 for term in scenario.expected_terms if metric_text(term) in expected_text)
        term_ratio = hits / max(1, len(scenario.expected_terms))
        quality_score = round(
            min(
                100.0,
                (45.0 * term_ratio)
                + (25.0 if len(content) >= 700 else 25.0 * min(1.0, len(content) / 700))
                + (20.0 if status == "completed" else 0.0)
                + (10.0 if wall_ms <= (TARGETS["complex_wall_ms"] if scenario.complex else TARGETS["standard_wall_ms"]) else 0.0),
            ),
            2,
        )
        analysis = SingleAgentAnalysis(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            turn_index=turn_index,
            status=status,
            wall_ms=wall_ms,
            first_token_ms=int((first_token_at - started) * 1000) if first_token_at else None,
            tokens_per_second=round(tokens_per_second, 2),
            estimated_output_tokens=output_tokens,
            expected_term_hits=hits,
            expected_term_total=len(scenario.expected_terms),
            quality_score=quality_score,
            final_chars=len(content),
            final_excerpt=content[:1200],
        )
        print(
            f"[baseline] scenario={scenario.id} rep={repetition} turn={turn_index} "
            f"status={status} quality={quality_score:.1f} wall_ms={wall_ms}",
            flush=True,
        )
        turns.append(
            {
                "turn_index": turn_index,
                "message": message,
                "analysis": asdict(analysis),
            }
        )
        history.extend(
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": content},
            ]
        )
    scores = [float(turn["analysis"]["quality_score"]) for turn in turns]
    return {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "repetition": repetition,
        "turns": turns,
        "summary": {
            "quality_score": round(statistics.mean(scores), 2) if scores else 0.0,
            "turn_count": len(turns),
            "statuses": [turn["analysis"]["status"] for turn in turns],
        },
    }


def analyze_events(
    *,
    scenario: Scenario,
    turn_index: int,
    events: list[dict[str, Any]],
    wall_ms: int,
) -> RunAnalysis:
    status = str(events[-1].get("event") if events else "no_events")
    first_event_ms = events[0].get("_offset_ms") if events else None
    final_output = str(_last_value(events, "final_output") or "")
    if not final_output:
        final_output = "".join(
            str(event.get("content") or "")
            for event in events
            if event.get("event") == "final_delta"
        )

    turn_events = [event for event in events if event.get("event") == "agent_turn_completed"]
    agent_tps_values = [turn_tokens_per_s(event) for event in turn_events]
    agent_tps_values = [value for value in agent_tps_values if value > 0]
    first_token_values = [
        float(event["first_token_ms"])
        for event in turn_events
        if isinstance(event.get("first_token_ms"), int)
    ]
    votes = [event for event in events if event.get("event") == "agent_vote"]
    vote_ms = sum(int(event.get("duration_ms") or 0) for event in votes)
    vote_overhead_ratio = vote_ms / max(1, wall_ms)

    independent_texts = [
        str(event.get("content") or event.get("digest") or "")
        for event in turn_events
        if event.get("phase") == "independent_round"
    ]
    debate_texts = [
        str(event.get("content") or event.get("digest") or "")
        for event in turn_events
        if event.get("phase") == "debate_round"
    ]
    independent_overlap = average_pairwise_overlap(independent_texts)
    debate_overlap = average_pairwise_overlap(debate_texts)
    overlap_reduction = None
    if independent_overlap is not None and debate_overlap is not None and independent_overlap > 0:
        overlap_reduction = max(0.0, (independent_overlap - debate_overlap) / independent_overlap)

    guidance_events = [
        event for event in events if event.get("event") == "coordinator_planning_completed"
    ]
    coverage, unique_focus = coordinator_guidance_metrics(guidance_events)
    tool_context_valid = all(tool_context_is_valid(event) for event in turn_events)
    claim_graph_nodes, duplicate_claim_ratio = claim_graph_metrics(events)
    coverage_ratio = coverage_matrix_ratio(events)
    avg_coherency_score = coherency_score_metric(events)
    adaptive_vote_count = sum(1 for event in events if event.get("event") == "adaptive_vote")
    tool_phase_count, tool_result_count, tool_proposal_count, tool_audit_agent_count, tool_latency_ms = tool_metrics(events)
    workspace_memory_present = any(
        isinstance(event.get("team_memory_snapshot"), dict)
        and bool((event.get("team_memory_snapshot") or {}).get("claim_graph"))
        for event in events
    )
    expected_text = metric_text(final_output)
    hits = sum(1 for term in scenario.expected_terms if metric_text(term) in expected_text)
    estimated_output_tokens = estimate_team_output_tokens(events, final_output)
    scores = score_run(
        scenario=scenario,
        status=status,
        wall_ms=wall_ms,
        first_event_ms=first_event_ms if isinstance(first_event_ms, int) else None,
        avg_first_token_ms=statistics.mean(first_token_values) if first_token_values else None,
        avg_agent_tps=statistics.mean(agent_tps_values) if agent_tps_values else 0.0,
        vote_overhead_ratio=vote_overhead_ratio,
        independent_overlap=independent_overlap,
        overlap_reduction=overlap_reduction,
        coordinator_assignment_coverage=coverage,
        coordinator_unique_focus_ratio=unique_focus,
        tool_context_valid=tool_context_valid,
        claim_graph_nodes=claim_graph_nodes,
        duplicate_claim_ratio=duplicate_claim_ratio,
        coverage_ratio=coverage_ratio,
        avg_coherency_score=avg_coherency_score,
        adaptive_vote_count=adaptive_vote_count,
        tool_phase_count=tool_phase_count,
        workspace_memory_present=workspace_memory_present,
        expected_term_hits=hits,
        expected_term_total=len(scenario.expected_terms),
        final_output=final_output,
    )
    score = round(sum(scores.values()), 2)
    hard_gate_failures = hard_gate_failures_for(
        scenario=scenario,
        turn_index=turn_index,
        status=status,
        vote_overhead_ratio=vote_overhead_ratio,
        independent_overlap=independent_overlap,
        overlap_reduction=overlap_reduction,
        duplicate_claim_ratio=duplicate_claim_ratio,
        coverage_ratio=coverage_ratio,
        avg_coherency_score=avg_coherency_score,
        tool_phase_count=tool_phase_count,
        tool_result_count=tool_result_count,
        tool_proposal_count=tool_proposal_count,
        workspace_memory_present=workspace_memory_present,
        expected_term_hits=hits,
        expected_term_total=len(scenario.expected_terms),
    )
    verdict = (
        "pass"
        if score >= TARGETS["quality_score"]
        and status == "team_run_completed"
        and not hard_gate_failures
        else "fail"
    )
    return RunAnalysis(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        turn_index=turn_index,
        status=status,
        wall_ms=wall_ms,
        first_event_ms=first_event_ms if isinstance(first_event_ms, int) else None,
        final_chars=len(final_output),
        final_excerpt=final_output[:1800],
        agent_turn_count=len(turn_events),
        avg_first_token_ms=round(statistics.mean(first_token_values), 2)
        if first_token_values
        else None,
        avg_agent_tps=round(statistics.mean(agent_tps_values), 2) if agent_tps_values else 0.0,
        min_agent_tps=round(min(agent_tps_values), 2) if agent_tps_values else 0.0,
        vote_overhead_ratio=round(vote_overhead_ratio, 4),
        independent_overlap=round(independent_overlap, 4)
        if independent_overlap is not None
        else None,
        debate_overlap=round(debate_overlap, 4) if debate_overlap is not None else None,
        overlap_reduction=round(overlap_reduction, 4)
        if overlap_reduction is not None
        else None,
        coordinator_assignment_coverage=round(coverage, 4),
        coordinator_unique_focus_ratio=round(unique_focus, 4),
        tool_context_valid=tool_context_valid,
        claim_graph_nodes=claim_graph_nodes,
        duplicate_claim_ratio=round(duplicate_claim_ratio, 4),
        coverage_ratio=round(coverage_ratio, 4),
        avg_coherency_score=round(avg_coherency_score, 4),
        adaptive_vote_count=adaptive_vote_count,
        tool_phase_count=tool_phase_count,
        tool_result_count=tool_result_count,
        tool_proposal_count=tool_proposal_count,
        tool_audit_agent_count=tool_audit_agent_count,
        tool_latency_ms=tool_latency_ms,
        workspace_memory_present=workspace_memory_present,
        expected_term_hits=hits,
        expected_term_total=len(scenario.expected_terms),
        estimated_output_tokens=estimated_output_tokens,
        hard_gate_failures=hard_gate_failures,
        scores=scores,
        score=score,
        verdict=verdict,
    )


def score_run(
    *,
    scenario: Scenario,
    status: str,
    wall_ms: int,
    first_event_ms: int | None,
    avg_first_token_ms: float | None,
    avg_agent_tps: float,
    vote_overhead_ratio: float,
    independent_overlap: float | None,
    overlap_reduction: float | None,
    coordinator_assignment_coverage: float,
    coordinator_unique_focus_ratio: float,
    tool_context_valid: bool,
    claim_graph_nodes: int,
    duplicate_claim_ratio: float,
    coverage_ratio: float,
    avg_coherency_score: float,
    adaptive_vote_count: int,
    tool_phase_count: int,
    workspace_memory_present: bool,
    expected_term_hits: int,
    expected_term_total: int,
    final_output: str,
) -> dict[str, float]:
    wall_target = TARGETS["complex_wall_ms"] if scenario.complex else TARGETS["standard_wall_ms"]
    performance = 0.0
    performance += 6.0 if status == "team_run_completed" else 0.0
    performance += 5.0 if first_event_ms is not None and first_event_ms <= TARGETS["first_event_ms"] else 0.0
    performance += 7.0 if avg_first_token_ms is not None and avg_first_token_ms <= TARGETS["first_token_ms"] else 0.0
    performance += 7.0 if avg_agent_tps >= TARGETS["tokens_per_s"] else min(7.0, 7.0 * avg_agent_tps / TARGETS["tokens_per_s"])
    performance += 5.0 if wall_ms <= wall_target else min(5.0, 5.0 * wall_target / max(1, wall_ms))

    cooperation = 0.0
    cooperation += 8.0 if independent_overlap is not None and independent_overlap <= TARGETS["independent_overlap"] else 0.0
    cooperation += 7.0 if overlap_reduction is not None and overlap_reduction >= TARGETS["overlap_reduction"] else 0.0
    cooperation += 5.0 if coordinator_unique_focus_ratio >= 0.75 else 5.0 * coordinator_unique_focus_ratio
    cooperation += 5.0 if coordinator_assignment_coverage >= 1.0 else 5.0 * coordinator_assignment_coverage
    cooperation += 4.0 if duplicate_claim_ratio <= TARGETS["duplicate_claim_ratio"] else 0.0
    cooperation += 4.0 if coverage_ratio >= TARGETS["coverage_ratio"] else 4.0 * coverage_ratio

    governance = 0.0
    governance += 8.0 if tool_context_valid else 0.0
    governance += 7.0 if vote_overhead_ratio <= TARGETS["vote_overhead_ratio"] else 0.0
    governance += 3.0 if adaptive_vote_count > 0 else 0.0
    if scenario.requires_tools:
        governance += 2.0 if tool_phase_count > 0 else 0.0
    else:
        governance += 2.0

    term_ratio = expected_term_hits / max(1, expected_term_total)
    answer_quality = 0.0
    answer_quality += 12.0 * term_ratio
    answer_quality += 8.0 if len(final_output) >= 700 else 8.0 * min(1.0, len(final_output) / 700)
    answer_quality += 5.0 if avg_coherency_score >= TARGETS["coherency_score"] else 5.0 * avg_coherency_score
    answer_quality += 3.0 if claim_graph_nodes > 0 else 0.0

    multi_turn = 5.0
    if scenario.multi_turn:
        multi_turn = (3.0 * term_ratio) + (2.0 if workspace_memory_present else 0.0)

    return {
        "performance": round(min(30.0, performance), 2),
        "cooperation": round(min(25.0, cooperation), 2),
        "governance": round(min(15.0, governance), 2),
        "answer_quality": round(min(25.0, answer_quality), 2),
        "multi_turn": round(min(5.0, multi_turn), 2),
    }


def summarize_scenario(turns: list[dict[str, Any]]) -> dict[str, Any]:
    analyses = [turn["analysis"] for turn in turns]
    scores = [float(item["score"]) for item in analyses]
    failures = [
        failure
        for item in analyses
        for failure in item.get("hard_gate_failures", [])
    ]
    return {
        "score": round(statistics.mean(scores), 2) if scores else 0.0,
        "verdict": "pass" if scores and all(item.get("verdict") == "pass" for item in analyses) else "fail",
        "turn_count": len(turns),
        "statuses": [item["status"] for item in analyses],
        "hard_gate_failures": failures,
    }


def turn_tokens_per_s(event: dict[str, Any]) -> float:
    content = f"{event.get('content') or ''}{event.get('reasoning_content') or ''}"
    tokens = output_tokens_from_usage(event.get("usage")) or estimate_tokens(content)
    duration_s = max(0.001, float(event.get("duration_ms") or 0) / 1000)
    return tokens / duration_s


def output_tokens_from_usage(raw: Any) -> int | None:
    if not isinstance(raw, dict):
        return None
    for key in (
        "output_tokens",
        "completion_tokens",
        "candidatesTokenCount",
        "candidates_token_count",
    ):
        value = raw.get(key)
        if isinstance(value, int) and value > 0:
            return value
    details = raw.get("completion_tokens_details")
    if isinstance(details, dict):
        value = details.get("accepted_prediction_tokens")
        if isinstance(value, int) and value > 0:
            return value
    return None


def estimate_tokens(text: str) -> int:
    normalized = text.strip()
    if not normalized:
        return 0
    return max(1, round(len(normalized) / 4))


def average_pairwise_overlap(texts: list[str]) -> float | None:
    vectors = [word_set(text) for text in texts if text.strip()]
    if len(vectors) < 2:
        return None
    values: list[float] = []
    for index, left in enumerate(vectors):
        for right in vectors[index + 1 :]:
            if not left or not right:
                values.append(0.0)
                continue
            values.append(len(left & right) / len(left | right))
    return statistics.mean(values) if values else None


def word_set(text: str) -> set[str]:
    stopwords = {
        "para",
        "como",
        "com",
        "uma",
        "que",
        "the",
        "and",
        "this",
        "that",
        "agent",
        "agents",
        "team",
    }
    return {
        word
        for word in re.findall(r"[a-zA-Z0-9_]{4,}", text.lower())
        if word not in stopwords
    }


def _looks_mutating_text(text: str) -> bool:
    normalized = text.lower()
    return any(
        token in normalized
        for token in ("write", "edit", "delete", "remove", "mutating", "destrut", "escrita")
    )


def metric_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def coordinator_guidance_metrics(events: list[dict[str, Any]]) -> tuple[float, float]:
    if not events:
        return 0.0, 0.0
    latest = events[-1].get("guidance")
    if not isinstance(latest, dict):
        return 0.0, 0.0
    assignments = latest.get("focus_assignments")
    if not isinstance(assignments, dict):
        return 0.0, 0.0
    expected_ids = {"analyst", "critic", "builder", "reviewer"}
    covered = {key for key, value in assignments.items() if key in expected_ids and str(value).strip()}
    normalized = {re.sub(r"\s+", " ", str(value).strip().lower()) for value in assignments.values()}
    normalized.discard("")
    return len(covered) / len(expected_ids), len(normalized) / len(expected_ids)


def claim_graph_metrics(events: list[dict[str, Any]]) -> tuple[int, float]:
    latest_snapshot = None
    for event in events:
        snapshot = event.get("snapshot") if event.get("event") == "blackboard_snapshot" else None
        if isinstance(snapshot, dict):
            latest_snapshot = snapshot
        if event.get("event") == "team_run_completed" and isinstance(event.get("blackboard_snapshot"), dict):
            latest_snapshot = event.get("blackboard_snapshot")
    graph = latest_snapshot.get("claim_graph") if isinstance(latest_snapshot, dict) else None
    if not isinstance(graph, dict):
        return 0, 1.0
    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        scored_nodes = [
            node
            for node in nodes
            if isinstance(node, dict) and node.get("type") != "tool_result"
        ]
        node_count = len(scored_nodes)
        duplicate_count = sum(1 for node in scored_nodes if node.get("status") == "duplicate")
        return int(graph.get("node_count") or len(nodes)), duplicate_count / max(1, node_count)
    node_count = int(graph.get("node_count") or 0)
    duplicate_count = int(graph.get("duplicate_count") or 0)
    return node_count, duplicate_count / max(1, node_count)


def coverage_matrix_ratio(events: list[dict[str, Any]]) -> float:
    latest = None
    for event in events:
        if event.get("event") == "coverage_matrix":
            latest = event
    if latest is None:
        return 0.0
    complete = int(latest.get("coverage_complete") or 0)
    total = int(latest.get("coverage_total") or 0)
    return complete / max(1, total)


def coherency_score_metric(events: list[dict[str, Any]]) -> float:
    latest_snapshot = None
    for event in events:
        if event.get("event") == "blackboard_snapshot" and isinstance(event.get("snapshot"), dict):
            latest_snapshot = event.get("snapshot")
        if event.get("event") == "team_run_completed" and isinstance(event.get("blackboard_snapshot"), dict):
            latest_snapshot = event.get("blackboard_snapshot")
        if event.get("event") == "team_consensus_failed" and isinstance(event.get("blackboard_snapshot"), dict):
            latest_snapshot = event.get("blackboard_snapshot")
    coherency = latest_snapshot.get("coherency") if isinstance(latest_snapshot, dict) else None
    if isinstance(coherency, dict) and isinstance(coherency.get("average"), (int, float)):
        return float(coherency["average"])
    values = [
        float(event["coherency_score"])
        for event in events
        if event.get("event") == "coherency_score"
        and isinstance(event.get("coherency_score"), (int, float))
    ]
    if values:
        return statistics.mean(values)
    return 0.0


def tool_metrics(events: list[dict[str, Any]]) -> tuple[int, int, int, int, int]:
    tool_events = [event for event in events if event.get("event") == "tool_phase"]
    result_count = 0
    proposal_count = 0
    latency_ms = 0
    agent_ids: set[str] = set()
    for event in tool_events:
        if event.get("agent_id"):
            agent_ids.add(str(event["agent_id"]))
        results = event.get("results")
        proposals = event.get("proposals")
        if isinstance(results, list):
            result_count += len(results)
        if isinstance(proposals, list):
            proposal_count += len(proposals)
        if event.get("tool_result"):
            result_count += 1
        duration = event.get("duration_ms")
        if isinstance(duration, int):
            latency_ms += duration
    latest_snapshot = None
    for event in events:
        if event.get("event") == "blackboard_snapshot" and isinstance(event.get("snapshot"), dict):
            latest_snapshot = event["snapshot"]
        if event.get("event") == "team_run_completed" and isinstance(event.get("blackboard_snapshot"), dict):
            latest_snapshot = event["blackboard_snapshot"]
        if event.get("event") == "team_consensus_failed" and isinstance(event.get("blackboard_snapshot"), dict):
            latest_snapshot = event["blackboard_snapshot"]
    graph = latest_snapshot.get("claim_graph") if isinstance(latest_snapshot, dict) else None
    nodes = graph.get("nodes") if isinstance(graph, dict) else []
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict) or node.get("status") == "duplicate":
                continue
            if node.get("type") == "tool_result":
                result_count += 1
            if node.get("type") == "proposal" and (node.get("mutating") or _looks_mutating_text(str(node.get("text") or ""))):
                proposal_count += 1
    return len(tool_events), result_count, proposal_count, len(agent_ids), latency_ms


def estimate_team_output_tokens(events: list[dict[str, Any]], final_output: str) -> int:
    total = estimate_tokens(final_output)
    for event in events:
        if event.get("event") != "agent_turn_completed":
            continue
        usage_tokens = output_tokens_from_usage(event.get("usage"))
        total += usage_tokens if usage_tokens is not None else estimate_tokens(
            f"{event.get('content') or ''}{event.get('reasoning_content') or ''}"
        )
    return total


def hard_gate_failures_for(
    *,
    scenario: Scenario,
    turn_index: int,
    status: str,
    vote_overhead_ratio: float,
    independent_overlap: float | None,
    overlap_reduction: float | None,
    duplicate_claim_ratio: float,
    coverage_ratio: float,
    avg_coherency_score: float,
    tool_phase_count: int,
    tool_result_count: int,
    tool_proposal_count: int,
    workspace_memory_present: bool,
    expected_term_hits: int,
    expected_term_total: int,
) -> list[str]:
    failures: list[str] = []
    if status != "team_run_completed":
        failures.append(f"status:{status}")
    if scenario.enforce_vote_overhead and vote_overhead_ratio > TARGETS["vote_overhead_ratio"]:
        failures.append(f"vote_overhead>{TARGETS['vote_overhead_ratio']}")
    if duplicate_claim_ratio > TARGETS["duplicate_claim_ratio"]:
        failures.append(f"duplicate_ratio>{TARGETS['duplicate_claim_ratio']}")
    if coverage_ratio < scenario.min_coverage_ratio:
        failures.append(f"coverage<{scenario.min_coverage_ratio}")
    if avg_coherency_score < TARGETS["coherency_score"]:
        failures.append(f"coherency<{TARGETS['coherency_score']}")
    if (
        scenario.requires_overlap_reduction
        and independent_overlap is not None
        and independent_overlap > TARGETS["independent_overlap"]
        and (overlap_reduction is None or overlap_reduction < TARGETS["overlap_reduction"])
    ):
        failures.append(f"overlap_reduction<{TARGETS['overlap_reduction']}")
    if scenario.requires_tools:
        if tool_phase_count <= 0:
            failures.append("tool_phase_missing")
        if tool_result_count <= 0:
            failures.append("tool_result_missing")
        if tool_proposal_count <= 0:
            failures.append("mutating_proposal_missing")
    if scenario.multi_turn and scenario.requires_memory_recall and turn_index > 1:
        term_ratio = expected_term_hits / max(1, expected_term_total)
        if not workspace_memory_present:
            failures.append("workspace_memory_missing")
        if term_ratio < scenario.min_expected_term_ratio:
            failures.append(f"memory_terms<{scenario.min_expected_term_ratio}")
    return failures


def tool_context_is_valid(event: dict[str, Any]) -> bool:
    context = event.get("tool_context")
    if not isinstance(context, dict):
        return False
    return (
        context.get("agent_id") == event.get("agent_id")
        and context.get("round") == event.get("round")
        and context.get("phase") == event.get("phase")
        and context.get("team_run_id") == event.get("run_id")
    )


def _last_value(events: Iterable[dict[str, Any]], key: str) -> Any:
    value = None
    for event in events:
        if key in event:
            value = event[key]
    return value


def write_outputs(
    *,
    output_dir: Path,
    args: argparse.Namespace,
    runs: list[dict[str, Any]],
    baselines: list[dict[str, Any]],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"team-mode-v3-benchmark-{stamp}.json"
    md_path = output_dir / f"team-mode-v3-benchmark-{stamp}.md"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            "provider": args.provider,
            "model": args.model,
            "repetitions": args.repetitions,
            "max_rounds": args.max_rounds,
            "vote_every_rounds": args.vote_every_rounds,
            "agent_max_tokens": args.agent_max_tokens,
            "coordinator_max_tokens": args.coordinator_max_tokens,
            "request_max_tokens": args.request_max_tokens,
            "reasoning_level": args.reasoning_level,
            "reasoning_budget": args.reasoning_budget,
            "compare_single_agent": args.compare_single_agent,
        },
        "targets": TARGETS,
        "summary": summarize_all(runs),
        "baseline_summary": summarize_baselines(baselines),
        "comparisons": compare_runs(runs, baselines),
        "runs": runs,
        "single_agent_baselines": baselines,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return json_path, md_path


def summarize_all(runs: list[dict[str, Any]]) -> dict[str, Any]:
    scenario_scores = [float(run["summary"]["score"]) for run in runs]
    turn_scores = [
        float(turn["analysis"]["score"])
        for run in runs
        for turn in run["turns"]
    ]
    return {
        "scenario_count": len(runs),
        "turn_count": sum(len(run["turns"]) for run in runs),
        "overall_score": round(statistics.mean(turn_scores), 2) if turn_scores else 0.0,
        "scenario_score": round(statistics.mean(scenario_scores), 2) if scenario_scores else 0.0,
        "passed_scenarios": sum(1 for run in runs if run["summary"]["verdict"] == "pass"),
        "failed_scenarios": sum(1 for run in runs if run["summary"]["verdict"] != "pass"),
    }


def summarize_baselines(baselines: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(run["summary"]["quality_score"]) for run in baselines]
    turns = [turn["analysis"] for run in baselines for turn in run["turns"]]
    return {
        "scenario_count": len(baselines),
        "turn_count": len(turns),
        "quality_score": round(statistics.mean(scores), 2) if scores else 0.0,
        "avg_wall_ms": round(statistics.mean(float(turn["wall_ms"]) for turn in turns), 2) if turns else 0.0,
        "avg_tokens_per_second": round(statistics.mean(float(turn["tokens_per_second"]) for turn in turns), 2) if turns else 0.0,
    }


def compare_runs(runs: list[dict[str, Any]], baselines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline_by_key = {
        (run["scenario_id"], run["repetition"]): run
        for run in baselines
    }
    comparisons: list[dict[str, Any]] = []
    for run in runs:
        baseline = baseline_by_key.get((run["scenario_id"], run["repetition"]))
        if baseline is None:
            continue
        team_turns = [turn["analysis"] for turn in run["turns"]]
        single_turns = [turn["analysis"] for turn in baseline["turns"]]
        team_score = statistics.mean(float(turn["score"]) for turn in team_turns) if team_turns else 0.0
        single_score = statistics.mean(float(turn["quality_score"]) for turn in single_turns) if single_turns else 0.0
        team_wall = statistics.mean(float(turn["wall_ms"]) for turn in team_turns) if team_turns else 0.0
        single_wall = statistics.mean(float(turn["wall_ms"]) for turn in single_turns) if single_turns else 0.0
        team_tokens = sum(int(turn["estimated_output_tokens"]) for turn in team_turns)
        single_tokens = sum(int(turn["estimated_output_tokens"]) for turn in single_turns)
        team_tps = statistics.mean(float(turn["avg_agent_tps"]) for turn in team_turns) if team_turns else 0.0
        single_tps = statistics.mean(float(turn["tokens_per_second"]) for turn in single_turns) if single_turns else 0.0
        comparisons.append(
            {
                "scenario_id": run["scenario_id"],
                "repetition": run["repetition"],
                "team_score": round(team_score, 2),
                "single_agent_score": round(single_score, 2),
                "quality_gain_pct": pct_delta(team_score, single_score),
                "team_wall_ms": round(team_wall, 2),
                "single_wall_ms": round(single_wall, 2),
                "latency_overhead_pct": pct_delta(team_wall, single_wall),
                "team_estimated_output_tokens": team_tokens,
                "single_estimated_output_tokens": single_tokens,
                "token_overhead_pct": pct_delta(team_tokens, single_tokens),
                "team_tokens_per_second": round(team_tps, 2),
                "single_tokens_per_second": round(single_tps, 2),
                "throughput_gain_pct": pct_delta(team_tps, single_tps),
            }
        )
    return comparisons


def pct_delta(left: float, right: float) -> float | None:
    if right == 0:
        return None
    return round(((left - right) / right) * 100, 2)


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Team Mode V3 Cooperation Benchmark",
        "",
        f"Generated: `{payload['generated_at']}`",
        f"Provider/model: `{payload['config']['provider']}` / `{payload['config']['model']}`",
        "",
        "## Targets",
        "",
        f"- First event: `<={payload['targets']['first_event_ms']} ms`",
        f"- Average first token: `<={payload['targets']['first_token_ms']} ms`",
        f"- Agent throughput: `>={payload['targets']['tokens_per_s']} tok/s`",
        f"- Vote overhead: `<={payload['targets']['vote_overhead_ratio']}`",
        f"- Independent overlap: `<={payload['targets']['independent_overlap']}`",
        f"- Overlap reduction after Coordinator: `>={payload['targets']['overlap_reduction']}`",
        f"- Claim coherency: `>={payload['targets']['coherency_score']}`",
        f"- Coverage ratio: `>={payload['targets']['coverage_ratio']}`",
        f"- Duplicate claim ratio: `<={payload['targets']['duplicate_claim_ratio']}`",
        "",
        "## Summary",
        "",
        f"- Overall turn score: `{payload['summary']['overall_score']}`",
        f"- Scenario score: `{payload['summary']['scenario_score']}`",
        f"- Passed scenarios: `{payload['summary']['passed_scenarios']}`",
        f"- Failed scenarios: `{payload['summary']['failed_scenarios']}`",
        f"- Single-agent baseline quality: `{payload.get('baseline_summary', {}).get('quality_score', 0.0)}`",
        "",
        "## Scenario Results",
        "",
        "| Scenario | Turn | Verdict | Score | Gates | Wall ms | Avg tok/s | First token ms | Vote ovh | Indep overlap | Reduction | Claims | Dup ratio | Coverage | Coherency | Tool phases | Tool results | Tool proposals | Memory | Terms |",
        "|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for run in payload["runs"]:
        for turn in run["turns"]:
            analysis = turn["analysis"]
            lines.append(
                "| "
                f"{run['scenario_id']} | "
                f"{analysis['turn_index']} | "
                f"{analysis['verdict']} | "
                f"{analysis['score']} | "
                f"{', '.join(analysis.get('hard_gate_failures') or []) or 'ok'} | "
                f"{analysis['wall_ms']} | "
                f"{analysis['avg_agent_tps']} | "
                f"{analysis['avg_first_token_ms']} | "
                f"{analysis['vote_overhead_ratio']} | "
                f"{analysis['independent_overlap']} | "
                f"{analysis['overlap_reduction']} | "
                f"{analysis['claim_graph_nodes']} | "
                f"{analysis['duplicate_claim_ratio']} | "
                f"{analysis['coverage_ratio']} | "
                f"{analysis['avg_coherency_score']} | "
                f"{analysis['tool_phase_count']} | "
                f"{analysis.get('tool_result_count', 0)} | "
                f"{analysis.get('tool_proposal_count', 0)} | "
                f"{'yes' if analysis['workspace_memory_present'] else 'no'} | "
                f"{analysis['expected_term_hits']}/{analysis['expected_term_total']} |"
            )
    comparisons = payload.get("comparisons") or []
    if comparisons:
        lines.extend(
            [
                "",
                "## Multi-Agent vs Single-Agent",
                "",
                "| Scenario | Team score | Single score | Quality gain | Team ms | Single ms | Latency overhead | Team tokens | Single tokens | Token overhead |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for item in comparisons:
            lines.append(
                "| "
                f"{item['scenario_id']} | "
                f"{item['team_score']} | "
                f"{item['single_agent_score']} | "
                f"{item['quality_gain_pct']}% | "
                f"{item['team_wall_ms']} | "
                f"{item['single_wall_ms']} | "
                f"{item['latency_overhead_pct']}% | "
                f"{item['team_estimated_output_tokens']} | "
                f"{item['single_estimated_output_tokens']} | "
                f"{item['token_overhead_pct']}% |"
            )
        lines.extend(
            [
                "",
                "```mermaid",
                "xychart-beta",
                '  title "Team vs Single-Agent Quality"',
                "  x-axis [" + ", ".join(f'\"{item["scenario_id"][:12]}\"' for item in comparisons) + "]",
                "  y-axis \"score\" 0 --> 100",
                "  bar [" + ", ".join(str(item["team_score"]) for item in comparisons) + "]",
                "  line [" + ", ".join(str(item["single_agent_score"]) for item in comparisons) + "]",
                "```",
            ]
        )
    lines.extend(["", "## Final Output Excerpts", ""])
    for run in payload["runs"]:
        for turn in run["turns"]:
            analysis = turn["analysis"]
            excerpt = analysis["final_excerpt"].replace("\n", "\n> ")
            lines.extend(
                [
                    f"### {run['scenario_id']} turn {analysis['turn_index']}",
                    "",
                    f"- Score: `{analysis['score']}`",
                    f"- Status: `{analysis['status']}`",
                    "",
                    f"> {excerpt}",
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
        timeout=max(args.timeout, args.stream_read_timeout),
        stream_read_timeout=args.stream_read_timeout,
        default_model=args.model,
        default_max_tokens=args.request_max_tokens,
        models_cache_ttl_seconds=0,
    )
    try:
        scenarios = selected_scenarios(args.scenarios)
        runs: list[dict[str, Any]] = []
        baselines: list[dict[str, Any]] = []
        for repetition in range(1, args.repetitions + 1):
            for scenario in scenarios:
                repo = MemoryConversationRepository()
                tool_registry, tool_runtime_config = build_tool_runtime(scenario)
                orchestrator = TeamChatOrchestrator(
                    conversation_repo=repo,
                    llm_backend=adapter,
                    tool_registry=tool_registry,
                    tool_runtime_config=tool_runtime_config,
                )
                runs.append(
                    await run_scenario(
                        scenario=scenario,
                        repetition=repetition,
                        orchestrator=orchestrator,
                        team=build_team(args, scenario),
                        args=args,
                    )
                )
                if args.compare_single_agent:
                    baselines.append(
                        await run_single_agent_scenario(
                            scenario=scenario,
                            repetition=repetition,
                            adapter=adapter,
                            args=args,
                        )
                    )
        json_path, md_path = write_outputs(
            output_dir=args.output_dir,
            args=args,
            runs=runs,
            baselines=baselines,
        )
        print(json.dumps({"summary": summarize_all(runs)}, indent=2, ensure_ascii=False))
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
