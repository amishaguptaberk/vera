from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

DEFAULT_DEMO_TZ = "America/Los_Angeles"


class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant as an aware UTC datetime."""
        ...


class FixedClock:
    """Demo clock pinned to one instant; tests and the synthetic environment inject it."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("clock instant must be timezone-aware")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant

    def set(self, instant: datetime) -> None:
        self._instant = instant.astimezone(UTC)


def demo_local(tz_name: str, year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """A wall-clock time in the demo timezone, returned as UTC."""
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def default_demo_clock(tz_name: str = DEFAULT_DEMO_TZ) -> FixedClock:
    """Fixed at 2026-11-10 09:08 in the demo timezone."""
    return FixedClock(demo_local(tz_name, 2026, 11, 10, 9, 8))
