"""Tests for :class:`StreamingTurnState`.

The dataclass bundles the cross-iteration locals of
``_stream_completion_turn``. These tests pin its defaults, mutation
semantics, and field types so that the upcoming streaming-loop
extraction can rely on a stable contract.
"""
from __future__ import annotations

import pytest

from personagent.application.use_cases.chat.state import StreamingTurnState


def test_defaults_are_none_or_empty_collections() -> None:
    state = StreamingTurnState()

    assert state.final_finish_reason is None
    assert state.final_usage is None
    assert state.final_model is None
    assert state.final_provider is None
    assert state.seen_tool_call_ids == set()
    assert state.iteration == 0
    assert state.executed_tools is False
    assert state.last_prompt_context_metadata == {}


def test_can_be_seeded_with_model_and_provider() -> None:
    state = StreamingTurnState(final_model="m", final_provider="p")

    assert state.final_model == "m"
    assert state.final_provider == "p"


def test_iteration_counter_supports_increment() -> None:
    state = StreamingTurnState()

    state.iteration += 1
    state.iteration += 1
    state.iteration += 1

    assert state.iteration == 3


def test_seen_tool_call_ids_default_is_unique_per_instance() -> None:
    a = StreamingTurnState()
    b = StreamingTurnState()

    a.seen_tool_call_ids.add("call-1")

    assert "call-1" not in b.seen_tool_call_ids
    assert "call-1" in a.seen_tool_call_ids


def test_last_prompt_context_metadata_default_is_unique_per_instance() -> None:
    a = StreamingTurnState()
    b = StreamingTurnState()

    a.last_prompt_context_metadata["tokens_in_context"] = 1234

    assert "tokens_in_context" not in b.last_prompt_context_metadata
    assert a.last_prompt_context_metadata["tokens_in_context"] == 1234


def test_executed_tools_flag_is_mutable() -> None:
    state = StreamingTurnState()
    assert state.executed_tools is False

    state.executed_tools = True

    assert state.executed_tools is True


def test_final_finish_reason_assignment_overrides_default() -> None:
    state = StreamingTurnState()

    state.final_finish_reason = "stop"
    assert state.final_finish_reason == "stop"

    state.final_finish_reason = "tool_loop_limit_exceeded"
    assert state.final_finish_reason == "tool_loop_limit_exceeded"


def test_final_usage_accepts_token_breakdown() -> None:
    state = StreamingTurnState()

    state.final_usage = {"prompt_tokens": 100, "completion_tokens": 25}

    assert state.final_usage == {"prompt_tokens": 100, "completion_tokens": 25}


def test_slots_prevents_typo_attribute_writes() -> None:
    state = StreamingTurnState()

    with pytest.raises(AttributeError):
        state.totally_wrong_attribute_name = "boom"  # type: ignore[attr-defined]


def test_each_field_is_distinct_from_others() -> None:
    state = StreamingTurnState(
        final_finish_reason="stop",
        final_usage={"prompt_tokens": 1},
        final_model="m",
        final_provider="p",
        iteration=7,
        executed_tools=True,
    )

    state.seen_tool_call_ids.add("c1")
    state.last_prompt_context_metadata["k"] = "v"

    assert state.final_finish_reason == "stop"
    assert state.final_usage == {"prompt_tokens": 1}
    assert state.final_model == "m"
    assert state.final_provider == "p"
    assert state.iteration == 7
    assert state.executed_tools is True
    assert state.seen_tool_call_ids == {"c1"}
    assert state.last_prompt_context_metadata == {"k": "v"}


def test_state_supports_max_iteration_pattern() -> None:
    state = StreamingTurnState()
    max_iterations = 4

    iterations_run = 0
    while state.iteration < max_iterations:
        iterations_run += 1
        state.iteration += 1

    assert iterations_run == max_iterations
    assert state.iteration == max_iterations


def test_tool_call_ids_accumulate_across_passes() -> None:
    state = StreamingTurnState()

    state.seen_tool_call_ids.update({"a", "b"})
    state.seen_tool_call_ids.update({"b", "c"})

    assert state.seen_tool_call_ids == {"a", "b", "c"}


def test_state_supports_legacy_or_fallback_pattern() -> None:
    """``assistant_state.x or turn_state.final_x`` should preserve the seed."""

    state = StreamingTurnState(final_model="seed-model", final_provider="seed-prov")

    state.final_model = "" or state.final_model
    state.final_provider = None or state.final_provider

    assert state.final_model == "seed-model"
    assert state.final_provider == "seed-prov"


def test_finish_reason_tool_calls_branch_preserves_previous() -> None:
    """Pin the legacy precedence: a ``tool_calls`` finish reason from
    the assistant pass must NOT overwrite the carried-over reason."""

    state = StreamingTurnState(final_finish_reason="permission_required")
    new_reason: str | None = "tool_calls"

    state.final_finish_reason = (
        new_reason if new_reason != "tool_calls" else state.final_finish_reason
    )

    assert state.final_finish_reason == "permission_required"


def test_finish_reason_non_tool_calls_overrides_previous() -> None:
    """Pin the legacy precedence: any non-``tool_calls`` finish reason
    DOES overwrite the carried-over reason."""

    state = StreamingTurnState(final_finish_reason="stop")
    new_reason: str | None = "length"

    state.final_finish_reason = (
        new_reason if new_reason != "tool_calls" else state.final_finish_reason
    )

    assert state.final_finish_reason == "length"
