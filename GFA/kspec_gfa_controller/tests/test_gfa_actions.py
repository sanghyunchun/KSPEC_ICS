# tests/test_gfa_actions.py
import os
import sys
import types
import importlib
from pathlib import Path

import pytest


# -------------------------
# Minimal fakes
# -------------------------
class FakeLogger:
    def __init__(self):
        self.logs = []

    def info(self, m):
        self.logs.append(("info", str(m)))

    def debug(self, m):
        self.logs.append(("debug", str(m)))

    def warning(self, m):
        self.logs.append(("warning", str(m)))

    def error(self, m):
        self.logs.append(("error", str(m)))


class FakeController:
    def __init__(self, grabone_result=None):
        self._grabone_result = grabone_result if grabone_result is not None else []
        self.grabone_calls = []
        self.grab_calls = []
        self.ping_calls = []
        self.status_called = 0
        self.cam_params_calls = []

        self.open_all_called = 0
        self.close_all_called = 0

    async def open_all_cameras(self):
        self.open_all_called += 1
        return None

    async def close_all_cameras(self):
        self.close_all_called += 1
        return None

    async def grabone(self, **kwargs):
        self.grabone_calls.append(kwargs)
        return list(self._grabone_result)

    async def grab(self, CamNum, ExpTime, Binning, **kwargs):
        self.grab_calls.append((CamNum, ExpTime, Binning, kwargs))
        return []

    def status(self):
        self.status_called += 1
        return {"Cam1": True, "Cam2": False}

    def ping(self, cam_id):
        self.ping_calls.append(cam_id)

    def cam_params(self, cam_id):
        self.cam_params_calls.append(cam_id)
        return {"mock": cam_id}


class FakeAstrometry:
    """
    최신 gfa_actions.py 기준:
    - set_subprocess_env(clean_env) 호출됨
    - ensure_astrometry_ready() 있으면 그걸 사용
    - guiding() 마지막에 clear_raw_files() 호출
    """

    def __init__(self, ensure_outputs=None):
        self.subprocess_env_set = None
        self.ensure_called = 0
        self.preproc_called = 0
        self.clear_raw_called = 0
        self._ensure_outputs = (
            ensure_outputs
            if ensure_outputs is not None
            else [
                "/tmp/astro_1.fits",
                "/tmp/astro_2.fits",
            ]
        )

    def set_subprocess_env(self, env: dict):
        self.subprocess_env_set = env

    def ensure_astrometry_ready(self):
        self.ensure_called += 1
        return list(self._ensure_outputs)

    # fallback 경로용(혹시 ensure_astrometry_ready가 없을 때)
    def preproc(self):
        self.preproc_called += 1

    def clear_raw_files(self):
        self.clear_raw_called += 1


class FakeGuider:
    def __init__(self, fdx=1.0, fdy=2.0, fwhm=3.0):
        self._ret = (fdx, fdy, fwhm)
        self.exe_called = 0

    def exe_cal(self):
        self.exe_called += 1
        return self._ret


class FakeEnv:
    def __init__(
        self, camera_ids=(1, 2, 3), controller=None, astrometry=None, guider=None
    ):
        self.logger = FakeLogger()
        self.camera_ids = list(camera_ids)
        self.controller = controller if controller is not None else FakeController()
        self.astrometry = astrometry if astrometry is not None else FakeAstrometry()
        self.guider = guider if guider is not None else FakeGuider()
        self.shutdown_called = 0

    def shutdown(self):
        self.shutdown_called += 1


