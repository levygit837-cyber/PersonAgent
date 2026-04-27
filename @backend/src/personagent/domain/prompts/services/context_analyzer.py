"""LLM-first prompt context analysis."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

import structlog

from personagent.domain.prompts.models import ConcretePromptMode, PromptMode, PromptProfile
from personagent.domain.prompts.prompt import normalize_prompt_mode
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

logger = structlog.get_logger(__name__)

_VALID_CONCRETE_MODES: set[str] = {"writing", "exploring", "research"}


class PromptContextAnalyzer:
    """Resolve `prompt_mode=auto` with a short, tool-free LLM classification."""

    def __init__(self, llm_backend: LLMBackendRepository | None = None) -> None:
        self._llm_backend = llm_backend
        self._cache: dict[str, PromptProfile] = {}

    async def analyze(
        self,
        *,
        message: str,
        requested_mode: str | None = "auto",
        available_tools: list[str] | None = None,
        workspace_root: str = "",
        model: str = "local-model",
        provider: str = "llama",
    ) -> PromptProfile:
        normalized = normalize_prompt_mode(requested_mode)
        if normalized != "auto":
            return PromptProfile(
                primary_mode=normalized,  # type: ignore[arg-type]
                requested_mode=normalized,
                confidence=1.0,
                source="override",
                intent="explicit prompt_mode override",
                surface_hints=_surface_hints_for_mode(normalized),
            )

        cache_key = self._cache_key(
            message=message,
            available_tools=available_tools,
            workspace_root=workspace_root,
        )
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return PromptProfile(
                primary_mode=cached.primary_mode,
                secondary_modes=cached.secondary_modes,
                intent=cached.intent,
                surface_hints=cached.surface_hints,
                confidence=cached.confidence,
                source="llm_cache",
                requested_mode="auto",
                raw=cached.raw,
            )

        if self._llm_backend is None:
            return fallback_prompt_profile()

        try:
            result = await self._llm_backend.chat_completion(
                messages=[
                    {"role": "system", "content": _ANALYZER_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "message": message,
                                "available_tools": available_tools or [],
                                "workspace_root": workspace_root,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0,
                max_tokens=1024,
                stream=False,
                tools=None,
                tool_choice=None,
                model=model,
                provider=provider,
                reasoning_level="low",
                reasoning_budget_tokens=0,
            )
            profile = _profile_from_json(result.content)
            self._cache[cache_key] = profile
            return profile
        except Exception:
            logger.warning("prompt_context_analysis_failed", exc_info=True)
            return fallback_prompt_profile()

    def _cache_key(
        self,
        *,
        message: str,
        available_tools: list[str] | None,
        workspace_root: str,
    ) -> str:
        raw = json.dumps(
            {
                "message": message,
                "tools": sorted(available_tools or []),
                "workspace_root": workspace_root,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return sha256(raw.encode("utf-8")).hexdigest()


def fallback_prompt_profile() -> PromptProfile:
    return PromptProfile(
        primary_mode="exploring",
        requested_mode="auto",
        confidence=0.0,
        source="fallback",
        intent="analysis unavailable",
        surface_hints=("system", "mode", "tool", "reminder"),
    )


def _profile_from_json(content: str) -> PromptProfile:
    payload = _extract_json_object(content)
    primary = str(payload.get("primary_mode") or "").strip().lower()
    if primary not in _VALID_CONCRETE_MODES:
        raise ValueError("invalid primary_mode")
    secondary: list[ConcretePromptMode] = []
    raw_secondary = payload.get("secondary_modes") or []
    if isinstance(raw_secondary, list):
        for item in raw_secondary:
            mode = str(item).strip().lower()
            if mode in _VALID_CONCRETE_MODES and mode != primary:
                secondary.append(mode)  # type: ignore[arg-type]
    hints = payload.get("surface_hints") or []
    surface_hints = tuple(str(item).strip().lower() for item in hints if str(item).strip())
    confidence = payload.get("confidence", 0.0)
    try:
        parsed_confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        parsed_confidence = 0.0
    if not surface_hints:
        surface_hints = _surface_hints_for_mode(primary)
    return PromptProfile(
        primary_mode=primary,  # type: ignore[arg-type]
        secondary_modes=tuple(secondary),
        intent=str(payload.get("intent") or ""),
        surface_hints=surface_hints,
        confidence=parsed_confidence,
        source="llm",
        requested_mode="auto",
        raw=payload,
    )


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("analysis output must be a JSON object")
    return parsed


def _surface_hints_for_mode(mode: PromptMode | str) -> tuple[str, ...]:
    if mode == "research":
        return ("system", "mode", "tool", "research", "memory", "next_step", "reminder")
    if mode == "writing":
        return ("system", "mode", "tool", "writing", "memory", "next_step", "reminder")
    return ("system", "mode", "tool", "exploring", "memory", "next_step", "reminder")


_ANALYZER_SYSTEM_PROMPT = """You classify a PersonAgent user message for prompt construction.

Return only compact JSON with:
- primary_mode: one of "writing", "exploring", "research"
- secondary_modes: array of zero or more of those modes
- intent: one short phrase describing the user intent
- surface_hints: array of prompt surfaces that should be active, such as system, mode, tool, command, skill, slash, memory, compact, next_step, reminder
- confidence: number from 0 to 1

Mode meanings:
- writing: the user wants files, code, docs, config, tests, or artifacts created or changed.
- exploring: the user wants repository understanding, code reading, mapping, debugging, review, explanation, or local investigation.
- research: the user wants web/browser research, current information, external documentation, sources, or cross-source synthesis.

Prefer mixed secondary_modes when the task clearly combines modes. Do not use keyword rules;
judge the actual task intent and likely tools."""
