#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2023-01-03
# @Filename: gfa_controller.py

import asyncio
import json
import os
import time
import logging
import sys
import yaml
import pypylon.pylon as py
from pypylon import genicam
from datetime import datetime, timezone
from typing import List

from pathlib import Path



from .gfa_img import GFAImage

__all__ = ["GFAController"]


###############################################################################
# Default Config and Logger
###############################################################################
def _get_default_config_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(script_dir, "etc", "cams.json")
    if not os.path.isfile(default_path):
        raise FileNotFoundError(
            f"Default config file not found at: {default_path}. "
            "Please adjust `_get_default_config_path()`."
        )
    return default_path


def _get_default_logger() -> logging.Logger:
    logger = logging.getLogger("gfa_controller_default")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        console_handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s - %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger


def from_config(config_path: str) -> dict:
    file_extension = os.path.splitext(config_path)[1].lower()
    with open(config_path, "r") as f:
        if file_extension in [".yml", ".yaml"]:
            data = yaml.load(f, Loader=yaml.FullLoader)
        elif file_extension == ".json":
            data = json.load(f)
        else:
            raise ValueError(
                "Unsupported file format. Please use a .yml, .yaml, or .json file."
            )
    return data


###############################################################################
# Main Controller Class
###############################################################################
class GFAController:
    """Talk to KSPEC GFA Cameras over TCP/IP with optimized open/grab/close."""

    def __init__(self, config: str = None, logger: logging.Logger = None):
        if config is None:
            config = _get_default_config_path()
        if logger is None:
            logger = _get_default_logger()
        self.logger = logger

        try:
            self.config = from_config(config)
            self.logger.info("Initializing GFAController with provided config.")
        except Exception as e:
            self.logger.error(f"Error loading configuration from {config}: {e}")
            raise

        try:
            self.cameras_info = self.config["GfaController"]["Elements"]["Cameras"][
                "Elements"
            ]
        except KeyError as e:
            self.logger.error(f"Configuration key error: {e}")
            raise

        self.NUM_CAMERAS = len(self.cameras_info)
        os.environ["PYLON_CAMEMU"] = f"{self.NUM_CAMERAS}"
        self.tlf = py.TlFactory.GetInstance()

        self.grab_timeout = 180000  # 3 minute
        self.img_class = GFAImage(logger)
        self.open_cameras = {}

        # Async safety for shared dict updates
        self._open_cameras_lock = asyncio.Lock()

        self.logger.info("GFAController initialization complete.")

    async def open_all_cameras(self):
        """Open all cameras once at startup (concurrently via asyncio)."""
        self.logger.info("Opening all cameras...")

        async def _open_one(cam_key: str, cam_info: dict):
            ip = cam_info["IpAddress"]

            def _blocking_open():
                dev_info = py.DeviceInfo()
                dev_info.SetIpAddress(ip)
                cam = py.InstantCamera(self.tlf.CreateDevice(dev_info))
                cam.Open()
                return cam

            cam = await asyncio.to_thread(_blocking_open)

            async with self._open_cameras_lock:
                self.open_cameras[cam_key] = cam

            self.logger.info(f"{cam_key} opened (IP {ip}).")

        tasks = [
            asyncio.create_task(_open_one(cam_key, cam_info))
            for cam_key, cam_info in self.cameras_info.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        failures = []
        for (cam_key, _), r in zip(self.cameras_info.items(), results):
            if isinstance(r, Exception):
                failures.append((cam_key, r))
                self.logger.exception(f"Failed to open {cam_key}: {r}")

        if failures:
            raise RuntimeError(
                "Some cameras failed to open: "
                + ", ".join([f"{k} ({type(e).__name__})" for k, e in failures])
            )

        self.logger.info("All cameras opened successfully.")

    async def close_all_cameras(self):
        """Close all opened cameras (concurrently via asyncio)."""
        self.logger.info("Closing all cameras...")

        async with self._open_cameras_lock:
            items = list(self.open_cameras.items())

        async def _close_one(cam_key: str, cam):
            def _blocking_close():
                if cam.IsOpen():
                    cam.Close()

            try:
                await asyncio.to_thread(_blocking_close)
                self.logger.info(f"{cam_key} closed.")
            except Exception as e:
                self.logger.exception(f"Failed to close {cam_key}: {e}")

        await asyncio.gather(
            *(asyncio.create_task(_close_one(cam_key, cam)) for cam_key, cam in items),
            return_exceptions=True,
        )

        async with self._open_cameras_lock:
            self.open_cameras.clear()

        self.logger.info("All cameras closed.")

    def ping(self, CamNum: int = 0):
        """Ping the specified camera to verify connectivity."""
        self.logger.info(f"Pinging camera {CamNum}...")
        key = f"Cam{CamNum}"
        if key not in self.cameras_info:
            self.logger.error(f"Camera {key} not found in config.")
            raise KeyError(f"{key} missing")
        ip = self.cameras_info[key]["IpAddress"]
        result = os.system(f"ping -c 3 -w 1 {ip}")
        self.logger.info(f"Ping result for {key} ({ip}): {result}")

    def status(self):
        """Check whether each camera is open/standby."""
        self.logger.info("Checking camera status...")
        status = {}
        for cam_key in self.cameras_info.keys():
            cam = self.open_cameras.get(cam_key)
            is_open = cam.IsOpen() if cam else False
            status[cam_key] = is_open
            if is_open:
                self.logger.info(f"{cam_key} is online and standby.")
            else:
                self.logger.warning(f"{cam_key} is not open.")
        return status

    def cam_params(self, CamNum: int):
        """
        Retrieves and logs parameters of the specified camera.
        Reuses already opened camera if available.

        Parameters
        ----------
        CamNum : int
            Camera number for which to retrieve parameters.

        Raises
        ------
        KeyError
            If the camera number is not found in the `cameras_info` dictionary.
        """
        self.logger.info(f"Checking parameters of camera {CamNum}")
        key = f"Cam{CamNum}"

        # 카메라 정보 확인
        if key not in self.cameras_info:
            self.logger.error(f"Invalid camera number {CamNum}.")
            raise KeyError(f"{key} not found in cameras_info.")

        # 이미 열려 있는 카메라 가져오기
        camera = self.open_cameras.get(key)

        # 없으면 예외적으로 새로 열기 (일반적으로는 open_all_cameras() 사용을 권장)
        if camera is None or not camera.IsOpen():
            self.logger.warning(f"{key} is not open — opening temporarily.")
            ip = self.cameras_info[key]["IpAddress"]
            dev_info = py.DeviceInfo()
            dev_info.SetIpAddress(ip)
            camera = py.InstantCamera(self.tlf.CreateDevice(dev_info))
            camera.Open()
            # 닫지 않고 유지 (close는 사용자가 결정)
            self.open_cameras[key] = camera

        # 카메라 정보 출력
        self.logger.info("Camera Device Information")
        self.logger.info("=========================")

        info_attributes = [
            ("DeviceModelName", "DeviceModelName"),
            ("DeviceSerialNumber", "DeviceSerialNumber"),
            ("DeviceUserID", "DeviceUserID"),
            ("Width", "Width"),
            ("Height", "Height"),
            ("PixelFormat", "PixelFormat"),
            ("ExposureTime (μs)", "ExposureTime"),
            ("BinningHorizontalMode", "BinningHorizontalMode"),
            ("BinningHorizontal", "BinningHorizontal"),
            ("BinningVerticalMode", "BinningVerticalMode"),
            ("BinningVertical", "BinningVertical"),
        ]

        params = {}
        for label, attribute in info_attributes:
            try:
                value = getattr(camera, attribute).GetValue()
                self.logger.info(f"{label} : {value}")
                params[label] = value
            except Exception as e:
                self.logger.error(f"AccessException for {label}: {e}")
                params[label] = None

        return params

    async def configure_and_grab(
        self,
        cam,
        ExpTime: float,
        Binning: int,
        packet_size: int,
        ipd: int,
        ftd_base: int,
        cam_index: int = 0,
        output_dir: str = None,
        serial_hint: str = None,
        ftd: int = None,
        ra: str = None,
        dec: str = None,
    ):
        """Configure camera and grab an image."""
        loop = asyncio.get_running_loop()

        # Transport layer settings
        await loop.run_in_executor(
            None, cam.GevSCPSPacketSize.SetValue, int(packet_size)
        )
        await loop.run_in_executor(None, cam.GevSCPD.SetValue, int(ipd))
        ftd_value = (
            int(ftd)
            if ftd is not None
            else int(ftd_base + cam_index * (packet_size + 18))
        )
        await loop.run_in_executor(None, cam.GevSCFTD.SetValue, ftd_value)

        # Imaging settings
        microsec = int(ExpTime * 1_000_000)
        await loop.run_in_executor(None, cam.ExposureTime.SetValue, microsec)
        await loop.run_in_executor(None, cam.PixelFormat.SetValue, "Mono12")
        await loop.run_in_executor(None, cam.BinningHorizontal.SetValue, int(Binning))
        await loop.run_in_executor(None, cam.BinningVertical.SetValue, int(Binning))

        try:
            result = await loop.run_in_executor(None, cam.GrabOne, self.grab_timeout)
            img = result.GetArray()

            # Get current UTC time
            now = datetime.now(timezone.utc)
            date_str = now.strftime("%Y%m%d")
            time_str = now.strftime("%H%M%S")  # e.g., 143012
            timestamp = f"D{date_str}_T{time_str}"

            # Prefer serial hint if provided, else use cam index
            cam_label = serial_hint if serial_hint else f"cam{cam_index}"
            filename = f"{timestamp}_{cam_label}_exp{int(ExpTime)}s.fits"

            self.img_class.save_fits(
                image_array=img,
                filename=filename,
                exptime=ExpTime,
                output_directory=output_dir,
                ra=ra,
                dec=dec,
            )

            # ---- PNG save (quick-look) ----
            png_dir = "./png"
            Path(png_dir).mkdir(parents=True, exist_ok=True)

            png_filename = filename.replace(".fits", ".png")

            self.img_class.save_png(
                image_array=img,
                filename=png_filename,
                output_directory=png_dir,
                #bit_depth=16,      # GFA dynamic range 유지
            )

            return img

        except genicam.TimeoutException:
            self.logger.error(
                f"Timeout while grabbing image from camera {serial_hint or 'cam' + str(cam_index)}."
            )
            return None

    async def grabone(
        self,
        CamNum: int,
        ExpTime: float,
        Binning: int,
        packet_size: int = None,
        ipd: int = None,
        ftd_base: int = 39000,
        output_dir: str = None,
        ftd: int = None,
        ra: str = None,
        dec: str = None,
    ) -> list:
        """
        Grab one image from a single camera.

        If packet_size or ipd is None, automatically use the value from cams.json.
        Otherwise, use the input parameter value.

        Parameters
        ----------
        CamNum : int
            Camera number (e.g., 1–7).
        ExpTime : float
            Exposure time in seconds.
        Binning : int
            Binning value.
        packet_size : int, optional
            Packet size for the camera. If None, use cams.json value.
        ipd : int, optional
            InterPacketDelay for the camera. If None, use cams.json value.
        ftd_base : int
            Frame Transmission Delay base value.
        output_dir : str, optional
            Output directory for image saving.
        ftd : int, optional
            Frame Transmission Delay (overrides ftd_base if set).

        Returns
        -------
        list
            List containing CamNum if timeout occurred, else empty list.
        """
        key = f"Cam{CamNum}"
        cam = self.open_cameras.get(key)
        if cam is None:
            self.logger.error(f"Camera {key} not opened.")
            return [CamNum]

        # --- PacketSize, IPD 우선순위 적용 ---
        if packet_size is None:
            packet_size = self.get_camera_param(CamNum, "PacketSize")
        if ipd is None:
            ipd = self.get_camera_param(CamNum, "InterPacketDelay")

        timeout_occurred = False

        try:
            serial = cam.DeviceSerialNumber.GetValue()
            img = await self.configure_and_grab(
                cam,
                ExpTime,
                Binning,
                packet_size=packet_size,
                ipd=ipd,
                ftd_base=ftd_base,
                cam_index=(CamNum - 1),
                output_dir=output_dir,
                serial_hint=serial,
                ftd=ftd,
                ra=ra,
                dec=dec,
            )

            if img is None:
                self.logger.error(f"Timeout detected after grabbing camera {CamNum}.")
                timeout_occurred = True

        except genicam.TimeoutException:
            self.logger.error(f"TimeoutException during grabbing camera {CamNum}.")
            timeout_occurred = True
        except Exception as e:
            self.logger.error(f"Error during grabbing camera {CamNum}: {e}")
            timeout_occurred = True

        return [CamNum] if timeout_occurred else []

    async def grab(
        self,
        CamNum,
        ExpTime: float,
        Binning: int,
        packet_size: int = None,
        ipd: int = None,
        ftd_base: int = 39000,
        output_dir: str = None,
        ra: str = None,
        dec: str = None,
    ):
        """
        Grab images from one or more cameras.

        Parameters
        ----------
        CamNum : int or list
            Camera number(s) to operate. 0 means all cameras.
        ExpTime : float
            Exposure time in seconds.
        Binning : int
            Binning value.
        packet_size : int, optional
            Packet size. If None, use cams.json value per camera.
        ipd : int, optional
            InterPacketDelay. If None, use cams.json value per camera.
        ftd_base : int
            Frame Transmission Delay base value.
        output_dir : str, optional
            Output directory for image saving.

        Returns
        -------
        list
            List of camera numbers where timeout occurred.
        """
        timeout_cams = []

        # Determine camera list
        if isinstance(CamNum, int) and CamNum == 0:
            cam_list = list(range(1, self.NUM_CAMERAS + 1))
        elif isinstance(CamNum, list):
            cam_list = CamNum
        else:
            cam_list = [CamNum]

        # Prepare async grab tasks for all target cameras
        tasks = [
            self.grabone(
                CamNum=cam_num,
                ExpTime=ExpTime,
                Binning=Binning,
                packet_size=packet_size,
                ipd=ipd,
                ftd_base=ftd_base,
                output_dir=output_dir,
                ra=ra,
                dec=dec,
            )
            for cam_num in cam_list
        ]
        results = await asyncio.gather(*tasks)

        # Aggregate timeout results
        for r in results:
            if r:
                timeout_cams.extend(r)

        return timeout_cams

    def get_camera_param(self, CamNum: int, param_name: str):
        key = f"Cam{CamNum}"
        value = self.cameras_info.get(key, {}).get(param_name)
        if value is None:
            self.logger.warning(
                f"{param_name} for {key} not found in config, using default."
            )
            return None
        try:
            return int(value)
        except Exception:
            self.logger.warning(
                f"{param_name} value for {key} is not an integer: {value}"
            )
            return None

    def open_selected_cameras(self, camera_ids: List[int]):
        for cam_id in camera_ids:
            key = f"Cam{cam_id}"
            if key in self.open_cameras and self.open_cameras[key].IsOpen():
                continue
            ip = self.cameras_info[key]["IpAddress"]
            dev_info = py.DeviceInfo()
            dev_info.SetIpAddress(ip)
            cam = py.InstantCamera(self.tlf.CreateDevice(dev_info))
            cam.Open()
            self.open_cameras[key] = cam
            self.logger.info(f"{key} opened.")

    def open_camera(self, CamNum: int):
        """
        Open a single camera by its number (e.g., 1–7).

        Parameters
        ----------
        CamNum : int
            The camera number to open (e.g., 1–7).
        """
        key = f"Cam{CamNum}"

        if key in self.open_cameras and self.open_cameras[key].IsOpen():
            self.logger.info(f"{key} is already open.")
            return

        cam_info = self.cameras_info.get(key)
        if cam_info is None:
            self.logger.error(f"Camera {key} not found in configuration.")
            raise KeyError(f"{key} not found")

        ip = cam_info["IpAddress"]
        dev_info = py.DeviceInfo()
        dev_info.SetIpAddress(ip)

        try:
            cam = py.InstantCamera(self.tlf.CreateDevice(dev_info))
            cam.Open()
            self.open_cameras[key] = cam
            self.logger.info(f"{key} opened (IP {ip}).")
        except Exception as e:
            self.logger.error(f"Failed to open {key}: {e}")
            raise
