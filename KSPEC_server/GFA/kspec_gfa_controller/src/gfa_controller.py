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
from concurrent.futures import ThreadPoolExecutor

import matplotlib.pyplot as plt
import pypylon.pylon as py
import yaml
from pypylon import genicam

from kspec_gfa_controller.src.gfa_img import gfa_img

__all__ = ["gfa_controller"]

class gfa_controller:
    """Talk to an KSPEC GFA Camera over TCP/IP."""

    def __init__(self, config, logger):
        """
        Initializes the GfaController with configuration and logger.

        Parameters
        ----------
        config : dict
            Configuration dictionary containing camera and controller settings.
        logger : gfa_logger
            Logger instance used for logging information and errors.

        Raises
        ------
        Exception
            If the configuration is not valid or missing, an exception is raised.
        """
        self.logger = logger
        self.grab_timeout = 5000
        self.img_class = gfa_img(logger)

        try:
            # Load configuration
            self.config = from_config(config)
            self.logger.info("Initializing gfa_controller")

            # Extract camera information from configuration
            self.cameras_info = self.config["GfaController"]["Elements"]["Cameras"][
                "Elements"
            ]
            #self.logger.info(f"Loaded cameras info: {self.cameras_info}")

        except KeyError as e:
            self.logger.error(f"Configuration key error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            raise

        self.NUM_CAMERAS = 6
        os.environ["PYLON_CAMEMU"] = f"{self.NUM_CAMERAS}"
        self.tlf = py.TlFactory.GetInstance()

        self.logger.info("GfaController initialization complete.")

    def ping(self, CamNum=0):
        """
        Pings the camera specified by CamNum to check connectivity.

        Parameters
        ----------
        CamNum : int, optional
            The number identifier of the camera to ping. Defaults to 0.

        Raises
        ------
        KeyError
            If the camera number is not found in the `cameras_info` dictionary.
        """
        self.logger.info(f"Pinging camera(s), CamNum={CamNum}")

        try:
            # Retrieve the camera's IP address from the cameras_info dictionary
            Cam_IpAddress = self.cameras_info[f"Cam{CamNum}"]["IpAddress"]
        except KeyError:
            self.logger.error(
                f"Camera number {CamNum} not found. Please provide a valid camera number."
            )
            raise

        self.logger.debug(f"Camera {CamNum} IP address: {Cam_IpAddress}")
        # Perform the ping test
        ping_test = os.system("ping -c 3 -w 1 " + Cam_IpAddress)
        self.logger.info(
            f"Pinging camera {CamNum} at {Cam_IpAddress}, result: {ping_test}"
        )

    def status(self):
        """
        Checks and logs the connection status of all cameras.

        This method iterates over a predefined range of cameras,
        retrieves each camera's IP address, and checks its connection
        status by attempting to open and close a connection to the camera.

        Notes
        -----
        - The method assumes there are up to 6 cameras, indexed from 1 to 6.
        - It uses the `py.DeviceInfo` and `py.InstantCamera` classes to interact with the camera.
        - Cameras are opened and closed to verify their connectivity status.
        """
        self.logger.info("Checking status of all cameras")
        for num in range(6):
            index = num + 1
            try:
                Cam_IpAddress = self.cameras_info[f"Cam{index}"]["IpAddress"]
                self.logger.debug(f"Camera {index} IP address: {Cam_IpAddress}")

                cam_info = py.DeviceInfo()
                cam_info.SetIpAddress(Cam_IpAddress)
                camera = py.InstantCamera(self.tlf.CreateDevice(cam_info))
                camera.Open()
                self.logger.info(f"Camera {index} is online and in standby mode.")

                # Close the camera connection
                camera.Close()
            except Exception as e:
                self.logger.error(f"Error with camera {index} ({Cam_IpAddress}): {e}")

    def cam_params(self, CamNum):
        """
        Retrieves and logs the parameters of the specified camera.

        Parameters
        ----------
        CamNum : int
            The number identifier of the camera whose parameters are to be retrieved.

        Raises
        ------
        KeyError
            If the camera number is not found in the `cameras_info` dictionary.

        Notes
        -----
        - The method assumes the camera information includes IP address and serial number.
        - It uses the `py.DeviceInfo` and `py.InstantCamera` classes to interact with the camera.
        - It logs detailed camera parameters and handles exceptions when accessing attributes.
        """
        self.logger.info(f"Checking the parameters from camera {CamNum}")

        try:
            # Retrieve camera information
            Cam_IpAddress = self.cameras_info[f"Cam{CamNum}"]["IpAddress"]
            Cam_SerialNumber = self.cameras_info[f"Cam{CamNum}"]["SerialNumber"]
        except KeyError:
            self.logger.error(
                f"Invalid camera number {CamNum}. Please provide a valid camera number."
            )
            raise

        self.logger.debug(
            f"Camera {CamNum} IP address: {Cam_IpAddress}, Serial number: {Cam_SerialNumber}"
        )

        cam_info = py.DeviceInfo()
        cam_info.SetIpAddress(Cam_IpAddress)
        camera = py.InstantCamera(self.tlf.CreateDevice(cam_info))

        # Open the camera
        self.logger.debug(f"Opening camera {CamNum}")
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
                self.logger.info(f"{label} : {value}")
            except Exception as e:
                self.logger.error(
                    f"AccessException occurred while accessing {label}: {e}"
                )

        # Close the camera
        camera.Close()

    async def grabone(self, CamNum, ExpTime, Bininng):
        """
        Grabs an image from the specified camera, sets exposure time and binning parameters.

        Parameters
        ----------
        CamNum : int
            The number identifier of the camera from which to grab the image.
        ExpTime : float
            The exposure time in seconds.
        Bininng : int
            The binning size for both horizontal and vertical directions.

        Raises
        ------
        KeyError
            If the camera number is not found in the `cameras_info` dictionary.
        genicam.TimeoutException
            If there is a timeout while grabbing the image.

        Notes
        -----
        - The method assumes the `py.DeviceInfo` and `py.InstantCamera` classes are used for camera interaction.
        - The image is saved in both FITS and PNG formats.
        - Binning parameters are set for both horizontal and vertical directions.
        """
        self.logger.info(f"Grabbing image from camera {CamNum}, ExpTime={ExpTime}")
        now1 = time.time()
        lt = time.localtime(now1)
        formatted = time.strftime("%Y-%m-%d_%H:%M:%S", lt)

        try:
            # Retrieve camera information
            Cam_IpAddress = self.cameras_info[f"Cam{CamNum}"]["IpAddress"]
            self.logger.debug(f"Camera {CamNum} IP address: {Cam_IpAddress}")
        except KeyError:
            self.logger.error(f"No Camera {CamNum} found in the camera information.")
            raise

        cam_info = py.DeviceInfo()
        cam_info.SetIpAddress(Cam_IpAddress)
        camera = py.InstantCamera(self.tlf.CreateDevice(cam_info))

        # Open the camera
        self.logger.debug(f"Opening camera {CamNum}")
        camera.Open()

        # Set Exposure Time
        ExpTime_microsec = ExpTime * 1_000_000  # Convert seconds to microseconds
        camera.ExposureTime.SetValue(ExpTime_microsec)
        self.logger.debug(
            f"Setting exposure time for camera {CamNum} to {ExpTime_microsec} microseconds"
        )

        # Set Binning mode and size
        camera.BinningHorizontal.SetValue(Bininng)
        camera.BinningVertical.SetValue(Bininng)
        self.logger.debug(f"Setting binning for camera {CamNum} to {Bininng}x{Bininng}")

        try:
            self.grab_timeout = 5000  # Define grab timeout
            res = camera.GrabOne(self.grab_timeout)
            img = res.GetArray()
            filename = f"{formatted}_grabone_cam{CamNum}.fits"
            self.img_class.save_fits(image_array=img, filename=filename, exptime=ExpTime)

            fig = plt.figure()
            plt.imshow(img)
            fig.savefig(f"save/{filename}.png", dpi=300, bbox_inches="tight")
            plt.close(fig)
                
        except genicam.TimeoutException:
            self.logger.error(
                f"TimeoutException occurred while grabbing an image from camera {CamNum}"
            )

        # Close the camera
        camera.Close()

        now2 = time.time()
        self.logger.info(f"Exposure time for camera {CamNum}: {ExpTime} sec")
        self.logger.info(f"Process time for camera {CamNum}: {now2 - now1} sec")

    async def grab(self, CamNum, ExpTime, Bininng):
        """
        Grabs images from specified cameras either individually or all cameras.

        Depending on the value of `CamNum`, the method will grab images from:
        - All cameras (if `CamNum` is 0)
        - A list of specified cameras (if `CamNum` is a list of integers)

        Parameters
        ----------
        CamNum : int or list of int
            The number identifier of the camera(s) from which to grab images. If `0`, grabs from all cameras. If a list, grabs from the specified cameras.
        ExpTime : float
            The exposure time in seconds for the image capture.
        Bininng : int
            The binning size for both horizontal and vertical directions.

        Raises
        ------
        KeyError
            If any specified camera number is not found in the `cameras_info` dictionary.
        ValueError
            If `CamNum` is neither `0` nor a list of integers.

        Notes
        -----
        - Uses `py.DeviceInfo` to create camera instances.
        - Handles asynchronous image grabbing for multiple cameras using `asyncio`.
        """
        devices = []

        if CamNum == 0:
            self.logger.info(f"Grabbing images from all cameras, ExpTime={ExpTime}")
            now1 = time.time()

            for index in range(6):
                num = index + 1
                try:
                    # Retrieve camera information
                    Cam_IpAddress = self.cameras_info[f"Cam{num}"]["IpAddress"]
                    self.logger.debug(f"Camera {num} IP address: {Cam_IpAddress}")

                    cam_info = py.DeviceInfo()
                    cam_info.SetIpAddress(Cam_IpAddress)
                    devices.append(cam_info)
                except KeyError:
                    self.logger.error(
                        f"Camera {num} not found in the camera information."
                    )

        elif isinstance(CamNum, list):
            self.logger.info(
                f"Grabbing images from cameras {CamNum}, ExpTime={ExpTime}"
            )
            now1 = time.time()

            for num in CamNum:
                try:
                    # Retrieve camera information
                    Cam_IpAddress = self.cameras_info[f"Cam{num}"]["IpAddress"]
                    self.logger.debug(f"Camera {num} IP address: {Cam_IpAddress}")

                    cam_info = py.DeviceInfo()
                    cam_info.SetIpAddress(Cam_IpAddress)
                    devices.append(cam_info)
                except KeyError:
                    self.logger.error(
                        f"Camera {num} not found in the camera information."
                    )

        else:
            self.logger.error(
                "Invalid CamNum. It should be either 0 or a list of camera numbers."
            )
            raise ValueError("CamNum should be either 0 or a list of camera numbers.")

        # Execute asynchronous tasks
        with ThreadPoolExecutor() as executor:
            loop = asyncio.get_running_loop()
            tasks = [self.process_camera(d, ExpTime, Bininng) for d in devices]
            await asyncio.gather(*tasks)

        now2 = time.time()
        self.logger.info(f"Final process time for grab: {now2 - now1:.2f} seconds")

    async def process_camera(self, device, ExpTime, Bininng):
        """
        Processes a single camera: opens it, sets exposure time and binning parameters, grabs an image, and saves it.

        Parameters
        ----------
        device : py.DeviceInfo
            The camera device information used to create and control the camera instance.
        ExpTime : float
            The exposure time in seconds for capturing the image.
        Bininng : int
            The binning size for both horizontal and vertical directions.

        Returns
        -------
        img : numpy.ndarray or None
            The captured image as a NumPy array. Returns `None` if an error occurs.

        Raises
        ------
        genicam.TimeoutException
            If there is a timeout while grabbing the image.
        Exception
            For any other unexpected errors during image capture.

        Notes
        -----
        - Uses `py.InstantCamera` for camera operations.
        - Executes camera operations asynchronously using `asyncio` and `run_in_executor`.
        - Saves the captured image in FITS and PNG formats.
        """
        now1 = time.time()
        lt = time.localtime(now1)
        formatted = time.strftime("%Y-%m-%d %H:%M:%S", lt)
        loop = asyncio.get_running_loop()

        img = None  # Initialize image variable

        # Open the camera
        camera = py.InstantCamera(self.tlf.CreateDevice(device))
        camera.Open()
        serial_number = await loop.run_in_executor(
            None, camera.DeviceSerialNumber.GetValue
        )
        self.logger.info(f"Opened camera: {serial_number}")

        # Set Exposure Time
        ExpTime_microsec = ExpTime * 1_000_000  # Convert seconds to microseconds
        await loop.run_in_executor(None, camera.ExposureTime.SetValue, ExpTime_microsec)

        # Set Binning mode and size
        await loop.run_in_executor(None, camera.BinningHorizontal.SetValue, Bininng)
        await loop.run_in_executor(None, camera.BinningVertical.SetValue, Bininng)

        # Grab the image
        try:
            self.grab_timeout = 5000  # Define grab timeout
            result = await loop.run_in_executor(None, camera.GrabOne, self.grab_timeout)
            img = result.GetArray()
            self.logger.info(f"Image grabbed from camera: {serial_number}")
            
            filename = f"{formatted}_grab_cam_{serial_number}.fits"
            png_filename = f"save/{formatted}_grab_cam_{serial_number}.png"
            # Save FITS file
            self.img_class.save_fits(image_array=img, filename=filename, exptime=ExpTime)

            # Save PNG file
            fig = plt.figure()
            plt.imshow(img)
            fig.savefig(png_filename, dpi=300, bbox_inches="tight")
            plt.close(fig)

        except genicam.TimeoutException:
            self.logger.error(
                f"TimeoutException occurred while grabbing an image from camera {serial_number}"
            )
        except Exception as e:
            self.logger.error(
                f"An unexpected error occurred while grabbing an image from camera {serial_number}: {str(e)}"
            )

        # Close the camera
        await loop.run_in_executor(None, camera.Close)
        self.logger.info(f"Closed camera: {serial_number}")

        return img


def from_config(config):
    """
    Creates a dictionary of the GFA camera information from a configuration file.

    This function reads the configuration file based on its extension (.yml, .yaml, .json)
    and loads its contents into a dictionary.

    Parameters
    ----------
    config : str
        Path to the configuration file. The file can be in YAML (.yml or .yaml) or JSON (.json) format.

    Returns
    -------
    dict
        A dictionary containing the GFA camera information extracted from the configuration file.

    Raises
    ------
    ValueError
        If the file format is unsupported (i.e., not .yml, .yaml, or .json).

    Notes
    -----
    - YAML files are loaded using `yaml.load` with `yaml.FullLoader`.
    - JSON files are loaded using `json.load`.
    """
    file_extension = os.path.splitext(config)[1]

    with open(config) as f:
        if file_extension in [".yml", ".yaml"]:
            film = yaml.load(f, Loader=yaml.FullLoader)
        elif file_extension == ".json":
            film = json.load(f)
        else:
            raise ValueError(
                "Unsupported file format. Please use a .yml, .yaml, or .json file."
            )

    return film
