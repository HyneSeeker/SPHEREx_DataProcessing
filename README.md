# SPHEREx Helium

`spherex-helium` is a Python package and command-line tool for producing a one-day metastable helium intensity plot from public SPHEREx Level 2 data.

The tool is intentionally date-driven: the user provides one UT observing date, and the package finds the corresponding SPHEREx band 1 FITS files, reads them from IRSA cloud storage, computes the He I intensity for every valid exposure, and overlays the north/south polar-pass points selected from JPL Horizons orbit geometry.

## Current Scope

This package currently processes **SPHEREx band 1 only**. The He I wavelength grid and Gaussian fitting window are the ones inherited from the original band 1 analysis scripts:

```text
wavelength range: 0.734-1.116 um
fit window:       1.06-1.11 um
```

Other SPHEREx bands are not exposed as a command-line option because they would need their own wavelength grid and fitting window before the resulting intensity plot can be interpreted safely.

## Installation

From this repository:

```bash
python3 -m pip install -e ".[test]"
```

After installation, the command-line entry point is:

```bash
spherex-helium --help
```

You can also run directly from the source tree without installing:

```bash
PYTHONPATH=src python3 -m spherex_helium.cli --help
```

## Recommended Command

For a full `2025-12-21` band 1 run:

```bash
PYTHONPATH=src python3 -m spherex_helium.cli 2025-12-21 \
  --output he_20251221.png \
  --save-csv he_20251221.csv \
  --prefilter-workers 32 \
  --process-workers 4
```

Do not use `--max-files` for a science run. It is only for short smoke tests.

## What The Pipeline Does

### 1. Parse The Observing Date

The required positional argument is a UT date:

```bash
spherex-helium YYYY-MM-DD
```

For example:

```bash
spherex-helium 2025-12-21
```

The output plot covers `00:00:00` through `24:00:00` UT for that date.

### 2. Request Or Load JPL Horizons Geometry

By default the package requests a JPL Horizons observer table for Earth observed from SPHEREx:

```text
Target body:       Earth
Observer location: @SPHEREx
Time span:         requested UT date
Step size:         1 min
Time digits:       fractional seconds
Angle format:      decimal degrees
Quantities:        14,23
```

Quantity `14` provides Observer sub-longitude and Observer sub-latitude. Quantity `23` provides the S-O-T angle used for the optional max-SOT vertical markers in the legacy-style plot.

You can provide a pre-downloaded Horizons text file instead:

```bash
spherex-helium 2025-12-21 \
  --horizons-file SOT1221.txt \
  --output he_20251221.png
```

The Horizons file must contain the data section between `$$SOE` and `$$EOE`.

### 3. Discover Public IRSA/SPHEREx FITS Files

The default data source is `auto`. It uses the public IRSA/SPHEREx S3 bucket:

```text
bucket:      nasa-irsa-spherex
root prefix: qr2/level2
band:        1
```

The public cloud layout is organized by planning period rather than by observing date. The package therefore:

1. Lists planning-period prefixes under `qr2/level2`.
2. Prioritizes prefixes near the requested ISO week.
3. Enters the Level 2 processing-version directory.
4. Keeps only the band 1 directory, i.e. the `/1/` detector/band path.
5. Uses S3 byte-range reads to inspect FITS headers.
6. Selects files whose observation time falls on the requested date.

For `2025-12-21`, the real public S3 discovery currently resolves to 516 band 1 FITS files. The first and last discovered files are:

```text
first: s3://nasa-irsa-spherex/qr2/level2/2025W51_2A/l2b-v21-2025-357/1/level2_2025W51_2A_0516_1D1_spx_l2b-v21-2025-357.fits
last:  s3://nasa-irsa-spherex/qr2/level2/2025W51_2A/l2b-v21-2025-357/1/level2_2025W51_2A_0743_1D1_spx_l2b-v21-2025-357.fits
```

### 4. Match FITS Times To Horizons Orbit Samples

For each discovered FITS file, the package reads the observation timestamp from the FITS header, preferring:

```text
DATE-AVG
DATE-BEG
DATE-OBS
DATE
```

It then matches that timestamp to the nearest one-minute Horizons sample. By default the maximum allowed difference is 90 seconds:

```bash
--horizons-match-tolerance 90
```

### 5. Label Polar Passes

The full-day intensity curve is computed from all valid band 1 FITS files.

Horizons orbit geometry is used only to decide which points should be highlighted:

```text
North: Observer sub-latitude >= +80 deg
South: Observer sub-latitude <= -80 deg
Other: all other valid exposures
```

