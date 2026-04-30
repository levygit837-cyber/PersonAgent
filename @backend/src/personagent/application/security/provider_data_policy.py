"""Provider data-boundary enforcement before hosted model calls."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.domain.exceptions import ErrorCategory, InvalidRequestError

HOSTED_PROVIDERS = {"nvidia", "deepseek", "zenmux", "vertex", "kimi", "codex"}

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key", re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*['\"]?[A-Za-z0-9._~:/+=-]{12,}")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("openai_like_key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{20,}\b")),
    ("nvidia_key", re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("cpf", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
)


@dataclass(frozen=True, slots=True)
class ProviderDataPolicyResult:
    policy: str
    blocked: bool
    findings: dict[str, int]


def enforce_provider_data_policy(
    *,
    request: ChatRequestDTO,
    system_prompt: str | None,
    user_context_message: str | None,
) -> ProviderDataPolicyResult:
    """Block high-confidence sensitive data before calling hosted providers."""

    provider = (request.provider or "").strip().lower()
    if provider not in HOSTED_PROVIDERS:
        return ProviderDataPolicyResult(
            policy="local_only",
            blocked=False,
            findings={},
        )

    text = "\n\n".join(
        item
        for item in (
            request.message,
            request.system_prompt or "",
            system_prompt or "",
            user_context_message or "",
            _json_for_scan(request.context_attachments),
        )
        if item
    )
    findings = _scan_sensitive_text(text)
    if findings:
        raise InvalidRequestError(
            "Hosted provider request blocked because the model context contains potential secrets or sensitive identifiers.",
            code="provider.data_policy_blocked",
            category=ErrorCategory.PROVIDER,
            http_status=403,
            metadata={
                "provider": provider,
                "policy": "blocked",
                "findings": findings,
            },
            safe_for_model=False,
            safe_for_telemetry=True,
        )
    return ProviderDataPolicyResult(
        policy="hosted_allowed",
        blocked=False,
        findings={},
    )


def _scan_sensitive_text(text: str) -> dict[str, int]:
    findings: dict[str, int] = {}
    for label, pattern in _SECRET_PATTERNS:
        count = len(pattern.findall(text))
        if count:
            findings[label] = count
    return findings


def _json_for_scan(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)