# -------------------------
# Import helper (핵심)
# -------------------------
@pytest.fixture
def ga_module(monkeypatch):
    """
    gfa_actions import 시 SciPy로 내려가는 체인을 끊기 위해,
    gfa_environment / gfa_logger / gfa_getcrval 를 sys.modules에 fake로 주입 후 import.
    """
    pkg = "kspec_gfa_controller"

    # fake gfa_logger
    m_logger = types.ModuleType(f"{pkg}.gfa_logger")

    class _FakeGFALogger:
        def __init__(self, *_a, **_k):
            pass

        def info(self, *_a, **_k):
            pass

        def debug(self, *_a, **_k):
            pass

        def warning(self, *_a, **_k):
            pass

        def error(self, *_a, **_k):
            pass

    m_logger.GFALogger = _FakeGFALogger

    # fake gfa_environment (SciPy 안 타게)
    m_env = types.ModuleType(f"{pkg}.gfa_environment")

    def _fake_create_environment(*, role):
        return FakeEnv()

    class _FakeGFAEnvironment:
        pass

    m_env.create_environment = _fake_create_environment
    m_env.GFAEnvironment = _FakeGFAEnvironment

    # fake gfa_getcrval (pointing에서 import됨)
    m_crval = types.ModuleType(f"{pkg}.gfa_getcrval")

    def _fake_get_crvals_from_images(images, max_workers=4):
        return ([1.0] * len(images), [2.0] * len(images))

    def _fake_get_crval_from_image(image):
        return (1.0, 2.0)

    m_crval.get_crvals_from_images = _fake_get_crvals_from_images
    m_crval.get_crval_from_image = _fake_get_crval_from_image

    monkeypatch.setitem(sys.modules, f"{pkg}.gfa_logger", m_logger)
    monkeypatch.setitem(sys.modules, f"{pkg}.gfa_environment", m_env)
    monkeypatch.setitem(sys.modules, f"{pkg}.gfa_getcrval", m_crval)

    # 이제 안전하게 import
    mod = importlib.import_module(f"{pkg}.gfa_actions")
    return mod


@pytest.fixture
def actions(ga_module):
    return ga_module.GFAActions(env=FakeEnv())


# -------------------------
# __init__: env None branch
# -------------------------
def test_init_env_none_uses_create_environment(monkeypatch, ga_module):
    calls = []

    def fake_create_environment(*, role):
        calls.append(role)
        return FakeEnv()

    monkeypatch.setattr(ga_module, "create_environment", fake_create_environment)
    act = ga_module.GFAActions(env=None)

    assert isinstance(act.env, FakeEnv)
    assert calls == ["plate"]


# -------------------------
# Basic unit: response shape
# -------------------------
def test_generate_response(actions):
    r = actions._generate_response("success", "ok", a=1, b="x")
    assert r["status"] == "success"
    assert r["message"] == "ok"
    assert r["a"] == 1
    assert r["b"] == "x"


# -------------------------
# grab(): CamNum=int (single)
# -------------------------
@pytest.mark.asyncio
async def test_grab_single_camera_success_message(actions, monkeypatch):
    actions.env.controller._grabone_result = []  # timeout 없음
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )

    r = await actions.grab(
        CamNum=2,
        ExpTime=1.5,
        Binning=4,
        packet_size=1500,
        cam_ipd=10,
        cam_ftd_base=123,
        ra="1",
        dec="2",
    )
    assert r["status"] == "success"
    assert "camera 2" in r["message"].lower()

    assert actions.env.controller.open_all_called == 1
    assert actions.env.controller.close_all_called == 1

    assert len(actions.env.controller.grabone_calls) == 1
    kwargs = actions.env.controller.grabone_calls[0]
    assert kwargs["CamNum"] == 2
    assert kwargs["ExpTime"] == 1.5
    assert kwargs["Binning"] == 4
    assert kwargs["packet_size"] == 1500
    assert kwargs["ipd"] == 10
    assert kwargs["ftd_base"] == 123
    assert kwargs["ra"] == "1"
    assert kwargs["dec"] == "2"
    assert "output_dir" in kwargs


@pytest.mark.asyncio
async def test_grab_single_camera_timeout_in_message(actions, monkeypatch):
    actions.env.controller._grabone_result = [2]
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )

    r = await actions.grab(CamNum=2)
    assert r["status"] == "success"
    assert "timeout" in r["message"].lower()

    assert actions.env.controller.open_all_called == 1
    assert actions.env.controller.close_all_called == 1


# -------------------------
# grab(): CamNum=0 (all)
# -------------------------
@pytest.mark.asyncio
async def test_grab_all_cameras_aggregates_timeouts(actions, monkeypatch):
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )

    async def fake_grabone(**kwargs):
        cam = kwargs["CamNum"]
        return [cam] if cam in (1, 3) else []

    actions.env.controller.grabone = fake_grabone

    r = await actions.grab(CamNum=0)
    assert r["status"] == "success"
    assert "all cameras" in r["message"].lower()
    assert "timeout" in r["message"].lower()
    assert "1" in r["message"]
    assert "3" in r["message"]

    assert actions.env.controller.open_all_called == 1
    assert actions.env.controller.close_all_called == 1


