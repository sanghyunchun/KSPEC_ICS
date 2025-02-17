#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: gfa_actions.py

import os
import asyncio
from typing import Union, List, Dict, Any, Optional

from gfa_logger import GFALogger
from gfa_controller import GFAController
from gfa_astrometry import GFAAstrometry
from gfa_guider import GFAGuider

###############################################################################
# Global Config Paths
###############################################################################
gfa_relative_config_path = "etc/cams.json"
ast_relative_config_path = "etc/astrometry_params.json"

###############################################################################
# Logger
###############################################################################
logger = GFALogger(__file__)

###############################################################################
# Helper Functions
###############################################################################
def get_config_path(relative_config_path: str) -> str:
    """
    Calculate and return the absolute path of the configuration file.

    Parameters
    ----------
    relative_config_path : str
        The relative path of the configuration file.

    Returns
    -------
    str
        Absolute path of the configuration file.

    Raises
    ------
    FileNotFoundError
        If the configuration file does not exist at the calculated path.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, relative_config_path)

    if not os.path.isfile(config_path):
        logger.error(f"Config file not found: {config_path}")
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.info(f"Configuration file found: {config_path}")
    return config_path

###############################################################################
# Environment Class for Dependency Injection
###############################################################################
class GFAEnvironment:
    """
    Holds references to controller, astrometry, and guider,
    as well as paths, logger, and camera count.
    """
    def __init__(self, 
                 gfa_config_path: str, 
                 ast_config_path: str,
                 logger,
                 camera_count: int = 6):
        self.gfa_config_path = gfa_config_path
        self.ast_config_path = ast_config_path
        self.logger = logger
        self.camera_count = camera_count

        # Initialize dependencies
        self.controller = GFAController(self.gfa_config_path, self.logger)
        self.astrometry = GFAAstrometry(self.ast_config_path, self.logger)
        self.guider = GFAGuider(self.ast_config_path, self.logger)

def create_environment() -> GFAEnvironment:
    """
    Creates and returns a GFAEnvironment object with the default config paths
    and logger. Adjust this factory function as needed for your deployment.
    """
    gfa_config_path = get_config_path(gfa_relative_config_path)
    ast_config_path = get_config_path(ast_relative_config_path)
    return GFAEnvironment(gfa_config_path, ast_config_path, logger, camera_count=6)

###############################################################################
# GFA Actions Class
###############################################################################
class GFAActions:
    """
    A class to handle GFA actions such as grabbing images, guiding,
    and controlling the cameras.
    """

    def __init__(self, env: Optional[GFAEnvironment] = None):
        """
        Parameters
        ----------
        env : GFAEnvironment, optional
            If provided, sets up the environment (controller, astrometry, etc.).
            If None, a default environment is created internally.
        """
        if env is None:
            env = create_environment()  # Your existing environment factory
        self.env = env

    def _generate_response(
        self, 
        status: str, 
        message: str
    ) -> Dict[str, Any]:
        """
        Generate a standardized response dictionary.

        Parameters
        ----------
        status : str
            Status of the operation ('success' or 'error').
        message : str
            Message describing the operation result.

        Returns
        -------
        dict
            A dictionary representing the response.
        """
        return {
            "status": status,
            "message": message,
        }

    async def grab(
        self, 
        CamNum: Union[int, List[int]] = 0, 
        ExpTime: float = 1.0, 
        Binning: int = 4
    ) -> Dict[str, Any]:
        """
        Grab an image from the specified camera(s) asynchronously.

        Parameters
        ----------
        CamNum : int or list of int
            Camera number(s) to grab images from. 
            0 means "all cameras".
        ExpTime : float
            Exposure time.
        Binning : int
            Binning factor.

        Returns
        -------
        dict
            Dictionary response with status, message, and any additional data.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        grab_save_path = os.path.join(base_dir, "img", "grab")
        self.env.logger.info(f"Image save path: {grab_save_path}")

        timeout_cameras = []
        try:
            # If CamNum is a single integer
            if isinstance(CamNum, int):
                if CamNum == 0:
                    self.env.logger.info(
                        f"Grabbing image from ALL cameras (ExpTime={ExpTime}, Binning={Binning})."
                    )
                    # This presumably awaits an async method in the controller
                    timeout_cameras = await self.env.controller.grab(
                        CamNum, ExpTime, Binning, output_dir=grab_save_path
                    )
                    message = (f"Images grabbed from all cameras. "
                               f"(ExpTime: {ExpTime}, Binning: {Binning})")
                    if timeout_cameras:
                        message += f" | Timeout occurred for cameras: {timeout_cameras}"
                    return self._generate_response("success", message)

                else:
                    self.env.logger.info(
                        f"Grabbing image from camera {CamNum} (ExpTime={ExpTime}, Binning={Binning})."
                    )
                    # Single camera capture
                    # This presumably awaits an async method in the controller
                    result = await self.env.controller.grabone(
                        CamNum, ExpTime, Binning, output_dir=grab_save_path
                    )
                    timeout_cameras.extend(result)
                    message = (f"Image grabbed from camera {CamNum}. "
                               f"(ExpTime: {ExpTime}, Binning: {Binning})")
                    if timeout_cameras:
                        message += f" | Timeout occurred for camera {timeout_cameras[0]}"
                    return self._generate_response("success", message)

            # If CamNum is a list of integers
            elif isinstance(CamNum, list):
                self.env.logger.info(
                    f"Grabbing image from cameras {CamNum} (ExpTime={ExpTime}, Binning={Binning})."
                )
                timeout_cameras = await self.env.controller.grab(
                    CamNum, ExpTime, Binning, output_dir=grab_save_path
                )
                message = (f"Images grabbed from cameras {CamNum}. "
                           f"(ExpTime: {ExpTime}, Binning: {Binning})")
                if timeout_cameras:
                    message += f" | Timeout occurred for cameras: {timeout_cameras}"
                return self._generate_response("success", message)

            else:
                error_msg = f"Wrong input for CamNum: {CamNum}."
                self.env.logger.error(error_msg)
                raise ValueError(error_msg)

        except Exception as e:
            self.env.logger.error(f"Error occurred: {str(e)}")
            return self._generate_response(
                "error", 
                (f"Error occurred: {str(e)} "
                 f"(CamNum: {CamNum}, ExpTime: {ExpTime}, Binning: {Binning})")
            )

    async def guiding(self) -> Dict[str, Any]:
        """
        The main guiding loop that grabs images, processes them with astrometry,
        and calculates offsets.

        Returns
        -------
        dict
            Dictionary response indicating success or error and relevant messages.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        grab_save_path = os.path.join(base_dir, "img", "raw")

        try:
            self.env.logger.info("Guiding starts...")

            self.env.logger.info("Step #1: Grab an image (uncomment if needed).")
            # Example call:
            # await self.grab(CamNum=0, ExpTime=0.1, Binning=4)

            self.env.logger.info("Step #2: Astrometry...")
            # If preproc() is synchronous, calling directly is fine
            self.env.astrometry.preproc()

            self.env.logger.info("Step #3: Calculating the offset...")
            # If exe_cal() is synchronous, calling directly is fine
            fdx, fdy, fwhm = self.env.guider.exe_cal()

            self.env.logger.info(
                f"Offsets calculated: fdx={fdx}, fdy={fdy}, FWHM={fwhm:.2f} arcsec"
            )
            return self._generate_response(
                "success",
                (f"Guiding completed successfully. "
                 f"Offsets: fdx={fdx}, fdy={fdy}, FWHM={fwhm:.5f} arcsec")
            )
        except Exception as e:
            self.env.logger.error(f"Error occurred during guiding: {str(e)}")
            return self._generate_response(
                "error",
                f"Error occurred during guiding: {str(e)}"
            )

    def status(self) -> Dict[str, Any]:
        """
        Check and log the status of all cameras.

        Returns
        -------
        dict
            Dictionary response with aggregated status information.
        """
        try:
            self.env.logger.info("Checking status of all cameras.")
            status_info = self.env.controller.status()
            # status_info is assumed to be an iterable of camera statuses
            status_message = "\n".join(
                [f"Camera {i+1}: {info}" for i, info in enumerate(status_info)]
            )
            return self._generate_response(
                "success",
                f"Camera status retrieved successfully:\n{status_message}"
            )
        except Exception as e:
            self.env.logger.error(f"Error occurred while checking status: {str(e)}")
            return self._generate_response(
                "error", 
                f"Error occurred while checking status: {str(e)}"
            )

    def ping(self, CamNum: int = 0) -> Dict[str, Any]:
        """
        Ping the specified camera(s) to check connectivity.

        Parameters
        ----------
        CamNum : int
            Camera number to ping. 0 means "all cameras".

        Returns
        -------
        dict
            Dictionary response with the ping result.
        """
        try:
            if CamNum == 0:
                self.env.logger.info("Pinging all cameras.")
                for index in range(1, self.env.camera_count + 1):
                    self.env.controller.ping(index)
                return self._generate_response("success", "Pinging all cameras completed.")
            else:
                self.env.logger.info(f"Pinging camera {CamNum}.")
                self.env.controller.ping(CamNum)
                return self._generate_response(
                    "success", 
                    f"Camera {CamNum} pinged successfully."
                )
        except Exception as e:
            self.env.logger.error(
                f"Error occurred while pinging camera(s): {str(e)}"
            )
            return self._generate_response(
                "error", 
                f"Error occurred while pinging camera {CamNum}: {str(e)}"
            )

    def cam_params(self, CamNum: int = 0) -> Dict[str, Any]:
        """
        Retrieve and log parameters from the specified camera(s).

        Parameters
        ----------
        CamNum : int
            Camera number to retrieve parameters from. 
            0 means "all cameras".

        Returns
        -------
        dict
            Dictionary response with retrieved camera parameters.
        """
        try:
            if CamNum == 0:
                self.env.logger.info("Retrieving parameters for ALL cameras.")
                params = []
                for n in range(self.env.camera_count):
                    index = n + 1
                    param = self.env.controller.cam_params(index)
                    params.append(param)
                param_message = "\n".join(
                    [f"Camera {i+1}: {param}" for i, param in enumerate(params)]
                )
                return self._generate_response(
                    "success",
                    f"Parameters retrieved for all cameras:\n{param_message}"
                )
            else:
                self.env.logger.info(f"Retrieving parameters for camera {CamNum}.")
                param = self.env.controller.cam_params(CamNum)
                return self._generate_response(
                    "success", 
                    f"Parameters retrieved for camera {CamNum}: {param}"
                )
        except Exception as e:
            self.env.logger.error(
                f"Error occurred while retrieving camera parameters: {str(e)}"
            )
            return self._generate_response(
                "error",
                f"Error occurred while retrieving parameters for camera {CamNum}: {str(e)}"
            )
