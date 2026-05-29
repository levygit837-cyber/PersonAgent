"""Token utilities for the prompt builder."""

from __future__ import annotations

from personagent.domain.token_counting import count_text_tokens


def estimate_text_tokens(text: str) -> int:
    """Count prompt tokens with the shared tokenizer fallback."""
    return count_text_tokens(text)
