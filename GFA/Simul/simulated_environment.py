"""Simulation-only environment supplied to the production GFA actions."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from astropy.io import fits

from .simulated_camera import SimulatedCameraController


def _create_logger() -> logging.Logger:
    logger = logging.getLogger("kspec.gfa.simulation")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


class SimulatedAstrometry:
    """Produces predictable astrometry outputs from the simulated raw frames."""

    def __init__(self, save_root: Path, logger: logging.Logger) -> None:
        self.logger = logger
        self.save_root = save_root
        self.inpar = {
            "paths": {
                "save_root": str(save_root),
                "directories": {
                    "grab_images": "grab",
                    "raw_images": "raw",
                    "guiding_save": "guiding_save",
                    "pointing_save": "pointing_save",
                    "unclean_images": "unclean",
                    "final_astrometry_images": "astrometry",
                },
            },
            # The goal of this simulator is command-flow coverage, not an
            # astrometry.net result.  Accept each generated demo image.
            "pointing_filter": {
                "min_valid_images": 1,
                "min_std_bg": 0.0,
                "min_peaks": 0,
                "min_brightest_flux": 0.0,
                "dao": {"fwhm": 3.0, "sigma_threshold": 5.0},
            },
        }
        self.raw_dir = save_root / "raw"
        self.final_astrometry_dir = save_root / "astrometry"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.final_astrometry_dir.mkdir(parents=True, exist_ok=True)

    def set_subprocess_env(self, _env: dict) -> None:
        """The simulator does not invoke external astrometry processes."""

    def clear_raw_files(self) -> None:
        for path in self.raw_dir.glob("*.fits"):
            path.unlink()

    def ensure_astrometry_ready(self) -> list[str]:
        raw_files = sorted(self.raw_dir.glob("*.fits"))
        for path in self.final_astrometry_dir.glob("astro_*.fits"):
            path.unlink()

        outputs = []
        for index, raw_file in enumerate(raw_files, start=1):
            output = self.final_astrometry_dir / f"astro_sim_{index:02d}.fits"
            shutil.copy2(raw_file, output)
            with fits.open(output, mode="update") as hdul:
                hdul[0].header["CRVAL1"] = 0.0
                hdul[0].header["CRVAL2"] = 0.0
                hdul[0].header["SIMULATE"] = True
            outputs.append(str(output))
        self.logger.info("[simulation] generated %s astrometry output(s)", len(outputs))
        return outputs


class SimulatedGuider:
    def exe_cal(self) -> tuple[float, float, float]:
        return (0.04, 0.10, 2.30)


@dataclass
class SimulatedGFAEnvironment:
    """Subset of ``GFAEnvironment`` used by the production action layer."""

    save_root: Path
    logger: logging.Logger = field(default_factory=_create_logger)
    camera_ids: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    controller: SimulatedCameraController = field(init=False)
    astrometry: SimulatedAstrometry = field(init=False)
    guider: SimulatedGuider = field(init=False)
    role: str = "plate"

    def __post_init__(self) -> None:
        self.save_root = Path(self.save_root).expanduser().resolve()
        self.save_root.mkdir(parents=True, exist_ok=True)
        self.controller = SimulatedCameraController(self.logger, self.camera_ids)
        self.astrometry = SimulatedAstrometry(self.save_root, self.logger)
        self.guider = SimulatedGuider()

    def shutdown(self) -> None:
        for camera_id in self.camera_ids:
            self.controller.close_camera(camera_id)


def create_simulated_environment(
    save_root: Optional[Path] = None,
) -> SimulatedGFAEnvironment:
    output_root = save_root or (Path(__file__).resolve().parent / "output")
    return SimulatedGFAEnvironment(save_root=output_root)
