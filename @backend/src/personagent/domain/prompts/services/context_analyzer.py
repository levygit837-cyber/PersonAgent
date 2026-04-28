"""LLM-first prompt context analysis."""

from __future__ import annotations

import asyncio
import json
import time
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

    def __init__(
        self,
        llm_backend: LLMBackendRepository | None = None,
        *,
        timeout_seconds: float = 12.0,
        long_timeout_seconds: float = 30.0,
        failure_cooldown_seconds: float = 15.0,
        long_context_chars: int = 200_000,
        max_payload_chars: int = 24_000,
    ) -> None:
        self._llm_backend = llm_backend
        self._timeout_seconds = max(0.1, float(timeout_seconds))
        self._long_timeout_seconds = max(self._timeout_seconds, float(long_timeout_seconds))
        self._failure_cooldown_seconds = max(0.0, float(failure_cooldown_seconds))
        self._long_context_chars = max(1, int(long_context_chars))
        self._max_payload_chars = max(1_000, int(max_payload_chars))
        self._cache: dict[str, PromptProfile] = {}
        self._fallback_until: dict[str, float] = {}

    async def analyze(
        self,
        *,
        message: str,
        requested_mode: str | None = "auto",
        available_tools: list[str] | None = None,
        workspace_root: str = "",
        model: str = "local-model",
        provider: str = "llama",
        context_size_chars: int = 0,
        conversation_message_count: int = 0,
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
            return fallback_prompt_profile(
                message=message,
                available_tools=available_tools,
                workspace_root=workspace_root,
                context_size_chars=context_size_chars,
                reason="no_llm_backend",
            )

        backend_key = f"{provider}:{model}".lower()
        if self._is_in_fallback_cooldown(backend_key):
            return fallback_prompt_profile(
                message=message,
                available_tools=available_tools,
                workspace_root=workspace_root,
                context_size_chars=context_size_chars,
                reason="cooldown",
            )

        trimmed_message, message_was_truncated = _trim_for_analysis(
            message,
            max_chars=self._max_payload_chars,
        )
        effective_timeout = self._effective_timeout_seconds(
            provider=provider,
            model=model,
            message_chars=len(message),
            context_size_chars=context_size_chars,
            conversation_message_count=conversation_message_count,
        )
        try:
            result = await asyncio.wait_for(
                self._llm_backend.chat_completion(
                    messages=[
                        {"role": "system", "content": _ANALYZER_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "message": trimmed_message,
                                    "message_chars": len(message),
                                    "message_was_truncated": message_was_truncated,
                                    "available_tools": available_tools or [],
                                    "tool_count": len(available_tools or []),
                                    "workspace_root": workspace_root,
                                    "context_size_chars": context_size_chars,
                                    "conversation_message_count": conversation_message_count,
                                    "long_session": context_size_chars >= self._long_context_chars,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    temperature=0,
                    max_tokens=512,
                    stream=False,
                    tools=None,
                    tool_choice=None,
                    model=model,
                    provider=provider,
                    reasoning_level="low",
                    reasoning_budget_tokens=0,
                ),
                timeout=effective_timeout,
            )
            try:
                profile = _profile_from_json(result.content)
            except (json.JSONDecodeError, ValueError):
                return self._fallback_after_failure(
                    cache_key=cache_key,
                    backend_key=backend_key,
                    reason="invalid_response",
                    provider=provider,
                    model=model,
                    message=message,
                    available_tools=available_tools,
                    workspace_root=workspace_root,
                    context_size_chars=context_size_chars,
                    effective_timeout=effective_timeout,
                )
            self._cache[cache_key] = profile
            return profile
        except TimeoutError:
            return self._fallback_after_failure(
                cache_key=cache_key,
                backend_key=backend_key,
                reason="timeout",
                provider=provider,
                model=model,
                message=message,
                available_tools=available_tools,
                workspace_root=workspace_root,
                context_size_chars=context_size_chars,
                effective_timeout=effective_timeout,
            )
        except Exception:
            return self._fallback_after_failure(
                cache_key=cache_key,
                backend_key=backend_key,
                reason="error",
                provider=provider,
                model=model,
                message=message,
                available_tools=available_tools,
                workspace_root=workspace_root,
                context_size_chars=context_size_chars,
                effective_timeout=effective_timeout,
                exc_info=True,
            )

    def _is_in_fallback_cooldown(self, backend_key: str) -> bool:
        until = self._fallback_until.get(backend_key, 0.0)
        return bool(until and time.monotonic() < until)

    def _fallback_after_failure(
        self,
        *,
        cache_key: str,
        backend_key: str,
        reason: str,
        provider: str,
        model: str,
        message: str,
        available_tools: list[str] | None,
        workspace_root: str,
        context_size_chars: int,
        effective_timeout: float,
        exc_info: bool = False,
    ) -> PromptProfile:
        profile = fallback_prompt_profile(
            message=message,
            available_tools=available_tools,
            workspace_root=workspace_root,
            context_size_chars=context_size_chars,
            reason=reason,
        )
        self._cache[cache_key] = profile
        if self._failure_cooldown_seconds:
            self._fallback_until[backend_key] = time.monotonic() + self._failure_cooldown_seconds
        logger.debug(
            "prompt_context_analysis_fallback",
            reason=reason,
            provider=provider,
            model=model,
            timeout_seconds=effective_timeout,
            base_timeout_seconds=self._timeout_seconds,
            long_timeout_seconds=self._long_timeout_seconds,
            cooldown_seconds=self._failure_cooldown_seconds,
            message_chars=len(message),
            context_size_chars=context_size_chars,
            fallback_source=profile.source,
            exc_info=exc_info,
        )
        return profile

    def _effective_timeout_seconds(
        self,
        *,
        provider: str,
        model: str,
        message_chars: int,
        context_size_chars: int,
        conversation_message_count: int,
    ) -> float:
        provider_key = provider.strip().lower()
        model_key = model.strip().lower()
        provider_floor = {
            "vertex": 18.0,
            "nvidia": 14.0,
            "kimi": 14.0,
            "codex": 14.0,
        }.get(provider_key, self._timeout_seconds)
        timeout = max(self._timeout_seconds, provider_floor)
        if (
            context_size_chars >= self._long_context_chars
            or message_chars >= self._max_payload_chars
            or conversation_message_count >= 80
            or "gemini-3" in model_key
            or "pro" in model_key
            or "gpt-oss" in model_key
        ):
            timeout = max(timeout, self._long_timeout_seconds)
        return timeout

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


def fallback_prompt_profile(
    *,
    message: str = "",
    available_tools: list[str] | None = None,
    workspace_root: str = "",
    context_size_chars: int = 0,
    reason: str = "analysis_unavailable",
) -> PromptProfile:
    mode, secondary_modes, confidence, intent = _fallback_mode_for_message(message)
    surface_hints = _surface_hints_for_mode(mode)
    if available_tools:
        surface_hints = tuple(dict.fromkeys((*surface_hints, "tool")))
    if context_size_chars >= 200_000:
        surface_hints = tuple(dict.fromkeys((*surface_hints, "compact", "memory")))
    if workspace_root:
        surface_hints = tuple(dict.fromkeys((*surface_hints, "workspace")))
    return PromptProfile(
        primary_mode=mode,
        secondary_modes=secondary_modes,
        requested_mode="auto",
        confidence=confidence,
        source="fallback_heuristic" if message else "fallback",
        intent=intent,
        surface_hints=surface_hints,
        raw={
            "reason": reason,
            "message_chars": len(message),
            "context_size_chars": context_size_chars,
            "tool_count": len(available_tools or []),
        },
    )


def _profile_from_json(content: str) -> PromptProfile:
    payload = _extract_json_object(content)
    primary = str(payload.get("primary_mode") or "").strip().lower()
    if primary not in _VALID_CONCRETE_MODES:
        primary = "exploring"
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


def _trim_for_analysis(message: str, *, max_chars: int) -> tuple[str, bool]:
    if len(message) <= max_chars:
        return message, False
    head = max_chars // 2
    tail = max_chars - head
    return (
        message[:head]
        + "\n\n[... message truncated for prompt context analysis ...]\n\n"
        + message[-tail:],
        True,
    )


def _fallback_mode_for_message(
    message: str,
) -> tuple[ConcretePromptMode, tuple[ConcretePromptMode, ...], float, str]:
    text = message.lower()
    writing_terms = (
        "implemente",
        "implementar",
        "corrija",
        "corrigir",
        "aplique",
        "aplicar",
        "crie",
        "criar",
        "adicione",
        "editar",
        "edite",
        "refatore",
        "instale",
        "faça",
        "execute",
        "build",
        "fix",
        "create",
        "add",
        "update",
    )
    research_terms = (
        "pesquise",
        "pesquisar",
        "busque",
        "busca",
        "fontes",
        "documentação",
        "docs",
        "web",
        "internet",
        "latest",
        "recente",
        "atual",
        "browser",
    )
    exploring_terms = (
        "analise",
        "analisar",
        "avalie",
        "avaliar",
        "investigue",
        "investigar",
        "revis",
        "explique",
        "por que",
        "causa",
        "verifique",
        "validar",
    )
    wants_writing = any(term in text for term in writing_terms)
    wants_research = any(term in text for term in research_terms)
    wants_exploring = any(term in text for term in exploring_terms)
    if wants_writing:
        secondary: tuple[ConcretePromptMode, ...] = ("research",) if wants_research else ()
        return "writing", secondary, 0.45, "local fallback: likely implementation task"
    if wants_research:
        return "research", (), 0.4, "local fallback: likely research task"
    if wants_exploring:
        return "exploring", (), 0.35, "local fallback: likely analysis task"
    return "exploring", (), 0.2, "local fallback: default exploration mode"


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
