"""Codex API request payload builders and message converters."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_MODEL = "gpt-5.5"
REASONING_LEVELS = {"low", "medium", "high", "xhigh"}


class CodexPayloadBuilder:
    """Builds Codex Responses API payloads from standard chat messages."""

    def __init__(self, default_model: str = DEFAULT_MODEL) -> None:
        self.default_model = default_model

    def build_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        extra: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        requested_model = str(extra.get("model") or "").strip()
        model = self.default_model if requested_model in {"", "local-model"} else requested_model
        instructions, input_items = self.convert_messages(messages)
        payload: dict[str, Any] = {
            "model": model,
            "instructions": instructions or "You are PersonAgent.",
            "input": input_items,
            "stream": stream,
            "store": False,
        }

        effort = self.reasoning_effort(extra)
        if effort:
            payload["reasoning"] = {"effort": effort, "summary": "auto"}
            payload["include"] = ["reasoning.encrypted_content"]

        converted_tools = self.convert_tools(tools)
        if converted_tools:
            payload["tools"] = converted_tools
            payload["tool_choice"] = self.convert_tool_choice(tool_choice)
            payload["parallel_tool_calls"] = True

        del max_tokens
        return payload

    def convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        instruction_parts: list[str] = []
        input_items: list[dict[str, Any]] = []

        for message in messages:
            role = str(message.get("role") or "user")
            content = self.message_text(message.get("content"))
            if role in {"system", "developer"}:
                if content:
                    instruction_parts.append(content)
                continue

            if role == "tool":
                call_id = str(message.get("tool_call_id") or message.get("call_id") or "")
                if call_id:
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": content,
                        }
                    )
                continue

            if role == "assistant":
                if content:
                    input_items.append(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": content}],
                        }
                    )
                for tool_call in message.get("tool_calls") or []:
                    converted = self.history_tool_call(tool_call)
                    if converted:
                        input_items.append(converted)
                continue

            input_items.append(
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": content}],
                }
            )

        return "\n\n".join(instruction_parts) or None, input_items

    def convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            parameters = function.get("parameters")
            if not isinstance(parameters, dict):
                parameters = {"type": "object", "properties": {}}
            converted.append(
                {
                    "type": "function",
                    "name": name,
                    "description": str(function.get("description") or ""),
                    "strict": False,
                    "parameters": parameters,
                }
            )
        return converted

    def convert_tool_choice(self, tool_choice: str | dict[str, Any] | None) -> str | dict[str, Any]:
        if isinstance(tool_choice, dict):
            function = tool_choice.get("function")
            if tool_choice.get("type") == "function" and isinstance(function, dict):
                name = str(function.get("name") or "").strip()
                if name:
                    return {"type": "function", "name": name}
            return tool_choice
        if tool_choice in {"none", "required", "auto"}:
            return tool_choice
        return "auto"

    def history_tool_call(self, tool_call: Any) -> dict[str, Any] | None:
        if not isinstance(tool_call, dict):
            return None
        function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
        name = str(function.get("name") or tool_call.get("name") or "").strip()
        call_id = str(tool_call.get("id") or tool_call.get("call_id") or "").strip()
        if not name or not call_id:
            return None
        arguments = function.get("arguments") or tool_call.get("arguments") or "{}"
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, ensure_ascii=False)
        return {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
        }

    def message_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(parts)
        if content is None:
            return ""
        return str(content)

    def reasoning_effort(self, extra: dict[str, Any]) -> str | None:
        raw = str(extra.get("reasoning_level") or "").strip().lower()
        if raw == "max":
            return "xhigh"
        if raw in REASONING_LEVELS:
            return raw
        budget = extra.get("reasoning_budget_tokens")
        if isinstance(budget, int) and budget > 0:
            if budget >= 32768:
                return "xhigh"
            if budget >= 16382:
                return "xhigh"
            if budget >= 8192:
                return "high"
            if budget >= 4082:
                return "medium"
            return "low"
        return None