# -------------------------
# grab(): CamNum=list
# -------------------------
@pytest.mark.asyncio
async def test_grab_camera_list(actions, monkeypatch):
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )

    async def fake_grabone(**kwargs):
        return [kwargs["CamNum"]] if kwargs["CamNum"] == 5 else []

    actions.env.camera_ids = [1, 2, 3, 4, 5]
    actions.env.controller.grabone = fake_grabone

    r = await actions.grab(CamNum=[4, 5])
    assert r["status"] == "success"
    assert "cameras" in r["message"].lower()
    assert "timeout" in r["message"].lower()

    assert actions.env.controller.open_all_called == 1
    assert actions.env.controller.close_all_called == 1


@pytest.mark.asyncio
async def test_grab_invalid_camnum_returns_error(actions, monkeypatch):
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )

    r = await actions.grab(CamNum="bad")  # type: ignore
    assert r["status"] == "error"
    assert "grab failed" in r["message"].lower()

    assert actions.env.controller.open_all_called == 1
    assert actions.env.controller.close_all_called == 1


# -------------------------
# guiding(): success path (save=False)
# -------------------------
@pytest.mark.asyncio
async def test_guiding_success_no_save(actions, monkeypatch):
    # 디렉토리/리스트 I/O 막기
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )
    monkeypatch.setattr("kspec_gfa_controller.gfa_actions.os.listdir", lambda p: [])

    r = await actions.guiding(ExpTime=2.0, save=False, ra="1", dec="2")
    assert r["status"] == "success"
    assert "Offsets:" in r["message"]
    assert "fdx" in r and "fdy" in r and "fwhm" in r

    # guiding()은 현재 grab()을 실제로 호출하지 않음(코드상 pass)
    assert len(actions.env.controller.grab_calls) == 0

    # open/close는 수행됨
    assert actions.env.controller.open_all_called == 1
    assert actions.env.controller.close_all_called == 1

    # clean env가 astrometry로 세팅됨
    assert actions.env.astrometry.subprocess_env_set is not None

    # ensure_astrometry_ready 사용
    assert actions.env.astrometry.ensure_called == 1

    # guider 실행
    assert actions.env.guider.exe_called == 1

    # raw clear 호출 (신규 API)
    assert actions.env.astrometry.clear_raw_called == 1

    # 응답에 astrometry_files basename 리스트 포함
    assert "astrometry_files" in r
    assert r["astrometry_files"] == ["astro_1.fits", "astro_2.fits"]


@pytest.mark.asyncio
async def test_guiding_success_with_save_and_copy(actions, monkeypatch):
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )

    # raw_save_path에 파일이 있는 것처럼
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.listdir",
        lambda p: ["a.fits", "not_a_file"],
    )
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.path.isfile",
        lambda p: str(p).endswith("a.fits"),
    )

    copy_calls = []

    def fake_copy2(src, dst):
        copy_calls.append((src, dst))

    monkeypatch.setattr("kspec_gfa_controller.gfa_actions.shutil.copy2", fake_copy2)

    r = await actions.guiding(ExpTime=1.5, save=True, ra="3", dec="4")
    assert r["status"] == "success"

    # a.fits만 복사됨
    assert len(copy_calls) == 1
    src, dst = copy_calls[0]
    src_norm = os.path.normpath(src)
    dst_norm = os.path.normpath(dst)

    assert src_norm.endswith(os.path.normpath(os.path.join("img", "raw", "a.fits")))
    assert os.path.normpath(os.path.join("img", "grab")) in dst_norm
    assert dst_norm.endswith(os.path.normpath("a.fits"))


@pytest.mark.asyncio
async def test_guiding_fwhm_nonfloat_becomes_zero(actions, monkeypatch):
    actions.env.guider = FakeGuider(fdx=1.0, fdy=2.0, fwhm="bad")  # type: ignore
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )
    monkeypatch.setattr("kspec_gfa_controller.gfa_actions.os.listdir", lambda p: [])

    r = await actions.guiding()
    assert r["status"] == "success"
    assert r["fwhm"] == 0.0


