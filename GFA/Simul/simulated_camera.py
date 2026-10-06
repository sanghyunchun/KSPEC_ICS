"""Hardware-free implementation of the camera API used by ``GFAActions``."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
from astropy.io import fits


class SimulatedImageWriter:
    """Small FITS writer matching the ``img_class.save_fits`` call contract."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def save_fits(
        self,
        image_array,
        filename: str,
        exptime: float,
        output_directory: Optional[str] = None,
        ra: Optional[str] = None,
        dec: Optional[str] = None,
        **_ignored,
    ) -> None:
        output_path = Path(output_directory or ".").expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)

        frames = image_array if isinstance(image_array, list) else [image_array]
        if not frames:
            raise ValueError("image_array list is empty")

        arrays = [np.asarray(frame, dtype=np.float32) for frame in frames]
        if any(array.ndim != 2 for array in arrays):
            raise ValueError("simulated camera images must be two-dimensional")
        if len({array.shape for array in arrays}) != 1:
            raise ValueError("simulated camera image sizes do not match")

        image = arrays[0] if len(arrays) == 1 else np.mean(arrays, axis=0)
        now = datetime.now(timezone.utc)
        header = fits.Header()
        header["INSTRUME"] = "KSPEC-GFA-SIM"
        header["DATE-OBS"] = now.strftime("%Y-%m-%d")
        header["TIME-OBS"] = now.strftime("%H:%M:%S")
        header["EXPTIME"] = float(exptime)
        header["NCOMB"] = len(arrays)
        header["RA"] = ra or "UNKNOWN"
        header["DEC"] = dec or "UNKNOWN"
        header["SIMULATE"] = True

        target = output_path / filename.replace(":", "-")
        if target.suffix.lower() != ".fits":
            target = target.with_suffix(".fits")
        fits.writeto(target, image.astype(np.float32), header, overwrite=True)
        self.logger.info("[simulation] FITS saved: %s", target)


class SimulatedCameraController:
    """Return repeatable FITS frames without opening a physical camera.

    The public methods intentionally follow the subset of ``GFAController``
    consumed by the production ``GFAActions`` implementation.
    """

    def __init__(
        self,
        logger: logging.Logger,
        camera_ids: Iterable[int] = range(1, 7),
        demo_directory: Optional[Path] = None,
    ) -> None:
        self.logger = logger
        self.camera_ids = tuple(camera_ids)
        self.open_cameras: set[int] = set()
        self.img_class = SimulatedImageWriter(logger)
        self.demo_directory = (
            Path(demo_directory)
            if demo_directory is not None
            else Path(__file__).resolve().parents[1] / "demo_save"
        )
        self._frames = self._load_demo_frames()

    def _load_demo_frames(self) -> dict[int, np.ndarray]:
        files = sorted(self.demo_directory.glob("*.fits"))
        if len(files) < len(self.camera_ids):
            raise FileNotFoundError(
                "Simulation requires one demo FITS per camera. "
                f"Found {len(files)} in {self.demo_directory}."
            )

        frames: dict[int, np.ndarray] = {}
        for camera_id, path in zip(self.camera_ids, files):
            image = fits.getdata(path, memmap=False)
            if image is None or np.asarray(image).ndim != 2:
                raise ValueError(f"Demo FITS is not a 2-D image: {path}")
            frames[camera_id] = np.asarray(image, dtype=np.float32)
        return frames

    async def open_all_cameras(self) -> None:
        self.open_cameras.update(self.camera_ids)
        self.logger.info("[simulation] opened cameras: %s", self.camera_ids)

    async def close_all_cameras(self) -> None:
        self.open_cameras.clear()
        self.logger.info("[simulation] closed all cameras")

    def close_camera(self, camera_id: int) -> None:
        self.open_cameras.discard(camera_id)

    def status(self) -> dict[str, bool]:
        return {
            f"Cam{camera_id}": camera_id in self.open_cameras
            for camera_id in self.camera_ids
        }

    def ping(self, camera_id: int = 0) -> None:
        targets = self.camera_ids if camera_id == 0 else (camera_id,)
        self._validate_camera_ids(targets)
        self.logger.info("[simulation] ping successful: %s", targets)

    def cam_params(self, camera_id: int) -> dict[str, object]:
        self._validate_camera_ids((camera_id,))
        image = self._frames[camera_id]
        return {
            "DeviceModelName": "KSPEC Simulated Camera",
            "DeviceSerialNumber": self._serial(camera_id),
            "Width": image.shape[1],
            "Height": image.shape[0],
            "PixelFormat": "Mono12 (simulated)",
            "ExposureTime (μs)": None,
            "BinningHorizontal": 1,
            "BinningVertical": 1,
        }

    async def grabone(
        self,
        CamNum: int,
        ExpTime: float,
        Binning: int,
        **_ignored,
    ) -> dict[str, object]:
        self._validate_camera_ids((CamNum,))
        if CamNum not in self.open_cameras:
            self.logger.error("[simulation] Cam%s was not open", CamNum)
            return {
                "cam_num": CamNum,
                "serial": self._serial(CamNum),
                "image": None,
                "timeout": True,
            }

        if ExpTime <= 0:
            raise ValueError("ExpTime must be greater than zero")
        if Binning < 1:
            raise ValueError("Binning must be greater than zero")

        # Return a copy: callers may modify/combine frames without changing the
        # reusable demo image kept by this controller.
        return {
            "cam_num": CamNum,
            "serial": self._serial(CamNum),
            "image": self._frames[CamNum].copy(),
            "timeout": False,
        }

    def _validate_camera_ids(self, camera_ids: Iterable[int]) -> None:
        invalid = [camera_id for camera_id in camera_ids if camera_id not in self.camera_ids]
        if invalid:
            raise KeyError(f"Unknown simulated camera(s): {invalid}")

    @staticmethod
    def _serial(camera_id: int) -> str:
        return f"SIM{camera_id:04d}"
