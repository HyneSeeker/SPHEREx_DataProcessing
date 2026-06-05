from __future__ import annotations

from datetime import date, datetime, time, timedelta


def parse_datetime(value: str) -> datetime:
    """Parse common FITS and Horizons datetime formats."""

    text = value.strip().replace("Z", "")
    if text.startswith("A.D. "):
        text = text[5:].strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%b-%d %H:%M:%S.%f",
        "%Y-%b-%d %H:%M:%S",
        "%Y-%b-%d %H:%M",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(text)


def day_bounds(observing_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(observing_date, time.min)
    return start, start + timedelta(days=1)


def datetime_to_ut_hour(value: datetime, observing_date: date) -> float:
    start, _ = day_bounds(observing_date)
    return (value - start).total_seconds() / 3600.0


def datetime_to_mjd(value: datetime) -> float:
    # MJD epoch: 1858-11-17 00:00:00 UTC.
    epoch = datetime(1858, 11, 17)
    return (value - epoch).total_seconds() / 86400.0
