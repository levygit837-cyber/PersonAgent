"""Backward-compat shim: vertex_ai_adapter → vertex_ai package.

TODO: Remove this file after all downstream consumers migrate to
      `personagent.infrastructure.llm.vertex_ai`.
"""

from personagent.infrastructure.llm.vertex_ai import VertexAiAdapter
from personagent.infrastructure.llm.vertex_ai.models import (
    DEFAULT_OUTPUT_TOKENS,
    DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_STREAM_POOL_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    GOOGLE_CLOUD_SCOPE,
    SKIP_THOUGHT_SIGNATURE_VALIDATOR,
    VERTEX_MODELS,
    VERTEX_MODELS_BY_ID,
    VertexModelSpec,
)

__all__ = [
    "VertexAiAdapter",
    "VertexModelSpec",
    "VERTEX_MODELS",
    "VERTEX_MODELS_BY_ID",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_STREAM_POOL_TIMEOUT_SECONDS",
    "DEFAULT_OUTPUT_TOKENS",
    "GOOGLE_CLOUD_SCOPE",
    "SKIP_THOUGHT_SIGNATURE_VALIDATOR",
]
