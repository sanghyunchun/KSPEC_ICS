"""
Guide offset as a shift + rotation (+ scale) fit over all guide stars.

The guider measures, per guide star i, the on-sky offset d_i (east, north
arcsec) of its centroid from its catalogue position. The cameras sit on a ring
1.47 deg (5300") from the field center, so a field rotation omega moves every
star by omega x (its position about the center): 0.001 deg (3.6") of rotation
is 0.09" at the ring. The stars' mean position is off the center when a camera
is missing or contributes fewer stars (0.3 deg with 5 cameras), so the plain
mean of d_i contains omega x that offset. The fit

    d_i = t + omega x p_i + k p_i,    p_i = star position about the ring center,

returns t, the shift at the field center, free of the rotation, plus omega and
k (scale), which are useful on their own. omega x p = omega (-p_north, p_east):
omega > 0 turns east toward north (counter-clockwise in the east-north plane),
so the stars' position angles (east of north) decrease by omega. On the 2026
Oct-Nov guide sets omega followed the change of the GFA pattern angle (corr
0.82) and the residual per star dropped from 0.278" (shift only) to 0.240".

Each camera has equal total weight (one crowded chip does not dominate);
stars beyond ``nsig`` x the weighted rms (floor ``min_sigma``) are clipped
iteratively.
"""

from typing import Dict, Sequence, Tuple

import numpy as np

ARCSEC = 3600.0


def _unit(ra_deg, dec_deg) -> np.ndarray:
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    return np.stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)], axis=-1)


def gnomonic(ra_deg, dec_deg, ra0_deg: float, dec0_deg: float) -> Tuple[np.ndarray, np.ndarray]:
    """Tangent-plane (xi east, eta north) [deg] of (ra, dec) about (ra0, dec0)."""
    ra, dec = np.radians(np.asarray(ra_deg, float)), np.radians(np.asarray(dec_deg, float))
    ra0, dec0 = np.radians(ra0_deg), np.radians(dec0_deg)
    cosc = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    xi = np.cos(dec) * np.sin(ra - ra0) / cosc
    eta = (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)) / cosc
    return np.degrees(xi), np.degrees(eta)


def gnomonic_inv(xi_deg, eta_deg, ra0_deg: float, dec0_deg: float) -> Tuple[np.ndarray, np.ndarray]:
    xi, eta = np.radians(np.asarray(xi_deg, float)), np.radians(np.asarray(eta_deg, float))
    ra0, dec0 = np.radians(ra0_deg), np.radians(dec0_deg)
    den = np.cos(dec0) - eta * np.sin(dec0)
    ra = ra0 + np.arctan2(xi, den)
    dec = np.arctan2(np.sin(dec0) + eta * np.cos(dec0), np.hypot(xi, den))
    return np.degrees(ra) % 360.0, np.degrees(dec)


def ring_center(ra_deg: Sequence[float], dec_deg: Sequence[float], max_iter: int = 20) -> Tuple[float, float]:
    """
    Center of the circle through >= 3 camera centers (the cameras sit at one
    radius from the boresight): a linear (Kasa) circle fit in the tangent plane,
    re-centered on the result until it converges, so missing cameras do not
    bias it. Same method as GFA/pointing.py ``ring_centre``.
    """
    ra_deg, dec_deg = np.asarray(ra_deg, float), np.asarray(dec_deg, float)
    if len(ra_deg) < 3:
        raise ValueError(f"ring center needs >= 3 cameras, got {len(ra_deg)}")
    v = _unit(ra_deg, dec_deg).mean(axis=0)
    ra0 = float(np.degrees(np.arctan2(v[1], v[0])) % 360.0)
    dec0 = float(np.degrees(np.arctan2(v[2], np.hypot(v[0], v[1]))))
    for _ in range(max_iter):
        x, y = gnomonic(ra_deg, dec_deg, ra0, dec0)
        a = np.c_[2.0 * x, 2.0 * y, np.ones_like(x)]
        (xc, yc, _), *_ = np.linalg.lstsq(a, x**2 + y**2, rcond=None)
        ra1, dec1 = gnomonic_inv(xc, yc, ra0, dec0)
        step = np.hypot(xc, yc) * ARCSEC
        ra0, dec0 = float(ra1), float(dec1)
        if step < 1e-3:
            break
    return ra0, dec0


def fit_shift_rotation(
    d: np.ndarray,
    p: np.ndarray,
    cam: np.ndarray,
    scale: bool = True,
    nsig: float = 3.0,
    min_sigma: float = 0.02,
    max_iter: int = 6,
) -> Dict[str, object]:
    """
    Least squares d = t + omega x p (+ k p), equal weight per camera, clipped.

    Parameters
    ----------
    d : (n, 2) offsets (east, north) [arcsec]
    p : (n, 2) star positions about the field center (east, north) [arcsec]
    cam : (n,) camera label of each star

    Returns
    -------
    dict with t (2,) [arcsec], omega [rad], k [fractional], rms [arcsec, per
    axis, weighted], keep (n,) bool, n_cam (cameras with kept stars).
    """
    d, p, cam = np.asarray(d, float), np.asarray(p, float), np.asarray(cam)
    n = len(d)
    npar = 4 if scale else 3
    a = np.zeros((2 * n, npar))
    a[:n, 0] = 1.0
    a[n:, 1] = 1.0
    # columns of omega and k scaled by 1 / 3600 (conditioning): x[2] = 3600 omega [rad]
    a[:n, 2] = -p[:, 1] / ARCSEC
    a[n:, 2] = p[:, 0] / ARCSEC
    if scale:
        a[:n, 3] = p[:, 0] / ARCSEC
        a[n:, 3] = p[:, 1] / ARCSEC
    b = np.concatenate([d[:, 0], d[:, 1]])
    keep = np.ones(n, bool)
    x = np.zeros(npar)
    rms = np.nan
    for _ in range(max_iter):
        cams, cnt = np.unique(cam[keep], return_counts=True)
        wmap = dict(zip(cams, 1.0 / cnt))
        w = np.array([wmap.get(c, 0.0) for c in cam]) * keep
        sw = np.sqrt(np.concatenate([w, w]))
        x, *_ = np.linalg.lstsq(a * sw[:, None], b * sw, rcond=None)
        res = (b - a @ x).reshape(2, n).T
        r = np.hypot(res[:, 0], res[:, 1])
        rms = float(np.sqrt(np.sum(w * r**2) / (2.0 * np.sum(w)))) if np.sum(w) > 0 else np.nan
        new = r <= nsig * max(np.sqrt(2.0) * rms, min_sigma)
        if np.array_equal(new, keep) or new.sum() < npar + 1:
            break
        keep = new
    return {
        "t": np.array(x[:2], float),
        "omega": float(x[2] / ARCSEC),
        "k": float(x[3] / ARCSEC) if scale else 0.0,
        "rms": rms,
        "keep": keep,
        "n_cam": int(len(np.unique(cam[keep]))),
    }
