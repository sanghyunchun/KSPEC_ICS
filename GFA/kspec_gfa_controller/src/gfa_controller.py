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


from gfa_img import GFAImage

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

        self.logger.info("GFAController initialization complete.")

    def open_all_cameras(self):
        """Open all cameras once at startup."""
        self.logger.info("Opening all cameras...")
        for cam_key, cam_info in self.cameras_info.items():
            ip = cam_info["IpAddress"]
            dev_info = py.DeviceInfo()
            dev_info.SetIpAddress(ip)
            cam = py.InstantCamera(self.tlf.CreateDevice(dev_info))
            cam.Open()
            self.open_cameras[cam_key] = cam
            self.logger.info(f"{cam_key} opened (IP {ip}).")
        self.logger.info("All cameras opened successfully.")

    def close_all_cameras(self):
        """Close all opened cameras."""
        self.logger.info("Closing all cameras...")
        for cam_key, cam in self.open_cameras.items():
            if cam.IsOpen():
                cam.Close()
                self.logger.info(f"{cam_key} closed.")
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
            )
            return img

        except genicam.TimeoutException:
            self.logger.error(
                f"Timeout while grabbing image from camera {serial_hint or 'cam'+str(cam_index)}."
            )
            return None

    async def grabone(
        self,
        CamNum: int,
        ExpTime: float,
        Binning: int,
        packet_size: int,
        ipd: int,
        ftd_base: int,
        output_dir: str = None,
        ftd: int = None,
    ) -> list:
        """Grab one image from a single camera."""
        key = f"Cam{CamNum}"
        cam = self.open_cameras.get(key)
        if cam is None:
            self.logger.error(f"Camera {key} not opened.")
            return [CamNum]

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
        packet_size: int = 8000,
        ipd: int = 39000,
        ftd_base: int = 39000,
        output_dir: str = None,
    ):
        """Grab images from one or more cameras."""
        timeout_cams = []

        if isinstance(CamNum, int) and CamNum == 0:
            cam_list = list(range(1, self.NUM_CAMERAS + 1))
        elif isinstance(CamNum, list):
            cam_list = CamNum
        else:
            cam_list = [CamNum]

        tasks = [
            self.grabone(
                CamNum=cam_num,
                ExpTime=ExpTime,
                Binning=Binning,
                packet_size=packet_size,
                ipd=ipd,
                ftd_base=ftd_base,
                output_dir=output_dir,
            )
            for cam_num in cam_list
        ]
        results = await asyncio.gather(*tasks)

        for r in results:
            if r:
                timeout_cams.extend(r)

        return timeout_cams

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
