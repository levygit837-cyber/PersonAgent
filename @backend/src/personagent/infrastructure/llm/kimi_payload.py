"""Payload building for Kimi Code Anthropic-compatible Messages API."""

from __future__ import annotations

from typing import Any

from personagent.infrastructure.llm.kimi_history import (
    anthropic_history_blocks_from_tool_calls,
    parse_tool_arguments,
)

REASONING_BUDGETS = {
    "low": 2048,
    "medium": 4082,
    "high": 8192,
    "xhigh": 16382,
    "max": 32768,
}

MIN_THINKING_BUDGET_TOKENS = 1024
MAX_THINKING_BUDGET_TOKENS = 30720
FINAL_RESPONSE_TOKEN_RESERVE = 1024


class KimiPayloadBuilder:
    """Builds Anthropic-compatible request payloads."""

    def __init__(self, *, default_model: str, default_max_tokens: int) -> None:
        self.default_model = default_model
        self.default_max_tokens = default_max_tokens

    def build_payload(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        stream: bool,
        extra: dict[str, Any],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del temperature
        requested_model = str(extra.get("model") or "").strip()
        model = self.default_model if requested_model in {"", "local-model"} else requested_model
        effective_max_tokens = self._resolve_effective_max_tokens(max_tokens)
        system, anthropic_messages = self.convert_messages(messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": effective_max_tokens,
            "stream": stream,
        }
        if system:
            payload["system"] = system

        thinking = self.thinking_config(extra, effective_max_tokens)
        if thinking is not None:
            payload["thinking"] = thinking

        anthropic_tools = self.convert_tools(tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools
            converted_tool_choice = self.convert_tool_choice(tool_choice)
            if converted_tool_choice:
                payload["tool_choice"] = converted_tool_choice

        return payload

    def convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []

        for message in messages:
            role = str(message.get("role") or "user")
            if role == "system":
                text = self._coerce_text(message.get("content"))
                if text:
                    system_parts.append(text)
                continue

            if role == "assistant":
                blocks = self._assistant_blocks(message)
                self._append_message(converted, "assistant", blocks)
                continue

            if role == "tool":
                self._append_message(
                    converted,
                    "user",
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(message.get("tool_call_id") or ""),
                            "content": self._coerce_text(message.get("content")),
                        }
                    ],
                )
                continue

            self._append_message(converted, "user", self._text_blocks(message.get("content")))

        if not converted:
            converted.append({"role": "user", "content": [{"type": "text", "text": ""}]})

        return "\n\n".join(system_parts) if system_parts else None, converted

    def _assistant_blocks(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        tool_calls = message.get("tool_calls") or []
        replay_blocks = anthropic_history_blocks_from_tool_calls(tool_calls)
        if replay_blocks:
            return replay_blocks

        blocks = self._text_blocks(message.get("content"))
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            arguments = function.get("arguments") or {}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(tool_call.get("id") or ""),
                    "name": str(function.get("name") or tool_call.get("name") or ""),
                    "input": parse_tool_arguments(arguments),
                }
            )
        return blocks or [{"type": "text", "text": ""}]

    def _append_message(
        self,
        messages: list[dict[str, Any]],
        role: str,
        content: list[dict[str, Any]],
    ) -> None:
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(content)
            return
        messages.append({"role": role, "content": content})

    def _text_blocks(self, content: Any) -> list[dict[str, Any]]:
        text = self._coerce_text(content)
        return [{"type": "text", "text": text}] if text else []

    def _coerce_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        return str(content)

    def convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools or []:
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            converted.append(
                {
                    "name": name,
                    "description": str(function.get("description") or ""),
                    "input_schema": function.get("parameters")
                    if isinstance(function.get("parameters"), dict)
                    else {"type": "object", "properties": {}},
                }
            )
        return converted

    def convert_tool_choice(
        self, tool_choice: str | dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if tool_choice is None:
            return {"type": "auto"}
        if isinstance(tool_choice, str):
            normalized = tool_choice.strip().lower()
            if normalized in {"", "none"}:
                return None
            if normalized in {"required", "any"}:
                return {"type": "any"}
            return {"type": "auto"}
        if isinstance(tool_choice, dict):
            if tool_choice.get("type") == "function":
                function = tool_choice.get("function") or {}
                if function.get("name"):
                    return {"type": "tool", "name": str(function["name"])}
            if tool_choice.get("type") in {"auto", "any", "tool"}:
                return tool_choice
        return {"type": "auto"}

    def thinking_config(
        self,
        extra: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any] | None:
        raw_budget = extra.get("reasoning_budget_tokens")
        if raw_budget is None and extra.get("reasoning_level"):
            raw_budget = REASONING_BUDGETS.get(str(extra["reasoning_level"]).strip().lower())
        if raw_budget is None:
            return None

        budget = int(raw_budget)
        if budget <= 0:
            return {"type": "disabled"}

        budget = max(MIN_THINKING_BUDGET_TOKENS, budget)
        budget = min(budget, MAX_THINKING_BUDGET_TOKENS, max_tokens - FINAL_RESPONSE_TOKEN_RESERVE)
        if budget < MIN_THINKING_BUDGET_TOKENS:
            return {"type": "disabled"}
        return {"type": "enabled", "budget_tokens": budget}

    def _resolve_effective_max_tokens(self, max_tokens: int) -> int:
        if max_tokens > 0:
            return min(max_tokens, self.default_max_tokens)
        return self.default_max_tokens
