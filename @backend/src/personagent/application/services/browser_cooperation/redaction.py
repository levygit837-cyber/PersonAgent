"""PII redaction and sanitization for browser cooperation events."""

from __future__ import annotations

import re
from collections.abc import Mapping
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from personagent.application.services.browser_cooperation.helpers import (
    MAX_PAYLOAD_CHARS,
    _cap_json,
    _coerce_dict,
)

_SENSITIVE_FIELD_RE = re.compile(
    r"(password|passcode|passwd|pwd|token|secret|api[_-]?key|auth|session|cookie|"
    r"credit|card|cc-|cc_|cvv|cvc|expiry|iban|routing|ssn|cpf|email)",
    re.IGNORECASE,
)
_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "auth",
    "code",
    "email",
    "key",
    "password",
    "refresh_token",
    "session",
    "state",
    "token",
}
_EMAIL_RE = re.compile(r"^[^@\s]{1,120}@[^@\s]{1,120}\.[^@\s]{2,30}$")
_CARD_RE = re.compile(r"(?:\d[ -]?){13,19}")
_JWT_RE = re.compile(r"^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}$")
_LONG_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=_-]{32,}$")


def _redact_payload(kind: str, target: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _redact_json(_coerce_dict(payload), sensitive_parent=False)
    data = _cap_json(data, max_chars=MAX_PAYLOAD_CHARS)
    sensitive = _is_sensitive_target(target) or _payload_has_sensitive_value(data)
    for key in ("value", "text", "input", "typed_text", "selected_text"):
        if key not in data:
            continue
        value = data.get(key)
        if sensitive:
            data[key] = "[REDACTED]"
            data[f"{key}_redacted"] = True
            if isinstance(value, str):
                data[f"{key}_hash"] = sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]
            elif isinstance(value, Mapping):
                if value.get("hash"):
                    data[f"{key}_hash"] = value.get("hash")
                if value.get("char_count") is not None:
                    data[f"{key}_char_count"] = value.get("char_count")
        elif isinstance(value, str):
            data[key] = {
                "preview": _single_line(value)[:120],
                "char_count": len(value),
                "hash": sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16],
            }
    if kind == "keydown" and isinstance(data.get("key"), str) and len(str(data["key"])) == 1:
        data["key"] = "[character]"
    if isinstance(data.get("url"), str):
        data["url"] = _redact_url(str(data["url"]))
    if isinstance(data.get("from_url"), str):
        data["from_url"] = _redact_url(str(data["from_url"]))
    return data


def _redact_target(target: Mapping[str, Any]) -> dict[str, Any]:
    sensitive = _is_sensitive_target(target)
    data = _redact_json(dict(target), sensitive_parent=False)
    if isinstance(data.get("href"), str):
        data["href"] = _redact_url(str(data["href"]))
    if isinstance(data.get("form_action"), str):
        data["form_action"] = _redact_url(str(data["form_action"]))
    if sensitive:
        data["sensitive"] = True
        for key in ("text", "label", "placeholder", "aria_label", "name", "id"):
            if isinstance(data.get(key), str) and data.get(key):
                data[key] = "[REDACTED]"
    return data


def _redact_json(value: Any, *, sensitive_parent: bool = False) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            sensitive = sensitive_parent or bool(_SENSITIVE_FIELD_RE.search(text_key))
            if sensitive:
                redacted[text_key] = _redacted_value(item)
            else:
                redacted[text_key] = _redact_json(item, sensitive_parent=False)
        return redacted
    if isinstance(value, list):
        return [_redact_json(item, sensitive_parent=sensitive_parent) for item in value[:80]]
    if isinstance(value, str):
        if _looks_sensitive_string(value):
            return _redacted_value(value)
        return value
    return value


def _redacted_value(value: Any) -> dict[str, Any] | str:
    if not isinstance(value, str):
        return "[REDACTED]"
    return {
        "redacted": True,
        "char_count": len(value),
        "hash": sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16],
    }


def _looks_sensitive_string(value: str) -> bool:
    compact = value.strip()
    if not compact:
        return False
    return bool(
        _EMAIL_RE.match(compact)
        or _CARD_RE.search(compact)
        or _JWT_RE.match(compact)
        or _LONG_TOKEN_RE.match(compact)
    )


def _is_sensitive_target(target: Mapping[str, Any]) -> bool:
    if target.get("sensitive") is True:
        return True
    text = " ".join(
        str(target.get(key) or "")
        for key in ("input_type", "type", "autocomplete", "name", "id", "label", "aria_label", "placeholder")
    )
    return bool(_SENSITIVE_FIELD_RE.search(text))


def _payload_has_sensitive_value(payload: Mapping[str, Any]) -> bool:
    for key in ("value", "text", "input", "typed_text", "selected_text"):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        compact = value.strip()
        if _EMAIL_RE.match(compact) or _CARD_RE.search(compact):
            return True
    return False


def _redact_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return value[:2_000]
    if not parsed.query:
        return value[:2_000]
    query = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_QUERY_KEYS or _SENSITIVE_FIELD_RE.search(key) or _looks_sensitive_string(item):
            query.append((key, "[REDACTED]"))
        else:
            query.append((key, item))
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))[:2_000]


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
