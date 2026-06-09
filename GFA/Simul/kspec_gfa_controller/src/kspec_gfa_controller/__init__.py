# src/kspec_gfa_controller/__init__.py
from __future__ import annotations

__all__ = ["GFAActions", "GFAEnvironment", "GFAGuider"]


def __getattr__(name: str):
    if name == "GFAActions":
        from .gfa_actions import GFAActions

        return GFAActions
    if name == "GFAEnvironment":
        from .gfa_environment import GFAEnvironment

        return GFAEnvironment
    if name == "GFAGuider":
        from .gfa_guider import GFAGuider

        return GFAGuider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
