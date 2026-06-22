# tests/test_gfa_getcrval.py
import json
import logging
import math
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

import kspec_gfa_controller.gfa_getcrval as mod


def _plain_test_logger() -> logging.Logger:
    """
    테스트 전용 로거.
    gfa_getcrval 내부의 GFALogger/adapter 로직과 충돌을 피하려고
    테스트에서는 _get_logger를 통째로 패치해서 이 로거만 쓰게 한다.
    """
    lg = logging.getLogger("test_gfa_getcrval_plain")
    lg.handlers.clear()
    lg.addHandler(logging.NullHandler())
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    return lg


@pytest.fixture
def lg(monkeypatch):
    """
    모든 테스트에서 gfa_getcrval._get_logger를 패치해서
    JobAdapter/LogRecordFactory 관련 부작용을 차단.
    """
    logger = _plain_test_logger()
    monkeypatch.setattr(mod, "_get_logger", lambda _logger=None: logger, raising=True)
    return logger


def _write_fits(
    path: Path, ra=None, dec=None, crval1=None, crval2=None, extra_hdr=None
):
    hdr = fits.Header()
    if ra is not None:
        hdr["RA"] = ra
    if dec is not None:
        hdr["DEC"] = dec
    if crval1 is not None:
        hdr["CRVAL1"] = crval1
    if crval2 is not None:
        hdr["CRVAL2"] = crval2
    if extra_hdr:
        for k, v in extra_hdr.items():
            hdr[k] = v

    data = np.zeros((2, 3), dtype=np.float32)
    fits.PrimaryHDU(data=data, header=hdr).writeto(path, overwrite=True)


def _write_config(path: Path, override: dict | None = None):
    cfg = {
        "astrometry": {
            "scale_range": [0.1, 2.0],
            "radius": 1.0,
        },
        "settings": {"cpu": {"limit": 30}},
    }
    if override:
        # shallow merge is enough for tests
        for k, v in override.items():
            cfg[k] = v
    path.write_text(json.dumps(cfg), encoding="utf-8")


# -------------------------
# _get_logger()
# -------------------------
def test_get_logger_returns_plain_logger_via_patch(lg):
    out = mod._get_logger(None)
    assert out is lg


# -------------------------
# _get_solve_field_path()
# -------------------------
def test_get_solve_field_path_env_override_success(monkeypatch, lg, tmp_path):
    fake = tmp_path / "solve-field"
    fake.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")

    # exists + executable
    monkeypatch.setattr(
        mod.Path, "exists", lambda self: str(self) == str(fake), raising=False
    )
    monkeypatch.setattr(
        mod.os, "access", lambda p, m: str(p) == str(fake), raising=True
    )

    env = {"ASTROMETRY_SOLVE_FIELD": str(fake)}
    got = mod._get_solve_field_path(lg, env=env)
    assert got == str(fake)


def test_get_solve_field_path_missing_raises_filenotfound(monkeypatch, lg):
    monkeypatch.setattr(mod.Path, "exists", lambda self: False, raising=False)
    monkeypatch.setattr(mod.os, "access", lambda p, m: True, raising=True)

    with pytest.raises(FileNotFoundError):
        mod._get_solve_field_path(
            lg, env={"ASTROMETRY_SOLVE_FIELD": "/nope/solve-field"}
        )


def test_get_solve_field_path_not_executable_raises_permission(
    monkeypatch, lg, tmp_path
):
    fake = tmp_path / "solve-field"
    fake.write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        mod.Path, "exists", lambda self: str(self) == str(fake), raising=False
    )
    monkeypatch.setattr(mod.os, "access", lambda p, m: False, raising=True)

    with pytest.raises(PermissionError):
        mod._get_solve_field_path(lg, env={"ASTROMETRY_SOLVE_FIELD": str(fake)})


# -------------------------
# _read_ra_dec()
# -------------------------
def test_read_ra_dec_float_and_string(tmp_path, lg):
    f1 = tmp_path / "a.fits"
    _write_fits(f1, ra=12.34, dec=-56.78)

    ra, dec = mod._read_ra_dec(f1, lg)
    assert ra == "12.34"
    assert dec == "-56.78"

    f2 = tmp_path / "b.fits"
    _write_fits(f2, ra="123.0", dec="45.6")

    ra, dec = mod._read_ra_dec(f2, lg)
    assert ra == "123.0"
    assert dec == "45.6"


def test_read_ra_dec_missing_raises(tmp_path, lg):
    f = tmp_path / "no_radec.fits"
    _write_fits(f)
    with pytest.raises(ValueError):
        mod._read_ra_dec(f, lg)


