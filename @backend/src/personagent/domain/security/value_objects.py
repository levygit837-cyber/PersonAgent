"""Domain security value objects — pure functions with no external deps."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def canonical_args_hash(action_kind: str, arguments: dict[str, Any]) -> str:
    """Return a deterministic SHA-256 hash of an action kind + arguments.

    Used for action approval validation and tool result verification.
    The hash is stable across runs because the JSON payload is sorted.
    """
    payload = {
        "action_kind": action_kind,
        "arguments": arguments,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False
    )
    return sha256(encoded.encode("utf-8")).hexdigest()
