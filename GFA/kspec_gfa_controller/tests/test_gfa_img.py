# tests/test_gfa_img.py
import logging
import os
import warnings
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from PIL import Image

warnings.filterwarnings("ignore", category=DeprecationWarning)

UNDER_TEST_MODNAME = "kspec_gfa_controller.gfa_img__under_test"


def _find_gfa_img_py() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root / "src" / "kspec_gfa_controller" / "gfa_img.py",  # src layout
        repo_root / "kspec_gfa_controller" / "gfa_img.py",  # non-src layout
    ]
    for p in candidates:
        if p.exists():
            return p
    raise RuntimeError(
        "gfa_img.py not found. tried:\n" + "\n".join(map(str, candidates))
    )


def _load_module_force():
    """
    gfa_img.py만 '강제' 로딩.
    다른 테스트가 같은 모듈명을 건드려도 영향 없도록 고정 이름 사용 + 재로딩.
    """
    path = _find_gfa_img_py()

    if UNDER_TEST_MODNAME in globals():
        pass

    # 항상 재로딩
    import sys

    if UNDER_TEST_MODNAME in sys.modules:
        del sys.modules[UNDER_TEST_MODNAME]

    spec = spec_from_file_location(UNDER_TEST_MODNAME, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to create import spec for: {path}")
    module = module_from_spec(spec)
    sys.modules[UNDER_TEST_MODNAME] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module_force()
GFAImage = mod.GFAImage


@pytest.fixture
def logger():
    lg = logging.getLogger("test_gfa_img")
    lg.setLevel(logging.DEBUG)
    if not lg.handlers:
        lg.addHandler(logging.NullHandler())
    return lg


# -------------------------
# save_fits
# -------------------------
def test_save_fits_writes_file_and_header(tmp_path, logger, caplog):
    caplog.set_level(logging.DEBUG)

    img = GFAImage(logger=logger)
    arr = np.arange(12, dtype=np.float32).reshape(3, 4) / 100.0

    img.save_fits(
        image_array=arr,
        filename="test_image",
        exptime=1.23,
        telescope="KMTNET",
        instrument="KSPEC-GFA",
        observer="Mingyeong",
        object_name="M42",
        date_obs="2025-12-17",
        time_obs="12:34:56",
        ra=None,
        dec=None,
        output_directory=str(tmp_path),
    )

    out = tmp_path / "test_image.fits"
    assert out.exists()

    with fits.open(out) as hdul:
        data = hdul[0].data
        hdr = hdul[0].header

    assert data.shape == (3, 4)
    assert np.isfinite(data).all()

    assert hdr["NAXIS"] == 2
    assert hdr["NAXIS1"] == 4
    assert hdr["NAXIS2"] == 3
    assert hdr["TELESCOP"] == "KMTNET"
    assert hdr["INSTRUME"] == "KSPEC-GFA"
    assert hdr["OBSERVER"] == "Mingyeong"
    assert hdr["OBJECT"] == "M42"
    assert hdr["DATE-OBS"] == "2025-12-17"
    assert hdr["TIME-OBS"] == "12:34:56"
    assert hdr["RA"] == "UNKNOWN"
    assert hdr["DEC"] == "UNKNOWN"
    assert hdr["EXPTIME"] == 1.23

    assert any("successfully saved" in r.message.lower() for r in caplog.records)


def test_save_fits_replaces_colon_in_filename(tmp_path, logger):
    img = GFAImage(logger=logger)
    arr = np.zeros((2, 2), dtype=np.float32)

    img.save_fits(
        image_array=arr,
        filename="2025-12-17T12:34:56",
        exptime=0.5,
        date_obs="2025-12-17",
        time_obs="12:34:56",
        output_directory=str(tmp_path),
    )

    assert (tmp_path / "2025-12-17T12-34-56.fits").exists()


def test_save_fits_creates_output_directory(tmp_path, logger):
    img = GFAImage(logger=logger)
    arr = np.ones((2, 3), dtype=np.float32)

    outdir = tmp_path / "new_dir"
    assert not outdir.exists()

    img.save_fits(
        image_array=arr,
        filename="abc",
        exptime=1.0,
        date_obs="2025-12-17",
        time_obs="00:00:00",
        output_directory=str(outdir),
    )

    assert outdir.exists()
    assert (outdir / "abc.fits").exists()


def test_save_fits_logs_warning_when_date_or_time_missing(
    tmp_path, logger, caplog, monkeypatch
):
    caplog.set_level(logging.WARNING)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 12, 17, 12, 34, 56)

    # gfa_img.py 내부는 "from datetime import datetime"
    monkeypatch.setattr(mod, "datetime", FixedDatetime, raising=True)

    img = mod.GFAImage(logger=logger)
    arr = np.zeros((1, 1), dtype=np.float32)

    img.save_fits(
        image_array=arr,
        filename="warn_case",
        exptime=1.0,
        date_obs=None,
        time_obs=None,
        output_directory=str(tmp_path),
    )

    msgs = [r.message.lower() for r in caplog.records]
    assert any("no date_obs provided" in m for m in msgs)
    assert any("no time_obs provided" in m for m in msgs)

    out = tmp_path / "warn_case.fits"
    with fits.open(out) as hdul:
        hdr = hdul[0].header
    assert hdr["DATE-OBS"] == "2025-12-17"
    assert hdr["TIME-OBS"] == "12:34:56"


