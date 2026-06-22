# tests/test_gfa_guider.py
import json
import math
import os
import sys
import types
import warnings
import logging
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import numpy as np
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)

# ✅ 다른 테스트들이 kspec_gfa_controller.gfa_guider를 Fake로 바꿔치기할 수 있으므로
#    우리는 절대 그 모듈명으로 import/재사용하지 않는다.
UNDER_TEST_FULLNAME = "kspec_gfa_controller.gfa_guider__under_test"


def _find_gfa_guider_py() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root / "src" / "kspec_gfa_controller" / "gfa_guider.py",  # src layout
        repo_root / "kspec_gfa_controller" / "gfa_guider.py",  # non-src layout
    ]
    for p in candidates:
        if p.exists():
            return p
    raise RuntimeError(
        "gfa_guider.py not found. tried:\n" + "\n".join(map(str, candidates))
    )


def _install_fake_scipy_and_photutils():
    """
    SciPy ABI 문제 회피용 stub.
    gfa_guider.py import 단계에서 photutils/scipy가 깨지면 coverage 자체가 불가능해짐.
    """
    # ---- fake scipy ----
    if "scipy" not in sys.modules:
        fake_scipy = types.ModuleType("scipy")
        fake_scipy.__path__ = []

        fake_opt = types.ModuleType("scipy.optimize")

        def _curve_fit_unavailable(*args, **kwargs):
            raise RuntimeError(
                "scipy.optimize.curve_fit is unavailable in test environment"
            )

        fake_opt.curve_fit = _curve_fit_unavailable

        fake_nd = types.ModuleType("scipy.ndimage")

        def _maximum_filter_unavailable(*args, **kwargs):
            raise RuntimeError(
                "scipy.ndimage.maximum_filter is unavailable in test environment"
            )

        fake_nd.maximum_filter = _maximum_filter_unavailable

        fake_spatial = types.ModuleType("scipy.spatial")

        class _KDTreeUnavailable:
            def __init__(self, *a, **k):
                raise RuntimeError(
                    "scipy.spatial.KDTree is unavailable in test environment"
                )

        fake_spatial.KDTree = _KDTreeUnavailable

        sys.modules["scipy"] = fake_scipy
        sys.modules["scipy.optimize"] = fake_opt
        sys.modules["scipy.ndimage"] = fake_nd
        sys.modules["scipy.spatial"] = fake_spatial

        fake_scipy.optimize = fake_opt
        fake_scipy.ndimage = fake_nd
        fake_scipy.spatial = fake_spatial

    # ---- fake photutils ----
    if "photutils" not in sys.modules:
        fake_photutils = types.ModuleType("photutils")
        fake_photutils.__path__ = []

        fake_detection = types.ModuleType("photutils.detection")

        def _find_peaks_unavailable(*args, **kwargs):
            raise RuntimeError(
                "photutils.detection.find_peaks is unavailable in test environment"
            )

        fake_detection.find_peaks = _find_peaks_unavailable

        sys.modules["photutils"] = fake_photutils
        sys.modules["photutils.detection"] = fake_detection
        fake_photutils.detection = fake_detection


def _ensure_pkg_stub(repo_root: Path):
    """
    coverage가 'kspec_gfa_controller.*'로 잡히게 하려면,
    최소한의 패키지 모듈(kspec_gfa_controller)이 sys.modules에 존재해야 함.
    """
    if "kspec_gfa_controller" not in sys.modules:
        pkg = types.ModuleType("kspec_gfa_controller")
        # src 레이아웃/비-src 둘 다 가능하니 둘 다 넣어둠
        pkg.__path__ = [
            str(repo_root / "src" / "kspec_gfa_controller"),
            str(repo_root / "kspec_gfa_controller"),
        ]
        sys.modules["kspec_gfa_controller"] = pkg
    return sys.modules["kspec_gfa_controller"]


