"""Result models and defaults for session title services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SESSION_TITLE_CACHE_KEY = "session_title_analysis"
SESSION_TITLE_CACHE_VERSION = 1
DEFAULT_PRIMARY_PROVIDER = "nvidia"
DEFAULT_PRIMARY_MODEL = "moonshotai/kimi-k2.6"
DEFAULT_FALLBACK_PROVIDER = "llama"
DEFAULT_FALLBACK_MODEL = "local-model"
DEFAULT_BATCH_SIZE = 6
DEFAULT_SCAN_LIMIT = 10_000
DEFAULT_MAX_HISTORY_CHARS = 180_000
DEFAULT_DUPLICATE_CHECK_INTERVAL_SECONDS = 300.0
DEFAULT_SIMILARITY_THRESHOLD = 0.9


@dataclass(slots=True)
class SessionTitleResult:
    """Result for one conversation title verification."""

    conversation_id: str
    old_title: str
    new_title: str
    status: str
    source: str
    history_hash: str
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "conversation_id": self.conversation_id,
            "old_title": self.old_title,
            "new_title": self.new_title,
            "status": self.status,
            "source": self.source,
            "history_hash": self.history_hash,
            "reason": self.reason,
        }


@dataclass(slots=True)
class SessionTitleBatchResult:
    """Aggregate result for a batch/all-session title verification."""

    checked: int = 0
    analyzed: int = 0
    updated: int = 0
    cached: int = 0
    skipped: int = 0
    failed: int = 0
    batches: int = 0
    duplicate_groups: int = 0
    primary_model: str = DEFAULT_PRIMARY_MODEL
    fallback_model: str = DEFAULT_FALLBACK_MODEL
    results: list[SessionTitleResult] = field(default_factory=list)

    def add(self, result: SessionTitleResult) -> None:
        self.checked += 1
        if result.status == "updated":
            self.updated += 1
        elif result.status == "cached":
            self.cached += 1
        elif result.status == "skipped":
            self.skipped += 1
        elif result.status == "failed":
            self.failed += 1
        if result.source in {"llm", "llm_fallback"}:
            self.analyzed += 1
        self.results.append(result)

    def merge(self, other: SessionTitleBatchResult) -> None:
        self.checked += other.checked
        self.analyzed += other.analyzed
        self.updated += other.updated
        self.cached += other.cached
        self.skipped += other.skipped
        self.failed += other.failed
        self.batches += other.batches
        self.duplicate_groups += other.duplicate_groups
        self.results.extend(other.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "analyzed": self.analyzed,
            "updated": self.updated,
            "cached": self.cached,
            "skipped": self.skipped,
            "failed": self.failed,
            "batches": self.batches,
            "duplicate_groups": self.duplicate_groups,
            "primary_model": self.primary_model,
            "fallback_model": self.fallback_model,
            "results": [result.to_dict() for result in self.results],
        }
