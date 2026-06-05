from __future__ import annotations

from pathlib import Path
import warnings

import numpy as np
from astropy.io import fits
from scipy.optimize import curve_fit

from .classification import FileListClassifier, classify_beta
from .fitsio import open_fits
from .timeutils import parse_datetime
from .types import ObservationResult, RunConfig


def process_uri(
    uri: str,
    config: RunConfig,
    *,
    file_classifier: FileListClassifier | None = None,
    forced_label: str | None = None,
    orbit_sub_lon: float | None = None,
    orbit_sub_lat: float | None = None,
) -> ObservationResult | None:
    with open_fits(uri) as hdul:
        image_hdu = _image_hdu(hdul)
        date_str = _observation_date_string(image_hdu.header)
        if date_str is None:
            return None

        image = get_masked_image(hdul)
        fit = fit_helium_intensity(
            image,
            wavelength_min_um=config.wavelength_min_um,
            wavelength_max_um=config.wavelength_max_um,
            fit_min_um=config.fit_min_um,
            fit_max_um=config.fit_max_um,
            rayleigh_conversion_factor=config.rayleigh_conversion_factor,
        )
        if fit is None:
            return None

        beta = image_hdu.header.get("SPS_ELAT")
        filename = Path(uri).name
        if forced_label is not None:
            label = forced_label
        elif config.classification == "file-list":
            if file_classifier is None:
                raise ValueError("classification='file-list' requires polar_list_dir")
            label = file_classifier.classify(filename)
        else:
            label = classify_beta(
                beta,
                north_min_deg=config.beta_north_min_deg,
                south_max_deg=config.beta_south_max_deg,
            )

        amp, mu, sigma, offset, integral = fit
        return ObservationResult(
            time=parse_datetime(date_str),
            intensity_rayleigh=integral,
            uri=uri,
            filename=filename,
            label=label,
            beta=float(beta) if beta is not None else None,
            orbit_sub_lon=orbit_sub_lon,
            orbit_sub_lat=orbit_sub_lat,
            gaussian_amp=amp,
            gaussian_mu=mu,
            gaussian_sigma=sigma,
            gaussian_offset=offset,
        )


def get_masked_image(hdul: fits.HDUList) -> np.ndarray:
    image = _image_hdu(hdul).data.astype(float)
    flags_hdu = _flags_hdu(hdul)
    if flags_hdu is None:
        return image
    flags = flags_hdu.data
    if flags.shape != image.shape:
        return image
    return np.where(flags == 0, image, np.nan)


def fit_helium_intensity(
    image: np.ndarray,
    *,
    wavelength_min_um: float = 0.734,
    wavelength_max_um: float = 1.116,
    fit_min_um: float = 1.06,
    fit_max_um: float = 1.11,
    rayleigh_conversion_factor: float = 1.751e4,
) -> tuple[float, float, float, float, float] | None:
    if not np.isfinite(image).any():
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        spec = np.nanmean(image, axis=1)
    if not np.isfinite(spec).any():
        return None
    wavelengths = np.linspace(wavelength_min_um, wavelength_max_um, len(spec))
    spec_flipped = np.flip(spec)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean1 = np.nanmean(spec)
        std1 = np.nanstd(spec)
    if not np.isfinite(mean1) or not np.isfinite(std1):
        return None
    mask1 = ~np.isnan(spec) & (spec >= mean1 - std1) & (spec <= mean1 + std1)
    if not np.any(mask1):
        return None

    mean2 = np.mean(spec[mask1])
    std2 = np.std(spec[mask1])
    mask2 = mask1 & (spec >= mean2 - std2) & (spec <= mean2 + std2)
    if not np.any(mask2):
        return None

    mean3 = np.mean(spec[mask2])
    subtraction_spec = np.full_like(spec_flipped, np.nan)
    valid_spec_mask = ~np.isnan(spec_flipped)
    subtraction_spec[valid_spec_mask] = spec_flipped[valid_spec_mask] - mean3

    mask_wavelength = (wavelengths >= fit_min_um) & (wavelengths <= fit_max_um)
    x_data = wavelengths[mask_wavelength]
    y_data = subtraction_spec[mask_wavelength]
    valid_mask = ~np.isnan(y_data)
    x_fit = x_data[valid_mask]
    y_fit = y_data[valid_mask]
    if len(y_fit) < 4:
        return None

    initial_guess = [
        np.max(y_fit) - np.min(y_fit),
        np.mean(x_fit),
        0.01,
        np.min(y_fit),
    ]
    try:
        popt, _ = curve_fit(_gaussian, x_fit, y_fit, p0=initial_guess, maxfev=10000)
    except (RuntimeError, ValueError, FloatingPointError):
        return None

    amp, mu, sigma, offset = (float(value) for value in popt)
    integral = amp * abs(sigma) * np.sqrt(2 * np.pi) * rayleigh_conversion_factor
    return amp, mu, sigma, offset, float(integral)


def _gaussian(x, amp, mu, sigma, offset):
    return amp * np.exp(-((x - mu) ** 2) / (2 * sigma**2)) + offset


def _image_hdu(hdul: fits.HDUList):
    if "IMAGE" in hdul:
        return hdul["IMAGE"]
    return hdul[1]


def _flags_hdu(hdul: fits.HDUList):
    if "FLAGS" in hdul:
        return hdul["FLAGS"]
    if len(hdul) > 2:
        return hdul[2]
    return None


def _observation_date_string(header) -> str | None:
    for keyword in ("DATE-AVG", "DATE-BEG", "DATE-OBS", "DATE"):
        value = header.get(keyword)
        if value:
            return value
    return None
