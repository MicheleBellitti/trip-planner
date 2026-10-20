"""The planner's notion of "now", in Michele's time zone (Europe/Rome).

Validators that compare against the current date (a requested trip must start in the future)
call `today()` / `now()` / `current_month()` through this module, never `datetime.now()`
directly, so there is one place that defines the reference zone. Tests freeze time with
time-machine (`time_machine.travel(...)`), which these helpers honour, or monkeypatch them.
`sleep_until()` waits for an instant on the same clock (a choice's deadline).
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable
from zoneinfo import ZoneInfo

HOME_TIMEZONE = ZoneInfo("Europe/Rome")
"""The user's zone: "today" means today in Rome, wherever the server runs (Railway is UTC)."""


def now() -> dt.datetime:
    """The current instant, timezone-aware, in Europe/Rome."""
    return dt.datetime.now(tz=HOME_TIMEZONE)


def today() -> dt.date:
    """Today's date in Europe/Rome."""
    return now().date()


def current_month() -> str:
    """The current month in Europe/Rome as "YYYY-MM" (the format of DateWindow.month)."""
    return now().strftime("%Y-%m")


async def sleep_until(
    deadline: dt.datetime,
    *,
    now: Callable[[], dt.datetime] = now,
    step_seconds: float = 1.0,
) -> None:
    """Wait until `now()` reaches `deadline` (timezone-aware); return at once when it already
    has. `now()` is read again at least every `step_seconds`, so a clock that jumps (an NTP
    step, time-machine's `shift` in tests) is honoured within one step, and the wait never ends
    early. The consumer's default `ConsumerDeps.sleep_until`."""
    if deadline.tzinfo is None:
        msg = "sleep_until needs a timezone-aware deadline"
        raise ValueError(msg)
    if step_seconds <= 0:
        msg = f"step_seconds must be positive, got {step_seconds}"
        raise ValueError(msg)
    # A poll, not an event: nothing signals a wall clock that moves.
    while True:
        remaining = (deadline - now()).total_seconds()
        if remaining <= 0:
            return
        await asyncio.sleep(min(remaining, step_seconds))