The threshold can be changed:

```bash
--orbit-pole-lat-threshold 80
```

For `2025-12-21`, the default `80 deg` threshold labels 37 highlighted polar-pass points among the 516 band 1 files:

```text
North: 15
South: 22
Other: remaining valid exposures
```

The `SPS_ELAT` value from the FITS header is no longer used for the default polar selection. It is still written to the CSV for comparison.

### 6. Read FITS Data From S3

For each selected date-matched band 1 FITS file, the package opens the FITS directly from S3 using Astropy/fsspec. It does not stage the entire day of FITS files on local disk.

For each FITS file:

1. Read the `IMAGE` HDU.
2. Read the `FLAGS` HDU when available.
3. Keep pixels with `FLAGS == 0`.
4. Set flagged pixels to `NaN`.
5. Skip files with no usable finite pixels or insufficient fitting samples.

### 7. Compute He I Intensity

The intensity calculation follows the original script logic:

1. Average the masked image along axis 1 to form a spectrum.
2. Create the band 1 wavelength grid from `0.734` to `1.116 um`.
3. Flip the spectrum to match the original wavelength ordering.
4. Estimate a continuum/background level using iterative one-standard-deviation masks.
5. Subtract that background.
6. Fit a Gaussian plus offset over `1.06-1.11 um`.
7. Convert the Gaussian integral to Rayleigh using:

```text
rayleigh_conversion_factor = 1.751e4
```

The CSV output stores the fitted Gaussian parameters and the final intensity.

### 8. Produce The Plot

The plot contains:

```text
black dash-dot curve: full-day He I intensity from all valid band 1 FITS files
red open circles:     Horizons-selected north polar points
blue open stars:      Horizons-selected south polar points
gray vertical lines:  max S-O-T markers, when Horizons S-O-T data are available
```

The output image is saved as PNG.

## Progress Bars And Speed

The command prints progress bars to the terminal:

```text
Matching Horizons: [#########-------------------] 168/516  32%
Processing FITS:   [############----------------] 240/516  46%
```

`Matching Horizons` performs small FITS-header reads and orbit matching. It is network-latency dominated because it only needs small byte ranges from S3.

`Processing FITS` opens the full image data and runs the intensity calculation. It is heavier because it reads larger FITS content and performs numerical fitting.

The recommended acceleration settings are:

```bash
--prefilter-workers 32 \
--process-workers 4
```

`--prefilter-workers 32` means up to 32 small header reads can happen concurrently. This usually speeds up the Horizons matching step because many small network requests are waiting on S3 response latency.

`--process-workers 4` means up to 4 FITS images are processed concurrently. This can speed up the full processing step, but setting it too high may slow the run down because S3 bandwidth, memory, and CPU fitting all start competing.

Good starting values:

```text
local laptop:       --prefilter-workers 16 or 32, --process-workers 2 or 4
AWS EC2 us-east-1:  --prefilter-workers 32 or 64, --process-workers 4 or 8
```

Disable progress output with:

```bash
--no-progress
```

## Command-Line Options

### Required

`date`

The observing date in `YYYY-MM-DD` format.

```bash
spherex-helium 2025-12-21
```

### Output

`--output PATH`

PNG plot output path.

```bash
--output he_20251221.png
```

`--save-csv PATH`

Optional CSV output path.

```bash
--save-csv he_20251221.csv
```

The CSV columns are:

```text
time
intensity_rayleigh
label
beta
orbit_sub_lon
orbit_sub_lat
filename
uri
gaussian_amp
gaussian_mu
gaussian_sigma
gaussian_offset
```

### Data Discovery

`--data-source auto`

Default. Discover band 1 FITS from the public IRSA/SPHEREx S3 bucket.

`--data-source local`

Read FITS files from a local directory:

```bash
spherex-helium 2025-12-21 \
  --data-source local \
  --local-dir /path/to/fits \
  --horizons-file SOT1221.txt \
  --output he_local.png
```

`--data-source s3-prefix`

List FITS files under a known S3 prefix:

```bash
spherex-helium 2025-12-21 \
  --data-source s3-prefix \
  --s3-prefix s3://nasa-irsa-spherex/qr2/level2/2025W51_2A/l2b-v21-2025-357 \
  --output he_s3prefix.png
```

`--data-source manifest`

Read one URI or local path per line from a text manifest:

```bash
spherex-helium 2025-12-21 \
  --data-source manifest \
  --manifest spherex_20251221_uris.txt \
  --output he_manifest.png
```

