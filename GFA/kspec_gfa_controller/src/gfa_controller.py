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
from concurrent.futures import ThreadPoolExecutor

import matplotlib.pyplot as plt
import pypylon.pylon as py
import yaml
from pypylon import genicam

from gfa_img import GFAImage

__all__ = ["gfa_controller"]


###############################################################################
# Default Config and Logger
###############################################################################
def _get_default_config_path() -> str:
    """
    Returns the default path for the GFA camera config file.
    Adjust this path as needed for your environment.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(script_dir, "etc", "cams.json")
    if not os.path.isfile(default_path):
        raise FileNotFoundError(
            f"Default config file not found at: {default_path}. "
            "Please adjust `_get_default_config_path()`."
        )
    return default_path


def _get_default_logger() -> logging.Logger:
    """
    Returns a simple default logger if none is provided.
    """
    logger = logging.getLogger("gfa_controller_default")
    # Only configure if no handlers have been set
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
    """
    Loads GFA camera configuration from a YAML or JSON file.

    Parameters
    ----------
    config_path : str
        Path to the configuration file. The file can be in .yml, .yaml, or .json format.

    Returns
    -------
    dict
        A dictionary containing the GFA camera configuration data.

    Raises
    ------
    ValueError
        If the file format is unsupported (i.e., not .yml, .yaml, or .json).
    """
    file_extension = os.path.splitext(config_path)[1].lower()

    with open(config_path, 'r') as f:
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
    """Talk to a KSPEC GFA Camera over TCP/IP."""

    def __init__(self, config: str = None, logger: logging.Logger = None):
        """
        Initializes the GfaController with configuration and logger.

        Parameters
        ----------
        config : str, optional
            Path to the configuration file. If None, a default path is used.
        logger : logging.Logger, optional
            Logger instance for logging. If None, a default logger is created.

        Raises
        ------
        FileNotFoundError
            If no valid default configuration file is found.
        KeyError
            If expected keys are not present in the configuration dictionary.
        """
        # 1. Use default config if none provided
        if config is None:
            config = _get_default_config_path()

        # 2. Use default logger if none provided
        if logger is None:
            logger = _get_default_logger()

        self.logger = logger

        # 3. Load configuration into self.config (dict)
        try:
            self.config = from_config(config)
            self.logger.info("Initializing gfa_controller with provided config.")
        except Exception as e:
            self.logger.error(f"Error loading configuration from {config}: {e}")
            raise

        # 4. Extract camera data from config
        try:
            self.cameras_info = self.config["GfaController"]["Elements"]["Cameras"]["Elements"]
        except KeyError as e:
            self.logger.error(f"Configuration key error: {e}")
            raise

        # 5. Set up camera environment
        self.NUM_CAMERAS = 6
        os.environ["PYLON_CAMEMU"] = f"{self.NUM_CAMERAS}"
        self.tlf = py.TlFactory.GetInstance()

        # 6. Internal attributes
        self.grab_timeout = 5000
        self.img_class = GFAImage(logger)
        self.logger.info("GfaController initialization complete.")

    def ping(self, CamNum: int = 0):
        """
        Pings the camera specified by CamNum to check connectivity.

        Parameters
        ----------
        CamNum : int, optional
            The number identifier of the camera to ping. Defaults to 0 (unused or special case).

        Raises
        ------
        KeyError
            If the camera number is not found in the `cameras_info` dictionary.
        """
        self.logger.info(f"Pinging camera(s), CamNum={CamNum}")

        # Retrieve the camera's IP address
        try:
            Cam_IpAddress = self.cameras_info[f"Cam{CamNum}"]["IpAddress"]
        except KeyError:
            self.logger.error(f"Camera number {CamNum} not found in config.")
            raise

        self.logger.debug(f"Camera {CamNum} IP address: {Cam_IpAddress}")
        ping_test = os.system("ping -c 3 -w 1 " + Cam_IpAddress)
        self.logger.info(f"Pinging camera {CamNum} at {Cam_IpAddress}, result: {ping_test}")
        
    def status(self):
        """
        Checks and logs the connection status of all cameras.

        Returns
        -------
        dict
            A dictionary containing True/False status for each camera.
        """
        self.logger.info("Checking status of all cameras")
        camera_status_dict = {}  # 카메라 상태 정보를 저장할 딕셔너리

        for num in range(6):
            index = num + 1
            cam_key = f"Cam{index}"
            
            try:
                Cam_IpAddress = self.cameras_info[cam_key]["IpAddress"]
                self.logger.debug(f"Camera {index} IP address: {Cam_IpAddress}")

                cam_info = py.DeviceInfo()
                cam_info.SetIpAddress(Cam_IpAddress)
                camera = py.InstantCamera(self.tlf.CreateDevice(cam_info))
                camera.Open()

                # Standby 모드로 간주하는 기준 (필요시 조건 변경 가능)
                is_standby = camera.IsOpen()  # 카메라가 열려 있으면 Standby로 간주
                camera_status_dict[cam_key] = is_standby  # 상태 저장
                
                if is_standby:
                    self.logger.info(f"Camera {index} is online and in standby mode.")
                else:
                    self.logger.warning(f"Camera {index} is online but not in standby mode.")

                camera.Close()

            except Exception as e:
                error_message = f"Error with Camera {index} ({Cam_IpAddress}): {e}"
                self.logger.error(error_message)
                camera_status_dict[cam_key] = False  # 오류 발생 시 False 저장

        return camera_status_dict  # 최종 결과 반환



    def cam_params(self, CamNum: int):
        """
        Retrieves and logs parameters of the specified camera.

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

        # Retrieve camera information
        try:
            Cam_IpAddress = self.cameras_info[f"Cam{CamNum}"]["IpAddress"]
            Cam_SerialNumber = self.cameras_info[f"Cam{CamNum}"]["SerialNumber"]
        except KeyError:
            self.logger.error(f"Invalid camera number {CamNum}.")
            raise

        self.logger.debug(
            f"Camera {CamNum} IP: {Cam_IpAddress}, Serial: {Cam_SerialNumber}"
        )

        cam_info = py.DeviceInfo()
        cam_info.SetIpAddress(Cam_IpAddress)
        camera = py.InstantCamera(self.tlf.CreateDevice(cam_info))
        camera.Open()

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

        for label, attribute in info_attributes:
            try:
                value = getattr(camera, attribute).GetValue()
                # Changed from info to debug for verbose device data
                self.logger.info(f"{label} : {value}")
            except Exception as e:
                self.logger.error(f"AccessException for {label}: {e}")

        camera.Close()

    async def grabone(self, CamNum: int, ExpTime: float, Bininng: int, output_dir: str = None):
        """
        Grabs an image from the specified camera, sets exposure time and binning.

        Returns
        -------
        list
            [CamNum] if timeout occurred, otherwise [].
        """
        self.logger.info(f"Grabbing image from camera {CamNum}, ExpTime={ExpTime}")
        now1 = time.time()
        formatted = time.strftime("%Y-%m-%d_%H:%M:%S", time.localtime(now1))
        timeout_occurred = False

        # Retrieve camera info
        try:
            Cam_IpAddress = self.cameras_info[f"Cam{CamNum}"]["IpAddress"]
            self.logger.debug(f"Camera {CamNum} IP: {Cam_IpAddress}")
        except KeyError:
            self.logger.error(f"No Camera {CamNum} in config.")
            raise

        cam_info = py.DeviceInfo()
        cam_info.SetIpAddress(Cam_IpAddress)
        camera = py.InstantCamera(self.tlf.CreateDevice(cam_info))
        camera.Open()

        # Set exposure time in microseconds
        ExpTime_microsec = ExpTime * 1_000_000
        camera.ExposureTime.SetValue(ExpTime_microsec)
        self.logger.debug(f"Set exposure time: {ExpTime_microsec} μs")

        # Set PixelFormat
        set_PixelFormat = "Mono12"
        camera.PixelFormat.SetValue(set_PixelFormat)
        self.logger.debug(f"Set PixelFormat {set_PixelFormat}")

        # Set Binning
        camera.BinningHorizontal.SetValue(Bininng)
        camera.BinningVertical.SetValue(Bininng)
        self.logger.debug(f"Set binning: {Bininng}x{Bininng}")

        # Grab image
        try:
            self.grab_timeout = 10000
            res = camera.GrabOne(self.grab_timeout)
            img = res.GetArray()
            self.logger.debug(f"Max pixel value of grabbed image (Cam {CamNum}): {img.max()}")
            filename = f"{formatted}_grabone_cam{CamNum}.fits"
            self.img_class.save_fits(image_array=img,
                                     filename=filename,
                                     exptime=ExpTime,
                                     output_directory=output_dir)

            fig = plt.figure()
            plt.imshow(img)
            # 파일 확장자 제거
            filename_clean = os.path.splitext(filename)[0]
            fig.savefig(f"/home/kspec/mingyeong/png_save/{filename_clean}.png", dpi=300, bbox_inches="tight")
            plt.close(fig)

        except genicam.TimeoutException:
            self.logger.error(f"TimeoutException while grabbing image from camera {CamNum}")
            timeout_occurred = True

        camera.Close()

        now2 = time.time()
        # Changed from info to debug
        self.logger.debug(f"Exposure time for camera {CamNum}: {ExpTime} sec")
        self.logger.debug(f"Process time for camera {CamNum}: {now2 - now1} sec")

        return [CamNum] if timeout_occurred else []

    async def grab(self, CamNum, ExpTime: float, Bininng: int, output_dir: str = None):
        """
        Grabs images from specified cameras or all cameras.

        Returns
        -------
        list
            List of cameras for which timeouts occurred.
        """
        devices = []
        timeout_cameras = []

        if CamNum == 0:
            self.logger.info(f"Grabbing images from ALL cameras, ExpTime={ExpTime}")
            now1 = time.time()

            for key in self.cameras_info.keys():
                num = int(key.replace("Cam", ""))
                try:
                    Cam_IpAddress = self.cameras_info[key]["IpAddress"]
                    self.logger.debug(f"Camera {num} IP: {Cam_IpAddress}")
                    cam_info = py.DeviceInfo()
                    cam_info.SetIpAddress(Cam_IpAddress)
                    devices.append((cam_info, num))
                except KeyError:
                    self.logger.error(f"Camera {num} not found in config.")

        elif isinstance(CamNum, list):
            self.logger.info(f"Grabbing images from cameras {CamNum}, ExpTime={ExpTime}")
            now1 = time.time()

            for num in CamNum:
                try:
                    Cam_IpAddress = self.cameras_info[f"Cam{num}"]["IpAddress"]
                    self.logger.debug(f"Camera {num} IP: {Cam_IpAddress}")
                    cam_info = py.DeviceInfo()
                    cam_info.SetIpAddress(Cam_IpAddress)
                    devices.append((cam_info, num))
                except KeyError:
                    self.logger.error(f"Camera {num} not found in config.")
        else:
            self.logger.error("Invalid CamNum. Must be 0 or a list of camera numbers.")
            raise ValueError("CamNum should be 0 or a list of camera numbers.")

        # Gather tasks for parallel execution
        with ThreadPoolExecutor() as executor:
            loop = asyncio.get_running_loop()
            tasks = [self.process_camera(d, ExpTime, Bininng, output_dir) for d, _ in devices]
            results = await asyncio.gather(*tasks)

        # Identify which cameras timed out
        timeout_cameras = [num for ((_, num), img) in zip(devices, results) if img is None]

        now2 = time.time()
        # Changed from info to debug
        self.logger.debug(f"Final process time for grab: {now2 - now1:.2f} seconds")

        return timeout_cameras

    async def process_camera(self, device, ExpTime: float, Bininng: int, output_dir: str = None):
        """
        Opens a camera, sets parameters, grabs an image, and saves it.

        Returns
        -------
        numpy.ndarray or None
            Image array if successful, or None if a timeout or error occurred.
        """
        now1 = time.time()
        formatted = time.strftime("%Y-%m-%d_%H:%M:%S", time.localtime(now1))
        loop = asyncio.get_running_loop()
        img = None
        timeout_occurred = False

        camera = py.InstantCamera(self.tlf.CreateDevice(device))
        camera.Open()
        serial_number = await loop.run_in_executor(None, camera.DeviceSerialNumber.GetValue)
        # Changed to debug
        self.logger.debug(f"Opened camera: {serial_number}")

        # Configure camera
        ExpTime_microsec = ExpTime * 1_000_000
        set_PixelFormat = "Mono12"
        await loop.run_in_executor(None, camera.ExposureTime.SetValue, ExpTime_microsec)
        await loop.run_in_executor(None, camera.PixelFormat.SetValue, set_PixelFormat)
        await loop.run_in_executor(None, camera.BinningHorizontal.SetValue, Bininng)
        await loop.run_in_executor(None, camera.BinningVertical.SetValue, Bininng)

        # Grab image
        try:
            self.grab_timeout = 5000
            result = await loop.run_in_executor(None, camera.GrabOne, self.grab_timeout)
            img = result.GetArray()
            self.logger.info(f"Image grabbed from camera: {serial_number}")
            self.logger.debug(f"Max pixel value of grabbed image (Cam {device}): {img.max()}")

            filename = f"{formatted}_grab_cam_{serial_number}.fits"
            png_filename = f"{formatted}_grab_cam_{serial_number}.png"

            # Save FITS
            self.img_class.save_fits(
                image_array=img,
                filename=filename,
                exptime=ExpTime,
                output_directory=output_dir
            )

            # Save PNG
            fig = plt.figure()
            plt.imshow(img)
            fig.savefig("/home/kspec/mingyeong/png_save/" + png_filename, dpi=300, bbox_inches="tight")
            plt.close(fig)

        except genicam.TimeoutException:
            self.logger.error(f"TimeoutException while grabbing image from camera {serial_number}")
            timeout_occurred = True
        except Exception as e:
            self.logger.error(f"Error grabbing image from camera {serial_number}: {e}")

        # Close camera
        await loop.run_in_executor(None, camera.Close)

        if timeout_occurred:
            self.logger.info(f"Timeout occurred for camera {serial_number}")
            return None
        else:
            # Changed to debug
            self.logger.debug(f"Closed camera: {serial_number}")
            return img
