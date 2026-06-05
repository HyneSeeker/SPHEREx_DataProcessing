from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True)
class HorizonsRecord:
    """One Horizons observer-table sample."""

    time: datetime
    obs_sub_lon: float | None = None
    obs_sub_lat: float | None = None
    sot: float | None = None


@dataclass(frozen=True)
class ObservationResult:
    """Fitted He I intensity for one SPHEREx FITS exposure."""

    time: datetime
    intensity_rayleigh: float
    uri: str
    filename: str
    label: str
    beta: float | None = None
    orbit_sub_lon: float | None = None
    orbit_sub_lat: float | None = None
    gaussian_amp: float | None = None
    gaussian_mu: float | None = None
    gaussian_sigma: float | None = None
    gaussian_offset: float | None = None


@dataclass(frozen=True)
class RunConfig:
    """Configuration for one observing-date run."""

    observing_date: date
    output_path: Path
    data_source: str = "auto"
    local_dir: Path | None = None
    s3_prefix: str | None = None
    manifest_path: Path | None = None
    collection: str = "spherex_qr2"
    classification: str = "horizons-orbit"
    polar_list_dir: Path | None = None
    horizons_file: Path | None = None
    fetch_horizons: bool = True
    horizons_quantities: str = "14,23"
    save_csv_path: Path | None = None
    max_files: int | None = None
    rayleigh_conversion_factor: float = 1.751e4
    wavelength_min_um: float = 0.734
    wavelength_max_um: float = 1.116
    fit_min_um: float = 1.06
    fit_max_um: float = 1.11
    beta_north_min_deg: float = 80.0
    beta_south_max_deg: float = -80.0
    orbit_pole_lat_threshold_deg: float = 80.0
    horizons_match_tolerance_s: float = 90.0
    prefilter_workers: int = 16
    process_workers: int = 4
    show_progress: bool = True
    request_timeout_s: float = 120.0
    s3_bucket: str = "nasa-irsa-spherex"
    s3_root_prefix: str = "qr2/level2"
    s3_planning_period_week_padding: int = 1


@dataclass
class DayResult:
    """Output from a full day run."""

    observing_date: date
    output_path: Path
    observations: list[ObservationResult] = field(default_factory=list)
    horizons: list[HorizonsRecord] = field(default_factory=list)
    skipped: int = 0

    @property
    def count(self) -> int:
        return len(self.observations)
