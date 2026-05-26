from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from personagent.application.services.session_titles.llm_titles import (
    TitleGenerator,
    _parse_title_response,
)
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.llm_backend.models import InferenceResult, StreamChunk
from personagent.domain.llm_backend.repositories import LLMBackendRepository


class StubLLMBackend(LLMBackendRepository):
    def __init__(self, response_content: str | None = None, raise_on_call: bool = False) -> None:
        self.response_content = response_content
        self.raise_on_call = raise_on_call
        self.calls: list[dict] = []

    async def chat_completion(self, messages, **kwargs) -> InferenceResult:
        self.calls.append({"messages": messages, **kwargs})
        if self.raise_on_call:
            raise RuntimeError("llm failed")
        return InferenceResult(content=self.response_content or "")

    async def chat_completion_stream(self, messages, **kwargs) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content="")

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {"data": []}


def _conversation_with_messages(*contents: str) -> Conversation:
    conversation = Conversation(title="Test")
    for content in contents:
        conversation.add_message(Message(role=Role.USER, content=content))
    return conversation


def _title_response(titles: dict[str, str]) -> str:
    return json.dumps({
        "titles": [
            {"id": conversation_id, "title": title}
            for conversation_id, title in titles.items()
        ]
    })


@pytest.mark.asyncio
async def test_generate_titles_primary_succeeds():
    primary = StubLLMBackend(_title_response({"c1": "Primary Title"}))
    generator = TitleGenerator(
        primary_llm_backend=primary,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    conversation = _conversation_with_messages("Hello world")

    result, source, reason = await generator.generate_titles_for_batch(
        [conversation],
        existing_titles=[],
    )

    assert result == {"c1": "Primary Title"}
    assert source == "primary"
    assert reason == ""
    assert len(primary.calls) == 1
    assert primary.calls[0]["provider"] == "nvidia"
    assert primary.calls[0]["model"] == "moonshotai/kimi-k2.6"


@pytest.mark.asyncio
async def test_generate_titles_fallback_when_primary_fails():
    primary = StubLLMBackend(raise_on_call=True)
    fallback = StubLLMBackend(_title_response({"c1": "Fallback Title"}))
    generator = TitleGenerator(
        primary_llm_backend=primary,
        fallback_llm_backend=fallback,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    conversation = _conversation_with_messages("Hello world")

    result, source, reason = await generator.generate_titles_for_batch(
        [conversation],
        existing_titles=[],
    )

    assert result == {"c1": "Fallback Title"}
    assert source == "fallback"
    assert reason == "primary_failed"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1
    assert fallback.calls[0]["provider"] == "llama"


@pytest.mark.asyncio
async def test_generate_titles_returns_empty_when_no_llm_backends():
    generator = TitleGenerator(
        primary_llm_backend=None,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    conversation = _conversation_with_messages("Hello world")

    result, source, reason = await generator.generate_titles_for_batch(
        [conversation],
        existing_titles=[],
    )

    assert result == {}
    assert source == "fallback_error"
    assert reason == "all_llm_generation_failed"


@pytest.mark.asyncio
async def test_generate_titles_splits_batch_after_failure():
    primary = StubLLMBackend(raise_on_call=True)
    fallback = StubLLMBackend(
        response_content=None,
        raise_on_call=True,
    )
    generator = TitleGenerator(
        primary_llm_backend=primary,
        fallback_llm_backend=fallback,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    c1 = _conversation_with_messages("Hello")
    c2 = _conversation_with_messages("World")

    result, source, reason = await generator.generate_titles_for_batch(
        [c1, c2],
        existing_titles=[],
    )

    assert result == {}
    assert source == "fallback_error"
    assert reason == "all_llm_generation_failed"
    # primary called once for batch, fallback called once for batch,
    # then split into 2 individual calls on primary, 2 on fallback
    assert len(primary.calls) == 3
    assert len(fallback.calls) == 3


@pytest.mark.asyncio
async def test_generate_titles_empty_conversations():
    generator = TitleGenerator(
        primary_llm_backend=None,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )

    result, source, reason = await generator.generate_titles_for_batch(
        [],
        existing_titles=[],
    )

    assert result == {}
    assert source == "none"
    assert reason == ""


@pytest.mark.asyncio
async def test_generate_titles_existing_titles_passed_to_payload():
    primary = StubLLMBackend(_title_response({"c1": "Title One"}))
    generator = TitleGenerator(
        primary_llm_backend=primary,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    conversation = _conversation_with_messages("Hello")

    await generator.generate_titles_for_batch(
        [conversation],
        existing_titles=["Existing A", "Existing B"],
    )

    payload = json.loads(primary.calls[0]["messages"][-1]["content"])
    assert payload["existing_titles"] == ["Existing A", "Existing B"]


@pytest.mark.asyncio
async def test_generate_titles_existing_titles_truncated_to_500():
    primary = StubLLMBackend(_title_response({"c1": "Title One"}))
    generator = TitleGenerator(
        primary_llm_backend=primary,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    conversation = _conversation_with_messages("Hello")

    await generator.generate_titles_for_batch(
        [conversation],
        existing_titles=[f"Title {i}" for i in range(600)],
    )

    payload = json.loads(primary.calls[0]["messages"][-1]["content"])
    assert len(payload["existing_titles"]) == 500


def test_parse_title_response_valid_json():
    content = json.dumps({"titles": [{"id": "abc", "title": "My Title"}]})
    result = _parse_title_response(content)
    assert result == {"abc": "My Title"}


def test_parse_title_response_markdown_code_block():
    content = "```\n" + json.dumps({"titles": [{"id": "abc", "title": "My Title"}]}) + "\n```"
    result = _parse_title_response(content)
    assert result == {"abc": "My Title"}


def test_parse_title_response_markdown_with_json_label():
    content = "```json\n" + json.dumps({"titles": [{"id": "abc", "title": "My Title"}]}) + "\n```"
    result = _parse_title_response(content)
    assert result == {"abc": "My Title"}


def test_parse_title_response_embedded_in_text():
    content = 'Some text before {"titles": [{"id": "abc", "title": "My Title"}]} some text after'
    result = _parse_title_response(content)
    assert result == {"abc": "My Title"}


def test_parse_title_response_missing_titles_list_raises():
    content = json.dumps({"other": []})
    with pytest.raises(ValueError, match="titles list"):
        _parse_title_response(content)


def test_parse_title_response_empty_titles_raises():
    content = json.dumps({"titles": []})
    with pytest.raises(ValueError, match="usable titles"):
        _parse_title_response(content)


def test_parse_title_response_uses_conversation_id_alias():
    content = json.dumps({"titles": [{"conversation_id": "abc", "title": "My Title"}]})
    result = _parse_title_response(content)
    assert result == {"abc": "My Title"}


def test_parse_title_response_skips_items_without_id_or_title():
    content = json.dumps({
        "titles": [
            {"id": "", "title": "No ID"},
            {"id": "abc", "title": ""},
            {"id": "abc", "title": "Valid"},
        ]
    })
    result = _parse_title_response(content)
    assert result == {"abc": "Valid"}


def test_parse_title_response_sanitizes_titles():
    content = json.dumps({"titles": [{"id": "abc", "title": "  Title: Hello World  "}]})
    result = _parse_title_response(content)
    assert result == {"abc": "Hello World"}


def test_render_history_empty_messages():
    generator = TitleGenerator(
        primary_llm_backend=None,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    assert generator._render_history([]) == "(empty session)"


def test_render_history_with_messages():
    generator = TitleGenerator(
        primary_llm_backend=None,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    messages = [
        Message(role=Role.USER, content="Hello"),
        Message(role=Role.ASSISTANT, content="Hi there"),
    ]
    result = generator._render_history(messages)
    assert "## 1. user\nHello" in result
    assert "## 2. assistant\nHi there" in result


def test_render_history_with_tool_calls_and_metadata():
    generator = TitleGenerator(
        primary_llm_backend=None,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    messages = [
        Message(
            role=Role.ASSISTANT,
            content="Using tool",
            tool_calls=[{"name": "search"}],
            metadata={"tool_name": "search", "finish_reason": "stop"},
        ),
    ]
    result = generator._render_history(messages)
    assert "Tool calls:" in result
    assert "Metadata:" in result


def test_render_history_truncates_long_content():
    generator = TitleGenerator(
        primary_llm_backend=None,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=20_000,
    )
    messages = [
        Message(role=Role.USER, content="A" * 10_000),
    ]
    result = generator._render_history(messages)
    assert "[message truncated]" in result


def test_render_history_truncates_total_budget():
    generator = TitleGenerator(
        primary_llm_backend=None,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=50,
    )
    messages = [
        Message(role=Role.USER, content="Hello world this is a test"),
        Message(role=Role.USER, content="Another message here"),
    ]
    result = generator._render_history(messages)
    assert "[session history truncated to title-analysis budget]" in result


@pytest.mark.asyncio
async def test_generate_titles_split_batch_with_fallback_success():
    """When batch fails, split into individual calls; if fallback succeeds on individuals, report correctly."""
    call_count = 0

    class CountingLLM(StubLLMBackend):
        async def chat_completion(self, messages, **kwargs):
            self.calls.append({"messages": messages, **kwargs})
            nonlocal call_count
            call_count += 1
            # Batch call fails, individual calls succeed
            payload = json.loads(messages[-1]["content"])
            if len(payload["sessions"]) > 1:
                raise RuntimeError("batch fails")
            return InferenceResult(content=_title_response({
                payload["sessions"][0]["id"]: f"Title {payload['sessions'][0]['id']}"
            }))

    primary = CountingLLM()
    generator = TitleGenerator(
        primary_llm_backend=primary,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    c1 = _conversation_with_messages("Hello")
    c2 = _conversation_with_messages("World")

    result, source, reason = await generator.generate_titles_for_batch(
        [c1, c2],
        existing_titles=[],
    )

    assert len(result) == 2
    assert source == "primary"
    assert reason == "split_after_batch_failure"


@pytest.mark.asyncio
async def test_call_title_llm_max_tokens_scales_with_batch_size():
    primary = StubLLMBackend(_title_response({"c1": "Title"}))
    generator = TitleGenerator(
        primary_llm_backend=primary,
        fallback_llm_backend=None,
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
        max_history_chars=180_000,
    )
    await generator._call_title_llm(
        primary,
        provider="nvidia",
        model="moonshotai/kimi-k2.6",
        payload={"sessions": []},
        batch_size=10,
    )

    assert primary.calls[0]["max_tokens"] == max(4_096, min(8_192, 768 * 10 + 512))