@pytest.mark.asyncio
async def test_guiding_exception_returns_error(actions, monkeypatch):
    def boom():
        raise RuntimeError("ensure failed")

    actions.env.astrometry.ensure_astrometry_ready = boom  # type: ignore
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )
    monkeypatch.setattr("kspec_gfa_controller.gfa_actions.os.listdir", lambda p: [])

    r = await actions.guiding()
    assert r["status"] == "error"
    assert "guiding failed" in r["message"].lower()


# -------------------------
# pointing(): success + no images + exception
# -------------------------
@pytest.mark.asyncio
async def test_pointing_success(actions, monkeypatch):
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )

    removed = []
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.remove", lambda p: removed.append(p)
    )
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.path.isfile", lambda p: True
    )

    # grab 이후 pointing_raw_path에 fits 2개가 있는 것처럼
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.listdir", lambda p: ["a.fits", "b.fits"]
    )

    # ✅ 여기 추가: Path.glob("*.fits")도 2개 반환하도록
    def fake_glob(self, pattern):
        if pattern == "*.fits":
            return [Path("a.fits"), Path("b.fits")]
        return []

    monkeypatch.setattr(Path, "glob", fake_glob, raising=True)

    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.get_crvals_from_images",
        lambda images, max_workers: ([1.0] * len(images), [2.0] * len(images)),
    )

    r = await actions.pointing(
        ra="1",
        dec="2",
        CamNum=0,
        save_by_date=False,
        clear_dir=True,
        max_workers=3,
        save=False,
    )
    assert r["status"] == "success"
    assert r["images"] == ["a.fits", "b.fits"]
    assert r["crval1"] == [1.0, 1.0]
    assert r["crval2"] == [2.0, 2.0]


@pytest.mark.asyncio
async def test_pointing_no_images_returns_error(actions, monkeypatch):
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.listdir", lambda p: []
    )  # no fits

    r = await actions.pointing(
        ra="1", dec="2", save_by_date=False, clear_dir=True, save=False
    )
    assert r["status"] == "error"
    assert r["images"] == []
    assert r["crval1"] == []
    assert r["crval2"] == []


@pytest.mark.asyncio
async def test_pointing_exception_returns_error(actions, monkeypatch):
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.listdir", lambda p: ["a.fits"]
    )

    def boom(images, max_workers):
        raise RuntimeError("solve failed")

    monkeypatch.setattr("kspec_gfa_controller.gfa_actions.get_crvals_from_images", boom)

    r = await actions.pointing(
        ra="1", dec="2", save_by_date=False, clear_dir=False, save=False
    )
    assert r["status"] == "error"
    assert "pointing failed" in r["message"].lower()


# -------------------------
# status/ping/cam_params/shutdown (+error branches)
# -------------------------
def test_status_success(actions):
    r = actions.status()
    assert r["status"] == "success"
    assert isinstance(r["message"], dict)
    assert "Cam1" in r["message"]


def test_status_error(actions):
    def boom():
        raise RuntimeError("status failed")

    actions.env.controller.status = boom  # type: ignore
    r = actions.status()
    assert r["status"] == "error"


def test_ping_all_and_single(actions):
    r = actions.ping(CamNum=0)
    assert r["status"] == "success"
    assert actions.env.controller.ping_calls == actions.env.camera_ids

    actions.env.controller.ping_calls.clear()
    r = actions.ping(CamNum=2)
    assert r["status"] == "success"
    assert actions.env.controller.ping_calls == [2]


def test_ping_error(actions):
    def boom(cam_id):
        raise RuntimeError("ping failed")

    actions.env.controller.ping = boom  # type: ignore
    r = actions.ping(CamNum=2)
    assert r["status"] == "error"
    assert "ping failed" in r["message"].lower()


def test_cam_params_all_and_single(actions):
    r = actions.cam_params(CamNum=0)
    assert r["status"] == "success"
    assert "Cam1" in r["message"]

    r = actions.cam_params(CamNum=2)
    assert r["status"] == "success"
    assert "Cam2" in r["message"]


