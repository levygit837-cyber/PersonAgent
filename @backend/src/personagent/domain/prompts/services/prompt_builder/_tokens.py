"""Token estimation utilities for the prompt builder."""

from __future__ import annotations


def estimate_text_tokens(text: str) -> int:
    """Cheap token estimate used before provider-specific tokenizers exist."""

    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)
