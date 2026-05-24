"""Vertex AI request payload builder — message conversion, tool formatting, thinking config."""

from __future__ import annotations

import json
from typing import Any

from personagent.infrastructure.llm.vertex_ai.models import (
    DEFAULT_OUTPUT_TOKENS,
    SKIP_THOUGHT_SIGNATURE_VALIDATOR,
    VERTEX_MODELS_BY_ID,
    VertexModelSpec,
)


class VertexContentBuilder:
    """Builds Vertex AI request payloads from PersonAgent internal message format."""

    def __init__(
        self,
        *,
        default_model: str,
        default_max_tokens: int,
    ) -> None:
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens

    def build_payload(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        extra: dict[str, Any],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], str]:
        requested_model = str(extra.get("model") or "").strip()
        model = self._default_model if requested_model in {"", "local-model"} else requested_model
        model_spec = self._model_spec(model)
        system_instruction, contents = self._convert_messages(messages, model_spec)
        effective_max_tokens = self._effective_max_tokens(model_spec, max_tokens)

        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": effective_max_tokens,
        }
        if model_spec.supports_thinking:
            generation_config["thinkingConfig"] = self._thinking_config(model_spec, extra)
        if model_spec.image_output:
            generation_config["responseModalities"] = ["TEXT", "IMAGE"]

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        function_declarations = self._function_declarations(tools or [])
        if function_declarations and model_spec.supports_tools:
            payload["tools"] = [{"functionDeclarations": function_declarations}]

        return payload, model

    def _convert_messages(
        self,
        messages: list[dict[str, Any]],
        model_spec: VertexModelSpec,
    ) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        tool_names_by_id: dict[str, str] = {}

        for message in messages:
            role = str(message.get("role") or "user")
            content = message.get("content") or ""
            if role == "system":
                if content:
                    system_parts.append(str(content))
                continue

            if role == "assistant":
                tool_calls = message.get("tool_calls") or []
                raw_parts = self._content_parts_from_tool_calls(tool_calls)
                parts: list[dict[str, Any]] = []
                if content:
                    parts.append({"text": str(content)})
                for tool_call in tool_calls:
                    function = tool_call.get("function") or {}
                    name = str(function.get("name") or "")
                    if not name:
                        continue
                    call_id = str(tool_call.get("id") or f"vertex-call-{len(tool_names_by_id)}")
                    tool_names_by_id[call_id] = name
                    if raw_parts:
                        continue
                    part: dict[str, Any] = {
                        "functionCall": {
                            "name": name,
                            "args": self._json_args(function.get("arguments")),
                        }
                    }
                    signature = _tool_call_thought_signature(tool_call)
                    if signature:
                        part["thoughtSignature"] = signature
                    parts.append(part)
                if raw_parts:
                    parts = self._ensure_function_call_signatures(raw_parts, model_spec)
                else:
                    parts = self._ensure_function_call_signatures(parts, model_spec)
                if parts:
                    contents.append({"role": "model", "parts": parts})
                continue

            if role == "tool":
                call_id = str(message.get("tool_call_id") or "")
                name = tool_names_by_id.get(call_id) or "tool_result"
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": name,
                                    "response": {"output": str(content)},
                                }
                            }
                        ],
                    }
                )
                continue

            contents.append({"role": "user", "parts": [{"text": str(content)}]})

        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})
        return "\n\n".join(system_parts), contents

    def _function_declarations(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        declarations: list[dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") != "function":
                continue
            function = tool.get("function") or {}
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            declaration: dict[str, Any] = {"name": name}
            if function.get("description"):
                declaration["description"] = function["description"]
            if isinstance(function.get("parameters"), dict):
                declaration["parameters"] = function["parameters"]
            declarations.append(declaration)
        return declarations

    def _content_parts_from_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        for tool_call in tool_calls:
            extra = tool_call.get("extra_content")
            if not isinstance(extra, dict):
                continue
            google = extra.get("google")
            if not isinstance(google, dict):
                continue
            parts = google.get("content_parts")
            if isinstance(parts, list):
                normalized = [part for part in parts if isinstance(part, dict)]
                if normalized:
                    return normalized
        return None

    def _ensure_function_call_signatures(
        self,
        parts: list[dict[str, Any]],
        model: VertexModelSpec,
    ) -> list[dict[str, Any]]:
        if not model.id.startswith("gemini-3-"):
            return parts
        has_function_call = any(part.get("functionCall") for part in parts)
        if not has_function_call or any(_part_thought_signature(part) for part in parts):
            return parts
        signed_parts: list[dict[str, Any]] = []
        for part in parts:
            if part.get("functionCall"):
                next_part = dict(part)
                next_part["thoughtSignature"] = SKIP_THOUGHT_SIGNATURE_VALIDATOR
                signed_parts.append(next_part)
            else:
                signed_parts.append(part)
        return signed_parts

    def _model_spec(self, model: str) -> VertexModelSpec:
        return VERTEX_MODELS_BY_ID.get(
            model,
            VertexModelSpec(
                id=model,
                label=_model_label(model),
                input_tokens=1_048_576,
                output_tokens=DEFAULT_OUTPUT_TOKENS,
                thinking_control="budget" if model.startswith("gemini-2.5-") else "level",
                thinking_budget_min=512 if model.startswith("gemini-2.5-flash-lite") else 1,
                thinking_budget_max=24_576 if model.startswith("gemini-2.5-") else None,
            ),
        )

    def _effective_max_tokens(self, model: VertexModelSpec, max_tokens: int) -> int:
        requested = max_tokens if max_tokens > 0 else self._default_max_tokens
        # Vertex reports a 65,536-token output window for several Gemini models,
        # but maxOutputTokens is validated as an exclusive upper bound.
        upper_bound = 65_535 if model.output_tokens >= 65_536 else model.output_tokens
        return min(requested, upper_bound)

    def _thinking_level(self, reasoning_level: Any) -> str:
        level = str(reasoning_level or "low").strip().lower()
        if level == "medium":
            return "MEDIUM"
        if level in {"high", "xhigh", "max"}:
            return "HIGH"
        return "LOW"

    def _thinking_config(
        self,
        model: VertexModelSpec,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        config: dict[str, Any] = {"includeThoughts": True}
        if model.thinking_control == "budget":
            config["thinkingBudget"] = self._thinking_budget(
                model,
                extra.get("reasoning_budget_tokens"),
                extra.get("reasoning_level"),
            )
        else:
            config["thinkingLevel"] = self._thinking_level(extra.get("reasoning_level"))
        return config

    def _thinking_budget(
        self,
        model: VertexModelSpec,
        requested_budget: Any,
        reasoning_level: Any,
    ) -> int:
        budget = _int_or_none(requested_budget)
        if budget is None or budget <= 0:
            budget = {
                "low": 2048,
                "medium": 4096,
                "high": 8192,
                "xhigh": 16_384,
                "max": 24_576,
            }.get(str(reasoning_level or "low").strip().lower(), 2048)
        if model.thinking_budget_min is not None:
            budget = max(model.thinking_budget_min, budget)
        if model.thinking_budget_max is not None:
            budget = min(model.thinking_budget_max, budget)
        return budget

    def _json_args(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return {"value": value}
            return decoded if isinstance(decoded, dict) else {"value": decoded}
        return {}


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _part_thought_signature(part: dict[str, Any]) -> str:
    value = part.get("thoughtSignature") or part.get("thought_signature")
    return value if isinstance(value, str) else ""


def _tool_call_thought_signature(tool_call: dict[str, Any]) -> str:
    extra = tool_call.get("extra_content")
    if isinstance(extra, dict):
        google = extra.get("google")
        if isinstance(google, dict):
            signature = google.get("thought_signature") or google.get("thoughtSignature")
            if isinstance(signature, str):
                return signature
    return ""


def _model_label(model_id: str) -> str:
    return model_id.replace("-", " ").replace("_", " ").title()
