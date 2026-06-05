from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import xml.etree.ElementTree as ET

import requests
from astropy.table import Table
from io import BytesIO

from .timeutils import day_bounds, datetime_to_mjd, parse_datetime

IRSA_SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
SPHEREX_BUCKET = "nasa-irsa-spherex"
S3_XML_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
BAND1_DETECTOR_PREFIX = "1"


def discover_observation_uris(
    observing_date: date,
    *,
    data_source: str = "auto",
    local_dir: Path | None = None,
    s3_prefix: str | None = None,
    manifest_path: Path | None = None,
    collection: str = "spherex_qr2",
    timeout_s: float = 120.0,
    max_files: int | None = None,
    s3_bucket: str = SPHEREX_BUCKET,
    s3_root_prefix: str = "qr2/level2",
    s3_planning_period_week_padding: int = 1,
) -> list[str]:
    if data_source == "local":
        if local_dir is None:
            raise ValueError("data_source='local' requires local_dir")
        return discover_local_fits(local_dir)
    if data_source == "manifest":
        if manifest_path is None:
            raise ValueError("data_source='manifest' requires manifest_path")
        return read_manifest(manifest_path)
    if data_source == "s3-prefix":
        if s3_prefix is None:
            raise ValueError("data_source='s3-prefix' requires s3_prefix")
        return list_s3_prefix(s3_prefix)
    if data_source == "auto":
        return discover_s3_by_date(
            observing_date,
            bucket=s3_bucket,
            root_prefix=s3_root_prefix,
            week_padding=s3_planning_period_week_padding,
            timeout_s=timeout_s,
            max_files=max_files,
        )
    if data_source == "sia":
        return discover_irsa_sia(observing_date, collection=collection, timeout_s=timeout_s)
    raise ValueError(f"Unknown data_source={data_source!r}")


def discover_local_fits(local_dir: Path) -> list[str]:
    return [str(path) for path in sorted(local_dir.glob("*.fits"))]