# -------------------------
# _load_config()
# -------------------------
def test_load_config_from_path(tmp_path, lg):
    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    cfg = mod._load_config(cfgp, lg)
    assert cfg["astrometry"]["scale_range"] == [0.1, 2.0]
    assert cfg["settings"]["cpu"]["limit"] == 30


def test_load_config_missing_file_raises_filenotfound(tmp_path, lg):
    cfgp = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError):
        mod._load_config(cfgp, lg)


def test_load_config_none_without_default_raises(monkeypatch, lg):
    """
    현재 구현은 config=None이면 _get_default_config_path()를 호출한다.
    _get_default_config_path 자체를 None으로 만들면 호출 시 TypeError가 나는 것이 정상.
    """
    monkeypatch.setattr(mod, "_get_default_config_path", None, raising=True)
    with pytest.raises(TypeError):
        mod._load_config(None, lg)


def test_load_config_none_uses_default_path(monkeypatch, tmp_path, lg):
    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    monkeypatch.setattr(
        mod, "_get_default_config_path", lambda: str(cfgp), raising=True
    )
    cfg = mod._load_config(None, lg)
    assert cfg["settings"]["cpu"]["limit"] == 30


# -------------------------
# _list_dir()
# -------------------------
def test_list_dir_handles_oserror(monkeypatch, tmp_path):
    def boom(_p):
        raise OSError("nope")

    monkeypatch.setattr(mod.os, "listdir", boom, raising=True)
    out = mod._list_dir(tmp_path)
    assert out == ["<failed to list directory>"]


# -------------------------
# _run_solve_field()
# -------------------------
def test_run_solve_field_timeout_becomes_runtimeerror(monkeypatch, lg):
    def _raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(
            cmd="solve-field ...", timeout=1, output="o", stderr="e"
        )

    monkeypatch.setattr(mod.subprocess, "run", _raise_timeout, raising=True)

    with pytest.raises(RuntimeError) as e:
        mod._run_solve_field("solve-field ...", lg, timeout=1, env={})
    assert "timed out" in str(e.value).lower()


def test_run_solve_field_crash_reraises(monkeypatch, lg):
    def _raise(*a, **k):
        raise RuntimeError("crash")

    monkeypatch.setattr(mod.subprocess, "run", _raise, raising=True)

    with pytest.raises(RuntimeError):
        mod._run_solve_field("solve-field ...", lg, timeout=1, env={})


def test_run_solve_field_returncode_nonzero_raises(monkeypatch, lg):
    class R:
        returncode = 2
        stdout = "OUT"
        stderr = "ERR"

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: R(), raising=True)

    with pytest.raises(RuntimeError):
        mod._run_solve_field("solve-field ...", lg, timeout=1, env={})


