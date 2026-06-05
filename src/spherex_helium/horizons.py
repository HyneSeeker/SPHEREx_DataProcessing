from __future__ import annotations

import csv
import re
from datetime import date
from io import StringIO

import requests
from scipy.signal import find_peaks

from .timeutils import day_bounds, parse_datetime
from .types import HorizonsRecord

HORIZONS_API_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"


def fetch_horizons_for_date(
    observing_date: date,
    *,
    quantities: str = "14,23",
    timeout_s: float = 120.0,
) -> str:
    """Fetch a Horizons observer table for Earth as observed from SPHEREx."""

    start, stop = day_bounds(observing_date)
    params = {
        "format": "text",
        "COMMAND": "'399'",
        "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "OBSERVER",
        "CENTER": "'@SPHEREx'",
        "START_TIME": f"'{start:%Y-%m-%d %H:%M:%S}'",
        "STOP_TIME": f"'{stop:%Y-%m-%d %H:%M:%S}'",
        "STEP_SIZE": "'1 min'",
        "QUANTITIES": f"'{quantities}'",
        "CSV_FORMAT": "YES",
        "TIME_DIGITS": "FRACSEC",
        "ANG_FORMAT": "DEG",
    }
    response = requests.get(HORIZONS_API_URL, params=params, timeout=timeout_s)
    response.raise_for_status()
    return response.text


def load_horizons(path_or_text: str) -> list[HorizonsRecord]:
    """Parse a Horizons text table from file content."""

    records: list[HorizonsRecord] = []
    in_data_section = False
    for raw_line in path_or_text.splitlines():
        line = raw_line.strip()
        if "$$SOE" in line:
            in_data_section = True
            continue
        if "$$EOE" in line:
            break
        if not in_data_section or not line:
            continue
        record = parse_horizons_line(line)
        if record is not None:
            records.append(record)
    return records


def load_horizons_file(path: str) -> list[HorizonsRecord]:
    with open(path, "r", encoding="utf-8") as handle:
        return load_horizons(handle.read())


def parse_horizons_line(line: str) -> HorizonsRecord | None:
    """Parse CSV or fixed-width Horizons observer lines.

    The package requests quantity 14 (observer sub-lon/sub-lat) and 23 (S-O-T)
    by default, but this parser also accepts files containing only either group.
    """

    csv_record = _parse_csv_line(line)
    if csv_record is not None:
        return csv_record
    return _parse_legacy_sot_line(line) or _parse_space_sub_lon_lat_line(line)


def max_sot_peak_hours(records: list[HorizonsRecord]) -> list[int]:
    values = [record.sot for record in records]
    finite = [value for value in values if value is not None]
    if len(finite) != len(values) or not values:
        return []
    peaks, _ = find_peaks(values, height=0)
    return [int(index) for index in peaks]


def _parse_csv_line(line: str) -> HorizonsRecord | None:
    if "," not in line:
        return None
    row = next(csv.reader(StringIO(line), skipinitialspace=True), [])
    if not row:
        return None
    try:
        stamp = parse_datetime(row[0])
    except Exception:
        return None

    numbers = [_to_float(value) for value in row[1:]]
    finite = [value for value in numbers if value is not None]
    obs_lon = finite[0] if len(finite) >= 1 else None
    obs_lat = finite[1] if len(finite) >= 2 else None
    sot = finite[2] if len(finite) >= 3 else None
    return HorizonsRecord(stamp, obs_lon, obs_lat, sot)


def _parse_legacy_sot_line(line: str) -> HorizonsRecord | None:
    date_match = re.match(
        r"\s*(\d{4}-[A-Za-z]{3}-\d{2}\s+\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)",
        line,
    )
    if not date_match:
        return None
    sot_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*,?\s*/[TL]", line[date_match.end() :])
    if not sot_match:
        return None
    return HorizonsRecord(parse_datetime(date_match.group(1)), sot=float(sot_match.group(1)))


def _parse_space_sub_lon_lat_line(line: str) -> HorizonsRecord | None:
    date_match = re.match(
        r"\s*(\d{4}-[A-Za-z]{3}-\d{2}\s+\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)",
        line,
    )
    if not date_match:
        return None
    numbers = re.findall(r"[+-]?\d+(?:\.\d+)?", line[date_match.end() :])
    if len(numbers) < 2:
        return None
    return HorizonsRecord(
        parse_datetime(date_match.group(1)),
        obs_sub_lon=float(numbers[0]),
        obs_sub_lat=float(numbers[1]),
    )


def _to_float(value: str) -> float | None:
    text = value.strip()
    if not text or text.lower() == "n.a.":
        return None
    match = re.match(r"([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1))
