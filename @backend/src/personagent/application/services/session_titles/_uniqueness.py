"""Title uniqueness tracker for deduplication."""

from __future__ import annotations

from collections.abc import Iterable

from personagent.application.services.session_titles._common import (
    _normalize_title,
    _title_similarity,
)


class _TitleUniqueness:
    def __init__(self, existing_titles: Iterable[str], similarity_threshold: float) -> None:
        self._similarity_threshold = similarity_threshold
        self._titles: list[str] = []
        self._normalized: set[str] = set()
        for title in existing_titles:
            self.add(title)

    def accepts(self, title: str) -> bool:
        normalized = _normalize_title(title)
        if not normalized or normalized in self._normalized:
            return False
        return all(
            _title_similarity(normalized, existing) < self._similarity_threshold
            for existing in self._normalized
        )

    def add(self, title: str) -> None:
        normalized = _normalize_title(title)
        if normalized:
            self._normalized.add(normalized)
            self._titles.append(title)

    def titles(self) -> list[str]:
        return list(self._titles)
