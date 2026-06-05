from __future__ import annotations

import csv
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import sys
from urllib.parse import urlparse

from astropy.io import fits

from .classification import FileListClassifier
from .discovery import discover_observation_uris, read_s3_fits_observation_time
from .horizons import fetch_horizons_for_date, load_horizons, load_horizons_file
from .plotting import plot_day
from .processing import process_uri
from .timeutils import parse_datetime
from .types import DayResult, HorizonsRecord, RunConfig


def run_day(config: RunConfig) -> DayResult:
    """Process one observing date and save the He I intensity plot."""

    horizons = []
    if config.horizons_file is not None:
        horizons = load_horizons_file(str(config.horizons_file))
    elif config.fetch_horizons:
        horizons_text = fetch_horizons_for_date(
            config.observing_date,
            quantities=config.horizons_quantities,
            timeout_s=config.request_timeout_s,
        )
        horizons = load_horizons(horizons_text)

    uris = discover_observation_uris(
        config.observing_date,
        data_source=config.data_source,
        local_dir=config.local_dir,
        s3_prefix=config.s3_prefix,
        manifest_path=config.manifest_path,
        collection=config.collection,
        timeout_s=config.request_timeout_s,
        max_files=config.max_files,
        s3_bucket=config.s3_bucket,
        s3_root_prefix=config.s3_root_prefix,
        s3_planning_period_week_padding=config.s3_planning_period_week_padding,
    )
    if config.max_files is not None and len(uris) > config.max_files:
        uris = uris[: config.max_files]
    _progress_message(config, f"Found {len(uris)} band 1 FITS files for {config.observing_date.isoformat()}")

    file_classifier = None
    if config.classification == "file-list":
        if config.polar_list_dir is None:
            raise ValueError("classification='file-list' requires polar_list_dir")
        file_classifier = FileListClassifier(config.polar_list_dir)

    orbit_matches: dict[str, HorizonsRecord] = {}
    if config.classification == "horizons-orbit":
        orbit_matches = _match_uris_by_horizons_orbit(uris, horizons, config)
        north_count = sum(1 for record in orbit_matches.values() if _label_for_orbit_record(record, config) == "North")
        south_count = sum(1 for record in orbit_matches.values() if _label_for_orbit_record(record, config) == "South")
        _progress_message(config, f"Horizons polar labels: North={north_count}, South={south_count}, Other={len(uris) - len(orbit_matches)}")

    def process_one(uri: str):
        orbit_record = orbit_matches.get(uri)
        if config.classification == "horizons-orbit":
            forced_label = _label_for_orbit_record(orbit_record, config) or "Other"
        else:
            forced_label = None
        return process_uri(
            uri,
            config,
            file_classifier=file_classifier,
            forced_label=forced_label,
            orbit_sub_lon=orbit_record.obs_sub_lon if orbit_record is not None else None,
            orbit_sub_lat=orbit_record.obs_sub_lat if orbit_record is not None else None,
        )

    if config.process_workers > 1 and len(uris) > 1:
        with ThreadPoolExecutor(max_workers=config.process_workers) as executor:
            futures = [executor.submit(process_one, uri) for uri in uris]
            results = _collect_futures_with_progress(futures, "Processing FITS", config)
    else:
        results = []
        progress = _ProgressBar("Processing FITS", len(uris), config.show_progress)
        for uri in uris:
            results.append(process_one(uri))
            progress.update()
        progress.finish()

    observations = []
    skipped = 0
    for result in results:
        if result is None:
            skipped += 1
            continue
        observations.append(result)

    observations.sort(key=lambda item: item.time)
    if not observations:
        if uris:
            raise ValueError(
                f"No valid observations to plot: discovered {len(uris)} FITS files "
                f"for {config.observing_date.isoformat()}, but skipped all {skipped} during processing."
            )
        raise ValueError(
            f"No valid observations to plot: discovered 0 FITS files for {config.observing_date.isoformat()} "
            f"using data_source={config.data_source!r}."
        )
    plot_day(observations, horizons, observing_date=config.observing_date, output_path=config.output_path)

    if config.save_csv_path is not None:
        _write_csv(config.save_csv_path, observations)

    return DayResult(
        observing_date=config.observing_date,
        output_path=config.output_path,
        observations=observations,
        horizons=horizons,
        skipped=skipped,
    )


