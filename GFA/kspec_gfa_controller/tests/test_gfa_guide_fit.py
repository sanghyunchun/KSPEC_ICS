# tests/test_gfa_guide_fit.py
"""Shift + rotation fit of the guide offsets (gfa_guide_fit)."""
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "kspec_gfa_controller"
_spec = spec_from_file_location("gfa_guide_fit__under_test", SRC / "gfa_guide_fit.py")
gf = module_from_spec(_spec)
_spec.loader.exec_module(gf)

RING = 1.473 * 3600.0  # arcsec


def _ring_stars(pas_deg, n_per_cam=20, seed=0, chip=300.0):
    """Star positions (E, N arcsec about the center) on chips at the given position angles."""
    rng = np.random.default_rng(seed)
    p, cam = [], []
    for c, pa in enumerate(pas_deg):
        t = np.radians(pa)
        centre = RING * np.array([np.sin(t), np.cos(t)])  # PA east of north
        p.append(centre + rng.uniform(-chip, chip, (n_per_cam, 2)))
        cam += [c] * n_per_cam
    return np.vstack(p), np.array(cam)


def _offsets(p, t, omega, k=0.0, noise=0.0, seed=1):
    rng = np.random.default_rng(seed)
    d = t + omega * np.c_[-p[:, 1], p[:, 0]] + k * p
    return d + rng.normal(0.0, noise, d.shape)


@pytest.mark.parametrize("pas", [[0, 60, 120, 180, 240, 300], [0, 60, 120, 180, 240], [0, 60, 120]])
def test_fit_recovers_shift_rotation_scale(pas):
    p, cam = _ring_stars(pas)
    t, omega, k = np.array([0.31, -0.22]), np.radians(0.002), 20e-6
    fit = gf.fit_shift_rotation(_offsets(p, t, omega, k, noise=0.05), p, cam)
    assert fit["t"] == pytest.approx(t, abs=0.03)
    assert np.degrees(fit["omega"]) == pytest.approx(0.002, abs=0.0002)
    assert fit["k"] == pytest.approx(k, abs=5e-6)
    assert fit["rms"] == pytest.approx(0.05, rel=0.3)
    assert fit["n_cam"] == len(pas)


def test_mean_is_biased_by_rotation_fit_is_not():
    """Five cameras: the stars' mean position is off the center, the mean picks up omega x it."""
    p, cam = _ring_stars([0, 60, 120, 180, 240])
    t, omega = np.array([0.0, 0.0]), np.radians(0.005)
    d = _offsets(p, t, omega)
    bias = np.hypot(*d.mean(axis=0))
    assert bias > 0.08  # 0.005 deg x (ring / 5) = 0.09"
    fit = gf.fit_shift_rotation(d, p, cam)
    assert np.hypot(*fit["t"]) < 1e-6


def test_equal_weight_per_camera():
    """A camera with 10x the stars does not pull the shift: only a rotation-free shift per camera."""
    p, cam = _ring_stars([0, 120, 240], n_per_cam=10)
    p2, cam2 = _ring_stars([0], n_per_cam=90, seed=5)
    p, cam = np.vstack([p, p2]), np.r_[cam, cam2]
    d = np.zeros_like(p)
    d[cam == 0] += [0.3, 0.0]  # camera 0 (100 stars) off by 0.3" east
    fit = gf.fit_shift_rotation(d, p, cam, scale=False, nsig=100.0)
    # equal camera weights: camera 0 counts for 1/3 of the shift, however many stars it has
    assert fit["t"][0] == pytest.approx(0.1, abs=0.02)


def test_outlier_star_is_clipped():
    p, cam = _ring_stars([0, 60, 120, 180, 240, 300])
    d = _offsets(p, np.array([0.2, 0.1]), 0.0, noise=0.03)
    d[7] += [5.0, -3.0]  # wrong centroid (captured by a neighbour)
    fit = gf.fit_shift_rotation(d, p, cam)
    assert not fit["keep"][7]
    assert fit["keep"].sum() >= len(d) - 3
    assert fit["t"] == pytest.approx([0.2, 0.1], abs=0.02)


@pytest.mark.parametrize("dec0", [-75.0, -37.0, 0.0, 30.0])
@pytest.mark.parametrize("keep", [[0, 1, 2, 3, 4, 5], [0, 1, 3], [1, 2, 4, 5]])
def test_ring_center_with_missing_cameras(dec0, keep):
    ra0 = 87.4
    pas = np.arange(6) * 60.0 + 7.0
    # camera centers 1.473 deg from (ra0, dec0) at the position angles, exactly on the sphere
    d0, r = np.radians(dec0), np.radians(1.473)
    t = np.radians(pas)
    dec = np.arcsin(np.sin(d0) * np.cos(r) + np.cos(d0) * np.sin(r) * np.cos(t))
    ra = ra0 + np.degrees(np.arctan2(np.sin(t) * np.sin(r) * np.cos(d0), np.cos(r) - np.sin(d0) * np.sin(dec)))
    rc, dc = gf.ring_center(ra[keep], np.degrees(dec)[keep])
    xi, eta = gf.gnomonic(rc, dc, ra0, dec0)
    assert np.hypot(xi, eta) * 3600.0 < 0.01


def test_ring_center_needs_three():
    with pytest.raises(ValueError):
        gf.ring_center([10.0, 11.0], [-30.0, -30.5])


def test_gnomonic_round_trip():
    ra, dec = np.array([10.0, 359.5, 0.2]), np.array([-60.0, -61.2, -58.9])
    xi, eta = gf.gnomonic(ra, dec, 0.0, -60.0)
    r2, d2 = gf.gnomonic_inv(xi, eta, 0.0, -60.0)
    assert np.allclose((r2 - ra + 180) % 360 - 180, 0, atol=1e-9)
    assert np.allclose(d2, dec, atol=1e-9)
