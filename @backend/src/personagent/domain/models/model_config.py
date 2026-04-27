"""Configuração do modelo LLM."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Configuração de um modelo para inferência."""

    id: str
    name: str
    description: str = ""
    ctx_size: int = 262144
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    max_tokens: int = 65536
    stop_sequences: list[str] = field(default_factory=list)
    system_prompt: str | None = None
    cache_type_k: str = "turbo4"
    cache_type_v: str = "turbo4"
    reasoning: str = "off"
    reasoning_budget: int = 2048
    n_gpu_layers: int = 999
    threads: int = 6
    metadata: dict[str, Any] = field(default_factory=dict)