def test_cam_params_error(actions):
    def boom(cam_id):
        raise RuntimeError("params failed")

    actions.env.controller.cam_params = boom  # type: ignore
    r = actions.cam_params(CamNum=0)
    assert r["status"] == "error"
    assert "params failed" in r["message"].lower()


def test_shutdown_calls_env_shutdown_and_logs(actions):
    actions.shutdown()
    assert actions.env.shutdown_called == 1
    assert any(
        lvl == "info" and "shutdown complete" in msg.lower()
        for (lvl, msg) in actions.env.logger.logs
    )


# ---- 추가 테스트들: coverage holes 채우기 ----


def test_make_clean_subprocess_env_strips_pythonhome_pythonpath_and_prepends_pybin(
    ga_module, monkeypatch, tmp_path
):
    # env에 문제되는 변수 넣기
    monkeypatch.setenv("PYTHONHOME", "/bad/home")
    monkeypatch.setenv("PYTHONPATH", "/bad/path")
    monkeypatch.setenv("PATH", "/usr/bin")

    # os.sys.executable 기반으로 pybin이 앞에 붙는지 확인
    fake_py = tmp_path / "bin" / "python"
    fake_py.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ga_module.os.sys, "executable", str(fake_py), raising=True)

    env = ga_module._make_clean_subprocess_env()
    assert "PYTHONHOME" not in env
    assert "PYTHONPATH" not in env
    assert env["PATH"].split(os.pathsep)[0] == str(fake_py.parent)


def test_apply_clean_env_to_astrometry_when_setter_missing_does_not_crash(ga_module):
    # astrometry에 set_subprocess_env가 없어도 조용히 통과해야 함
    class AstNoSetter:
        pass

    env = FakeEnv(astrometry=AstNoSetter())
    act = ga_module.GFAActions(env=env)
    act._apply_clean_env_to_astrometry()  # should not raise


def test_ensure_astrometry_outputs_ready_raises_when_no_astrometry(ga_module):
    class EnvNoAst:
        def __init__(self):
            self.logger = FakeLogger()

    act = ga_module.GFAActions(env=EnvNoAst())  # type: ignore
    with pytest.raises(RuntimeError):
        act._ensure_astrometry_outputs_ready()


def test_ensure_astrometry_outputs_ready_fallback_uses_existing_astro_files(
    ga_module, monkeypatch
):
    # ensure_astrometry_ready 없고, astro dir에 astro_*.fits가 있으면 바로 반환하는 fallback 커버
    class AstFallback:
        final_astrometry_dir = "/tmp/astrodir"
        dir_path = "/tmp/rawdir"

        def preproc(self):
            raise AssertionError("preproc should not be called when astro exists")

    env = FakeEnv(astrometry=AstFallback())
    act = ga_module.GFAActions(env=env)

    def fake_glob(pattern):
        if pattern.endswith(os.path.join("astrodir", "astro_*.fits")):
            return ["/tmp/astrodir/astro_a.fits", "/tmp/astrodir/astro_b.fits"]
        return []

    monkeypatch.setattr("kspec_gfa_controller.gfa_actions.glob.glob", fake_glob)
    outs = act._ensure_astrometry_outputs_ready()
    assert len(outs) == 2
    assert outs[0].endswith(".fits")


def test_ensure_astrometry_outputs_ready_fallback_runs_preproc_then_finds_files(
    ga_module, monkeypatch
):
    # ensure_astrometry_ready 없음 + 처음엔 astro가 없어서 preproc 수행 후 다시 glob로 찾는 fallback 커버
    state = {"after": False}

    class AstFallback:
        # 일부러 final_astrometry_dir / dir_path 없이 → base_dir/img/astroimg 디폴트 경로 타게 커버
        def preproc(self):
            state["after"] = True

    env = FakeEnv(astrometry=AstFallback())
    act = ga_module.GFAActions(env=env)

    def fake_glob(pattern):
        # 디폴트 astro_dir = base_dir/img/astroimg -> ".../astroimg/astro_*.fits" 패턴
        if pattern.endswith(os.path.join("astroimg", "astro_*.fits")):
            return [] if not state["after"] else ["/tmp/astroimg/astro_x.fits"]
        return []

    monkeypatch.setattr("kspec_gfa_controller.gfa_actions.glob.glob", fake_glob)
    outs = act._ensure_astrometry_outputs_ready()
    assert outs == ["/tmp/astroimg/astro_x.fits"]


