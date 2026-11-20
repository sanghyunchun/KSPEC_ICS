#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GFA chip WCS refit: fixed distortion + linear fit to Gaia DR3 at the epoch.

solve-field fits a fresh SIP distortion (order 2) on every frame from the
~20 index stars it matched, and its index is Gaia DR2 at J2015.5 without
proper motion. Both move the chip solution with the star field: the GFA
field center (boresight) then differs by (0.77, 1.16) arcsec rms (E, N)
between fields. This module keeps solve-field's answer only as the starting
point and refits each chip:

1. Gaia DR3 stars around the chip center from a local catalogue
   (``GaiaCatalog``: FITS/ECSV files with ra, dec, pmra, pmdec made before
   the night, e.g. one per tile with ``GFA/make_gaia_catalog.py``), moved to
   the observation epoch with their proper motions.
2. Every detection of the frame's star list matched to them through the
   solve-field WCS (nearest, unique, < 3 px).
3. The fixed distortion of the chip (``etc/gfa_distortion.json``: the
   telescope's planner mapping seen by that chip, as SIP order 3, nothing
   fitted) applied to the pixel offsets, then a weighted linear TAN fit
   (CRVAL and CD; CRPIX stays at the chip center), clipped at 3.5 sigma.
   Weights 1 / (a^2 + (b Fref / F)^2), a = 0.079", b = 0.135", Fref = 10th
   percentile of the list's fluxes (centroid error model of the 2026-10/11
   frames after the fixed distortion is removed). The clipping runs on the
   distortion-corrected positions.