# -------------------------
# _find_solved_new_file()
# -------------------------
def test_find_solved_new_file_fit_extension_and_fallback_glob(
    tmp_path, lg, monkeypatch
):
    """
    .fit 확장자 패턴 분기 + stem*.new 폴백 분기 커버(207-218, 224, 242-245 등).
    """
    img = tmp_path / "x.fit"
    img.write_text("dummy", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()

    # exact /x.new 패턴은 빈 리스트 -> fallback stem*.new에서 찾게
    solved = work / "x_something.new"
    solved.write_text("dummy", encoding="utf-8")

    def fake_glob(pat):
        s = str(pat)
        if s.endswith(str(work / "x.new")):
            return []
        if s.endswith(str(work / "x*.new")):
            return [str(solved)]
        return []

    monkeypatch.setattr(mod.glob, "glob", fake_glob, raising=True)

    got = mod._find_solved_new_file(img, work, lg)
    assert got.name == "x_something.new"


def test_find_solved_new_file_multiple_candidates_sorted_first(
    tmp_path, lg, monkeypatch
):
    img = tmp_path / "img.fits"
    img.write_text("dummy", encoding="utf-8")
    work = tmp_path / "work2"
    work.mkdir()

    a = work / "img_b.new"
    b = work / "img_a.new"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")

    monkeypatch.setattr(mod.glob, "glob", lambda pat: [str(a), str(b)], raising=True)

    got = mod._find_solved_new_file(img, work, lg)
    # sorted(set()) => img_a.new 먼저
    assert got.name == "img_a.new"


# -------------------------
# get_crval_from_image()
# -------------------------
def _patch_solve_field_ok(monkeypatch):
    """
    gfa_getcrval은 solve-field 경로를 Path.exists + os.access로 검사한다.
    테스트에서는 이 검사를 우회한다.
    """
    monkeypatch.setattr(mod.Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(mod.os, "access", lambda p, m: True, raising=True)


def test_get_crval_from_image_input_missing_raises(tmp_path, monkeypatch, lg):
    _patch_solve_field_ok(monkeypatch)

    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    with pytest.raises(FileNotFoundError):
        mod.get_crval_from_image(tmp_path / "nope.fits", config=cfgp, logger=lg)


def test_get_crval_from_image_explicit_solve_field_missing_raises(tmp_path, lg):
    """
    solve_field 인자 명시 시: exists 체크 분기 커버.
    Path.exists를 패치하면 pytest 내부까지 영향가서 위험하므로 실제로 없는 경로를 준다.
    """
    img = tmp_path / "img.fits"
    _write_fits(img, ra=10.0, dec=20.0)
    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    with pytest.raises(FileNotFoundError):
        mod.get_crval_from_image(
            img, config=cfgp, logger=lg, solve_field=tmp_path / "nope_solve_field"
        )


def test_get_crval_from_image_explicit_solve_field_not_exec_raises(
    tmp_path, monkeypatch, lg
):
    """
    solve_field 인자 명시 시: executable 체크(PermissionError) 분기 커버.
    Path.exists 패치 금지(pytest 내부에 영향) -> 실제 파일을 만들고 os.access만 False로 둔다.
    """
    img = tmp_path / "img.fits"
    _write_fits(img, ra=10.0, dec=20.0)
    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    sf = tmp_path / "solve-field"
    sf.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")  # exists=True 보장

    # executable check만 실패시키기
    monkeypatch.setattr(mod.os, "access", lambda p, m: False, raising=True)

    with pytest.raises(PermissionError):
        mod.get_crval_from_image(img, config=cfgp, logger=lg, solve_field=sf)


def test_get_crval_from_image_config_missing_required_keys_raises_keyerror(
    tmp_path, monkeypatch, lg
):
    """
    inpar 키 누락 시 KeyError 분기(350-352) 커버.
    """
    _patch_solve_field_ok(monkeypatch)

    img = tmp_path / "img.fits"
    _write_fits(img, ra=10.0, dec=20.0)

    # astrometry/settings.cpu.limit 일부러 누락
    cfgp = tmp_path / "cfg_bad.json"
    cfgp.write_text(
        json.dumps({"astrometry": {}}, ensure_ascii=False), encoding="utf-8"
    )

    # solve-field는 실행되면 안 되므로 여기서 막아도 됨
    monkeypatch.setattr(mod, "_run_solve_field", lambda *a, **k: None, raising=True)

    with pytest.raises(KeyError):
        mod.get_crval_from_image(
            img, config=cfgp, logger=lg, work_dir=tmp_path / "w", keep_work_dir=True
        )


def test_get_crval_from_image_crval_missing_raises(tmp_path, monkeypatch, lg):
    """
    solved header에 CRVAL1/2가 없을 때 예외 분기(387-395) 커버.
    """
    _patch_solve_field_ok(monkeypatch)

    img = tmp_path / "img.fits"
    _write_fits(img, ra=10.0, dec=20.0)
    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    work = tmp_path / "work_crval"
    work.mkdir()

    # solve-field 성공처럼
    monkeypatch.setattr(mod, "_run_solve_field", lambda *a, **k: None, raising=True)

    # .new 파일 생성 (CRVAL 없음, 대신 WCS 비슷한 키만 넣어서 candidate 키 로깅 경로 유도)
    solved = work / "img.new"
    _write_fits(
        solved,
        crval1=None,
        crval2=None,
        extra_hdr={"CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN"},
    )

    monkeypatch.setattr(
        mod, "_find_solved_new_file", lambda *a, **k: solved, raising=True
    )

    with pytest.raises(Exception):
        mod.get_crval_from_image(
            img, config=cfgp, logger=lg, work_dir=work, keep_work_dir=True
        )


def test_get_crval_from_image_subprocess_error_becomes_runtimeerror_and_keeps_persistent_dir(
    tmp_path, monkeypatch, lg
):
    """
    work_dir=None이면 DEFAULT_RES_ROOT 아래 persistent work_dir 생성(tmp_created=True).
    실패해도 기본적으로 삭제하지 않는다. (keep_work_dir=False라도 tmp_created=True면 유지)
    """
    _patch_solve_field_ok(monkeypatch)

    img = tmp_path / "img.fits"
    _write_fits(img, ra=10.0, dec=20.0)
    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    # _run_solve_field가 RuntimeError를 던지도록
    monkeypatch.setattr(
        mod,
        "_run_solve_field",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        raising=True,
    )

    # DEFAULT_RES_ROOT를 tmp_path 아래로 바꿔서 테스트가 시스템 경로를 건드리지 않게
    res_root = tmp_path / "res_root"
    monkeypatch.setattr(mod, "DEFAULT_RES_ROOT", res_root, raising=True)

    with pytest.raises(RuntimeError):
        mod.get_crval_from_image(
            img, config=cfgp, logger=lg, work_dir=None, keep_work_dir=False
        )

    assert res_root.exists()


def test_get_crval_from_image_stem_fallback_glob(tmp_path, monkeypatch, lg):
    _patch_solve_field_ok(monkeypatch)

    img = tmp_path / "img.fits"
    _write_fits(img, ra=10.0, dec=20.0)
    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    work = tmp_path / "work"
    work.mkdir()

    # solve-field 성공처럼
    monkeypatch.setattr(mod, "_run_solve_field", lambda *a, **k: None, raising=True)

    solved = work / "img.new"
    _write_fits(solved, crval1=1.1, crval2=2.2)

    def fake_glob(pattern):
        s = str(pattern)
        if s.endswith("/img.new") or s.endswith("\\img.new"):
            return []
        return [str(solved)]

    monkeypatch.setattr(mod.glob, "glob", fake_glob, raising=True)

    c1, c2 = mod.get_crval_from_image(
        img, config=cfgp, logger=lg, work_dir=work, keep_work_dir=True
    )
    assert c1 == 1.1
    assert c2 == 2.2


def test_get_crval_from_image_new_file_missing_lists_dir(tmp_path, monkeypatch, lg):
    _patch_solve_field_ok(monkeypatch)

    img = tmp_path / "img.fits"
    _write_fits(img, ra=10.0, dec=20.0)
    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    work = tmp_path / "work"
    work.mkdir()
    (work / "dummy.txt").write_text("x", encoding="utf-8")

    # solve-field 성공처럼
    monkeypatch.setattr(mod, "_run_solve_field", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(mod.glob, "glob", lambda pattern: [], raising=True)

    with pytest.raises(FileNotFoundError) as e:
        mod.get_crval_from_image(
            img, config=cfgp, logger=lg, work_dir=work, keep_work_dir=True
        )

    assert "Files=" in str(e.value)
    assert "dummy.txt" in str(e.value)


def test_get_crval_from_image_happy_path_and_cleanup_when_keep_false(
    tmp_path, monkeypatch, lg
):
    """
    caller가 work_dir를 명시적으로 준 경우(tmp_created=False),
    keep_work_dir=False면 cleanup(rmtree) 호출이 일어난다.
    """
    _patch_solve_field_ok(monkeypatch)

    img = tmp_path / "img.fits"
    _write_fits(img, ra=10.0, dec=20.0)
    cfgp = tmp_path / "cfg.json"
    _write_config(cfgp)

    work = tmp_path / "work"
    work.mkdir()

    # solve-field 성공처럼
    monkeypatch.setattr(mod, "_run_solve_field", lambda *a, **k: None, raising=True)

    solved = work / "img.new"
    _write_fits(solved, crval1=123.456, crval2=-78.9)
    monkeypatch.setattr(mod.glob, "glob", lambda pattern: [str(solved)], raising=True)

    called = {"rm": 0}
    monkeypatch.setattr(
        mod.shutil,
        "rmtree",
        lambda p, ignore_errors=True: called.__setitem__("rm", called["rm"] + 1),
        raising=True,
    )

    c1, c2 = mod.get_crval_from_image(
        img, config=cfgp, logger=lg, work_dir=work, keep_work_dir=False
    )
    assert c1 == 123.456
    assert c2 == -78.9
    assert called["rm"] == 1


# -------------------------
# get_crvals_from_images()
# -------------------------
def test_get_crvals_from_images_preserves_order_and_nan(tmp_path, monkeypatch, lg):
    paths = [tmp_path / f"i{i}.fits" for i in range(4)]
    for p in paths:
        p.write_text("dummy", encoding="utf-8")

    def _fake_get_crval_from_image(
        p,
        config=None,
        logger=None,
        work_dir=None,
        keep_work_dir=False,
        solve_field=None,
        subprocess_env=None,
    ):
        name = Path(p).name
        if name in ("i1.fits", "i3.fits"):
            raise RuntimeError("boom")
        idx = int(name[1])  # i0.fits -> 0
        return (100.0 + idx, 200.0 + idx)

    monkeypatch.setattr(
        mod, "get_crval_from_image", _fake_get_crval_from_image, raising=True
    )

    cr1, cr2 = mod.get_crvals_from_images(paths, config=None, logger=lg, max_workers=2)

    assert cr1[0] == 100.0 and cr2[0] == 200.0
    assert math.isnan(cr1[1]) and math.isnan(cr2[1])
    assert cr1[2] == 102.0 and cr2[2] == 202.0
    assert math.isnan(cr1[3]) and math.isnan(cr2[3])
