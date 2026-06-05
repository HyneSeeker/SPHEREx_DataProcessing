from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .pipeline import run_day
from .types import RunConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spherex-helium",
        description="Generate a one-day SPHEREx metastable helium intensity plot.",
    )
    parser.add_argument("date", help="Observing date in YYYY-MM-DD, interpreted as UT day.")
    parser.add_argument("-o", "--output", type=Path, help="Output PNG path.")
    parser.add_argument(
        "--data-source",
        choices=("auto", "local", "s3-prefix", "manifest", "sia"),
        default="auto",
        help="How to find SPHEREx FITS files. Default: auto via public S3 date discovery.",
    )
    parser.add_argument("--local-dir", type=Path, help="Directory containing one day's FITS files.")
    parser.add_argument("--s3-prefix", help="S3 prefix to scan, for example s3://nasa-irsa-spherex/qr2/level2/...")
    parser.add_argument("--manifest", type=Path, help="Text file with one FITS URI/path per line.")
    parser.add_argument("--collection", default="spherex_qr2", help="IRSA SIA2 collection.")
    parser.add_argument(
        "--classification",
        choices=("horizons-orbit", "beta", "file-list"),
        default="horizons-orbit",
        help="North/South selection strategy. Default: Horizons Observer sub-latitude.",
    )
    parser.add_argument("--polar-list-dir", type=Path, help="Directory with north/south pole file-id lists.")
    parser.add_argument("--horizons-file", type=Path, help="Use an existing Horizons text file instead of the API.")
    parser.add_argument("--no-fetch-horizons", action="store_true", help="Skip Horizons download and S-O-T overlay.")
    parser.add_argument(
        "--horizons-quantities",
        default="14,23",
        help="Horizons observer quantities. 14 is Observer sub-lon/sub-lat; 23 adds S-O-T overlay.",
    )
    parser.add_argument("--save-csv", type=Path, help="Optional CSV summary output.")
    parser.add_argument("--max-files", type=int, help="Process only the first N files, useful for smoke tests.")
    parser.add_argument(
        "--orbit-pole-lat-threshold",
        type=float,
        default=80.0,
        help="Absolute Horizons Observer sub-latitude threshold for polar selection. Default: 80 deg.",
    )
    parser.add_argument(
        "--horizons-match-tolerance",
        type=float,
        default=90.0,
        help="Maximum seconds between FITS DATE-AVG and nearest Horizons sample. Default: 90.",
    )
    parser.add_argument(
        "--prefilter-workers",
        type=int,
        default=16,
        help="Parallel workers for small FITS-header reads during Horizons orbit prefiltering. Default: 16.",
    )
    parser.add_argument(
        "--process-workers",
        type=int,
        default=4,
        help="Parallel workers for processing selected FITS images. Default: 4.",
    )
    parser.add_argument("--no-progress", action="store_true", help="Disable terminal progress bars.")
    parser.add_argument("--s3-bucket", default="nasa-irsa-spherex", help="Public SPHEREx S3 bucket.")
    parser.add_argument("--s3-root-prefix", default="qr2/level2", help="Root prefix for level2 spectral images.")
    parser.add_argument(
        "--s3-week-padding",
        type=int,
        default=1,
        help="Number of neighboring ISO weeks to inspect around the requested date.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    observing_date = date.fromisoformat(args.date)
    output = args.output or Path(f"spherex_helium_{observing_date:%Y%m%d}.png")
    config = RunConfig(
        observing_date=observing_date,
        output_path=output,
        data_source=args.data_source,
        local_dir=args.local_dir,
        s3_prefix=args.s3_prefix,
        manifest_path=args.manifest,
        collection=args.collection,
        classification=args.classification,
        polar_list_dir=args.polar_list_dir,
        horizons_file=args.horizons_file,
        fetch_horizons=not args.no_fetch_horizons,
        horizons_quantities=args.horizons_quantities,
        save_csv_path=args.save_csv,
        max_files=args.max_files,
        orbit_pole_lat_threshold_deg=args.orbit_pole_lat_threshold,
        horizons_match_tolerance_s=args.horizons_match_tolerance,
        prefilter_workers=args.prefilter_workers,
        process_workers=args.process_workers,
        show_progress=not args.no_progress,
        s3_bucket=args.s3_bucket,
        s3_root_prefix=args.s3_root_prefix,
        s3_planning_period_week_padding=args.s3_week_padding,
    )
    result = run_day(config)
    print(f"Saved {result.output_path}")
    print(f"Processed {result.count} FITS files; skipped {result.skipped}.")
    if result.observations:
        print(f"Time range: {result.observations[0].time} to {result.observations[-1].time}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