def _write_csv(path, observations) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "time",
                "intensity_rayleigh",
                "label",
                "beta",
                "orbit_sub_lon",
                "orbit_sub_lat",
                "filename",
                "uri",
                "gaussian_amp",
                "gaussian_mu",
                "gaussian_sigma",
                "gaussian_offset",
            ]
        )
        for item in observations:
            writer.writerow(
                [
                    item.time.isoformat(),
                    item.intensity_rayleigh,
                    item.label,
                    item.beta,
                    item.orbit_sub_lon,
                    item.orbit_sub_lat,
                    item.filename,
                    item.uri,
                    item.gaussian_amp,
                    item.gaussian_mu,
                    item.gaussian_sigma,
                    item.gaussian_offset,
                ]
            )


def _match_uris_by_horizons_orbit(
    uris: list[str],
    horizons: list[HorizonsRecord],
    config: RunConfig,
) -> dict[str, HorizonsRecord]:
    orbit_records = sorted((record for record in horizons if record.obs_sub_lat is not None), key=lambda item: item.time)
    if not orbit_records:
        raise ValueError(
            "classification='horizons-orbit' requires Horizons records with Observer sub-latitude. "
            "Use the default Horizons quantities or provide a compatible --horizons-file."
        )

    matches: dict[str, HorizonsRecord] = {}
    with ThreadPoolExecutor(max_workers=max(1, config.prefilter_workers)) as executor:
        futures = {executor.submit(_read_uri_observation_time, uri): uri for uri in uris}
        progress = _ProgressBar("Matching Horizons", len(futures), config.show_progress)
        for future in as_completed(futures):
            uri = futures[future]
            try:
                obs_time = future.result()
            except Exception:
                obs_time = None
            if obs_time is None:
                progress.update()
                continue
            record = _nearest_horizons_record(obs_time, orbit_records, config.horizons_match_tolerance_s)
            if _label_for_orbit_record(record, config) is not None:
                matches[uri] = record
            progress.update()
        progress.finish()
    return matches


def _nearest_horizons_record(
    obs_time: datetime,
    records: list[HorizonsRecord],
    tolerance_s: float,
) -> HorizonsRecord | None:
    times = [record.time for record in records]
    index = bisect_left(times, obs_time)
    candidates = []
    if index < len(records):
        candidates.append(records[index])
    if index > 0:
        candidates.append(records[index - 1])
    if not candidates:
        return None
    nearest = min(candidates, key=lambda record: abs((record.time - obs_time).total_seconds()))
    if abs((nearest.time - obs_time).total_seconds()) > tolerance_s:
        return None
    return nearest


def _label_for_orbit_record(record: HorizonsRecord | None, config: RunConfig) -> str | None:
    if record is None or record.obs_sub_lat is None:
        return None
    if record.obs_sub_lat >= config.orbit_pole_lat_threshold_deg:
        return "North"
    if record.obs_sub_lat <= -config.orbit_pole_lat_threshold_deg:
        return "South"
    return None


def _read_uri_observation_time(uri: str) -> datetime | None:
    if uri.startswith("s3://"):
        parsed = urlparse(uri)
        return read_s3_fits_observation_time(parsed.netloc, parsed.path.lstrip("/"))
    try:
        header = fits.getheader(Path(uri), ext=1)
    except Exception:
        return None
    for keyword in ("DATE-AVG", "DATE-BEG", "DATE-OBS", "DATE"):
        value = header.get(keyword)
        if value:
            return parse_datetime(value)
    return None


def _collect_futures_with_progress(futures, label: str, config: RunConfig):
    results = []
    progress = _ProgressBar(label, len(futures), config.show_progress)
    for future in as_completed(futures):
        try:
            results.append(future.result())
        except Exception:
            results.append(None)
        progress.update()
    progress.finish()
    return results


def _progress_message(config: RunConfig, message: str) -> None:
    if config.show_progress:
        print(message, file=sys.stderr, flush=True)


class _ProgressBar:
    def __init__(self, label: str, total: int, enabled: bool = True):
        self.label = label
        self.total = max(total, 0)
        self.enabled = enabled and self.total > 0
        self.count = 0
        if self.enabled:
            self._render()

    def update(self, step: int = 1) -> None:
        if not self.enabled:
            return
        self.count = min(self.total, self.count + step)
        self._render()

    def finish(self) -> None:
        if self.enabled:
            self.count = self.total
            self._render()
            print(file=sys.stderr, flush=True)

    def _render(self) -> None:
        width = 28
        fraction = self.count / self.total if self.total else 1.0
        filled = int(width * fraction)
        bar = "#" * filled + "-" * (width - filled)
        percent = int(fraction * 100)
        print(f"\r{self.label}: [{bar}] {self.count}/{self.total} {percent:3d}%", end="", file=sys.stderr, flush=True)
