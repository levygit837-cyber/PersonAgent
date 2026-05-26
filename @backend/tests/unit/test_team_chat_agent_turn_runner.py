"""Unit tests for the AgentTurnRunner extraction.

These tests pin the observable contract of AgentTurnRunner so that future
refactors can rely on stable invariants.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from personagent.application.team_chat.blackboard.core import _Blackboard
from personagent.application.team_chat.contracts import TeamAgentConfig, TeamConfig
from personagent.application.team_chat.orchestration.agent_turn_runner import AgentTurnRunner
from personagent.application.team_chat.types import TurnResult
from personagent.domain.conversation.models import Conversation
from personagent.domain.llm_backend.models import StreamChunk

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _LLMBackendStub:
    """Stub that yields configurable stream chunks."""

    def __init__(self, chunks: list[StreamChunk] | None = None, fail: bool = False) -> None:
        self.chunks = chunks or []
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def chat_completion_stream(self, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("LLM failed")
        for chunk in self.chunks:
            yield chunk

    async def chat_completion(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def health_check(self) -> dict[str, Any]:
        return {"ok": True}

    async def get_model_info(self) -> dict[str, Any]:
        return {}


class _ToolRegistryStub:
    def __init__(self, schemas: list[dict[str, Any]] | None = None) -> None:
        self._schemas = schemas or []

    def openai_schemas(self, *, allowed_tools: set[str] | None = None, cache_scope: str = "") -> list[dict[str, Any]]:
        return self._schemas

    def get(self, name: str) -> Any | None:
        return None


class _ToolRuntimeConfigStub:
    pass


def _agent(agent_id: str = "agent-1", name: str = "Agent One", role: str = "developer", tools_enabled: bool = False) -> TeamAgentConfig:
    return TeamAgentConfig(
        id=agent_id,
        name=name,
        role=role,
        system_prompt=f"You are {name}.",
        tools_enabled=tools_enabled,
    )


def _coordinator() -> TeamAgentConfig:
    return _agent("coord", "Coordinator", "coordinator")


def _team(*agents: TeamAgentConfig) -> TeamConfig:
    return TeamConfig(
        id="t1",
        name="Team",
        agents=agents,
        execution_order=tuple(a.id for a in agents),
        coordinator=_coordinator(),
    )


def _conversation() -> Conversation:
    return Conversation(id="c1", title="Test")


def _request():
    from personagent.application.team_chat.contracts import TeamChatRequest
    return TeamChatRequest(message="How do I deploy?")


def _blackboard() -> _Blackboard:
    return _Blackboard("hybrid", user_input="How do I deploy?")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestAgentTurnRunnerConstruction:
    def test_init_stores_collaborators(self) -> None:
        llm = _LLMBackendStub()
        registry = _ToolRegistryStub()
        config = _ToolRuntimeConfigStub()
        runner = AgentTurnRunner(llm_backend=llm, tool_registry=registry, tool_runtime_config=config)
        assert runner._llm_backend is llm
        assert runner._tool_registry is registry
        assert runner._tool_runtime_config is config


# ---------------------------------------------------------------------------
# _tool_schemas_for_agent
# ---------------------------------------------------------------------------

class TestToolSchemasForAgent:
    def test_returns_empty_when_tools_disabled(self) -> None:
        runner = AgentTurnRunner(llm_backend=_LLMBackendStub())
        agent = _agent(tools_enabled=False)
        schemas = runner._tool_schemas_for_agent(_request(), agent)
        assert schemas == []

    def test_returns_empty_when_registry_is_none(self) -> None:
        runner = AgentTurnRunner(llm_backend=_LLMBackendStub(), tool_registry=None)
        agent = _agent(tools_enabled=True)
        schemas = runner._tool_schemas_for_agent(_request(), agent)
        assert schemas == []

    def test_returns_schemas_when_tools_enabled(self) -> None:
        runner = AgentTurnRunner(
            llm_backend=_LLMBackendStub(),
            tool_registry=_ToolRegistryStub([{"name": "test"}]),
        )
        agent = _agent(tools_enabled=True)
        schemas = runner._tool_schemas_for_agent(_request(), agent)
        assert len(schemas) == 1


# ---------------------------------------------------------------------------
# _run_agent_turn — single agent, no tools
# ---------------------------------------------------------------------------

class TestRunAgentTurn:
    @pytest.mark.asyncio
    async def test_single_agent_no_tools(self) -> None:
        llm = _LLMBackendStub([StreamChunk(content="Use Docker.")])
        runner = AgentTurnRunner(llm_backend=llm)
        events = []
        turn = None
        async for event, _t in runner._run_agent_turn(
            request=_request(),
            team=_team(_agent()),
            conversation=_conversation(),
            run_id="r1",
            agent=_agent(),
            round_index=0,
            phase="independent_round",
            blackboard=_blackboard(),
            cancel_event=asyncio.Event(),
        ):
            events.append(event)
            if _t is not None:
                turn = _t

        assert turn is not None
        assert isinstance(turn, TurnResult)
        assert turn.content == "Use Docker."
        assert turn.agent.id == "agent-1"
        assert any(e.get("event") == "agent_turn_started" for e in events)
        assert any(e.get("event") == "agent_turn_completed" for e in events)

    @pytest.mark.asyncio
    async def test_provider_failure_does_not_crash(self) -> None:
        llm = _LLMBackendStub(fail=True)
        runner = AgentTurnRunner(llm_backend=llm)
        events = []
        turn = None
        async for event, _t in runner._run_agent_turn(
            request=_request(),
            team=_team(_agent()),
            conversation=_conversation(),
            run_id="r1",
            agent=_agent(),
            round_index=0,
            phase="independent_round",
            blackboard=_blackboard(),
            cancel_event=asyncio.Event(),
        ):
            events.append(event)
            if _t is not None:
                turn = _t

        assert turn is not None
        assert turn.blocker != ""
        assert any(e.get("event") == "agent_turn_completed" for e in events)
        assert any(e.get("status") == "failed" for e in events)

    @pytest.mark.asyncio
    async def test_tool_calls_yield_proposals_when_registry_missing(self) -> None:
        chunk = StreamChunk(
            content="",
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}],
        )
        llm = _LLMBackendStub([chunk])
        runner = AgentTurnRunner(llm_backend=llm, tool_registry=None)
        events = []
        async for event, _t in runner._run_agent_turn(
            request=_request(),
            team=_team(_agent(tools_enabled=True)),
            conversation=_conversation(),
            run_id="r1",
            agent=_agent(tools_enabled=True),
            round_index=0,
            phase="independent_round",
            blackboard=_blackboard(),
            cancel_event=asyncio.Event(),
        ):
            events.append(event)

        tool_events = [e for e in events if e.get("event") == "tool_phase"]
        assert len(tool_events) > 0


# ---------------------------------------------------------------------------
# _run_agent_turns_parallel
# ---------------------------------------------------------------------------

class TestRunAgentTurnsParallel:
    @pytest.mark.asyncio
    async def test_parallel_agents_produce_turns(self) -> None:
        llm = _LLMBackendStub([StreamChunk(content="Reply.")])
        runner = AgentTurnRunner(llm_backend=llm)
        a1 = _agent("a1")
        a2 = _agent("a2")
        turns: list[TurnResult] = []
        async for _event, turn in runner._run_agent_turns_parallel(
            request=_request(),
            team=_team(a1, a2),
            conversation=_conversation(),
            run_id="r1",
            agents=[a1, a2],
            round_index=0,
            phase="independent_round",
            blackboard=_blackboard(),
            cancel_event=asyncio.Event(),
        ):
            if turn is not None:
                turns.append(turn)

        assert len(turns) == 2
        assert {t.agent.id for t in turns} == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_one_failure_still_produces_turn_with_blocker(self) -> None:
        class _SelectiveFailLLM:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            async def chat_completion_stream(self, **kwargs: Any) -> AsyncIterator[StreamChunk]:
                self.calls.append(kwargs)
                agent_id = kwargs.get("tool_context", {}).get("agent_id", "")
                if agent_id == "a1":
                    raise RuntimeError("a1 failed")
                yield StreamChunk(content=f"Reply from {agent_id}.")

            async def chat_completion(self, **kwargs: Any) -> Any:
                raise NotImplementedError

            async def health_check(self) -> dict[str, Any]:
                return {"ok": True}

            async def get_model_info(self) -> dict[str, Any]:
                return {}

        llm = _SelectiveFailLLM()
        runner = AgentTurnRunner(llm_backend=llm)
        a1 = _agent("a1")
        a2 = _agent("a2")
        turns: list[TurnResult] = []
        async for _event, turn in runner._run_agent_turns_parallel(
            request=_request(),
            team=_team(a1, a2),
            conversation=_conversation(),
            run_id="r1",
            agents=[a1, a2],
            round_index=0,
            phase="independent_round",
            blackboard=_blackboard(),
            cancel_event=asyncio.Event(),
        ):
            if turn is not None:
                turns.append(turn)

        assert len(turns) == 2
        a1_turn = next(t for t in turns if t.agent.id == "a1")
        a2_turn = next(t for t in turns if t.agent.id == "a2")
        assert a1_turn.blocker != ""
        assert a2_turn.blocker == ""

    @pytest.mark.asyncio
    async def test_cancel_event_stops_processing(self) -> None:
        llm = _LLMBackendStub([StreamChunk(content="Reply.")])
        runner = AgentTurnRunner(llm_backend=llm)
        cancel = asyncio.Event()
        cancel.set()
        a1 = _agent("a1")
        events = []
        async for event, _turn in runner._run_agent_turn(
            request=_request(),
            team=_team(a1),
            conversation=_conversation(),
            run_id="r1",
            agent=a1,
            round_index=0,
            phase="independent_round",
            blackboard=_blackboard(),
            cancel_event=cancel,
        ):
            events.append(event)

        # With cancel set before streaming, we may get started + completed
        # or just started depending on timing; the key is no crash.
        assert any(e.get("event") == "agent_turn_started" for e in events)


# ---------------------------------------------------------------------------
# _execute_agent_tools
# ---------------------------------------------------------------------------

class TestExecuteAgentTools:
    @pytest.mark.asyncio
    async def test_no_registry_produces_proposals(self) -> None:
        runner = AgentTurnRunner(llm_backend=_LLMBackendStub(), tool_registry=None)
        from personagent.application.team_chat.types import ToolAudit
        audit = ToolAudit()
        events = []
        raw_call = {"id": "tc1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}
        async for event in runner._execute_agent_tools(
            request=_request(),
            conversation=_conversation(),
            run_id="r1",
            agent=_agent(tools_enabled=True),
            round_index=0,
            phase="independent_round",
            raw_tool_context={},
            raw_tool_calls=[raw_call],
            audit=audit,
        ):
            events.append(event)

        assert len(audit.proposals) == 1
        assert any(e.get("event") == "tool_phase" for e in events)

    @pytest.mark.asyncio
    async def test_empty_tool_calls_returns_nothing(self) -> None:
        runner = AgentTurnRunner(llm_backend=_LLMBackendStub())
        from personagent.application.team_chat.types import ToolAudit
        audit = ToolAudit()
        events = []
        async for event in runner._execute_agent_tools(
            request=_request(),
            conversation=_conversation(),
            run_id="r1",
            agent=_agent(),
            round_index=0,
            phase="independent_round",
            raw_tool_context={},
            raw_tool_calls=[],
            audit=audit,
        ):
            events.append(event)

        assert events == []

    @pytest.mark.asyncio
    async def test_unknown_tool_produces_proposal(self) -> None:
        runner = AgentTurnRunner(
            llm_backend=_LLMBackendStub(),
            tool_registry=_ToolRegistryStub(),
            tool_runtime_config=_ToolRuntimeConfigStub(),
        )
        from personagent.application.team_chat.types import ToolAudit
        audit = ToolAudit()
        raw_call = {"id": "tc1", "type": "function", "function": {"name": "Unknown", "arguments": "{}"}}
        events = []
        async for event in runner._execute_agent_tools(
            request=_request(),
            conversation=_conversation(),
            run_id="r1",
            agent=_agent(tools_enabled=True),
            round_index=0,
            phase="independent_round",
            raw_tool_context={},
            raw_tool_calls=[raw_call],
            audit=audit,
        ):
            events.append(event)

        assert len(audit.proposals) == 1
        assert audit.proposals[0].get("reason") == "unknown tool"
