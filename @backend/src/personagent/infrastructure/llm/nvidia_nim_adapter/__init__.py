"""Adapter for NVIDIA NIM hosted OpenAI-compatible APIs."""

from personagent.infrastructure.llm.nvidia_nim_adapter.adapter import NvidiaNimAdapter
from personagent.infrastructure.llm.nvidia_nim_adapter.constants import (
    DEFAULT_OUTPUT_TOKENS,
    FINAL_RESPONSE_TOKEN_RESERVE,
    MIN_REASONING_MAX_TOKENS,
)
from personagent.infrastructure.llm.nvidia_nim_adapter.streaming import _response_error_text

__all__ = [
    "NvidiaNimAdapter",
    "DEFAULT_OUTPUT_TOKENS",
    "FINAL_RESPONSE_TOKEN_RESERVE",
    "MIN_REASONING_MAX_TOKENS",
    "_response_error_text",
]
