# tests/test_gfa_logger.py
import logging
import sys
import warnings
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

# (환경에 filterwarnings=error 가 걸려 있으면 matplotlib DeprecationWarning이 collection을 깨버릴 수 있어서 방어)
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"matplotlib\..*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"pyparsing\..*")


def _find_gfa_logger_py() -> Path:
    """
    프로젝트 루트부터 src-layout / non-src-layout 둘 다 커버해서
    gfa_logger.py 위치를 찾아 반환한다.
    """
    repo_root = Path(__file__).resolve().parents[1]

    candidates = [
        repo_root / "src" / "kspec_gfa_controller" / "gfa_logger.py",  # src layout
        repo_root / "kspec_gfa_controller" / "gfa_logger.py",  # non-src layout
    ]

    for p in candidates:
        if p.exists():
            return p

    raise RuntimeError(
        "gfa_logger.py not found. tried:\n" + "\n".join(str(p) for p in candidates)
    )


def _load_gfa_logger_class():
    """
    패키지 전체 import를 피하고 gfa_logger.py 파일만 직접 로딩해서 GFALogger를 가져온다.
    """
    gfa_logger_path = _find_gfa_logger_py()

    # module name은 임의여도 되지만, 충돌 방지 위해 유니크하게 둠
    module_name = "_test_gfa_logger_module"

    spec = spec_from_file_location(module_name, str(gfa_logger_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to create import spec for: {gfa_logger_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GFALogger


GFALogger = _load_gfa_logger_class()


@pytest.fixture(autouse=True)
def _reset_gfa_logger_state():
    """
    GFALogger는 전역 상태(_initialized_loggers)와 logging.getLogger(...) 전역 로거를 쓰므로
    테스트 간 간섭을 막기 위해 매 테스트마다 초기화한다.
    """
    GFALogger._initialized_loggers.clear()

    test_logger_name = "dummy.py"
    logger = logging.getLogger(test_logger_name)

    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    yield

    logger = logging.getLogger(test_logger_name)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    GFALogger._initialized_loggers.clear()


def _console_handlers(logger: logging.Logger):
    # FileHandler는 StreamHandler subclass라서 콘솔 핸들러만 분리
    return [
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    ]


def _file_handlers(logger: logging.Logger):
    return [h for h in logger.handlers if isinstance(h, logging.FileHandler)]


def test_creates_stream_and_file_handlers(tmp_path):
    g = GFALogger(file="dummy.py", log_dir=str(tmp_path))

    assert len(_console_handlers(g.logger)) == 1
    assert len(_file_handlers(g.logger)) == 1


def test_prevents_duplicate_handlers_on_same_logger(tmp_path):
    g1 = GFALogger(file="dummy.py", log_dir=str(tmp_path))
    handler_count_1 = len(g1.logger.handlers)

    g2 = GFALogger(file="dummy.py", log_dir=str(tmp_path))
    handler_count_2 = len(g2.logger.handlers)

    assert handler_count_2 == handler_count_1


def test_stream_level_is_applied(tmp_path):
    g = GFALogger(file="dummy.py", log_dir=str(tmp_path), stream_level=logging.WARNING)

    ch = _console_handlers(g.logger)
    assert len(ch) == 1
    assert ch[0].level == logging.WARNING
    assert getattr(ch[0], "stream", None) is sys.stdout


def test_writes_log_to_file(tmp_path):
    g = GFALogger(file="dummy.py", log_dir=str(tmp_path))
    msg = "hello-gfa-logger"
    g.info(msg)

    # 파일 핸들러 flush (버퍼 이슈 방지)
    for h in g.logger.handlers:
        try:
            h.flush()
        except Exception:
            pass

    today = datetime.now().strftime("%Y-%m-%d")
    log_path = tmp_path / f"gfa_{today}.log"

    assert log_path.exists()
    assert msg in log_path.read_text(encoding="utf-8")


def test_log_methods_do_not_raise(tmp_path):
    g = GFALogger(file="dummy.py", log_dir=str(tmp_path))

    g.debug("d")
    g.info("i")
    g.warning("w")
    g.error("e")
    g.critical("c")