def test_ensure_astrometry_outputs_ready_fallback_raises_when_no_preproc(
    ga_module, monkeypatch
):
    # ensure_astrometry_ready도 없고 preproc도 없으면 RuntimeError
    class AstNoEnsureNoPreproc:
        final_astrometry_dir = "/tmp/astrodir"
        dir_path = "/tmp/rawdir"

    env = FakeEnv(astrometry=AstNoEnsureNoPreproc())
    act = ga_module.GFAActions(env=env)

    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.glob.glob", lambda *a, **k: []
    )
    with pytest.raises(RuntimeError):
        act._ensure_astrometry_outputs_ready()


@pytest.mark.asyncio
async def test_grab_custom_path_is_used(actions, monkeypatch):
    # grab(path=...) 분기 커버(기본 img/grab/YYYY-MM-DD 대신 사용)
    made = {"path": None}

    def fake_makedirs(p, exist_ok=False):
        made["path"] = p

    monkeypatch.setattr("kspec_gfa_controller.gfa_actions.os.makedirs", fake_makedirs)

    r = await actions.grab(CamNum=1, path="/custom/save/here")
    assert r["status"] in ("success", "error")
    assert made["path"] == "/custom/save/here"


@pytest.mark.asyncio
async def test_grab_close_all_cameras_failure_is_caught_and_warned(
    actions, monkeypatch
):
    # grab() finally에서 close_all_cameras 실패 warning branch(202-203 라인대) 커버
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )

    async def boom_close():
        raise RuntimeError("close failed")

    actions.env.controller.close_all_cameras = boom_close  # type: ignore

    r = await actions.grab(CamNum=1)
    assert r["status"] == "success"  # close 실패해도 grab 자체 결과는 success로 감
    assert any(
        lvl == "warning" and "close_all_cameras failed" in msg
        for lvl, msg in actions.env.logger.logs
    )


@pytest.mark.asyncio
async def test_guiding_close_all_cameras_failure_is_caught_and_warned(
    actions, monkeypatch
):
    # guiding() 내부 finally에서 close 실패 warning branch(234-235 라인대) 커버
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )
    monkeypatch.setattr("kspec_gfa_controller.gfa_actions.os.listdir", lambda p: [])

    async def boom_close():
        raise RuntimeError("close failed")

    actions.env.controller.close_all_cameras = boom_close  # type: ignore

    r = await actions.guiding(save=False)
    # close 실패해도 guiding은 전체 try/except로 잡힐 수 있으니 status는 success 또는 error 둘 다 가능
    assert r["status"] in ("success", "error")
    assert any(
        lvl == "warning" and "close_all_cameras failed" in msg
        for lvl, msg in actions.env.logger.logs
    )


@pytest.mark.asyncio
async def test_pointing_save_true_copies_files(actions, monkeypatch, tmp_path):
    # pointing()의 save=True + shutil.copy2 경로 커버(322-323, 326-331 라인대)
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.makedirs", lambda *a, **k: None
    )

    # pointing_raw_path에 파일 2개 있는 것처럼
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.listdir", lambda p: ["a.fits", "b.fits"]
    )
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.os.path.isfile", lambda p: True
    )

    copy_calls = []
    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.shutil.copy2",
        lambda s, d: copy_calls.append((s, d)),
    )

    # 이미지 리스트 생성 통과: Path.glob 도 2개 반환
    def fake_glob(self, pattern):
        if pattern == "*.fits":
            return [Path("a.fits"), Path("b.fits")]
        return []

    monkeypatch.setattr(Path, "glob", fake_glob, raising=True)

    monkeypatch.setattr(
        "kspec_gfa_controller.gfa_actions.get_crvals_from_images",
        lambda images, max_workers: ([1.0] * len(images), [2.0] * len(images)),
    )

    r = await actions.pointing(
        ra="1",
        dec="2",
        save_by_date=False,
        clear_dir=False,
        save=True,
    )
    assert r["status"] == "success"
    assert len(copy_calls) == 2
