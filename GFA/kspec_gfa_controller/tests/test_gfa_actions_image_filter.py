# tests/test_gfa_actions_image_filter.py
"""
Pre-astrometry image filter used by guiding() and pointing().

_filter_pointing_raw_images calls _evaluate_pointing_image_quality for every raw
frame; the method had been dropped from GFAActions while the call stayed, so the
filter raised AttributeError and every guide/pointing cycle failed. These tests run
the real filter (real photutils DAOStarFinder, no stubs) on synthetic GFA frames.

The check is optional: pointing_filter.enabled (false in astrometry_params.json)
turns it on; when off, every raw frame passes and astrometry decides.

min_brightest_flux (3000 in astrometry_params.json) is compared with DAOStarFinder's
"flux", whose meaning depends on the photutils version: a summed flux in photutils 2.x
(22269 for a 2500-ADU-peak star here) but a peak-to-threshold ratio in 1.3 (67). The
tests below set that cut explicitly, except the one marked for photutils >= 2.
"""
import json
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits

SRC = Path(__file__).resolve().parents[1] / "src" / "kspec_gfa_controller"
CONFIG = SRC / "etc" / "astrometry_params.json"
PKG = "kspec_gfa_controller"
_STUBBED = ("scipy", "photutils")


def _split_modules():
    real, stubs = {}, {}
    for name, mod in list(sys.modules.items()):
        if name.split(".")[0] in _STUBBED:
            (real if getattr(mod, "__file__", None) else stubs)[name] = mod
    return real, stubs


def _load_gfa_actions():
    """
    Import gfa_actions with the hardware/environment modules faked (as in
    test_gfa_actions.py) and against the real scipy/photutils: test_gfa_guider.py
    installs stubs for those, which are set aside while importing.
    """
    _, stubs = _split_modules()
    for name in stubs:
        del sys.modules[name]
    fakes = {}
    for sub, attrs in {
        "gfa_logger": {"GFALogger": lambda *a, **k: SimpleNamespace()},
        "gfa_environment": {"create_environment": lambda **k: None,
                            "GFAEnvironment": type("GFAEnvironment", (), {})},
        "gfa_getcrval": {"get_crvals_from_images": lambda *a, **k: ([], []),
                         "get_crval_from_image": lambda *a, **k: (0.0, 0.0)},
    }.items():
        m = types.ModuleType(f"{PKG}.{sub}")
        for k, v in attrs.items():
            setattr(m, k, v)
        fakes[f"{PKG}.{sub}"] = m
    saved = {k: sys.modules.get(k) for k in [PKG, *fakes]}
    try:
        pytest.importorskip("photutils.detection")
        pkg = types.ModuleType(PKG)
        pkg.__path__ = [str(SRC)]
        sys.modules[PKG] = pkg
        sys.modules.update(fakes)
        spec = spec_from_file_location(f"{PKG}.gfa_actions__image_filter", SRC / "gfa_actions.py")
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        real, _ = _split_modules()
        return mod, real
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        sys.modules.update(stubs)


ga, _REAL_MODULES = _load_gfa_actions()


@pytest.fixture(autouse=True)
def _real_scipy_photutils():
    """photutils imports scipy lazily; keep the real modules in place during a test."""
    saved = {n: m for n, m in sys.modules.items() if n.split(".")[0] in _STUBBED}
    for name in saved:
        del sys.modules[name]
    sys.modules.update(_REAL_MODULES)
    yield
    for name in [n for n in sys.modules if n.split(".")[0] in _STUBBED]:
        del sys.modules[name]
    sys.modules.update(saved)


class _Log:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda msg, *a, **k: self.lines.append((level, str(msg)))


def make_actions(**pointing_filter):
    inpar = json.loads(CONFIG.read_text())
    inpar["pointing_filter"].update(pointing_filter)
    obj = ga.GFAActions.__new__(ga.GFAActions)  # no hardware / environment
    obj.env = SimpleNamespace(astrometry=SimpleNamespace(inpar=inpar), logger=_Log())
    return obj


@pytest.fixture
def actions():
    """Filter enabled with the config cuts, minus the version-dependent brightest-flux cut."""
    return make_actions(enabled=True, min_brightest_flux=0.0)


def _photutils_major():
    import photutils
    return int(photutils.__version__.split(".")[0])


