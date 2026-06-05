from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from astropy.io import fits


@contextmanager
def open_fits(uri: str) -> Iterator[fits.HDUList]:
    """Open a local, HTTP, or S3 FITS URI.

    For S3 this uses anonymous fsspec access, which lets Astropy perform range
    reads instead of staging the full day of data on local disk.
    """

    if _is_remote(uri):
        fsspec_kwargs = {"default_fill_cache": False}
        if uri.startswith("s3://"):
            fsspec_kwargs["anon"] = True
        try:
            with fits.open(
                uri,
                use_fsspec=True,
                fsspec_kwargs=fsspec_kwargs,
                memmap=False,
            ) as hdul:
                yield hdul
                return
        except TypeError:
            pass

        import fsspec

        storage_options = {"anon": True} if uri.startswith("s3://") else {}
        with fsspec.open(uri, "rb", **storage_options) as handle:
            with fits.open(handle, memmap=False) as hdul:
                yield hdul
    else:
        with fits.open(Path(uri), memmap=True) as hdul:
            yield hdul


def _is_remote(uri: str) -> bool:
    return uri.startswith(("s3://", "http://", "https://"))