The result is a TAN-SIP header with the fixed SIP terms: everything that
reads ``astro_*.fits`` through astropy WCS (boresight, guider) uses it as
before. Offline on 758 state-A sets of 25 fields (2026-10-28 ... 11-08) the
GFA center then varies by (0.41, 0.27) arcsec between fields (the repeat
level on one field), and the jump when one camera drops out is 0.32 arcsec
instead of 0.69-0.82.
"""

import glob
import json
import os
import threading
from typing import Dict, Optional, Tuple

import numpy as np
from astropy.io import fits
from astropy.table import Table
from astropy.time import Time
from astropy.wcs import WCS

AS = 3600.0
GAIA_EPOCH = 2016.0  # Gaia DR3 reference epoch


# --------------------------------------------------------------------------
# geometry helpers (degrees in and out)
# --------------------------------------------------------------------------
def gnomonic(ra, dec, ra0, dec0):
    """Standard coordinates (xi east, eta north) [deg] about (ra0, dec0)."""
    ra, dec, ra0, dec0 = (np.radians(x) for x in (ra, dec, ra0, dec0))
    c = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    xi = np.cos(dec) * np.sin(ra - ra0) / c
    eta = (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)) / c
    return np.degrees(xi), np.degrees(eta)


def gnomonic_inv(xi, eta, ra0, dec0):
    xi, eta, ra0, dec0 = (np.radians(x) for x in (xi, eta, ra0, dec0))
    d = np.cos(dec0) - eta * np.sin(dec0)
    ra = ra0 + np.arctan2(xi, d)
    dec = np.arctan2(np.sin(dec0) + eta * np.cos(dec0), np.hypot(xi, d))
    return np.degrees(ra) % 360, np.degrees(dec)


def _unit(ra, dec):
    ra, dec = np.radians(ra), np.radians(dec)
    return np.stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)], axis=-1)


def sip_eval(coef: Dict[str, float], u, v):
    """Sum of c u^p v^q over {"A_p_q": c} (any prefix)."""
    out = np.zeros_like(np.asarray(u, float))
    for key, c in coef.items():
        _, p, q = key.rsplit("_", 2)
        out = out + c * u ** int(p) * v ** int(q)
    return out


def fit_tan(u, v, ra, dec, crval, w=None, niter=3):
    """Linear TAN fit with CRPIX fixed: xi = c0 + CD (u, v).

    ``u, v``: (distortion-corrected) pixel offsets from CRPIX. Returns CRVAL
    [deg], CD [deg/px] and the residuals [arcsec, (n, 2)].
    """
    sw = np.ones_like(u) if w is None else np.sqrt(w)
    a = np.column_stack([np.ones_like(u), u, v])
    aw = a * sw[:, None]
    crval = tuple(crval)
    for it in range(niter + 1):
        xi, eta = gnomonic(ra, dec, *crval)
        cx = np.linalg.lstsq(aw, xi * sw, rcond=None)[0]
        cy = np.linalg.lstsq(aw, eta * sw, rcond=None)[0]
        if it < niter:
            crval = gnomonic_inv(cx[0], cy[0], *crval)
    res = np.c_[xi - a @ cx, eta - a @ cy] * AS
    return crval, np.array([[cx[1], cx[2]], [cy[1], cy[2]]]), res


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------
class GaiaCatalog:
    """
    Gaia DR3 stars from the FITS / ECSV files of a directory.

    Columns ra, dec [deg, ICRS, epoch 2016.0], pmra, pmdec [mas/yr] (missing
    or NaN -> 0); ``phot_g_mean_mag`` optional. Files may overlap (duplicate
    source_id are dropped). Loaded once; reloaded when the set of files or
    their mtimes change.
    """

    def __init__(self, directory: str):
        self.directory = os.path.expanduser(directory)
        self._key = None
        self.ra = self.dec = self.pmra = self.pmdec = np.zeros(0)
        self._tree = None
        self._lock = threading.Lock()

    def _files(self):
        pats = ("*.fits", "*.fits.gz", "*.ecsv")
        files = sorted(f for p in pats for f in glob.glob(os.path.join(self.directory, p)))
        return files, tuple((f, os.path.getmtime(f)) for f in files)

    def _load(self):
        with self._lock:
            self._load_locked()

    def _load_locked(self):
        from scipy.spatial import cKDTree

        files, key = self._files()
        if key == self._key:
            return
        ra, dec, pmra, pmdec, sid = [], [], [], [], []
        for f in files:
            t = Table.read(f)
            n = len(t)
            ra.append(np.asarray(t["ra"], float))
            dec.append(np.asarray(t["dec"], float))
            for col, acc in (("pmra", pmra), ("pmdec", pmdec)):
                if col in t.colnames:
                    acc.append(np.nan_to_num(np.ma.filled(np.ma.asarray(t[col], float), 0.0)))
                else:
                    acc.append(np.zeros(n))
            if "source_id" in t.colnames:
                sid.append(np.asarray(t["source_id"], np.int64))
            else:  # no id: keep every row (negative ids never collide with Gaia's)
                sid.append(-1 - np.arange(n, dtype=np.int64) - sum(len(a) for a in ra[:-1]))
        if ra:
            sid = np.concatenate(sid)
            _, keep = np.unique(sid, return_index=True)
            self.ra, self.dec = np.concatenate(ra)[keep], np.concatenate(dec)[keep]
            self.pmra, self.pmdec = np.concatenate(pmra)[keep], np.concatenate(pmdec)[keep]
            self._tree = cKDTree(_unit(self.ra, self.dec)) if len(self.ra) else None
        else:
            self.ra = self.dec = self.pmra = self.pmdec = np.zeros(0)
            self._tree = None
        self._key = key

    def __len__(self):
        self._load()
        return len(self.ra)

    def cone(self, ra0: float, dec0: float, radius_deg: float, epoch: float) -> Tuple[np.ndarray, np.ndarray]:
        """Stars within ``radius_deg`` of (ra0, dec0), at ``epoch`` [Julian year]."""
        self._load()
        if self._tree is None:
            return np.zeros(0), np.zeros(0)
        ii = np.array(self._tree.query_ball_point(_unit(ra0, dec0), 2 * np.sin(np.radians(radius_deg) / 2)), int)
        if len(ii) == 0:
            return np.zeros(0), np.zeros(0)
        dt = epoch - GAIA_EPOCH
        dec = self.dec[ii] + self.pmdec[ii] * dt / 3.6e6
        ra = self.ra[ii] + self.pmra[ii] * dt / 3.6e6 / np.cos(np.radians(self.dec[ii]))
        return ra % 360.0, dec


def load_distortion(path: str) -> Dict[str, Dict[str, Dict[str, float]]]:
    """gfa_distortion.json -> {serial: {"A": {...}, "B": {...}, "AP": {...}, "BP": {...}}}."""
    with open(path, "r") as f:
        doc = json.load(f)
    cams = doc["cameras"]
    # a camera without its own entry (e.g. not solved during the calibration) gets the
    # mean: the terms depend only on sep_deg and the pixel pitch, equal to 0.2 %
    keys = {k: list(next(iter(cams.values()))[k]) for k in ("A", "B", "AP", "BP")}
    cams["default"] = {
        k: {n: float(np.mean([c[k][n] for c in cams.values() if isinstance(c, dict) and k in c]))
            for n in names}
        for k, names in keys.items()
    }
    return cams


def frame_epoch(header, name: str = "") -> Optional[float]:
    """Julian year of the exposure.

    From the file name ``D<yyyymmdd>_T<hhmmss>`` (UTC) when given, else the
    date of DATE-OBS (the GFA writes the local date there, TIME-OBS local),
    else MJD-OBS. A day is plenty: 10 mas/yr x 1 day = 0.03 mas.
    """
    import re

    m = re.search(r"D(\d{4})(\d{2})(\d{2})_T(\d{2})(\d{2})(\d{2})", os.path.basename(name or ""))
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        return float(Time(f"{y}-{mo}-{d}T{hh}:{mm}:{ss}", scale="utc").jyear)
    if "DATE-OBS" in header:
        try:
            return float(Time(str(header["DATE-OBS"])[:10], scale="utc").jyear)
        except Exception:
            pass
    if "MJD-OBS" in header:
        try:
            return float(Time(float(header["MJD-OBS"]), format="mjd", scale="utc").jyear)
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------
# the refit
# --------------------------------------------------------------------------
def refine_wcs(
    header: fits.Header,
    x: np.ndarray,
    y: np.ndarray,
    flux: np.ndarray,
    cat_ra: np.ndarray,
    cat_dec: np.ndarray,
    sip: Dict[str, Dict[str, float]],
    match_px: float = 3.0,
    min_stars: int = 6,
    error_model: Tuple[float, float] = (0.079, 0.135),
    clip: float = 3.5,
    floor_arcsec: float = 0.3,
):
    """
    Refit one chip.

    header: solve-field solution (CRPIX at the chip center); x, y: detections
    (FITS 1-based pixels) with their fluxes; cat_ra, cat_dec: catalogue at the
    observation epoch; sip: this chip's fixed {"A", "B", "AP", "BP"}.

    Returns (new_header_cards, matches, info) or (None, None, info) when fewer
    than ``min_stars`` stars match. new_header_cards: fits.Header with the
    WCS keywords to put on the frame; matches: dict of arrays (x, y, flux,
    ra, dec) of the stars used.
    """
    x, y, flux = (np.asarray(a, float) for a in (x, y, flux))
    info = {"n_det": int(len(x)), "n_cat": int(len(cat_ra))}
    if len(x) < min_stars or len(cat_ra) < min_stars:
        info["reason"] = "too few detections or catalogue stars"
        return None, None, info

    from scipy.spatial import cKDTree

    w0 = WCS(header)
    nx = int(header.get("IMAGEW", header.get("NAXIS1", 1332)))
    ny = int(header.get("IMAGEH", header.get("NAXIS2", 1152)))
    px, py = w0.all_world2pix(cat_ra, cat_dec, 1, quiet=True)
    on = np.flatnonzero(np.isfinite(px) & (px > 0.5) & (px < nx + 0.5) & (py > 0.5) & (py < ny + 0.5))
    info["n_cat_chip"] = int(len(on))
    if len(on) < min_stars:
        info["reason"] = "too few catalogue stars on the chip"
        return None, None, info
    d, k = cKDTree(np.c_[px[on], py[on]]).query(np.c_[x, y])
    best = {}
    for i in np.flatnonzero(d < match_px):
        if k[i] not in best or d[i] < d[best[k[i]]]:
            best[k[i]] = i
    ci = on[np.array(sorted(best), int)]
    di = np.array([best[q] for q in sorted(best)], int)
    info["n_match"] = int(len(di))
    if len(di) < min_stars:
        info["reason"] = "too few matches"
        return None, None, info

    crpix = (float(header["CRPIX1"]), float(header["CRPIX2"]))
    u0, v0 = x[di] - crpix[0], y[di] - crpix[1]
    u = u0 + sip_eval(sip["A"], u0, v0)
    v = v0 + sip_eval(sip["B"], u0, v0)
    ra, dec = cat_ra[ci], cat_dec[ci]
    crval0 = (float(header["CRVAL1"]), float(header["CRVAL2"]))
    fref = float(np.percentile(flux, 10)) if len(flux) else 1.0
    a2, b2 = error_model[0] ** 2, error_model[1] ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        w = 1.0 / (a2 + b2 / np.clip(flux[di] / fref, 1e-3, None) ** 2)

    good = np.ones(len(di), bool)
    for _ in range(5):
        if good.sum() < min_stars:
            break
        _, _, res = fit_tan(u[good], v[good], ra[good], dec[good], crval0)
        rr = np.hypot(*res.T)
        new = good.copy()
        new[good] = rr < max(clip * np.median(rr) / 1.1774, floor_arcsec)
        if new.sum() == good.sum():
            break
        good = new
    if good.sum() < min_stars:
        info["reason"] = "too few stars after clipping"
        return None, None, info

    crval, cd, res = fit_tan(u[good], v[good], ra[good], dec[good], crval0, w=w[good])
    rms = float(np.sqrt(np.mean(np.sum(res**2, axis=1) / 2)))
    info.update(n_fit=int(good.sum()), rms_arcsec=rms,
                shift_arcsec=float(np.hypot(*gnomonic(crval[0], crval[1], *crval0)) * AS))

    h = fits.Header()
    h["WCSAXES"] = 2
    h["CTYPE1"] = ("RA---TAN-SIP", "TAN + fixed GFA distortion (SIP)")
    h["CTYPE2"] = ("DEC--TAN-SIP", "TAN + fixed GFA distortion (SIP)")
    h["EQUINOX"] = 2000.0
    h["LONPOLE"] = 180.0
    h["LATPOLE"] = 0.0
    h["CRVAL1"], h["CRVAL2"] = float(crval[0]), float(crval[1])
    h["CRPIX1"], h["CRPIX2"] = crpix
    h["CUNIT1"], h["CUNIT2"] = "deg", "deg"
    h["CD1_1"], h["CD1_2"] = float(cd[0, 0]), float(cd[0, 1])
    h["CD2_1"], h["CD2_2"] = float(cd[1, 0]), float(cd[1, 1])
    order = max(int(k.rsplit("_", 2)[1]) + int(k.rsplit("_", 2)[2]) for k in sip["A"])
    iorder = max(int(k.rsplit("_", 2)[1]) + int(k.rsplit("_", 2)[2]) for k in sip["AP"])
    h["A_ORDER"], h["B_ORDER"] = order, order
    for key in ("A", "B"):
        for name, c in sip[key].items():
            h[name] = float(c)
    h["AP_ORDER"], h["BP_ORDER"] = iorder, iorder
    for key in ("AP", "BP"):
        for name, c in sip[key].items():
            h[name] = float(c)
    h["GFAREFIT"] = (True, "WCS refit: fixed distortion + Gaia DR3 at epoch")
    h["GFARFN"] = (int(good.sum()), "stars in the refit")
    h["GFARFRMS"] = (round(rms, 4), "[arcsec] refit residual per coordinate")
    h["GFARFSH"] = (round(info["shift_arcsec"], 3), "[arcsec] CRVAL change from solve-field")

    keep = di[good]
    matches = {"x": x[keep], "y": y[keep], "flux": flux[keep], "ra": ra[good], "dec": dec[good],
               "det_index": keep}
    return h, matches, info


WCS_KEYS_PREFIXES = ("A_", "B_", "AP_", "BP_")
WCS_KEYS = {"WCSAXES", "CTYPE1", "CTYPE2", "EQUINOX", "LONPOLE", "LATPOLE", "CRVAL1", "CRVAL2",
            "CRPIX1", "CRPIX2", "CUNIT1", "CUNIT2", "CD1_1", "CD1_2", "CD2_1", "CD2_2",
            "PC1_1", "PC1_2", "PC2_1", "PC2_2", "CDELT1", "CDELT2", "RADESYS", "RADECSYS"}


def replace_wcs(header: fits.Header, new: fits.Header) -> None:
    """Remove the WCS (incl. SIP) keywords of ``header`` and add those of ``new`` in place."""
    for key in list(header.keys()):
        sip_coef = key.startswith(WCS_KEYS_PREFIXES) and key[-1].isdigit()
        sip_order = key in ("A_ORDER", "B_ORDER", "AP_ORDER", "BP_ORDER")
        if key in WCS_KEYS or sip_coef or sip_order:
            del header[key]
    for card in new.cards:
        header[card.keyword] = (card.value, card.comment)