def frame(n_stars, seed=1, shape=(288, 333)):
    """Binned GFA-like frame: background 100 ADU, read noise 5, Gaussian stars (FWHM 3 px)."""
    rng = np.random.default_rng(seed)
    ny, nx = shape
    img = 100.0 + rng.normal(0.0, 5.0, shape)
    yy, xx = np.mgrid[0:ny, 0:nx]
    sig = 3.0 / 2.3548
    for x0, y0, a in zip(rng.uniform(15, nx - 15, n_stars), rng.uniform(15, ny - 15, n_stars),
                         rng.uniform(600.0, 2500.0, n_stars)):
        img += a * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * sig**2))
    return img.astype(np.float32)


def write(path, data):
    fits.writeto(path, data, overwrite=True)
    return path


def test_star_field_passes(actions, tmp_path):
    res = actions._evaluate_pointing_image_quality(write(tmp_path / "stars.fits", frame(25)))
    assert res["passed"], res["reasons"]
    assert res["n_peaks"] >= actions.env.astrometry.inpar["pointing_filter"]["min_peaks"]
    assert res["std_bg"] > 0


def test_brightest_flux_cut_applies(tmp_path):
    res = make_actions(min_brightest_flux=1e9)._evaluate_pointing_image_quality(
        write(tmp_path / "stars.fits", frame(25)))
    assert not res["passed"]
    assert [r.split("=")[0] for r in res["reasons"]] == ["low_brightest_flux"]


@pytest.mark.skipif(_photutils_major() < 2, reason="DAOStarFinder flux is a ratio before photutils 2")
def test_shipped_config_passes_star_field(tmp_path):
    res = make_actions()._evaluate_pointing_image_quality(write(tmp_path / "stars.fits", frame(25)))
    assert res["passed"], res["reasons"]


def test_blank_frame_fails_on_peaks(actions, tmp_path):
    res = actions._evaluate_pointing_image_quality(write(tmp_path / "blank.fits", frame(0)))
    assert not res["passed"]
    assert any(r.startswith("few_peaks") for r in res["reasons"])


def test_cube_and_unreadable_are_rejected(actions, tmp_path):
    res = actions._evaluate_pointing_image_quality(
        write(tmp_path / "cube.fits", np.zeros((2, 10, 10), np.float32)))
    assert not res["passed"] and res["reasons"][0].startswith("invalid_dimension")
    res = actions._evaluate_pointing_image_quality(tmp_path / "missing.fits")
    assert not res["passed"] and res["reasons"][0].startswith("filter_error")


def three_frames(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    write(raw / "D20261027_T000000_40103651_exp5s.fits", frame(25, seed=2))
    write(raw / "D20261027_T000000_40103667_exp5s.fits", frame(25, seed=3))
    write(raw / "D20261027_T000000_40103831_exp5s.fits", frame(0, seed=4))  # clouded out
    return raw, tmp_path / "unclean"


def test_filter_is_off_in_shipped_config(tmp_path, monkeypatch):
    assert json.loads(CONFIG.read_text())["pointing_filter"]["enabled"] is False
    act = make_actions()
    monkeypatch.setattr(act, "_evaluate_pointing_image_quality",
                        lambda *a, **k: pytest.fail("quality check ran while disabled"))
    raw, unclean = three_frames(tmp_path)

    res = act._filter_pointing_raw_images(raw_path=raw, unclean_path=unclean, label="pointing")

    assert res["n_passed"] == 3 and res["n_failed"] == 0
    assert res["passed_files"] == sorted(str(p) for p in raw.iterdir())
    assert not unclean.exists()


def test_filter_off_when_key_missing(tmp_path):
    act = make_actions()
    del act.env.astrometry.inpar["pointing_filter"]["enabled"]
    raw, unclean = three_frames(tmp_path)
    res = act._filter_pointing_raw_images(raw_path=raw, unclean_path=unclean)
    assert res["n_passed"] == 3


def test_filter_keeps_good_frames_and_moves_bad_ones(actions, tmp_path):
    raw, unclean = three_frames(tmp_path)

    res = actions._filter_pointing_raw_images(raw_path=raw, unclean_path=unclean, label="guiding")

    assert res["n_passed"] == 2 and res["n_failed"] == 1
    assert sorted(p.name for p in raw.iterdir()) == [
        "D20261027_T000000_40103651_exp5s.fits", "D20261027_T000000_40103667_exp5s.fits"]
    assert [p.name for p in unclean.iterdir()] == ["D20261027_T000000_40103831_exp5s.fits"]
