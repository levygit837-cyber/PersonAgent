"""Serviço para tracking de idade e staleness de memórias.

Calcula há quanto tempo uma memória foi escrita e determina
se deve incluir avisos de staleness no contexto.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class MemoryAge:
    """Idade de uma memória em múltiplas unidades."""

    days: int
    hours: int
    is_fresh: bool  # < 24h
    is_stale: bool  # > 7 dias

    def human_readable(self) -> str:
        """Retorna string legível da idade."""
        if self.days == 0:
            if self.hours == 0:
                return "just now"
            return f"{self.hours} hour{'s' if self.hours > 1 else ''} ago"
        if self.days == 1:
            return "1 day ago"
        return f"{self.days} days ago"


class MemoryAgeTracker:
    """Calcula idade e staleness de memórias."""

    STALE_THRESHOLD_DAYS = 7
    FRESH_THRESHOLD_HOURS = 24

    def calculate(self, mtime_ms: int) -> MemoryAge:
        """Calcula a idade de uma memória a partir do mtime.

        Args:
            mtime_ms: Timestamp da última modificação em milissegundos.

        Returns:
            MemoryAge com idade calculada.
        """
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        diff_ms = max(0, now_ms - mtime_ms)

        diff_hours = diff_ms / (1000 * 3600)
        diff_days = int(diff_hours / 24)
        remaining_hours = int(diff_hours % 24)

        return MemoryAge(
            days=diff_days,
            hours=remaining_hours,
            is_fresh=diff_hours < self.FRESH_THRESHOLD_HOURS,
            is_stale=diff_days >= self.STALE_THRESHOLD_DAYS,
        )

    def format_staleness_warning(self, age: MemoryAge) -> str | None:
        """Retorna warning de staleness se a memória for antiga.

        Args:
            age: Idade da memória.

        Returns:
            String de warning ou None se não for stale.
        """
        if not age.is_stale:
            return None
        return (
            f"<system-reminder>This memory is {age.days} days old. "
            "It may be outdated.</system-reminder>"
        )

    def should_consolidate(self, mtime_ms: int, min_days: int = 30) -> bool:
        """Verifica se uma memória é candidata à consolidação.

        Args:
            mtime_ms: Timestamp da última modificação.
            min_days: Mínimo de dias para considerar consolidação.

        Returns:
            True se a memória deve ser revisada na consolidação.
        """
        age = self.calculate(mtime_ms)
        return age.days >= min_days