`--data-source sia`

Use the IRSA SIA interface. This is retained as a fallback, but the default S3 discovery is preferred for date-driven processing.

### Horizons

`--horizons-file PATH`

Use a local Horizons table instead of requesting the JPL API.

`--no-fetch-horizons`

Skip Horizons download. Use this only when you do not need S-O-T overlays or Horizons polar labels, or when using another classification mode.

`--horizons-quantities TEXT`

Horizons observer-table quantities. The default is:

```bash
--horizons-quantities 14,23
```

Quantity `14` is required for the default orbit-based polar labels.

### Polar Labels

`--classification horizons-orbit`

Default. Label polar points using Horizons Observer sub-latitude.

`--classification beta`

Legacy comparison mode. Label points from the FITS header beta value, using `SPS_ELAT`.

`--classification file-list`

Legacy comparison mode. Label points from external north/south file lists:

```bash
spherex-helium 2025-12-21 \
  --classification file-list \
  --polar-list-dir /path/to/polar-lists \
  --data-source local \
  --local-dir /path/to/fits \
  --output he_filelist.png
```

The directory must contain:

```text
north_pole_spherex_file_ids.txt
south_pole_spherex_file_ids.txt
```

`--orbit-pole-lat-threshold FLOAT`

Absolute Observer sub-latitude threshold for Horizons polar labels. Default:

```bash
--orbit-pole-lat-threshold 80
```

`--horizons-match-tolerance FLOAT`

Maximum time difference in seconds between FITS `DATE-AVG` and the nearest Horizons sample. Default:

```bash
--horizons-match-tolerance 90
```

### Performance

`--prefilter-workers N`

Parallel workers for small FITS-header reads during Horizons matching. Default:

```bash
--prefilter-workers 16
```

`--process-workers N`

Parallel workers for full FITS image processing. Default:

```bash
--process-workers 4
```

`--max-files N`

Process only the first `N` discovered band 1 FITS files. This is for smoke tests only.

```bash
--max-files 5
```

`--no-progress`

Disable progress bars.

### S3 Settings

`--s3-bucket NAME`

Default:

```bash
--s3-bucket nasa-irsa-spherex
```

`--s3-root-prefix PREFIX`

Default:

```bash
--s3-root-prefix qr2/level2
```

`--s3-week-padding N`

Number of neighboring ISO weeks to inspect around the requested date. Default:

```bash
--s3-week-padding 1
```

## Python API

```python
from datetime import date
from pathlib import Path

from spherex_helium import RunConfig, run_day

result = run_day(
    RunConfig(
        observing_date=date(2025, 12, 21),
        output_path=Path("he_20251221.png"),
        save_csv_path=Path("he_20251221.csv"),
        prefilter_workers=32,
        process_workers=4,
    )
)

print(result.count)
```

## Smoke Test

Use a short smoke test before a full run:

```bash
PYTHONPATH=src python3 -m spherex_helium.cli 2025-12-21 \
  --max-files 5 \
  --output smoke.png \
  --save-csv smoke.csv
```

Expected behavior:

```text
Found 5 band 1 FITS files for 2025-12-21
Matching Horizons: ... 5/5 100%
Processing FITS: ... 5/5 100%
Saved smoke.png
Processed N FITS files; skipped M.
```

## Full Run Example

```bash
PYTHONPATH=src python3 -m spherex_helium.cli 2025-12-21 \
  --output he_20251221.png \
  --save-csv he_20251221.csv \
  --prefilter-workers 32 \
  --process-workers 4
```

For `2025-12-21`, public S3 discovery has been verified to find 516 band 1 files. With the default `80 deg` orbit threshold, 37 of those files are highlighted as polar-pass points while the full valid set is used for the intensity curve.

## Packaging

The package is configured with `pyproject.toml` and exposes the console script:

```text
spherex-helium = spherex_helium.cli:main
```

Build a wheel locally with:

```bash
python3 -m pip wheel . --no-deps -w dist
```

Install the generated wheel with:

```bash
python3 -m pip install dist/spherex_helium-0.1.0-py3-none-any.whl
```

For editable development:

```bash
python3 -m pip install -e ".[test]"
```

Run tests:

```bash
PYTHONPATH=src python3 -m pytest -q
```

## Notes

SPHEREx data are public IRSA products. For published work, include the SPHEREx acknowledgement requested by IRSA.

The most efficient AWS location for this workflow is generally close to the public S3 bucket region documented by IRSA, `us-east-1`, because the package streams data from `nasa-irsa-spherex`.
