#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Star lists from a GFA frame: Gaussian matched filter + windowed centroid.

``detect_peaks`` is the detector of ``gfa_actions.matched_filter_peaks``
(sanghyunchun/KSPEC_ICS#27), moved here so the astrometry can use it without
importing ``gfa_actions``. ``source_list`` adds a centroid and a flux per peak
and returns the list solve-field takes as input (an astrometry.net xylist).

Solving from this list instead of the image (solve-field's own simplexy
detection) was benchmarked on the GFA PC on 40 frames of 2026-11-06: 38/40
solved against 35/40, and a camera that does not solve gives up in 2-14 s
instead of running into ``--cpulimit`` (~70 s), because a short clean list
runs out of quads quickly. The list costs ~0.3 s per frame.
"""

from typing import Optional, Tuple

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.table import Table


def detect_peaks(
    img: np.ndarray,
    fwhm: float = 7.0,
    nsigma: float = 6.0,
    box_size: int = 64,
    border: int = 8,
) -> Tuple[Optional[Table], np.ndarray]:
    """
    Peaks of a Gaussian matched filter on a GFA frame.

    The local background (photutils Background2D, ``box_size`` px boxes) is
    subtracted and the image is convolved with a unit-sum Gaussian of FWHM
    ``fwhm`` px. Dividing by the local rms times sqrt(sum k^2) gives a
    detection S/N map. That map is rescaled by its own sigma-clipped std,
    because the pixel noise is correlated (the filtered noise is 1.6-2x the
    white-noise value on the 2026-10-28 frames). Peaks above ``nsigma``, at
    most one per ``fwhm`` box and none within ``border`` px of the edge, are
    the stars. Zero pixels (hot pixels zeroed upstream) are ignored.

    fwhm = 7, nsigma = 6 is the best setting on the 182 frames of
    2026-10-28: 88-92 % of the reference stars with < 1 spurious peak per
    frame, against 24-28 % for DAOStarFinder fwhm = 3, 5 sigma. Any fwhm
    from 5 to 8 px gives >= 97 % of the best S/N for those ~7 px stars.

    Returns
    -------
    peaks : astropy Table or None
        ``find_peaks`` output (``x_peak``, ``y_peak``, 0-based pixels), None
        when there is no peak or no usable noise estimate.
    sub : ndarray
        The background-subtracted image (0 on bad pixels).
    """
    from scipy import ndimage
    from photutils.background import (
        Background2D,
        MedianBackground,
        StdBackgroundRMS,
    )
    from photutils.detection import find_peaks

    img = np.asarray(img, dtype=float)
    bad = ~np.isfinite(img) | (img <= 0)
    bkg = Background2D(
        img,
        box_size,
        filter_size=3,
        mask=bad,
        bkg_estimator=MedianBackground(),
        bkgrms_estimator=StdBackgroundRMS(),
    )
    sub = np.where(bad, 0.0, img - bkg.background)

    sig = fwhm / 2.3548
    delta = np.zeros((81, 81))
    delta[40, 40] = 1.0
    knorm = np.sqrt(np.sum(ndimage.gaussian_filter(delta, sig, truncate=4.0) ** 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        snr = ndimage.gaussian_filter(sub, sig, truncate=4.0) / (
            bkg.background_rms * knorm
        )
    bad |= ~np.isfinite(snr)
    snr[bad] = 0.0
    _, _, renorm = sigma_clipped_stats(
        snr[::2, ::2], mask=bad[::2, ::2], sigma=3.0, maxiters=5
    )
    if not renorm > 0:
        return None, sub
    snr /= renorm

    box = max(3, int(round(fwhm)))
    peaks = find_peaks(
        snr,
        nsigma,
        box_size=box if box % 2 else box + 1,
        mask=bad,
        border_width=border,
    )
    if peaks is None or len(peaks) == 0:
        return None, sub
    return peaks, sub


def windowed_centroid(
    sub: np.ndarray, x0: float, y0: float, fwhm: float = 7.0, n_iter: int = 10
) -> Tuple[float, float]:
    """
    Gaussian-weighted (windowed) centroid around (x0, y0), 0-based pixels.

    Window sigma = fwhm / 2.3548, half-size 3 sigma, iterated to 1e-3 px.
    Falls back to (x0, y0) when the weights vanish or the centroid walks
    more than ``fwhm`` from the peak.
    """
    sig = fwhm / 2.3548
    h = int(np.ceil(3 * sig))
    x, y = float(x0), float(y0)
    ny, nx = sub.shape
    for _ in range(n_iter):
        xi, yi = int(round(x)), int(round(y))
        x1, x2 = max(xi - h, 0), min(xi + h + 1, nx)
        y1, y2 = max(yi - h, 0), min(yi + h + 1, ny)
        yy, xx = np.mgrid[y1:y2, x1:x2]
        w = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sig**2)) * sub[y1:y2, x1:x2]
        s = w.sum()
        if not s > 0:
            return float(x0), float(y0)
        xn, yn = (w * xx).sum() / s, (w * yy).sum() / s
        if abs(xn - x0) > fwhm or abs(yn - y0) > fwhm:
            return float(x0), float(y0)
        done = abs(xn - x) < 1e-3 and abs(yn - y) < 1e-3
        x, y = float(xn), float(yn)
        if done:
            break
    return x, y


def source_list(
    img: np.ndarray,
    fwhm: float = 7.0,
    nsigma: float = 6.0,
    box_size: int = 64,
    border: int = 8,
) -> Table:
    """
    Star list of a GFA frame for solve-field.

    Matched-filter peaks (``detect_peaks``), a windowed centroid and an
    aperture flux (radius ``fwhm``) on the background-subtracted image.

    Returns
    -------
    Table with columns X, Y (1-based FITS pixels, the xylist convention of
    astrometry.net) and FLUX, sorted by FLUX descending; empty when nothing
    is detected.
    """
    from photutils.aperture import CircularAperture, aperture_photometry

    peaks, sub = detect_peaks(
        img, fwhm=fwhm, nsigma=nsigma, box_size=box_size, border=border
    )
    if peaks is None:
        return Table({"X": np.zeros(0), "Y": np.zeros(0), "FLUX": np.zeros(0)})

    xy = np.array(
        [
            windowed_centroid(sub, x, y, fwhm=fwhm)
            for x, y in zip(peaks["x_peak"], peaks["y_peak"])
        ],
        dtype=float,
    )
    flux = np.asarray(
        aperture_photometry(sub, CircularAperture(xy, r=fwhm))["aperture_sum"],
        dtype=float,
    )
    order = np.argsort(-flux)
    return Table(
        {"X": xy[order, 0] + 1.0, "Y": xy[order, 1] + 1.0, "FLUX": flux[order]}
    )


def write_xylist(table: Table, path: str, width: int, height: int) -> None:
    """Write ``table`` (X, Y, FLUX) as an xylist with IMAGEW / IMAGEH."""
    hdu = fits.BinTableHDU(table)
    hdu.header["IMAGEW"] = int(width)
    hdu.header["IMAGEH"] = int(height)
    hdu.writeto(path, overwrite=True)
