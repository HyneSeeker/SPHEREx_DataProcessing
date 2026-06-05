from datetime import date, datetime

from spherex_helium.classification import classify_beta, filename_to_obs_detector_key
from spherex_helium.discovery import extract_cloud_uri
from spherex_helium.discovery import _parse_fits_headers
from spherex_helium.horizons import parse_horizons_line
from spherex_helium.timeutils import datetime_to_ut_hour, parse_datetime


def test_parse_datetime_formats():
    assert parse_datetime("2025-12-21T01:02:03.123Z") == datetime(2025, 12, 21, 1, 2, 3, 123000)
    assert parse_datetime("2025-Dec-21 01:02:03.123") == datetime(2025, 12, 21, 1, 2, 3, 123000)
    assert parse_datetime("A.D. 2025-Dec-21 01:02:03.123") == datetime(2025, 12, 21, 1, 2, 3, 123000)


def test_parse_horizons_csv_with_sub_lon_lat_and_sot():
    record = parse_horizons_line("2025-Dec-21 00:01:00.000, 120.5, -30.25, 89.1, /T")
    assert record.time == datetime(2025, 12, 21, 0, 1)
    assert record.obs_sub_lon == 120.5
    assert record.obs_sub_lat == -30.25
    assert record.sot == 89.1


def test_parse_legacy_sot_line():
    record = parse_horizons_line(" 2025-Dec-21 00:01:00.000   89.1 /T")
    assert record.time == datetime(2025, 12, 21, 0, 1)
    assert record.sot == 89.1


def test_classification():
    assert classify_beta(81) == "North"
    assert classify_beta(-81) == "South"
    assert classify_beta(0) == "Other"


def test_filename_key():
    filename = "level2_2025W19_2B_0073_2D3_spx_l2b-v20-2025-247.fits"
    assert filename_to_obs_detector_key(filename) == "2025W19_2B_0073_2D3"


def test_extract_cloud_uri():
    assert extract_cloud_uri("s3://nasa-irsa-spherex/qr2/level2/a.fits") == "s3://nasa-irsa-spherex/qr2/level2/a.fits"
    assert extract_cloud_uri('{"bucket": "nasa-irsa-spherex", "key": "qr2/level2/a.fits"}') == (
        "s3://nasa-irsa-spherex/qr2/level2/a.fits"
    )


def test_datetime_to_ut_hour():
    assert datetime_to_ut_hour(datetime(2025, 12, 21, 6), date(2025, 12, 21)) == 6.0


def test_parse_fits_headers_from_range_bytes():
    primary = (
        "SIMPLE  =                    T / conforms to FITS standard".ljust(80)
        + "BITPIX  =                    8".ljust(80)
        + "NAXIS   =                    0".ljust(80)
        + "END".ljust(80)
    ).encode("ascii")
    primary = primary.ljust(2880, b" ")
    image = (
        "XTENSION= 'IMAGE   '".ljust(80)
        + "BITPIX  =                  -32".ljust(80)
        + "NAXIS   =                    2".ljust(80)
        + "NAXIS1  =                 2040".ljust(80)
        + "NAXIS2  =                 2040".ljust(80)
        + "DATE-AVG= '2025-12-21T03:00:00.000'".ljust(80)
        + "END".ljust(80)
    ).encode("ascii")
    image = image.ljust(2880, b" ")
    headers = _parse_fits_headers(primary + image)
    assert headers[1]["DATE-AVG"] == "2025-12-21T03:00:00.000"