def read_manifest(manifest_path: Path) -> list[str]:
    uris: list[str] = []
    with open(manifest_path, "r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text and not text.startswith("#"):
                uris.append(text)
    return uris


def list_s3_prefix(s3_prefix: str) -> list[str]:
    import fsspec

    fs = fsspec.filesystem("s3", anon=True)
    prefix = s3_prefix.rstrip("/")
    paths = fs.glob(f"{prefix}/**/*.fits")
    return [path if path.startswith("s3://") else f"s3://{path}" for path in sorted(paths)]


def discover_s3_by_date(
    observing_date: date,
    *,
    bucket: str = SPHEREX_BUCKET,
    root_prefix: str = "qr2/level2",
    week_padding: int = 1,
    timeout_s: float = 120.0,
    max_files: int | None = None,
) -> list[str]:
    """Discover public SPHEREx QR2 FITS files for one UT date from S3.

    The S3 layout is organized by planning period, not observation date. We
    therefore inspect nearby ISO-week planning-period prefixes and filter each
    candidate file using the IMAGE header DATE-AVG/DATE-BEG/DATE-OBS keyword.
    Only a byte range containing the FITS headers is requested during discovery.
    """

    root = root_prefix.strip("/")
    wanted_periods = _planning_period_codes_ordered(observing_date, week_padding)
    period_prefixes_by_code = {}
    for prefix in _list_s3_common_prefixes(bucket, f"{root}/", timeout_s=timeout_s):
        code = _planning_period_code_from_prefix(prefix)
        if code in wanted_periods:
            period_prefixes_by_code.setdefault(code, []).append(prefix)

    uris: list[str] = []
    for period_code in wanted_periods:
        period_prefixes = period_prefixes_by_code.get(period_code, [])
        for period_prefix in _sort_period_prefixes_for_date(period_prefixes, observing_date):
            period_uris = _discover_s3_period_date_uris(
                bucket,
                period_prefix,
                observing_date,
                timeout_s=timeout_s,
                max_files=None if max_files is None else max_files - len(uris),
            )
            uris.extend(period_uris)
            if max_files is not None and len(uris) >= max_files:
                return sorted(uris)
    return sorted(uris)


def _discover_s3_period_date_uris(
    bucket: str,
    period_prefix: str,
    observing_date: date,
    *,
    timeout_s: float,
    max_files: int | None,
) -> list[str]:
    uris: list[str] = []
    for version_prefix in _list_s3_common_prefixes(bucket, period_prefix, timeout_s=timeout_s):
        version_uris = _discover_s3_version_date_uris(
            bucket,
            version_prefix,
            observing_date,
            timeout_s=timeout_s,
            max_files=None if max_files is None else max_files - len(uris),
        )
        uris.extend(version_uris)
        if max_files is not None and len(uris) >= max_files:
            return uris
    return uris


def _discover_s3_version_date_uris(
    bucket: str,
    version_prefix: str,
    observing_date: date,
    *,
    timeout_s: float,
    max_files: int | None,
) -> list[str]:
    uris: list[str] = []
    for detector_prefix in _list_s3_common_prefixes(bucket, version_prefix, timeout_s=timeout_s):
        if _band_from_detector_prefix(detector_prefix) != BAND1_DETECTOR_PREFIX:
            continue
        keys = [
            key
            for key in _list_s3_keys(bucket, detector_prefix, timeout_s=timeout_s)
            if key.endswith(".fits")
        ]
        span = _s3_key_date_span(bucket, keys, timeout_s=timeout_s)
        if span is None:
            continue
        first_date, last_date = span
        if observing_date < first_date or observing_date > last_date:
            continue
        limit = None if max_files is None else max_files - len(uris)
        for key in _select_s3_keys_for_date(bucket, keys, observing_date, timeout_s=timeout_s, limit=limit):
            uris.append(f"s3://{bucket}/{key}")
            if max_files is not None and len(uris) >= max_files:
                return uris
    return uris


def read_s3_fits_observation_time(
    bucket: str,
    key: str,
    *,
    timeout_s: float = 120.0,
    header_bytes: int = 65536,
) -> object | None:
    url = f"https://{bucket}.s3.us-east-1.amazonaws.com/{key}"
    response = requests.get(
        url,
        headers={"Range": f"bytes=0-{header_bytes - 1}"},
        timeout=timeout_s,
    )
    response.raise_for_status()
    headers = _parse_fits_headers(response.content)
    image_header = headers[1] if len(headers) > 1 else (headers[0] if headers else {})
    for keyword in ("DATE-AVG", "DATE-BEG", "DATE-OBS", "DATE"):
        value = image_header.get(keyword)
        if value:
            return parse_datetime(value)
    return None


def _s3_key_date_span(
    bucket: str,
    keys: list[str],
    *,
    timeout_s: float,
) -> tuple[date, date] | None:
    if not keys:
        return None
    first_time = read_s3_fits_observation_time(bucket, keys[0], timeout_s=timeout_s)
    last_time = read_s3_fits_observation_time(bucket, keys[-1], timeout_s=timeout_s)
    if first_time is None or last_time is None:
        return None
    return first_time.date(), last_time.date()


def _select_s3_keys_for_date(
    bucket: str,
    keys: list[str],
    observing_date: date,
    *,
    timeout_s: float,
    limit: int | None = None,
) -> list[str]:
    if not keys:
        return []
    if limit is not None and limit <= 0:
        return []

    cache: dict[int, date | None] = {}

    def date_at(index: int) -> date | None:
        if index not in cache:
            obs_time = read_s3_fits_observation_time(bucket, keys[index], timeout_s=timeout_s)
            cache[index] = obs_time.date() if obs_time is not None else None
        return cache[index]

    start = _lower_bound_date(keys, observing_date, date_at)
    stop = _lower_bound_date(keys, date.fromordinal(observing_date.toordinal() + 1), date_at)
    selected = keys[start:stop]
    if limit is not None:
        return selected[:limit]
    return selected


def _lower_bound_date(keys: list[str], target: date, date_at) -> int:
    left = 0
    right = len(keys)
    while left < right:
        mid = (left + right) // 2
        mid_date = date_at(mid)
        if mid_date is None or mid_date >= target:
            right = mid
        else:
            left = mid + 1
    return left


def discover_irsa_sia(
    observing_date: date,
    *,
    collection: str = "spherex_qr2",
    timeout_s: float = 120.0,
) -> list[str]:
    start, stop = day_bounds(observing_date)
    params = {
        "COLLECTION": collection,
        "TIME": f"{datetime_to_mjd(start)} {datetime_to_mjd(stop)}",
        "RESPONSEFORMAT": "VOTABLE",
    }
    response = requests.get(IRSA_SIA_URL, params=params, timeout=timeout_s)
    response.raise_for_status()
    table = Table.read(BytesIO(response.content), format="votable")
    uris = [_row_to_uri(row) for row in table]
    return sorted({uri for uri in uris if uri})


def _list_s3_common_prefixes(bucket: str, prefix: str, *, timeout_s: float) -> list[str]:
    prefixes: list[str] = []
    for root in _iter_s3_list_pages(bucket, prefix, delimiter="/", timeout_s=timeout_s):
        for item in root.findall("s3:CommonPrefixes", S3_XML_NS):
            prefix_node = item.find("s3:Prefix", S3_XML_NS)
            if prefix_node is not None and prefix_node.text:
                prefixes.append(prefix_node.text)
    return prefixes


def _list_s3_keys(bucket: str, prefix: str, *, timeout_s: float) -> list[str]:
    keys: list[str] = []
    for root in _iter_s3_list_pages(bucket, prefix, delimiter=None, timeout_s=timeout_s):
        for item in root.findall("s3:Contents", S3_XML_NS):
            key_node = item.find("s3:Key", S3_XML_NS)
            if key_node is not None and key_node.text:
                keys.append(key_node.text)
    return keys


def _iter_s3_list_pages(bucket: str, prefix: str, *, delimiter: str | None, timeout_s: float):
    token = None
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if delimiter is not None:
            params["delimiter"] = delimiter
        if token:
            params["continuation-token"] = token
        response = requests.get(
            f"https://{bucket}.s3.us-east-1.amazonaws.com/",
            params=params,
            timeout=timeout_s,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        yield root
        truncated = root.findtext("s3:IsTruncated", default="false", namespaces=S3_XML_NS)
        if truncated.lower() != "true":
            break
        token = root.findtext("s3:NextContinuationToken", namespaces=S3_XML_NS)
        if not token:
            break


def _planning_period_codes_ordered(observing_date: date, week_padding: int) -> list[str]:
    offsets = [0]
    for offset in range(1, week_padding + 1):
        offsets.extend([offset, -offset])

    codes: list[str] = []
    seen: set[str] = set()
    for week_offset in offsets:
        shifted = date.fromordinal(observing_date.toordinal() + 7 * week_offset)
        iso = shifted.isocalendar()
        code = f"{iso.year}W{iso.week:02d}"
        if code not in seen:
            codes.append(code)
            seen.add(code)
    return codes


def _planning_period_code_from_prefix(prefix: str) -> str | None:
    match = re.search(r"/(\d{4}W\d{2})_[^/]+/$", prefix)
    return match.group(1) if match else None


def _band_from_detector_prefix(prefix: str) -> str | None:
    match = re.search(r"/([1-6])/$", prefix)
    return match.group(1) if match else None


def _sort_period_prefixes_for_date(prefixes: list[str], observing_date: date) -> list[str]:
    preferred_half = "1" if observing_date.isoweekday() <= 3 else "2"

    def key(prefix: str):
        match = re.search(r"/\d{4}W\d{2}_(\d)[^/]*/$", prefix)
        half = match.group(1) if match else ""
        return (0 if half == preferred_half else 1, prefix)

    return sorted(prefixes, key=key)


def _parse_fits_headers(content: bytes) -> list[dict[str, str]]:
    headers: list[dict[str, str]] = []
    offset = 0
    while offset + 80 <= len(content):
        header, header_length = _parse_one_fits_header(content[offset:])
        if header is None or header_length <= 0:
            break
        headers.append(header)
        data_length = _fits_data_length(header)
        offset += header_length + data_length
        if len(headers) >= 2:
            break
    return headers


def _parse_one_fits_header(content: bytes) -> tuple[dict[str, str] | None, int]:
    header: dict[str, str] = {}
    cards_seen = 0
    for card_start in range(0, len(content) - 79, 80):
        card = content[card_start : card_start + 80].decode("ascii", errors="ignore")
        cards_seen += 1
        keyword = card[:8].strip()
        if keyword == "END":
            return header, int(math.ceil(cards_seen * 80 / 2880.0) * 2880)
        if not keyword or card[8:10] != "= ":
            continue
        header[keyword] = _parse_fits_card_value(card[10:])
    return None, 0


def _parse_fits_card_value(value_comment: str) -> str:
    text = value_comment.split("/", 1)[0].strip()
    if text.startswith("'"):
        chars: list[str] = []
        escaped = False
        for char in text[1:]:
            if char == "'" and not escaped:
                break
            chars.append(char)
            escaped = char == "'"
        return "".join(chars).strip()
    return text


def _fits_data_length(header: dict[str, str]) -> int:
    try:
        bitpix = abs(int(header.get("BITPIX", "0")))
        naxis = int(header.get("NAXIS", "0"))
    except ValueError:
        return 0
    if naxis <= 0 or bitpix <= 0:
        return 0
    elements = 1
    for index in range(1, naxis + 1):
        try:
            elements *= int(header.get(f"NAXIS{index}", "0"))
        except ValueError:
            return 0
    bytes_count = elements * bitpix // 8
    return int(math.ceil(bytes_count / 2880.0) * 2880)


def _row_to_uri(row) -> str | None:
    names = set(row.colnames)
    if "cloud_access" in names:
        uri = extract_cloud_uri(_cell_to_text(row["cloud_access"]))
        if uri:
            return uri
    if "access_url" in names:
        return _cell_to_text(row["access_url"])
    return None


def extract_cloud_uri(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    if text.startswith("s3://"):
        return text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return _dict_to_s3_uri(parsed)
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                uri = _dict_to_s3_uri(item)
                if uri:
                    return uri

    s3_match = re.search(r"s3://[A-Za-z0-9._/-]+", text)
    if s3_match:
        return s3_match.group(0)
    bucket_match = re.search(r"bucket['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9._-]+)", text, re.I)
    key_match = re.search(r"(?:key|object)['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9._/-]+\.fits)", text, re.I)
    if bucket_match and key_match:
        return f"s3://{bucket_match.group(1)}/{key_match.group(1)}"
    url = _http_s3_url_to_uri(text)
    if url:
        return url
    return None


def _dict_to_s3_uri(value: dict) -> str | None:
    for key in ("s3_url", "s3_uri", "uri", "url"):
        item = value.get(key)
        if isinstance(item, str) and item.startswith("s3://"):
            return item
    bucket = value.get("bucket") or value.get("Bucket")
    object_key = value.get("key") or value.get("Key") or value.get("object") or value.get("path")
    if bucket and object_key:
        return f"s3://{bucket}/{object_key}"
    return None


def _http_s3_url_to_uri(value: str) -> str | None:
    parsed = urlparse(value)
    if not parsed.scheme.startswith("http"):
        return None
    host = parsed.netloc
    path = parsed.path.lstrip("/")
    if host.startswith(f"{SPHEREX_BUCKET}.s3"):
        return f"s3://{SPHEREX_BUCKET}/{path}"
    query = parse_qs(parsed.query)
    for item in query.get("uri", []) + query.get("s3_uri", []):
        decoded = unquote(item)
        if decoded.startswith("s3://"):
            return decoded
    return None


def _cell_to_text(value) -> str:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)
