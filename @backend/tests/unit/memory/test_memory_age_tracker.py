"""Unit tests for MemoryAgeTracker."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from personagent.domain.memory.services.memory_age_tracker import MemoryAge, MemoryAgeTracker


class TestMemoryAgeTracker:
    """Tests for MemoryAgeTracker."""

    @pytest.fixture
    def tracker(self):
        """Create a MemoryAgeTracker instance."""
        return MemoryAgeTracker()

    def _mtime_ms(self, hours_ago: float = 0, days_ago: float = 0) -> int:
        """Helper to compute mtime_ms relative to now."""
        now = datetime.now(UTC).timestamp()
        delta_seconds = hours_ago * 3600 + days_ago * 86400
        return int((now - delta_seconds) * 1000)

    def test_calculate_fresh(self, tracker):
        """Test age calculation for a very recent memory."""
        mtime = self._mtime_ms(hours_ago=0.5)
        age = tracker.calculate(mtime)

        assert age.days == 0
        assert age.is_fresh is True
        assert age.is_stale is False

    def test_calculate_one_day_old(self, tracker):
        """Test age calculation for a 1-day-old memory."""
        mtime = self._mtime_ms(days_ago=1)
        age = tracker.calculate(mtime)

        assert age.days == 1
        assert age.is_fresh is False
        assert age.is_stale is False
        assert age.human_readable() == "1 day ago"

    def test_calculate_stale(self, tracker):
        """Test age calculation for a stale memory (>7 days)."""
        mtime = self._mtime_ms(days_ago=10)
        age = tracker.calculate(mtime)

        assert age.days == 10
        assert age.is_fresh is False
        assert age.is_stale is True
        assert age.human_readable() == "10 days ago"

    def test_calculate_just_now(self, tracker):
        """Test age calculation for a brand new memory."""
        mtime = int(datetime.now(UTC).timestamp() * 1000)
        age = tracker.calculate(mtime)

        assert age.days == 0
        assert age.hours == 0
        assert age.human_readable() == "just now"

    def test_format_staleness_warning(self, tracker):
        """Test staleness warning formatting."""
        fresh_age = MemoryAge(days=0, hours=5, is_fresh=True, is_stale=False)
        assert tracker.format_staleness_warning(fresh_age) is None

        stale_age = MemoryAge(days=10, hours=0, is_fresh=False, is_stale=True)
        warning = tracker.format_staleness_warning(stale_age)
        assert warning is not None
        assert "10 days old" in warning
        assert "system-reminder" in warning

    def test_should_consolidate(self, tracker):
        """Test consolidation threshold check."""
        old_mtime = self._mtime_ms(days_ago=40)
        assert tracker.should_consolidate(old_mtime, min_days=30) is True

        recent_mtime = self._mtime_ms(days_ago=10)
        assert tracker.should_consolidate(recent_mtime, min_days=30) is False

        borderline_mtime = self._mtime_ms(days_ago=30)
        assert tracker.should_consolidate(borderline_mtime, min_days=30) is True
