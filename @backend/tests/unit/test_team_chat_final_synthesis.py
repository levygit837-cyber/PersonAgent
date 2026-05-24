"""Unit tests for the FinalSynthesis extraction.

These tests pin the observable contract of FinalSynthesis so that future
refactors can rely on stable invariants.
"""

from __future__ import annotations

from typing import Any

import pytest

from personagent.application.team_chat.final_synthesis import FinalSynthesis
from personagent.application.team_chat.types import Vote

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StreamChunk:
    def __init__(
        self,
        content: str = "",
        reasoning_content: str = "",
        usage: Any | None = None,
        is_thinking: bool = False,
    ) -> None:
        self.content = content
        self.reasoning_content = reasoning_content
        self.usage = usage
        self.is_thinking = is_thinking


class _LLMBackendStub:
    def __init__(self, chunks: list[_StreamChunk] | None = None, fail: bool = False) -> None:
        self.chunks = chunks or []
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def chat_completion_stream(self, **kwargs: Any):
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


def _vote(agent_id: str = "a1", name: str = "One", approve: bool = True) -> Vote:
    from personagent.application.team_chat.contracts import TeamAgentConfig

    agent = TeamAgentConfig(
        id=agent_id,
        name=name,
        role="developer",
        system_prompt=f"You are {name}.",
    )
    return Vote(
        agent=agent,
        approve=approve,
        confidence=0.9,
        blocker="",
        critical_blocker=False,
        final_points="ok",
        duration_ms=100,
        usage=None,
    )


def _team() -> Any:
    from personagent.application.team_chat.contracts import TeamAgentConfig, TeamConfig

    coord = TeamAgentConfig(
        id="coord",
        name="Coordinator",
        role="coordinator",
        system_prompt="You are the coordinator.",
    )
    return TeamConfig(
        id="team-1",
        name="Test Team",
        coordinator=coord,
        agents=[coord],
        execution_order=["coord"],
        consensus_threshold=0.5,
        vote_every_rounds=2,
        max_rounds=3,
    )


