"""Allow the production action module to be imported without pypylon.

The production :mod:`gfa_actions` module imports ``gfa_environment``, whose
camera controller imports pypylon at module-import time.  Simulation never
constructs that controller, but it still needs the import to succeed.  This
module supplies the minimum import-only stand-in when pypylon is not installed.
It deliberately does not emulate any camera SDK behaviour.
"""

from __future__ import annotations

import importlib
import sys
import types


def ensure_pypylon_importable() -> None:
    """Install an import-only pypylon stand-in when the SDK is unavailable."""
    try:
        importlib.import_module("pypylon.pylon")
        importlib.import_module("pypylon.genicam")
        return
    except ModuleNotFoundError as exc:
        if exc.name not in {"pypylon", "pypylon.pylon", "pypylon.genicam"}:
            raise

    pypylon = types.ModuleType("pypylon")
    pypylon.__path__ = []
    pylon = types.ModuleType("pypylon.pylon")
    genicam = types.ModuleType("pypylon.genicam")

    class TimeoutException(Exception):
        """Compatibility type used only by production exception handlers."""

    genicam.TimeoutException = TimeoutException
    pypylon.pylon = pylon
    pypylon.genicam = genicam

    sys.modules.setdefault("pypylon", pypylon)
    sys.modules.setdefault("pypylon.pylon", pylon)
    sys.modules.setdefault("pypylon.genicam", genicam)
