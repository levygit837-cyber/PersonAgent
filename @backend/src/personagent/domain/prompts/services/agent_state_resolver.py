"""Resolve active agent execution states for prompt construction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from personagent.domain.prompts.models import AgentState, AgentStateProfile, PromptProfile


class AgentStateResolver:
    """Heuristic resolver for per-turn execution-state prompt overlays."""

    def __init__(
        self,
        *,
        long_context_chars: int = 200_000,
        long_conversation_messages: int = 80,
    ) -> None:
        self._long_context_chars = max(1, int(long_context_chars))
        self._long_conversation_messages = max(1, int(long_conversation_messages))

    def resolve(
        self,
        *,
        message: str,
        prompt_profile: PromptProfile,
        available_tools: Sequence[str] | None = None,
        conversation_metadata: Mapping[str, Any] | None = None,
        context_size_chars: int = 0,
        conversation_message_count: int = 0,
        recent_tool_names: Sequence[str] | None = None,
        recent_error_count: int = 0,
        has_session_memory: bool = False,
        has_relevant_memories: bool = False,
        context_compacted: bool = False,
    ) -> AgentStateProfile:
        """Return the active states that should steer this turn."""

        metadata = conversation_metadata or {}
        text = message.lower()
        tool_names = tuple(name for name in available_tools or () if name)
        recent_tools = tuple(name for name in recent_tool_names or () if name)
        long_context = (
            context_size_chars >= self._long_context_chars
            or conversation_message_count >= self._long_conversation_messages
        )
        plan_active = _plan_mode_active(metadata)
        has_memory = has_session_memory or has_relevant_memories
        has_tools = bool(tool_names)
        high_risk = _contains_any(text, _HIGH_RISK_TERMS)
        debug_intent = (
            prompt_profile.primary_mode == "exploring"
            and _contains_any(text, _DEBUG_TERMS)
        ) or recent_error_count > 0
        validation_intent = _contains_any(text, _VALIDATION_TERMS)
        planning_intent = _contains_any(text, _PLANNING_TERMS)
        long_running_intent = _contains_any(text, _LONG_RUNNING_TERMS)

        states: list[AgentState] = ["intake"]
        reasons: list[str] = []

        if plan_active:
            _add(states, "plan_mode")
            reasons.append("active plan mode metadata")

        if prompt_profile.primary_mode in {"exploring", "research"}:
            _add(states, "context_discovery")
            reasons.append(f"{prompt_profile.primary_mode} prompt mode")
        if prompt_profile.primary_mode == "writing":
            _add(states, "implementation")
            reasons.append("writing prompt mode")
        if "research" in prompt_profile.all_modes and "context_discovery" not in states:
            _add(states, "context_discovery")
            reasons.append("research secondary mode")
        if "writing" in prompt_profile.all_modes and "implementation" not in states:
            _add(states, "implementation")
            reasons.append("writing secondary mode")

        if planning_intent or plan_active:
            _add(states, "planning")
        if has_tools:
            _add(states, "tool_execution")
            reasons.append("tools available")
        if debug_intent:
            _add(states, "debug_recovery")
            reasons.append("debug/error signal")
        if prompt_profile.primary_mode in {"writing", "research"} or validation_intent:
            _add(states, "runtime_validation")
        if long_context or context_compacted or _context_compacted(metadata):
            _add(states, "context_compaction")
            reasons.append("long or compacted context")
        if has_memory:
            _add(states, "memory_recall")
            reasons.append("memory available")
        if long_running_intent or conversation_message_count >= 20 or len(tool_names) >= 4:
            _add(states, "user_checkpoint")
        if high_risk and "planning" not in states:
            _add(states, "planning")
            reasons.append("high-risk action terms")
        if recent_tools and "tool_execution" not in states:
            _add(states, "tool_execution")
            reasons.append("recent tool history")

        _add(states, "finalization")

        return AgentStateProfile(
            states=tuple(states),
            source="heuristic",
            reason=", ".join(dict.fromkeys(reasons)) or "default turn state",
            confidence=_confidence_for(states, prompt_profile, recent_error_count),
            raw={
                "prompt_mode": prompt_profile.primary_mode,
                "secondary_modes": list(prompt_profile.secondary_modes),
                "tool_count": len(tool_names),
                "recent_tool_count": len(recent_tools),
                "recent_error_count": recent_error_count,
                "context_size_chars": context_size_chars,
                "conversation_message_count": conversation_message_count,
                "has_session_memory": has_session_memory,
                "has_relevant_memories": has_relevant_memories,
                "context_compacted": context_compacted or _context_compacted(metadata),
                "plan_mode_active": plan_active,
            },
        )


def fallback_agent_state_profile(
    *,
    prompt_profile: PromptProfile | None = None,
    available_tools: Sequence[str] | None = None,
    has_memory: bool = False,
) -> AgentStateProfile:
    """Return a conservative state profile when no resolver is available."""

    profile = prompt_profile or PromptProfile()
    states: list[AgentState] = ["intake"]
    if profile.primary_mode in {"exploring", "research"}:
        states.append("context_discovery")
    if profile.primary_mode == "writing":
        states.append("implementation")
    if available_tools:
        states.append("tool_execution")
    if profile.primary_mode in {"writing", "research"}:
        states.append("runtime_validation")
    if has_memory:
        states.append("memory_recall")
    states.append("finalization")
    return AgentStateProfile(
        states=tuple(dict.fromkeys(states)),
        source="fallback",
        reason="agent state resolver unavailable",
        confidence=0.3,
    )


def _add(states: list[AgentState], state: AgentState) -> None:
    if state not in states:
        states.append(state)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _plan_mode_active(metadata: Mapping[str, Any]) -> bool:
    raw = metadata.get("plan_mode")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, Mapping):
        return bool(raw.get("active"))
    return False


def _context_compacted(metadata: Mapping[str, Any]) -> bool:
    raw = metadata.get("context_compaction")
    return isinstance(raw, Mapping) and bool(raw.get("compacted"))


def _confidence_for(
    states: Sequence[AgentState],
    prompt_profile: PromptProfile,
    recent_error_count: int,
) -> float:
    confidence = max(0.35, min(0.9, prompt_profile.confidence or 0.45))
    if recent_error_count > 0:
        confidence = max(confidence, 0.7)
    if len(states) >= 4:
        confidence = max(confidence, 0.6)
    return confidence


_DEBUG_TERMS = (
    "bug",
    "crash",
    "erro",
    "error",
    "falha",
    "failure",
    "stack",
    "trace",
    "causa",
    "root cause",
    "por que",
    "corrija",
    "fix",
    "debug",
)

_VALIDATION_TERMS = (
    "teste",
    "test",
    "valid",
    "verifique",
    "verify",
    "prove",
    "reprodu",
    "runtime",
    "live",
)

_PLANNING_TERMS = (
    "plan",
    "plano",
    "planeje",
    "arquitetura",
    "strategy",
    "estrategia",
    "sugira",
    "proposal",
)

_LONG_RUNNING_TERMS = (
    "longa",
    "longo",
    "horas",
    "complex",
    "complexo",
    "end-to-end",
    "e2e",
    "persistente",
)

_HIGH_RISK_TERMS = (
    "delete",
    "remova",
    "remove",
    "drop",
    "migration",
    "migracao",
    "deploy",
    "push",
    "production",
    "producao",
    "token",
    "secret",
)
