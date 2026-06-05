from datetime import date

import numpy as np
from astropy.io import fits

from spherex_helium import RunConfig, run_day


def test_run_day_local_smoke(tmp_path):
    wavelengths = np.linspace(0.734, 1.116, 64)
    gaussian = 10.0 * np.exp(-((wavelengths - 1.082) ** 2) / (2 * 0.009**2))
    spec_flipped = 100.0 + gaussian
    spec = np.flip(spec_flipped)
    image = np.repeat(spec[:, None], 8, axis=1)
    flags = np.zeros_like(image, dtype=np.int16)

    fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(image.astype(np.float32), name="IMAGE"),
            fits.ImageHDU(flags, name="FLAGS"),
        ]
    ).writeto(tmp_path / "level2_fake_spx_l2b-v1-2025-355.fits")
    with fits.open(tmp_path / "level2_fake_spx_l2b-v1-2025-355.fits", mode="update") as hdul:
        hdul["IMAGE"].header["DATE-AVG"] = "2025-12-21T03:00:00.000"
        hdul["IMAGE"].header["SPS_ELAT"] = 85.0

    output_path = tmp_path / "he.png"
    result = run_day(
        RunConfig(
            observing_date=date(2025, 12, 21),
            output_path=output_path,
            data_source="local",
            local_dir=tmp_path,
            fetch_horizons=False,
            classification="beta",
        )
    )

    assert result.count == 1
    assert result.observations[0].label == "North"
    assert result.observations[0].intensity_rayleigh > 0
    assert output_path.exists()
