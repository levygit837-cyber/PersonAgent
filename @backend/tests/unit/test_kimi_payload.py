"""Tests for Kimi payload building."""

from personagent.infrastructure.llm.kimi_payload import KimiPayloadBuilder


class TestKimiPayloadBuilder:
    def test_build_payload_basic(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        payload = builder.build_payload(
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.7,
            max_tokens=-1,
            stream=False,
            extra={},
        )
        assert payload["model"] == "kimi-for-coding"
        assert payload["stream"] is False
        assert payload["max_tokens"] == 32768
        assert len(payload["messages"]) == 1

    def test_build_payload_custom_model(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        payload = builder.build_payload(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.7,
            max_tokens=100,
            stream=True,
            extra={"model": "custom-model"},
        )
        assert payload["model"] == "custom-model"
        assert payload["stream"] is True
        assert payload["max_tokens"] == 100

    def test_build_payload_with_tools(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        payload = builder.build_payload(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.7,
            max_tokens=-1,
            stream=False,
            extra={},
            tools=[{"function": {"name": "read", "description": "Read file", "parameters": {"type": "object"}}}],
            tool_choice="auto",
        )
        assert "tools" in payload
        assert payload["tool_choice"] == {"type": "auto"}

    def test_convert_messages_system(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        system, messages = builder.convert_messages([
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"},
        ])
        assert system == "You are helpful"
        assert messages[0]["role"] == "user"

    def test_convert_messages_assistant_with_tools(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        system, messages = builder.convert_messages([
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "function": {"name": "read", "arguments": "{}"}}]},
        ])
        assert messages[0]["role"] == "assistant"
        blocks = messages[0]["content"]
        assert any(b.get("type") == "tool_use" for b in blocks)

    def test_convert_messages_tool_role(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        system, messages = builder.convert_messages([
            {"role": "tool", "tool_call_id": "t1", "content": "result"},
        ])
        assert messages[0]["role"] == "user"
        assert messages[0]["content"][0]["type"] == "tool_result"

    def test_convert_tools(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        tools = builder.convert_tools([
            {"function": {"name": "read", "description": "Read file", "parameters": {"type": "object"}}},
        ])
        assert len(tools) == 1
        assert tools[0]["name"] == "read"
        assert tools[0]["input_schema"] == {"type": "object"}

    def test_convert_tool_choice_string(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        assert builder.convert_tool_choice("auto") == {"type": "auto"}
        assert builder.convert_tool_choice("none") is None
        assert builder.convert_tool_choice("required") == {"type": "any"}

    def test_convert_tool_choice_dict(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        assert builder.convert_tool_choice({"type": "function", "function": {"name": "read"}}) == {"type": "tool", "name": "read"}

    def test_thinking_config_enabled(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        config = builder.thinking_config({"reasoning_budget_tokens": 2048}, 32768)
        assert config == {"type": "enabled", "budget_tokens": 2048}

    def test_thinking_config_disabled(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        config = builder.thinking_config({"reasoning_budget_tokens": 0}, 32768)
        assert config == {"type": "disabled"}

    def test_thinking_config_by_level(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        config = builder.thinking_config({"reasoning_level": "high"}, 32768)
        assert config == {"type": "enabled", "budget_tokens": 8192}

    def test_resolve_effective_max_tokens(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        assert builder._resolve_effective_max_tokens(1000) == 1000
        assert builder._resolve_effective_max_tokens(-1) == 32768
        assert builder._resolve_effective_max_tokens(50000) == 32768

    def test_coerce_text(self) -> None:
        builder = KimiPayloadBuilder(default_model="kimi-for-coding", default_max_tokens=32768)
        assert builder._coerce_text(None) == ""
        assert builder._coerce_text("hello") == "hello"
        assert builder._coerce_text([{"text": "hello"}, " world"]) == "hello world"
