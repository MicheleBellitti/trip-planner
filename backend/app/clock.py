"""The planner's notion of "now", in Michele's time zone (Europe/Rome).

Validators that compare against the current date (a requested trip must start in the future)
call `today()` / `now()` / `current_month()` through this module, never `datetime.now()`
directly, so there is one place that defines the reference zone. Tests freeze time with
time-machine (`time_machine.travel(...)`), which these helpers honour, or monkeypatch them.
"""

from __future__ import annotations

import datetime as dt
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
