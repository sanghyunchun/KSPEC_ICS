# tests/test_gfa_environment.py
import sys
import types
import json
from pathlib import Path

import pytest


# -----------------------------------------------------------------------------
# ✅ IMPORT BLOCKER: gfa_environment import 전에 gfa_guider를 가짜로 주입
# (gfa_environment.py가 "from .gfa_guider import GFAGuider"를 하므로,
#  여기서 먼저 sys.modules에 stub을 넣어 SciPy import를 원천 차단)
# -----------------------------------------------------------------------------
fake_gfa_guider = types.ModuleType("kspec_gfa_controller.gfa_guider")


class FakeGuider:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger


fake_gfa_guider.GFAGuider = FakeGuider
sys.modules["kspec_gfa_controller.gfa_guider"] = fake_gfa_guider


# 이제 안전하게 import 가능 (SciPy 안 불림)
import kspec_gfa_controller.gfa_environment as gfa_environment


# -------------------------
# Fakes
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
    def __init__(self, config_path, logger):
        self.config_path = config_path
        self.logger = logger
        self.close_camera_calls = []

    def close_camera(self, camnum: int):
        self.close_camera_calls.append(camnum)


class FakeAstrometry:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger


# -------------------------
# Helpers
# -------------------------
def _write_env_cams_json(path: Path):
    cfg = {
        "GfaController": {
            "Elements": {
                "Cameras": {
                    "Elements": {
                        "Cam1": {"Number": 1},
                        "Cam2": {"Number": 2},
                        "Cam3": {"Number": 3},
                        "Cam4": {"Number": 4},
                        "Cam5": {"Number": 5},
                        "Cam6": {"Number": 6},
                        "Cam7": {"Number": 7},
                        "CamX": {},
                        "Cam8": {"Number": 8},
                    }
                }
            }
        }
    }
    path.write_text(json.dumps(cfg), encoding="utf-8")


# -------------------------
# get_config_path
# -------------------------
def test_get_config_path_success(tmp_path, monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(gfa_environment, "logger", fake_logger)

    fake_module_file = tmp_path / "gfa_environment.py"
    fake_module_file.write_text("# dummy", encoding="utf-8")
    monkeypatch.setattr(gfa_environment, "__file__", str(fake_module_file))

    rel = "cams.json"
    target = tmp_path / rel
    target.write_text("{}", encoding="utf-8")

    out = gfa_environment.get_config_path(rel)
    assert out == str(target)


def test_get_config_path_missing_raises(tmp_path, monkeypatch):
    fake_logger = FakeLogger()
    monkeypatch.setattr(gfa_environment, "logger", fake_logger)

    fake_module_file = tmp_path / "gfa_environment.py"
    fake_module_file.write_text("# dummy", encoding="utf-8")
    monkeypatch.setattr(gfa_environment, "__file__", str(fake_module_file))

    with pytest.raises(FileNotFoundError):
        gfa_environment.get_config_path("nope.json")


# -------------------------
# get_camera_ids
# -------------------------
def test_get_camera_ids_plate_and_finder(tmp_path):
    cfgp = tmp_path / "cams.json"
    _write_env_cams_json(cfgp)

    plate = gfa_environment.get_camera_ids(str(cfgp), role="plate")
    finder = gfa_environment.get_camera_ids(str(cfgp), role="finder")

    assert plate == [1, 2, 3, 4, 5, 6]
    assert finder == [7]


# -------------------------
# GFAEnvironment (plate)
# -------------------------
def test_environment_plate(monkeypatch, tmp_path):
    monkeypatch.setattr(gfa_environment, "GFAController", FakeController)
    monkeypatch.setattr(gfa_environment, "GFAAstrometry", FakeAstrometry)
    monkeypatch.setattr(gfa_environment, "logger", FakeLogger())

    cfgp = tmp_path / "cams.json"
    _write_env_cams_json(cfgp)
    astp = tmp_path / "ast.json"
    astp.write_text("{}", encoding="utf-8")

    env = gfa_environment.GFAEnvironment(
        gfa_config_path=str(cfgp),
        ast_config_path=str(astp),
        role="plate",
    )

    assert env.camera_ids == [1, 2, 3, 4, 5, 6]
    assert isinstance(env.controller, FakeController)
    assert isinstance(env.astrometry, FakeAstrometry)
    # guider는 위에서 sys.modules에 주입한 FakeGuider가 들어감
    assert isinstance(env.guider, FakeGuider)


def test_environment_plate_shutdown(monkeypatch, tmp_path):
    monkeypatch.setattr(gfa_environment, "GFAController", FakeController)
    monkeypatch.setattr(gfa_environment, "GFAAstrometry", FakeAstrometry)
    monkeypatch.setattr(gfa_environment, "logger", FakeLogger())

    cfgp = tmp_path / "cams.json"
    _write_env_cams_json(cfgp)
    astp = tmp_path / "ast.json"
    astp.write_text("{}", encoding="utf-8")

    env = gfa_environment.GFAEnvironment(
        gfa_config_path=str(cfgp),
        ast_config_path=str(astp),
        role="plate",
    )
    env.shutdown()

    assert env.controller.close_camera_calls == [1, 2, 3, 4, 5, 6]


# -------------------------
# GFAEnvironment (finder)
# -------------------------
def test_environment_finder(monkeypatch, tmp_path):
    monkeypatch.setattr(gfa_environment, "GFAController", FakeController)
    monkeypatch.setattr(gfa_environment, "logger", FakeLogger())

    cfgp = tmp_path / "cams.json"
    _write_env_cams_json(cfgp)

    env = gfa_environment.GFAEnvironment(
        gfa_config_path=str(cfgp),
        ast_config_path=None,
        role="finder",
    )

    assert env.camera_ids == [7]
    assert env.astrometry is None
    assert env.guider is None


def test_environment_finder_shutdown(monkeypatch, tmp_path):
    monkeypatch.setattr(gfa_environment, "GFAController", FakeController)
    monkeypatch.setattr(gfa_environment, "logger", FakeLogger())

    cfgp = tmp_path / "cams.json"
    _write_env_cams_json(cfgp)

    env = gfa_environment.GFAEnvironment(
        gfa_config_path=str(cfgp),
        ast_config_path=None,
        role="finder",
    )
    env.shutdown()

    assert env.controller.close_camera_calls == [7]