def test_save_fits_uses_cwd_when_output_directory_none(tmp_path, logger, monkeypatch):
    img = GFAImage(logger=logger)
    arr = np.zeros((2, 2), dtype=np.float32)

    monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))

    img.save_fits(
        image_array=arr,
        filename="cwd_case",
        exptime=1.0,
        date_obs="2025-12-17",
        time_obs="00:00:00",
        output_directory=None,
    )

    assert (tmp_path / "cwd_case.fits").exists()


def test_save_fits_does_not_call_makedirs_if_dir_exists(tmp_path, logger, monkeypatch):
    img = GFAImage(logger=logger)
    arr = np.zeros((2, 2), dtype=np.float32)

    called = {"n": 0}

    def _boom(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("os.makedirs should not be called when dir exists")

    monkeypatch.setattr(os, "makedirs", _boom)

    img.save_fits(
        image_array=arr,
        filename="exists_dir",
        exptime=1.0,
        date_obs="2025-12-17",
        time_obs="00:00:00",
        output_directory=str(tmp_path),
    )

    assert called["n"] == 0
    assert (tmp_path / "exists_dir.fits").exists()


def test_save_fits_raises_when_cannot_create_directory(
    tmp_path, logger, monkeypatch, caplog
):
    caplog.set_level(logging.ERROR)

    img = GFAImage(logger=logger)
    arr = np.zeros((2, 2), dtype=np.float32)
    bad_dir = tmp_path / "cannot_make"
    assert not bad_dir.exists()

    def _raise(*args, **kwargs):
        raise OSError("no permission")

    monkeypatch.setattr(os, "makedirs", _raise)

    with pytest.raises(OSError):
        img.save_fits(
            image_array=arr,
            filename="x",
            exptime=1.0,
            output_directory=str(bad_dir),
        )

    assert any("error creating directory" in r.message.lower() for r in caplog.records)


def test_save_fits_when_filename_already_has_extension(tmp_path, logger):
    img = GFAImage(logger=logger)
    arr = np.zeros((1, 2), dtype=np.float32)

    img.save_fits(
        image_array=arr,
        filename="already.fits",
        exptime=1.0,
        date_obs="2025-12-17",
        time_obs="00:00:00",
        output_directory=str(tmp_path),
    )

    assert (tmp_path / "already.fits").exists()


# -------------------------
# save_png (커버리지 핵심 구간)
# -------------------------
def test_save_png_invalid_bit_depth_raises(tmp_path, logger):
    img = GFAImage(logger=logger)
    arr = np.zeros((10, 10), dtype=np.float32)

    with pytest.raises(ValueError):
        img.save_png(arr, "x", output_directory=str(tmp_path), bit_depth=12)


def test_save_png_flat_image_saves_black_and_returns(tmp_path, logger, caplog):
    caplog.set_level(logging.WARNING)

    img = GFAImage(logger=logger)
    arr = np.full((8, 8), 7.0, dtype=np.float32)  # img_min == img_max

    img.save_png(arr, "flat", output_directory=str(tmp_path), bit_depth=8)
    out = tmp_path / "flat.png"
    assert out.exists()

    im = Image.open(out)
    data = np.array(im)
    assert data.dtype == np.uint8
    assert np.all(data == 0)  # black

    assert any("flat image detected" in r.message.lower() for r in caplog.records)


def test_save_png_zscale_failure_falls_back_to_minmax(
    tmp_path, logger, monkeypatch, caplog
):
    caplog.set_level(logging.WARNING)

    img = GFAImage(logger=logger)
    arr = np.arange(100, dtype=np.float32).reshape(10, 10)

    # ZScaleInterval(...).get_limits(img)에서 예외를 던지게 만들기
    class FakeZ:
        def __init__(self, contrast=0.25):
            pass

        def get_limits(self, _img):
            raise RuntimeError("zscale boom")

    monkeypatch.setattr(mod, "ZScaleInterval", FakeZ, raising=True)

    img.save_png(arr, "zfail", output_directory=str(tmp_path), bit_depth=8)
    out = tmp_path / "zfail.png"
    assert out.exists()

    assert any("zscale failed" in r.message.lower() for r in caplog.records)


def test_save_png_invalid_range_even_after_fallback_raises(
    tmp_path, logger, monkeypatch, caplog
):
    caplog.set_level(logging.ERROR)

    img = GFAImage(logger=logger)
    arr = np.arange(9, dtype=np.float32).reshape(3, 3)

    # vmin/vmax를 강제로 동일하게 주면 final safety guard가 터져야 함
    with pytest.raises(ValueError):
        img.save_png(
            arr,
            "bad_range",
            output_directory=str(tmp_path),
            vmin=1.0,
            vmax=1.0,
            bit_depth=8,
        )

    assert any(
        "invalid normalization range" in r.message.lower() for r in caplog.records
    )


def test_save_png_16bit_saves_uint16(tmp_path, logger):
    img = GFAImage(logger=logger)
    arr = np.linspace(0, 100, 256, dtype=np.float32).reshape(16, 16)

    img.save_png(arr, "img16", output_directory=str(tmp_path), bit_depth=16)
    out = tmp_path / "img16.png"
    assert out.exists()

    im = Image.open(out)
    data = np.array(im)
    # PIL이 모드/플랫폼에 따라 uint16로 읽힐 수 있음 (대부분 uint16)
    assert data.dtype in (np.uint16, np.int32, np.int64)


# -------------------------
# hot_pixel_removal_median_ratio (295/299/307-308 커버)
# -------------------------
def test_hot_pixel_removal_replaces_hot_pixel_float():
    img = np.zeros((5, 5), dtype=np.float32)
    img[2, 2] = 1000.0  # hot pixel
    out = GFAImage.hot_pixel_removal_median_ratio(img, factor=5.0, n_iter=1, eps=1e-6)

    # 주변 median=0 근처 -> eps로 denom 보호
    # hot pixel은 median(0)에 치환되어 0이 되어야 함
    assert out[2, 2] == 0.0


def test_hot_pixel_removal_respects_saturated_value():
    img = np.zeros((5, 5), dtype=np.float32)
    img[2, 2] = 65535.0  # saturated
    out = GFAImage.hot_pixel_removal_median_ratio(
        img, factor=1.5, n_iter=1, saturated_value=65535.0
    )
    # saturated_value는 제외되어 그대로 남아야 함
    assert out[2, 2] == 65535.0


def test_hot_pixel_removal_abs_threshold_blocks_small_diffs():
    img = np.zeros((5, 5), dtype=np.float32)
    img[2, 2] = 2.0
    # 주변 median ~0, factor=1.5면 mask 후보지만 abs_threshold=10이면 제거되면 안됨
    out = GFAImage.hot_pixel_removal_median_ratio(
        img, factor=1.5, n_iter=1, abs_threshold=10.0
    )
    assert out[2, 2] == 2.0


def test_hot_pixel_removal_keep_dtype_integer_roundtrip():
    img = np.zeros((5, 5), dtype=np.uint16)
    img[2, 2] = 5000
    out = GFAImage.hot_pixel_removal_median_ratio(
        img, factor=1.5, n_iter=1, keep_dtype=True
    )

    assert out.dtype == np.uint16
    # 주변 median=0 => 치환되면 0
    assert out[2, 2] == 0