def _request(message: str = "Hello", max_tokens: int = -1) -> Any:
    from personagent.application.team_chat.contracts import TeamChatRequest

    return TeamChatRequest(
        message=message,
        model="gpt-4",
        provider="openai",
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# final_messages
# ---------------------------------------------------------------------------

def test_final_messages_contains_system_and_user() -> None:
    phase = FinalSynthesis(_LLMBackendStub())
    team = _team()
    request = _request()
    from personagent.application.team_chat.blackboard import _Blackboard

    blackboard = _Blackboard("full", user_input=request.message)
    votes = [_vote()]
    consensus = {"approvals": 1, "required": 1}
    msgs = phase.final_messages(request, team, blackboard, votes, consensus)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "synthesize the final answer" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert "Consensus:" in msgs[1]["content"]
    assert "Votes and final points:" in msgs[1]["content"]


# ---------------------------------------------------------------------------
# synthesize_final — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_final_yields_final_delta_events() -> None:
    stub = _LLMBackendStub(
        chunks=[
            _StreamChunk(content="Hello "),
            _StreamChunk(content="world"),
        ]
    )
    phase = FinalSynthesis(stub)
    team = _team()
    request = _request()
    from personagent.application.team_chat.blackboard import _Blackboard
    from personagent.domain.models.conversation import Conversation

    blackboard = _Blackboard("full", user_input=request.message)
    conversation = Conversation(title="Test")
    votes = [_vote()]
    consensus = {"approvals": 1, "required": 1}
    cancel_event = type("E", (), {"is_set": lambda self: False})()

    events = []
    async for event in phase.synthesize_final(
        request=request,
        team=team,
        conversation=conversation,
        run_id="run-1",
        votes=votes,
        consensus=consensus,
        blackboard=blackboard,
        cancel_event=cancel_event,
    ):
        events.append(event)

    assert len(events) == 2
    assert events[0]["event"] == "final_delta"
    assert events[0]["content"] == "Hello "
    assert events[0]["phase"] == "coordinator_final"
    assert events[0]["agent_id"] == "coord"
    assert events[1]["content"] == "world"
    assert events[0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_synthesize_final_skips_empty_chunks() -> None:
    stub = _LLMBackendStub(
        chunks=[
            _StreamChunk(content=""),
            _StreamChunk(content="only"),
            _StreamChunk(content=""),
        ]
    )
    phase = FinalSynthesis(stub)
    team = _team()
    request = _request()
    from personagent.application.team_chat.blackboard import _Blackboard
    from personagent.domain.models.conversation import Conversation

    blackboard = _Blackboard("full", user_input=request.message)
    conversation = Conversation(title="Test")
    votes = [_vote()]
    consensus = {"approvals": 1, "required": 1}
    cancel_event = type("E", (), {"is_set": lambda self: False})()

    events = []
    async for event in phase.synthesize_final(
        request=request,
        team=team,
        conversation=conversation,
        run_id="run-1",
        votes=votes,
        consensus=consensus,
        blackboard=blackboard,
        cancel_event=cancel_event,
    ):
        events.append(event)

    assert len(events) == 1
    assert events[0]["content"] == "only"


@pytest.mark.asyncio
async def test_synthesize_final_respects_cancel_event() -> None:
    stub = _LLMBackendStub(
        chunks=[
            _StreamChunk(content="first"),
            _StreamChunk(content="second"),
        ]
    )
    phase = FinalSynthesis(stub)
    team = _team()
    request = _request()
    from personagent.application.team_chat.blackboard import _Blackboard
    from personagent.domain.models.conversation import Conversation

    blackboard = _Blackboard("full", user_input=request.message)
    conversation = Conversation(title="Test")
    votes = [_vote()]
    consensus = {"approvals": 1, "required": 1}
    cancel_event = type("E", (), {"is_set": lambda self: True})()

    events = []
    async for event in phase.synthesize_final(
        request=request,
        team=team,
        conversation=conversation,
        run_id="run-1",
        votes=votes,
        consensus=consensus,
        blackboard=blackboard,
        cancel_event=cancel_event,
    ):
        events.append(event)

    assert len(events) == 0


@pytest.mark.asyncio
async def test_synthesize_final_passes_correct_max_tokens() -> None:
    stub = _LLMBackendStub(chunks=[_StreamChunk(content="x")])
    phase = FinalSynthesis(stub)
    team = _team()
    request = _request(max_tokens=500)
    from personagent.application.team_chat.blackboard import _Blackboard
    from personagent.domain.models.conversation import Conversation

    blackboard = _Blackboard("full", user_input=request.message)
    conversation = Conversation(title="Test")
    votes = [_vote()]
    consensus = {"approvals": 1, "required": 1}
    cancel_event = type("E", (), {"is_set": lambda self: False})()

    async for _ in phase.synthesize_final(
        request=request,
        team=team,
        conversation=conversation,
        run_id="run-1",
        votes=votes,
        consensus=consensus,
        blackboard=blackboard,
        cancel_event=cancel_event,
    ):
        pass

    assert stub.calls[0]["max_tokens"] == 500


@pytest.mark.asyncio
async def test_synthesize_final_uses_coordinator_max_tokens_when_request_none() -> None:
    stub = _LLMBackendStub(chunks=[_StreamChunk(content="x")])
    phase = FinalSynthesis(stub)
    team = _team()
    request = _request(max_tokens=-1)
    from personagent.application.team_chat.blackboard import _Blackboard
    from personagent.domain.models.conversation import Conversation

    blackboard = _Blackboard("full", user_input=request.message)
    conversation = Conversation(title="Test")
    votes = [_vote()]
    consensus = {"approvals": 1, "required": 1}
    cancel_event = type("E", (), {"is_set": lambda self: False})()

    async for _ in phase.synthesize_final(
        request=request,
        team=team,
        conversation=conversation,
        run_id="run-1",
        votes=votes,
        consensus=consensus,
        blackboard=blackboard,
        cancel_event=cancel_event,
    ):
        pass

    assert stub.calls[0]["max_tokens"] == team.coordinator.max_tokens
