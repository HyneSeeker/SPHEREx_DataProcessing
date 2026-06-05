from __future__ import annotations

import re
from pathlib import Path


def classify_beta(
    beta: float | None,
    *,
    north_min_deg: float = 80.0,
    south_max_deg: float = -80.0,
) -> str:
    if beta is None:
        return "Other"
    try:
        beta_value = float(beta)
    except (TypeError, ValueError):
        return "Other"
    if beta_value >= north_min_deg:
        return "North"
    if beta_value <= south_max_deg:
        return "South"
    return "Other"


def filename_to_obs_detector_key(filename: str) -> str:
    match = re.match(r"level2_(.+)_spx_l2b-v\d+-\d+-\d+\.fits$", Path(filename).name)
    return match.group(1) if match else Path(filename).name


def file_id_to_obs_detector_key(file_id: str) -> str:
    obs_id, detector = file_id.strip().split("/")
    return f"{obs_id}{detector}"


def read_polar_file_keys(file_path: Path) -> set[str]:
    keys: set[str] = set()
    with open(file_path, "r", encoding="utf-8") as handle:
        for line in handle:
            file_id = line.strip()
            if file_id:
                keys.add(file_id_to_obs_detector_key(file_id))
    return keys


class FileListClassifier:
    def __init__(self, polar_list_dir: Path):
        self.north_keys = read_polar_file_keys(polar_list_dir / "north_pole_spherex_file_ids.txt")
        self.south_keys = read_polar_file_keys(polar_list_dir / "south_pole_spherex_file_ids.txt")

    def classify(self, filename: str) -> str:
        key = filename_to_obs_detector_key(filename)
        if key in self.north_keys:
            return "North"
        if key in self.south_keys:
            return "South"
        return "Other"
