"""Resultados de inferência do LLM."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    """Imagem gerada por um modelo multimodal."""

    mime_type: str
    data: str = ""
    alt: str = ""
    artifact_id: str = ""
    url: str = ""
    size_bytes: int = 0
    sha256: str = ""

    def to_dict(self) -> dict[str, str | int]:
        data: dict[str, str | int] = {
            "mime_type": self.mime_type,
            "alt": self.alt,
        }
        if self.data:
            data["data"] = self.data
        if self.artifact_id:
            data["artifact_id"] = self.artifact_id
        if self.url:
            data["url"] = self.url
        if self.size_bytes:
            data["size_bytes"] = self.size_bytes
        if self.sha256:
            data["sha256"] = self.sha256
        return data


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """Resultado completo de uma inferência não-streaming."""

    content: str
    reasoning_content: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    model: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    images: list[GeneratedImage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """Um chunk de uma resposta em streaming."""

    content: str = ""
    reasoning_content: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    images: list[GeneratedImage] = field(default_factory=list)
    is_thinking: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Retorna True se o chunk não tem conteúdo significativo."""
        return (
            not self.content
            and not self.reasoning_content
            and not self.tool_calls
            and not self.images
            and not self.metadata
            and self.finish_reason is None
        )

    @property
    def is_finished(self) -> bool:
        """Retorna True se este é o chunk final."""
        return self.finish_reason is not None
