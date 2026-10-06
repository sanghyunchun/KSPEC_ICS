"""Factory that combines production commands/actions with simulated hardware."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from astropy.io import fits

from .pypylon_compat import ensure_pypylon_importable
from .simulated_environment import create_simulated_environment


def create_simulated_actions(save_root: Optional[Path] = None):
    """Create the unmodified production ``GFAActions`` with fake hardware."""
    ensure_pypylon_importable()

    # Import only after the compatibility hook is installed.  The real camera
    # controller class is imported by GFAActions' type environment, but is
    # never instantiated because we explicitly pass a simulated environment.
    from GFA.kspec_gfa_controller.src.kspec_gfa_controller.gfa_actions import (
        GFAActions,
    )

    class SimulatedGFAActions(GFAActions):
        def _evaluate_pointing_image_quality(self, fits_path: Path) -> dict:
            """Accept valid demo FITS frames for the command-flow simulator.

            The current production action calls this helper but does not define
            it.  Keeping this small implementation here lets the production
            guiding/pointing control flow run unchanged, without changing the
            production controller package.  It is intentionally a structural
            check, not an astrometric-quality assessment.
            """
            try:
                image = np.asarray(fits.getdata(fits_path), dtype=float)
                if image.ndim != 2:
                    return {
                        "passed": False,
                        "n_peaks": 0,
                        "brightest_flux": 0.0,
                        "std_bg": 0.0,
                        "reasons": [f"invalid_dimension={image.ndim}"],
                    }
                if not np.isfinite(image).all():
                    return {
                        "passed": False,
                        "n_peaks": 0,
                        "brightest_flux": 0.0,
                        "std_bg": 0.0,
                        "reasons": ["non_finite_pixels"],
                    }
                return {
                    "passed": True,
                    "n_peaks": 0,
                    "brightest_flux": float(np.max(image)),
                    "std_bg": float(np.std(image)),
                    "reasons": [],
                }
            except Exception as exc:
                return {
                    "passed": False,
                    "n_peaks": 0,
                    "brightest_flux": 0.0,
                    "std_bg": 0.0,
                    "reasons": [f"simulation_filter_error={exc}"],
                }

    return SimulatedGFAActions(
        env=create_simulated_environment(save_root=save_root)
    )