def _load_guider_module_force():
    """
    gfa_guider.py를 UNDER_TEST_FULLNAME 이름으로 강제 로드.
    - 다른 테스트가 kspec_gfa_controller.gfa_guider 를 Fake로 바꿔도 영향 없음.
    - sys.modules에 같은 이름이 있으면 삭제 후 재로딩.
    """
    _install_fake_scipy_and_photutils()

    path = _find_gfa_guider_py()
    repo_root = Path(__file__).resolve().parents[1]
    _ensure_pkg_stub(repo_root)

    # ✅ 항상 "진짜 파일"을 강제로 로드
    if UNDER_TEST_FULLNAME in sys.modules:
        del sys.modules[UNDER_TEST_FULLNAME]

    spec = spec_from_file_location(UNDER_TEST_FULLNAME, str(path))
    if spec is None or spec.loader is None:
        pytest.fail(f"Could not create import spec for {path}")

    module = module_from_spec(spec)
    sys.modules[UNDER_TEST_FULLNAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        pytest.fail(f"Failed to import guider module from {path}: {e}")

    return module


mod = _load_guider_module_force()
GFAGuider = mod.GFAGuider


def _ensure_mod_os():
    # gfa_guider.py가 import os를 안했을 수도 있으니 주입
    if not hasattr(mod, "os"):
        setattr(mod, "os", os)


def _test_logger():
    lg = logging.getLogger("test_gfa_guider")
    if not lg.handlers:
        lg.addHandler(logging.NullHandler())
    return lg


@pytest.fixture(scope="function")
def guider_config(tmp_path: Path) -> Path:
    """
    GFAGuider 요구 키를 만족하는 최소 config.
    절대경로를 넣어 os.path.join(base_dir, abs) => abs 우선 되도록 함.
    """
    cfg = {
        "paths": {
            "directories": {
                "raw_images": str(tmp_path / "raw"),
                "final_astrometry_images": str(tmp_path / "final"),
                "cutout_directory": str(tmp_path / "cutout"),
                "star_catalog": str(tmp_path / "catalog"),
            }
        },
        "detection": {
            "box_size": 20,
            "criteria": {"critical_outlier": 0.5},
            "peak_detection": {"max": 30000, "min": 10},
        },
        "catalog_matching": {
            "tolerance": {"angular_distance": 1.0, "mag_flux_min": 0.1},
            "fields": {"ra_column": "RA", "dec_column": "DEC", "mag_flux": "FLUX"},
        },
        "settings": {"image_processing": {"pixel_scale": 0.4}},
    }
    cfgp = tmp_path / "cfg.json"
    cfgp.write_text(json.dumps(cfg), encoding="utf-8")
    return cfgp


def _write_bad_json(path: Path):
    path.write_text("{bad json", encoding="utf-8")


def _mk_guider(config_path: Path):
    kwargs = {}
    if "logger" in GFAGuider.__init__.__code__.co_varnames:
        kwargs["logger"] = _test_logger()
    return GFAGuider(config=str(config_path), **kwargs)


def _load_cfg(cfgp: Path) -> dict:
    return json.loads(cfgp.read_text(encoding="utf-8"))


def _save_cfg(cfgp: Path, cfg: dict) -> None:
    cfgp.write_text(json.dumps(cfg), encoding="utf-8")


# -------------------------
# helper: _get_default_config_path / _get_default_logger (있으면 테스트)
# -------------------------
def test_get_default_config_path_missing_raises(monkeypatch):
    if not hasattr(mod, "_get_default_config_path"):
        pytest.skip("module has no _get_default_config_path()")
    _ensure_mod_os()
    monkeypatch.setattr(mod.os.path, "isfile", lambda p: False)
    with pytest.raises(FileNotFoundError):
        mod._get_default_config_path()


def test_get_default_config_path_success(monkeypatch):
    if not hasattr(mod, "_get_default_config_path"):
        pytest.skip("module has no _get_default_config_path()")
    _ensure_mod_os()
    monkeypatch.setattr(mod.os.path, "isfile", lambda p: True)
    p = mod._get_default_config_path()
    norm = os.path.normpath(p)
    assert norm.endswith(
        os.path.normpath(os.path.join("etc", "astrometry_params.json"))
    )


def test_default_logger_no_duplicate_handlers():
    if not hasattr(mod, "_get_default_logger"):
        pytest.skip("module has no _get_default_logger()")
    lg1 = mod._get_default_logger()
    n1 = len(lg1.handlers)
    lg2 = mod._get_default_logger()
    n2 = len(lg2.handlers)
    assert lg1 is lg2
    assert n2 == n1


# -------------------------
# __init__ error branches
# -------------------------
def test_init_bad_json_raises_runtimeerror(tmp_path):
    cfgp = tmp_path / "bad.json"
    _write_bad_json(cfgp)
    with pytest.raises(RuntimeError):
        _mk_guider(cfgp)


def test_init_missing_config_raises_runtimeerror(tmp_path):
    with pytest.raises(RuntimeError):
        _mk_guider(tmp_path / "nope.json")


def test_init_missing_raw_key_raises_keyerror(tmp_path):
    cfg = {
        "paths": {
            "directories": {
                "final_astrometry_images": str(tmp_path / "final"),
                "cutout_directory": str(tmp_path / "cutout"),
                "star_catalog": str(tmp_path / "catalog"),
            }
        },
        "detection": {
            "box_size": 20,
            "criteria": {"critical_outlier": 0.5},
            "peak_detection": {"max": 30000, "min": 10},
        },
        "catalog_matching": {
            "tolerance": {"angular_distance": 1.0, "mag_flux_min": 0.1},
            "fields": {"ra_column": "RA", "dec_column": "DEC", "mag_flux": "FLUX"},
        },
        "settings": {"image_processing": {"pixel_scale": 0.4}},
    }
    cfgp = tmp_path / "cfg.json"
    cfgp.write_text(json.dumps(cfg), encoding="utf-8")

    with pytest.raises(KeyError):
        _mk_guider(cfgp)


# -------------------------
# ✅ NEW 1/6: init(logger=None) should not crash
# -------------------------
def test_init_logger_none_does_not_crash(guider_config):
    if "logger" not in GFAGuider.__init__.__code__.co_varnames:
        pytest.skip("GFAGuider.__init__ has no logger parameter")
    g = GFAGuider(config=str(guider_config), logger=None)
    assert g is not None


# -------------------------
# _astro_to_raw_path branches
# -------------------------
def test_astro_to_raw_path_parse_fail_returns_none(guider_config):
    g = _mk_guider(guider_config)
    assert g._astro_to_raw_path("astro_badname.fits") is None


# -------------------------
# ✅ NEW 2/6: parse ok but no candidates => None
# -------------------------
def test_astro_to_raw_path_parse_ok_but_no_candidates_returns_none(
    tmp_path, guider_config
):
    cfg = _load_cfg(guider_config)
    raw_dir = tmp_path / "raw_empty"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cfg["paths"]["directories"]["raw_images"] = str(raw_dir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)
    astro = "astro_D20260121_T171409_40103651_exp5s.fits"
    assert g._astro_to_raw_path(astro) is None


# -------------------------
# ✅ NEW 3/6: .fit/.fts extension candidates
# -------------------------
@pytest.mark.parametrize("ext", [".fit", ".fts"])
def test_astro_to_raw_path_accepts_other_extensions(tmp_path, guider_config, ext):
    cfg = _load_cfg(guider_config)
    raw_dir = tmp_path / "raw_ext"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cfg["paths"]["directories"]["raw_images"] = str(raw_dir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    p = raw_dir / f"D20260121_T171500_40103651_exp5s{ext}"
    p.write_text("x", encoding="utf-8")

    astro = "astro_D20260121_T171409_40103651_exp5s.fits"
    got = g._astro_to_raw_path(astro)
    assert got is not None
    assert os.path.basename(got) == p.name


def test_astro_to_raw_path_selects_latest(tmp_path, guider_config):
    cfg = _load_cfg(guider_config)
    raw_dir = tmp_path / "rawtok"
    raw_dir.mkdir(parents=True, exist_ok=True)

    cfg["paths"]["directories"]["raw_images"] = str(raw_dir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    p1 = raw_dir / "D20260121_T171409_40103651_exp5s.fits"
    p2 = raw_dir / "D20260121_T171500_40103651_exp5s.fits"
    p1.write_text("x", encoding="utf-8")
    p2.write_text("y", encoding="utf-8")

    os.utime(p1, (1, 1))
    os.utime(p2, (2, 2))  # newer

    astro = "astro_D20260121_T171409_40103651_exp5s.fits"
    got = g._astro_to_raw_path(astro)
    assert got is not None
    assert os.path.basename(got) == p2.name


# -------------------------
# load_image_and_wcs / load_only_image
# -------------------------
def test_load_image_and_wcs_file_not_found(guider_config, tmp_path):
    g = _mk_guider(guider_config)
    with pytest.raises(FileNotFoundError):
        g.load_image_and_wcs(str(tmp_path / "missing.fits"))


def test_load_image_and_wcs_other_exception(monkeypatch, guider_config):
    g = _mk_guider(guider_config)

    def boom(*a, **k):
        raise RuntimeError("fits broken")

    monkeypatch.setattr(mod.fits, "getdata", boom)
    with pytest.raises(RuntimeError):
        g.load_image_and_wcs("any.fits")


def test_load_only_image_just_calls_fits_getdata(monkeypatch, guider_config):
    g = _mk_guider(guider_config)

    called = {"n": 0}

    def fake_getdata(path, ext=0):
        called["n"] += 1
        return np.zeros((2, 2), dtype=np.float32)

    monkeypatch.setattr(mod.fits, "getdata", fake_getdata)
    out = g.load_only_image("x.fits")
    assert out.shape == (2, 2)
    assert called["n"] == 1


# -------------------------
# background
# -------------------------
def test_background_returns_subtracted_and_stddev(guider_config):
    g = _mk_guider(guider_config)

    img = np.zeros((600, 1024), dtype=np.float32)
    img[:, :511] = 100.0
    img[:, 511:] = 200.0
    img[0, 0] = 101.0
    img[0, 511] = 199.0

    bg_sub, stddev = g.background(img)

    assert abs(float(np.mean(bg_sub[:, :511]))) < 1.0
    assert abs(float(np.mean(bg_sub[:, 511:]))) < 1.0
    assert stddev >= 0.0


# -------------------------
# load_star_catalog branches
# -------------------------
def _write_combined_star_fits(path: Path, cols: dict[str, Any]):
    from astropy.io import fits

    col_defs = []
    for name, arr in cols.items():
        arr = np.array(arr)
        fmt = "D" if arr.dtype.kind in ("f",) else "K"
        col_defs.append(fits.Column(name=name, format=fmt, array=arr))
    hdu1 = fits.BinTableHDU.from_columns(col_defs)
    fits.HDUList([fits.PrimaryHDU(), hdu1]).writeto(path, overwrite=True)


def test_load_star_catalog_missing_file_raises(monkeypatch, guider_config):
    g = _mk_guider(guider_config)
    _ensure_mod_os()
    monkeypatch.setattr(mod.os.path, "exists", lambda p: False)
    with pytest.raises(FileNotFoundError):
        g.load_star_catalog(1.0, 2.0)


def test_load_star_catalog_invalid_hdu_raises_runtimeerror(tmp_path, guider_config):
    cfg = _load_cfg(guider_config)
    catdir = tmp_path / "cat"
    catdir.mkdir()
    cfg["paths"]["directories"]["star_catalog"] = str(catdir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    bad = catdir / "combined_star.fits"
    from astropy.io import fits

    fits.PrimaryHDU().writeto(bad, overwrite=True)

    with pytest.raises(RuntimeError):
        g.load_star_catalog(10.0, 20.0)


def test_load_star_catalog_missing_columns_raises_keyerror(tmp_path, guider_config):
    cfg = _load_cfg(guider_config)
    catdir = tmp_path / "cat2"
    catdir.mkdir()
    cfg["paths"]["directories"]["star_catalog"] = str(catdir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    p = catdir / "combined_star.fits"
    _write_combined_star_fits(p, {"AAA": [1.0], "BBB": [2.0], "FLUX": [3.0]})

    with pytest.raises(KeyError):
        g.load_star_catalog(10.0, 20.0)


def test_load_star_catalog_ra_hour_auto_converts(tmp_path, guider_config):
    cfg = _load_cfg(guider_config)
    catdir = tmp_path / "cat3"
    catdir.mkdir()
    cfg["paths"]["directories"]["star_catalog"] = str(catdir)
    cfg["catalog_matching"]["fields"].pop("ra_unit", None)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    p = catdir / "combined_star.fits"
    _write_combined_star_fits(
        p, {"RA": [1.0, 2.0], "DEC": [0.0, 0.1], "FLUX": [1.0, 1.0]}
    )

    _, _, _, _, ra_p, _, _ = g.load_star_catalog(10.0, 20.0)
    assert np.allclose(ra_p, np.array([15.0, 30.0]))


def test_load_star_catalog_ra_unit_force_deg_no_convert(tmp_path, guider_config):
    cfg = _load_cfg(guider_config)
    catdir = tmp_path / "cat4"
    catdir.mkdir()
    cfg["paths"]["directories"]["star_catalog"] = str(catdir)
    cfg["catalog_matching"]["fields"]["ra_unit"] = "deg"
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    p = catdir / "combined_star.fits"
    _write_combined_star_fits(
        p, {"RA": [1.0, 2.0], "DEC": [0.0, 0.1], "FLUX": [1.0, 1.0]}
    )

    _, _, _, _, ra_p, _, _ = g.load_star_catalog(10.0, 20.0)
    assert np.allclose(ra_p, np.array([1.0, 2.0]))


# -------------------------
# ✅ NEW 4/6: combined_star.fits is a directory -> error
# -------------------------
def test_load_star_catalog_is_directory_raises(tmp_path, guider_config):
    cfg = _load_cfg(guider_config)
    catdir = tmp_path / "cat_isdir"
    catdir.mkdir()
    cfg["paths"]["directories"]["star_catalog"] = str(catdir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)
    (catdir / "combined_star.fits").mkdir()

    with pytest.raises((IsADirectoryError, OSError, RuntimeError)):
        g.load_star_catalog(10.0, 20.0)


# -------------------------
# select_stars
# -------------------------
def test_select_stars_filters_by_angle_and_flux(guider_config):
    g = _mk_guider(guider_config)

    ra1_rad, dec1_rad = 0.0, 0.0
    ra_p = np.array([0.0, 10.0, 0.1])
    dec_p = np.array([0.0, 0.0, 0.1])
    flux = np.array([1.0, 1.0, np.nan])

    ra2_rad = np.radians(ra_p)
    dec2_rad = np.radians(dec_p)

    ra_sel, dec_sel, flux_sel = g.select_stars(
        ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux
    )

    assert np.allclose(ra_sel, [0.0])
    assert np.allclose(dec_sel, [0.0])
    assert np.allclose(flux_sel, [1.0])


def test_select_stars_no_mag_flux_min_selects_by_angle_only(guider_config):
    g = _mk_guider(guider_config)
    g.inpar["catalog_matching"]["tolerance"].pop("mag_flux_min", None)

    ra1_rad, dec1_rad = 0.0, 0.0
    ra_p = np.array([0.0, 10.0])
    dec_p = np.array([0.0, 0.0])
    flux = np.array([np.nan, np.nan])

    ra2_rad = np.radians(ra_p)
    dec2_rad = np.radians(dec_p)

    ra_sel, dec_sel, flux_sel = g.select_stars(
        ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux
    )
    assert len(ra_sel) == 1
    assert np.allclose(ra_sel, [0.0])
    assert np.allclose(flux_sel, [0.0])  # nan_to_num


# -------------------------
# radec_to_xy_stars
# -------------------------
def test_radec_to_xy_stars_rounding_rule(guider_config):
    g = _mk_guider(guider_config)

    class FakeWCS:
        def world_to_pixel_values(self, ra, dec):
            return np.array([0.2, 0.6]), np.array([1.49, 1.51])

    ra = np.array([0.0, 0.0])
    dec = np.array([0.0, 0.0])

    dra, ddec, dra_f, ddec_f = g.radec_to_xy_stars(ra, dec, FakeWCS())

    assert np.all(dra == np.array([1, 2]))
    assert np.all(ddec == np.array([2, 3]))
    assert np.allclose(dra_f, np.array([1.2, 1.6]))
    assert np.allclose(ddec_f, np.array([2.49, 2.51]))


# -------------------------
# cal_centroid_offset
# -------------------------
def test_cal_centroid_offset_success_and_failure(tmp_path, monkeypatch, guider_config):
    g = _mk_guider(guider_config)

    Path(g.cutout_path).mkdir(parents=True, exist_ok=True)
    g.boxsize = 8

    image_data = np.zeros((100, 100), dtype=np.float32)
    image_data[50, 50] = 1000.0

    dra = np.array([50, 60])
    ddec = np.array([50, 60])
    dra_f = np.array([50.0, 60.0])
    ddec_f = np.array([50.0, 60.0])
    fluxn = np.array([1000.0, 2000.0])

    stddev = 1.0

    class FakeWCS:
        def pixel_to_world_values(self, x, y):
            return (0.001 * x, 0.001 * y)

    wcs = FakeWCS()

    call = {"n": 0}

    def fake_find_peaks(cutout, threshold, box_size, npeaks):
        call["n"] += 1
        if call["n"] == 2:
            raise RuntimeError("peak finding failed")
        return {
            "x_peak": [g.boxsize // 2],
            "y_peak": [g.boxsize // 2],
            "peak_value": [123.0],
        }

    monkeypatch.setattr(mod.pd, "find_peaks", fake_find_peaks, raising=True)

    cutoutn_stack = []
    dx, dy, peakc, cutoutn_stack = g.cal_centroid_offset(
        dra=dra,
        ddec=ddec,
        dra_f=dra_f,
        ddec_f=ddec_f,
        stddev=stddev,
        wcs=wcs,
        fluxn=fluxn,
        file_counter=1,
        cutoutn_stack=cutoutn_stack,
        image_data=image_data,
    )

    assert len(dx) == 2 and len(dy) == 2 and len(peakc) == 2
    assert peakc[0] == 123.0
    assert dx[1] == 0
    assert dy[1] == 0
    assert peakc[1] == -1


def test_cal_centroid_offset_branches_oob_edge_nopeaks_badflux(
    monkeypatch, guider_config, tmp_path
):
    g = _mk_guider(guider_config)
    Path(g.cutout_path).mkdir(parents=True, exist_ok=True)
    g.boxsize = 10

    image_data = np.zeros((30, 30), dtype=np.float32)
    stddev = 1.0

    class FakeWCS:
        def pixel_to_world_values(self, x, y):
            return (0.001 * x, 0.001 * y)

    wcs = FakeWCS()

    dra = np.array([100, 1, 15, 15])
    ddec = np.array([100, 1, 15, 15])
    dra_f = dra.astype(float)
    ddec_f = ddec.astype(float)
    fluxn = np.array([10.0, 10.0, 10.0, 10.0])

    call = {"n": 0}

    def fake_find_peaks(cutout, threshold, box_size, npeaks):
        call["n"] += 1
        if call["n"] == 1:
            return []
        return {
            "x_peak": [g.boxsize // 2],
            "y_peak": [g.boxsize // 2],
            "peak_value": [50.0],
        }

    monkeypatch.setattr(mod.pd, "find_peaks", fake_find_peaks, raising=True)

    dx, dy, peakc, _ = g.cal_centroid_offset(
        dra=dra,
        ddec=ddec,
        dra_f=dra_f,
        ddec_f=ddec_f,
        stddev=stddev,
        wcs=wcs,
        fluxn=fluxn,
        file_counter=1,
        cutoutn_stack=[],
        image_data=image_data,
    )

    assert len(dx) == 4 and len(dy) == 4 and len(peakc) == 4
    assert peakc[0] == -1 and dx[0] == 0 and dy[0] == 0  # oob
    assert peakc[1] == -1 and dx[1] == 0 and dy[1] == 0  # edge
    assert peakc[2] == -1 and dx[2] == 0 and dy[2] == 0  # no peaks
    assert peakc[3] == -1 and dx[3] == 0 and dy[3] == 0  # badflux


# -------------------------
# peak_select
# -------------------------
def test_peak_select_filters(guider_config):
    g = _mk_guider(guider_config)

    dx = [1, 2, 3, 4]
    dy = [10, 20, 30, 40]
    peakc = [5, 50, 50000, 15]

    dxn, dyn, pindn = g.peak_select(dx, dy, peakc)

    assert np.all(pindn == np.array([1, 3]))
    assert np.all(dxn == np.array([2, 4]))
    assert np.all(dyn == np.array([20, 40]))


def test_peak_select_validation_errors(guider_config):
    g = _mk_guider(guider_config)

    with pytest.raises(ValueError):
        g.peak_select(None, [1], [1])  # type: ignore

    with pytest.raises(ValueError):
        g.peak_select([1], [1, 2], [1])  # mismatch

    with pytest.raises(ValueError):
        g.peak_select([], [], [])  # empty


def test_peak_select_no_kept_raises_runtimeerror(guider_config):
    g = _mk_guider(guider_config)

    dx = [0.1, 0.2]
    dy = [0.1, 0.2]
    peakc = [1, 2]  # below peakmin=10

    with pytest.raises(RuntimeError):
        g.peak_select(dx, dy, peakc)


# -------------------------
# cal_final_offset
# -------------------------
def test_cal_final_offset_warning_when_no_stars(guider_config):
    g = _mk_guider(guider_config)
    fdx, fdy = g.cal_final_offset(np.array([]), np.array([]), np.array([]))
    assert fdx == "Warning"
    assert fdy == "Warning"


def test_cal_final_offset_returns_zero_when_below_threshold(guider_config):
    g = _mk_guider(guider_config)

    dxp = np.array([0.05, 0.1, 0.0])
    dyp = np.array([0.05, 0.0, 0.1])
    pindp = np.array([0, 1, 2])

    fdx, fdy = g.cal_final_offset(dxp, dyp, pindp)
    assert fdx == 0.0
    assert fdy == 0.0


def test_cal_final_offset_above_threshold_and_trim_minmax(monkeypatch, guider_config):
    g = _mk_guider(guider_config)

    class FakeClipped:
        def __init__(self, n):
            self.mask = np.array([False] * n)

    monkeypatch.setattr(
        mod,
        "sigma_clip",
        lambda distances, sigma, maxiters: FakeClipped(len(distances)),
    )

    dxp = np.array([2.0, 2.0, 2.0, 2.0, 2.0, 10.0])
    dyp = np.zeros_like(dxp)
    pindp = np.arange(len(dxp))

    fdx, fdy = g.cal_final_offset(dxp, dyp, pindp)
    assert isinstance(fdx, float) and isinstance(fdy, float)
    assert fdx > g.crit_out
    assert fdy == 0.0


# -------------------------
# cal_seeing
# -------------------------
def test_cal_seeing_nan_when_no_cutouts(guider_config):
    g = _mk_guider(guider_config)
    fwhm = g.cal_seeing([])
    assert math.isnan(fwhm)


def test_cal_seeing_curve_fit_none_returns_nan(monkeypatch, guider_config):
    g = _mk_guider(guider_config)
    monkeypatch.setattr(mod, "curve_fit", None, raising=True)
    cutout = np.ones((11, 11), dtype=np.float32)
    assert math.isnan(g.cal_seeing([cutout]))


def test_cal_seeing_save_fails_still_returns_value(monkeypatch, guider_config):
    g = _mk_guider(guider_config)
    Path(g.cutout_path).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        mod.fits,
        "writeto",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")),
    )

    def fake_curve_fit(func, xy, z, p0):
        params = np.array([100.0, 5.0, 5.0, 2.0, 0.0])
        cov = np.eye(5)
        return params, cov

    monkeypatch.setattr(mod, "curve_fit", fake_curve_fit, raising=True)

    cutout = np.ones((11, 11), dtype=np.float32)
    fwhm = g.cal_seeing([cutout, cutout])

    expected = 2.0 * math.sqrt(2.0 * math.log(2.0)) * 2.0 * g.pixel_scale
    assert abs(fwhm - expected) < 1e-6


def test_cal_seeing_curve_fit_failure_returns_nan(monkeypatch, guider_config):
    g = _mk_guider(guider_config)
    Path(g.cutout_path).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        mod,
        "curve_fit",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fit fail")),
        raising=True,
    )

    cutout = np.ones((11, 11), dtype=np.float32)
    fwhm = g.cal_seeing([cutout])
    assert math.isnan(fwhm)


# -------------------------
# ✅ NEW 5/6: cal_seeing success, writeto ok
# -------------------------
def test_cal_seeing_success_writeto_ok(monkeypatch, guider_config):
    g = _mk_guider(guider_config)
    Path(g.cutout_path).mkdir(parents=True, exist_ok=True)

    wrote = {"n": 0}

    def fake_writeto(*a, **k):
        wrote["n"] += 1
        return None

    monkeypatch.setattr(mod.fits, "writeto", fake_writeto, raising=True)

    def fake_curve_fit(func, xy, z, p0):
        params = np.array([100.0, 5.0, 5.0, 1.5, 0.0])
        cov = np.eye(5)
        return params, cov

    monkeypatch.setattr(mod, "curve_fit", fake_curve_fit, raising=True)

    cutout = np.ones((11, 11), dtype=np.float32)
    fwhm = g.cal_seeing([cutout, cutout])

    assert wrote["n"] == 1
    assert math.isfinite(fwhm)


# -------------------------
# exe_cal
# -------------------------
def test_exe_cal_no_astro_files_returns_nan(guider_config):
    g = _mk_guider(guider_config)
    Path(g.final_astrometry_dir).mkdir(parents=True, exist_ok=True)
    fdx, fdy, fwhm = g.exe_cal()
    assert math.isnan(fdx) and math.isnan(fdy) and math.isnan(fwhm)


# -------------------------
# ✅ NEW 6/6: exe_cal when astrometry dir path missing -> nan
# -------------------------
def test_exe_cal_missing_astrometry_dir_path_returns_nan(guider_config):
    g = _mk_guider(guider_config)
    g.final_astrometry_dir = ""
    fdx, fdy, fwhm = g.exe_cal()
    assert math.isnan(fdx) and math.isnan(fdy) and math.isnan(fwhm)


def test_exe_cal_missing_catalog_returns_nan(tmp_path, guider_config):
    cfg = _load_cfg(guider_config)
    final_dir = tmp_path / "final"
    raw_dir = tmp_path / "raw"
    cut_dir = tmp_path / "cut"
    cat_dir = tmp_path / "cat"
    final_dir.mkdir()
    raw_dir.mkdir()
    cut_dir.mkdir()
    cat_dir.mkdir()

    cfg["paths"]["directories"]["final_astrometry_images"] = str(final_dir)
    cfg["paths"]["directories"]["raw_images"] = str(raw_dir)
    cfg["paths"]["directories"]["cutout_directory"] = str(cut_dir)
    cfg["paths"]["directories"]["star_catalog"] = str(cat_dir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    (final_dir / "astro_x.fits").write_text("dummy", encoding="utf-8")

    fdx, fdy, fwhm = g.exe_cal()
    assert math.isnan(fdx) and math.isnan(fdy) and math.isnan(fwhm)


def test_exe_cal_all_skipped_raw_match_returns_nan(tmp_path, guider_config):
    cfg = _load_cfg(guider_config)
    final_dir = tmp_path / "final2"
    raw_dir = tmp_path / "raw2"
    cut_dir = tmp_path / "cut2"
    cat_dir = tmp_path / "cat2"
    final_dir.mkdir()
    raw_dir.mkdir()
    cut_dir.mkdir()
    cat_dir.mkdir()

    cfg["paths"]["directories"]["final_astrometry_images"] = str(final_dir)
    cfg["paths"]["directories"]["raw_images"] = str(raw_dir)
    cfg["paths"]["directories"]["cutout_directory"] = str(cut_dir)
    cfg["paths"]["directories"]["star_catalog"] = str(cat_dir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    astro = final_dir / "astro_badname.fits"
    astro.write_text("dummy", encoding="utf-8")

    _write_combined_star_fits(
        cat_dir / "combined_star.fits", {"RA": [0.0], "DEC": [0.0], "FLUX": [1.0]}
    )

    fdx, fdy, fwhm = g.exe_cal()
    assert math.isnan(fdx) and math.isnan(fdy) and math.isnan(fwhm)


def test_exe_cal_loop_error_raises_runtimeerror(tmp_path, guider_config, monkeypatch):
    cfg = _load_cfg(guider_config)
    final_dir = tmp_path / "final3"
    raw_dir = tmp_path / "raw3"
    cut_dir = tmp_path / "cut3"
    cat_dir = tmp_path / "cat3"
    final_dir.mkdir()
    raw_dir.mkdir()
    cut_dir.mkdir()
    cat_dir.mkdir()

    cfg["paths"]["directories"]["final_astrometry_images"] = str(final_dir)
    cfg["paths"]["directories"]["raw_images"] = str(raw_dir)
    cfg["paths"]["directories"]["cutout_directory"] = str(cut_dir)
    cfg["paths"]["directories"]["star_catalog"] = str(cat_dir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    astro = final_dir / "astro_D20260121_T171409_40103651_exp5s.fits"
    astro.write_text("dummy", encoding="utf-8")
    raw = raw_dir / "D20260121_T171409_40103651_exp5s.fits"
    raw.write_text("dummy", encoding="utf-8")

    _write_combined_star_fits(
        cat_dir / "combined_star.fits", {"RA": [0.0], "DEC": [0.0], "FLUX": [1.0]}
    )

    monkeypatch.setattr(
        g,
        "load_image_and_wcs",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError):
        g.exe_cal()


def test_exe_cal_success_minimal_flow(tmp_path, guider_config, monkeypatch):
    cfg = _load_cfg(guider_config)
    final_dir = tmp_path / "final4"
    raw_dir = tmp_path / "raw4"
    cut_dir = tmp_path / "cut4"
    cat_dir = tmp_path / "cat4"
    final_dir.mkdir()
    raw_dir.mkdir()
    cut_dir.mkdir()
    cat_dir.mkdir()

    cfg["paths"]["directories"]["final_astrometry_images"] = str(final_dir)
    cfg["paths"]["directories"]["raw_images"] = str(raw_dir)
    cfg["paths"]["directories"]["cutout_directory"] = str(cut_dir)
    cfg["paths"]["directories"]["star_catalog"] = str(cat_dir)
    _save_cfg(guider_config, cfg)

    g = _mk_guider(guider_config)

    astro = final_dir / "astro_D20260121_T171409_40103651_exp5s.fits"
    astro.write_text("dummy", encoding="utf-8")
    raw = raw_dir / "D20260121_T171409_40103651_exp5s.fits"
    raw.write_text("dummy", encoding="utf-8")

    _write_combined_star_fits(
        cat_dir / "combined_star.fits", {"RA": [0.0], "DEC": [0.0], "FLUX": [1.0]}
    )

    class FakeWCS:
        def world_to_pixel_values(self, ra, dec):
            return np.array([10.0]), np.array([10.0])

    fake_header = {"CRVAL1": 10.0, "CRVAL2": 20.0}

    monkeypatch.setattr(
        g, "load_image_and_wcs", lambda p: (np.zeros((2, 2)), fake_header, FakeWCS())
    )
    monkeypatch.setattr(
        g, "load_only_image", lambda p: np.zeros((20, 20), dtype=np.float32)
    )
    monkeypatch.setattr(g, "background", lambda img: (img, 1.0))

    monkeypatch.setattr(
        g,
        "load_star_catalog",
        lambda cr1, cr2: (
            0.0,
            0.0,
            np.array([0.0]),
            np.array([0.0]),
            np.array([10.0]),
            np.array([20.0]),
            np.array([1000.0]),
        ),
    )
    monkeypatch.setattr(
        g,
        "select_stars",
        lambda *a, **k: (np.array([10.0]), np.array([20.0]), np.array([1000.0])),
    )
    monkeypatch.setattr(
        g,
        "radec_to_xy_stars",
        lambda *a, **k: (
            np.array([10]),
            np.array([10]),
            np.array([10.0]),
            np.array([10.0]),
        ),
    )

    def fake_cal_centroid_offset(*args, **kwargs):
        stack = kwargs.get("cutoutn_stack", args[8] if len(args) > 8 else [])
        return [1.0], [2.0], [100.0], stack

    monkeypatch.setattr(g, "cal_centroid_offset", fake_cal_centroid_offset)
    monkeypatch.setattr(
        g,
        "peak_select",
        lambda dx, dy, peakc: (np.array([1.0]), np.array([2.0]), np.array([0])),
    )

    monkeypatch.setattr(g, "cal_final_offset", lambda dxp, dyp, pindp: (1.23, 4.56))
    monkeypatch.setattr(g, "cal_seeing", lambda cutouts: 0.78)

    fdx, fdy, fwhm = g.exe_cal()
    assert fdx == 1.23 and fdy == 4.56 and fwhm == 0.78
