"""
How current is the data?

NSE closes at 15:30 IST and publishes the day's bhav copy roughly two to three
hours later. So "today" only counts as an expected session once that file has
had time to appear - before then, the most recent data anyone could have is
yesterday's.

Holidays are the awkward part. Knowing them for certain needs a network call to
NSE, which defeats the point of a cheap freshness check. So this works on
weekdays alone and deliberately describes staleness in soft terms: one session
behind is normal on a holiday and is reported as such rather than as a problem.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# Hour (IST) after which the current day's bhav copy should exist.
PUBLISH_HOUR = 19


def now_ist() -> datetime:
    return datetime.now(IST)


def expected_last_session(at: datetime | None = None) -> date:
    """The most recent day for which data should plausibly exist."""
    at = at or now_ist()
    day = at.date()
    if at.hour < PUBLISH_HOUR:
        day -= timedelta(days=1)
    while day.weekday() >= 5:  # rewind over Saturday and Sunday
        day -= timedelta(days=1)
    return day


def sessions_behind(latest: date | str | None, at: datetime | None = None) -> int | None:
    """Weekdays between the data's last session and the expected one."""
    if latest is None:
        return None
    if isinstance(latest, str):
        latest = date.fromisoformat(latest)
    target = expected_last_session(at)
    if latest >= target:
        return 0
    count, cursor = 0, latest
    while cursor < target:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            count += 1
    return count


def describe(latest: date | str | None, at: datetime | None = None) -> dict:
    """A freshness verdict the interface can show without further thought."""
    behind = sessions_behind(latest, at)
    target = expected_last_session(at)

    if behind is None:
        return {"state": "missing", "behind": None,
                "expected_session": target.isoformat(),
                "message": "No price data yet."}
    if behind == 0:
        return {"state": "current", "behind": 0,
                "expected_session": target.isoformat(),
                "message": "Up to date with the last close."}
    if behind == 1:
        return {"state": "likely_current", "behind": 1,
                "expected_session": target.isoformat(),
                "message": "One session behind, which is normal if the last "
                           "weekday was a market holiday."}
    return {"state": "stale", "behind": behind,
            "expected_session": target.isoformat(),
            "message": f"{behind} sessions behind the last close."}
