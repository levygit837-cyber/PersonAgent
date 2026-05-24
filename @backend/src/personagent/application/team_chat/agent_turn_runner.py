"""Agent turn runner for team chat orchestration."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog

from personagent.application.team_chat.blackboard import (
    _Blackboard,
    _now_iso,
)
from personagent.application.team_chat.blackboard_json_parsing import (
    _digest,
)
from personagent.application.team_chat.contracts import (
    TeamAgentConfig,
    TeamChatRequest,
    TeamConfig,
)
from personagent.application.team_chat.helpers import (
    INDEPENDENT_PHASE,
    TOOL_PHASE_AUDIT,
    TOOL_PHASE_MUTATING_PROPOSAL,
    TOOL_PHASE_PLAN,
    TOOL_PHASE_READ,
    _agent_system_prompt,
    _agent_tool_context,
    _claim_graph_output_contract,
    _duration_ms,
    _runtime_context,
    _tool_phase_event,
    _tool_proposal,
    _tool_result_payload,
    _tool_use_context_from_request,
    _turn_coherency_score,
    _turn_text,
    _unique_tool_call_ids,
)
from personagent.application.team_chat.types import (
    QueuedTurnItem,
    ToolAudit,
    TurnResult,
)
from personagent.application.tools import ToolOrchestrator, ToolRegistry, ToolRuntimeConfig
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import ToolCall

logger = structlog.get_logger(__name__)


class AgentTurnRunner:
    """Runs individual agent turns and their tool execution within a team chat."""

    def __init__(
        self,
        *,
        llm_backend: LLMBackendRepository,
        tool_registry: ToolRegistry | None = None,
        tool_runtime_config: ToolRuntimeConfig | None = None,
    ) -> None:
        self._llm_backend = llm_backend
        self._tool_registry = tool_registry
        self._tool_runtime_config = tool_runtime_config

    async def _run_agent_turns_parallel(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        conversation: Conversation,
        run_id: str,
        agents: list[TeamAgentConfig],
        round_index: int,
        phase: str,
        blackboard: _Blackboard,
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[tuple[dict[str, Any], TurnResult | None]]:
        queue: asyncio.Queue[QueuedTurnItem] = asyncio.Queue()

        async def run_one(agent: TeamAgentConfig) -> None:
            try:
                async for event, turn in self._run_agent_turn(
                    request=request,
                    team=team,
                    conversation=conversation,
                    run_id=run_id,
                    agent=agent,
                    round_index=round_index,
                    phase=phase,
                    blackboard=blackboard,
                    cancel_event=cancel_event,
                ):
                    await queue.put(QueuedTurnItem(event=event, turn=turn))
            except Exception as exc:
                await queue.put(QueuedTurnItem(error=exc))
            finally:
                await queue.put(QueuedTurnItem(done=True))

        tasks = [asyncio.create_task(run_one(agent)) for agent in agents]
        remaining = len(tasks)
        try:
            while remaining:
                item = await queue.get()
                if item.done:
                    remaining -= 1
                    continue
                if item.error is not None:
                    raise item.error
                if item.event is not None:
                    yield item.event, item.turn
        finally:
            if cancel_event.is_set():
                for task in tasks:
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_agent_turn(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        conversation: Conversation,
        run_id: str,
        agent: TeamAgentConfig,
        round_index: int,
        phase: str,
        blackboard: _Blackboard,
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[tuple[dict[str, Any], TurnResult | None]]:
        started = time.perf_counter()
        first_token_at: float | None = None
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage = None
        tool_context = _agent_tool_context(request, run_id, agent, round_index, phase)
        tool_schemas = self._tool_schemas_for_agent(request, agent)
        assistant_tool_calls: list[dict[str, Any]] | None = None
        yield (
            {
                "event": "agent_turn_started",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "phase": phase,
                "agent_id": agent.id,
                "agent_name": agent.name,
                "agent_role": agent.role,
                "tool_context": tool_context,
                "started_at": _now_iso(),
            },
            None,
        )

        blocker = ""
        try:
            async for chunk in self._llm_backend.chat_completion_stream(
                messages=self._agent_messages(request, team, agent, round_index, phase, blackboard),
                temperature=agent.temperature,
                max_tokens=agent.max_tokens,
                model=request.model,
                provider=request.provider,
                reasoning_level=request.reasoning_level,
                reasoning_budget_tokens=request.reasoning_budget_tokens,
                tools=tool_schemas,
                tool_choice="auto" if tool_schemas else None,
                tools_enabled=agent.tools_enabled,
                tool_context=tool_context,
                tool_policy=team.tool_policy,
            ):
                if cancel_event.is_set():
                    break
                if first_token_at is None and (chunk.content or chunk.reasoning_content):
                    first_token_at = time.perf_counter()
                if chunk.content:
                    content_parts.append(chunk.content)
                if chunk.reasoning_content:
                    reasoning_parts.append(chunk.reasoning_content)
                if chunk.tool_calls:
                    assistant_tool_calls = _unique_tool_call_ids(
                        chunk.tool_calls,
                        round_index=round_index,
                        agent_id=agent.id,
                    )
                if chunk.usage:
                    usage = chunk.usage
                if chunk.content or chunk.reasoning_content:
                    yield (
                        {
                            "event": "agent_delta",
                            "run_id": run_id,
                            "conversation_id": str(conversation.id),
                            "round": round_index,
                            "phase": phase,
                            "agent_id": agent.id,
                            "agent_name": agent.name,
                            "content": chunk.content,
                            "reasoning_content": chunk.reasoning_content,
                            "is_thinking": chunk.is_thinking,
                            "created_at": _now_iso(),
                        },
                        None,
                    )
        except Exception as exc:
            blocker = f"{agent.name} failed during {phase}: {exc}"
            logger.warning("team_agent_turn_failed", agent_id=agent.id, phase=phase, error=str(exc))

        duration_ms = _duration_ms(started)
        first_token_ms = (
            int((first_token_at - started) * 1000) if first_token_at is not None else None
        )
        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        turn_content = _turn_text(content, reasoning)
        digest = blocker or _digest(turn_content)
        tool_audit = ToolAudit()
        if assistant_tool_calls and not blocker:
            async for event in self._execute_agent_tools(
                request=request,
                conversation=conversation,
                run_id=run_id,
                agent=agent,
                round_index=round_index,
                phase=phase,
                raw_tool_context=tool_context,
                raw_tool_calls=assistant_tool_calls,
                audit=tool_audit,
            ):
                yield event, None
        coherency_score = _turn_coherency_score(turn_content, request.message, blackboard)
        turn = TurnResult(
            agent=agent,
            round_index=round_index,
            phase=phase,
            content=turn_content,
            reasoning=reasoning,
            digest=digest,
            usage=usage,
            duration_ms=duration_ms,
            first_token_ms=first_token_ms,
            tool_context=tool_context,
            coherency_score=coherency_score,
            tool_calls=assistant_tool_calls or [],
            tool_results=tool_audit.results,
            tool_proposals=tool_audit.proposals,
            blocker=blocker,
        )
        yield (
            {
                "event": "agent_turn_completed",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "phase": phase,
                "agent_id": agent.id,
                "agent_name": agent.name,
                "content": turn_content,
                "reasoning_content": reasoning,
                "digest": turn.digest,
                "usage": usage,
                "tool_context": tool_context,
                "coherency_score": coherency_score,
                "tool_calls": assistant_tool_calls or [],
                "tool_summary": {
                    "calls": len(tool_audit.calls),
                    "results": len(tool_audit.results),
                    "proposals": len(tool_audit.proposals),
                },
                "blocker": blocker or None,
                "status": "failed" if blocker else "completed",
                "completed_at": _now_iso(),
                "duration_ms": duration_ms,
                "first_token_ms": first_token_ms,
            },
            turn,
        )

    def _tool_schemas_for_agent(
        self,
        request: TeamChatRequest,
        agent: TeamAgentConfig,
    ) -> list[dict[str, Any]]:
        if not agent.tools_enabled or self._tool_registry is None:
            return []
        allowed_tools = set(request.allowed_tools) if request.allowed_tools else None
        return self._tool_registry.openai_schemas(
            allowed_tools=allowed_tools,
            cache_scope=f"team:{request.provider}:{request.model}:{agent.id}",
        )

    async def _execute_agent_tools(
        self,
        *,
        request: TeamChatRequest,
        conversation: Conversation,
        run_id: str,
        agent: TeamAgentConfig,
        round_index: int,
        phase: str,
        raw_tool_context: dict[str, Any],
        raw_tool_calls: list[dict[str, Any]],
        audit: ToolAudit,
    ) -> AsyncIterator[dict[str, Any]]:

        if self._tool_registry is None or self._tool_runtime_config is None:
            for raw_call in raw_tool_calls:
                proposal = _tool_proposal(raw_call, reason="tool runtime is not configured")
                audit.proposals.append(proposal)
            if audit.proposals:
                yield _tool_phase_event(
                    run_id,
                    conversation.id,
                    agent,
                    round_index,
                    phase,
                    TOOL_PHASE_MUTATING_PROPOSAL,
                    proposals=audit.proposals,
                )
            return

        calls = [ToolCall.from_openai(raw_call) for raw_call in raw_tool_calls]
        calls = [call for call in calls if call.id and call.name]
        if not calls:
            return
        audit.calls.extend(raw_tool_calls)
        yield _tool_phase_event(
            run_id,
            conversation.id,
            agent,
            round_index,
            phase,
            TOOL_PHASE_PLAN,
            calls=[call.to_openai() for call in calls],
        )

        read_calls: list[ToolCall] = []
        for call in calls:
            tool = self._tool_registry.get(call.name)
            if tool is None:
                audit.proposals.append(_tool_proposal(call.to_openai(), reason="unknown tool"))
                continue
            try:
                is_read_only = tool.is_read_only(call.arguments)
            except Exception:
                is_read_only = bool(tool.definition.is_read_only)
            if is_read_only:
                read_calls.append(call)
            else:
                audit.proposals.append(
                    _tool_proposal(
                        call.to_openai(),
                        reason="mutating or non-read-only tool requires Coordinator consensus",
                    )
                )

        if audit.proposals:
            yield _tool_phase_event(
                run_id,
                conversation.id,
                agent,
                round_index,
                phase,
                TOOL_PHASE_MUTATING_PROPOSAL,
                proposals=audit.proposals,
            )
        if not read_calls:
            yield _tool_phase_event(
                run_id,
                conversation.id,
                agent,
                round_index,
                phase,
                TOOL_PHASE_AUDIT,
                calls=[call.to_openai() for call in calls],
                proposals=audit.proposals,
            )
            return

        context = _tool_use_context_from_request(
            request=request,
            conversation=conversation,
            raw_context=raw_tool_context,
            config=self._tool_runtime_config,
        )
        orchestrator = ToolOrchestrator(self._tool_registry, self._tool_runtime_config)
        async for tool_event in orchestrator.execute(read_calls, context):
            metadata = tool_event.to_stream_metadata()
            metadata.update(
                {
                    "event": "tool_phase",
                    "run_id": run_id,
                    "conversation_id": str(conversation.id),
                    "round": round_index,
                    "phase": phase,
                    "tool_phase": TOOL_PHASE_READ,
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "agent_role": agent.role,
                    "created_at": _now_iso(),
                }
            )
            if tool_event.result is not None:
                audit.results.append(_tool_result_payload(tool_event.result))
            yield metadata

        yield _tool_phase_event(
            run_id,
            conversation.id,
            agent,
            round_index,
            phase,
            TOOL_PHASE_AUDIT,
            calls=[call.to_openai() for call in calls],
            results=audit.results,
            proposals=audit.proposals,
        )

    def _agent_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        agent: TeamAgentConfig,
        round_index: int,
        phase: str,
        blackboard: _Blackboard,
    ) -> list[dict[str, str]]:
        focus = blackboard.latest_focus_for(agent.id)
        lane = blackboard.latest_lane_for(agent.id)
        lane_text = ""
        if lane:
            lane_text = (
                "Your mandatory subproblem lane:\n"
                f"{json.dumps(lane, ensure_ascii=False)}\n\n"
            )
        delta_guard = blackboard.delta_guard_text(agent.id)
        focus_text = (
            f"Your Coordinator focus assignment:\n{focus}\n\n"
            if focus
            else ""
        )
        if phase == INDEPENDENT_PHASE:
            body = (
                f"User input:\n{request.message}\n\n"
                f"Round: {round_index}\n"
                f"Runtime context:\n{_runtime_context(request)}\n\n"
                f"Execution contract and workspace memory:\n{blackboard.snapshot_text()}\n\n"
                f"{lane_text}"
                f"{focus_text}"
                "This is the independent first pass. Do not assume, cite, or react to "
                "other agents. Follow your assigned focus and publish a distinct view "
                "for the shared claim_graph. You must cover your mandatory subproblem "
                "and include coverage ids for every claim. If the user asks for a conceptual "
                "evaluation and did not provide a concrete artifact, proceed with explicit "
                "assumptions instead of blocking the run.\n\n"
                f"{_claim_graph_output_contract()}"
            )
        else:
            body = (
                f"User input:\n{request.message}\n\n"
                f"Round: {round_index}\n"
                f"Runtime context:\n{_runtime_context(request)}\n\n"
                f"Blackboard snapshot:\n{blackboard.snapshot_text()}\n\n"
                f"{lane_text}"
                f"{focus_text}"
                f"Delta guard:\n{delta_guard}\n\n"
                "Debate only the compact blackboard delta. Publish only new information: "
                "critique, refinements, evidence, contradictions, blockers, or decisions that "
                "are not already covered. Repeated claims will be marked duplicate and penalized. "
                "Do not restate existing claims. If your lane is already covered, add a targeted "
                "coherence check or a missing risk with coverage ids. Treat missing optional examples "
                "as assumptions for conceptual questions, not blockers. Keep it concise.\n\n"
                f"{_claim_graph_output_contract()}"
            )
        return [
            {"role": "system", "content": _agent_system_prompt(request, team, agent)},
            {"role": "user", "content": body},
        ]
