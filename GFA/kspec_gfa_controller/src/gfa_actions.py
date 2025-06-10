#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: gfa_actions.py

import os
import asyncio
from typing import Union, List, Dict, Any, Optional

from .gfa_logger import GFALogger
from .gfa_controller import GFAController
from .gfa_astrometry import GFAAstrometry
from .gfa_guider import GFAGuider

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
        # --- OPEN ALL CAMERAS ONCE AT STARTUP ---
        self.controller.open_all_cameras()

        self.astrometry = GFAAstrometry(self.ast_config_path, self.logger)
        self.guider = GFAGuider(self.ast_config_path, self.logger)

    def shutdown(self):
        """Cleanly close all cameras before exit."""
        self.logger.info("Shutting down environment: closing all cameras.")
        self.controller.close_all_cameras()

def create_environment() -> GFAEnvironment:
    """
    Creates and returns a GFAEnvironment object with the default config paths
    and logger, and opens all cameras immediately.
    """
    gfa_config_path = get_config_path(gfa_relative_config_path)
    ast_config_path = get_config_path(ast_relative_config_path)
    env = GFAEnvironment(gfa_config_path, ast_config_path, logger, camera_count=6)
    return env

###############################################################################
# GFA Actions Class
###############################################################################
class GFAActions:
    """
    A class to handle GFA actions such as grabbing images, guiding,
    and controlling the cameras.
    """

    def __init__(self, env: Optional[GFAEnvironment] = None):
        if env is None:
            env = create_environment()
        self.env = env

    def _generate_response(self, status: str, message: str, **kwargs) -> dict:
        response = {"status": status, "message": message}
        response.update(kwargs)
        return response

    async def grab(
        self,
        CamNum: Union[int, List[int]] = 0,
        ExpTime: float = 1.0,
        Binning: int = 4,
        *,
        packet_size: int = 8192,
        cam_ipd: int = 367318,         # default for Cam1~5
        cam_ftd_base: int = 0    # default for Cam1~5
    ) -> Dict[str, Any]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        grab_save_path = os.path.join(base_dir, "img", "grab")
        self.env.logger.info(f"Image save path: {grab_save_path}")

        timeout_cameras: List[int] = []

        try:
            # Single camera
            if isinstance(CamNum, int) and CamNum != 0:
                self.env.logger.info(
                    f"Grabbing from camera {CamNum} (ExpTime={ExpTime}, Binning={Binning}, PacketSize={packet_size}, IPD={cam_ipd}, FTD_Base={cam_ftd_base})"
                )
                result = await self.env.controller.grabone(
                    CamNum=CamNum,
                    ExpTime=ExpTime,
                    Binning=Binning,
                    output_dir=grab_save_path,
                    packet_size=packet_size,
                    ipd=cam_ipd,
                    ftd_base=cam_ftd_base,
                )
                timeout_cameras.extend(result)
                msg = f"Image grabbed from camera {CamNum}."
                if timeout_cameras:
                    msg += f" Timeout: {timeout_cameras[0]}"
                return self._generate_response("success", msg)

            # All cameras with individual settings
            if isinstance(CamNum, int) and CamNum == 0:
                self.env.logger.info("Grabbing from ALL cameras with per-camera settings")
                for cam_id in range(1, self.env.camera_count + 1):

                    self.env.logger.info(
                        f"Grabbing from Cam{cam_id} (ExpTime={ExpTime}, Binning={Binning}, PacketSize={packet_size}, IPD={cam_ipd}, FTD_Base={cam_ftd_base})"
                    )

                    res = await self.env.controller.grabone(
                        CamNum=cam_id,
                        ExpTime=ExpTime,
                        Binning=Binning,
                        output_dir=grab_save_path,
                        packet_size=packet_size,
                        ipd=cam_ipd,
                        ftd_base=cam_ftd_base,
                    )
                    timeout_cameras.extend(res)

                msg = f"Images grabbed from all cameras with individual settings."
                if timeout_cameras:
                    msg += f" Timeout: {timeout_cameras}"
                return self._generate_response("success", msg)

            # List of specific cameras (all use common ipd/ftd_base here)
            if isinstance(CamNum, list):
                self.env.logger.info(
                    f"Grabbing from cameras {CamNum} (ExpTime={ExpTime}, Binning={Binning}, PacketSize={packet_size}, IPD={ipd}, FTD_Base={ftd_base})"
                )
                for num in CamNum:
                    res = await self.env.controller.grabone(
                        CamNum=num,
                        ExpTime=ExpTime,
                        Binning=Binning,
                        output_dir=grab_save_path,
                        packet_size=packet_size,
                        ipd=cam_ipd,
                        ftd_base=cam_ftd_base,
                    )
                    timeout_cameras.extend(res)

                msg = f"Images grabbed from cameras {CamNum}."
                if timeout_cameras:
                    msg += f" Timeout: {timeout_cameras}"
                return self._generate_response("success", msg)

            raise ValueError(f"Wrong input for CamNum: {CamNum}")

        except Exception as e:
            self.env.logger.error(f"Error in grab(): {e}")
            return self._generate_response(
                "error",
                f"Error in grab(): {e} (CamNum={CamNum}, ExpTime={ExpTime}, Binning={Binning}, PacketSize={packet_size}, IPD={ipd}, FTD_Base={ftd_base})"
            )



    async def guiding(self, ExpTime: float = 1.0) -> Dict[str, Any]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        raw_save_path = os.path.join(base_dir, "img", "raw")

        try:
            self.env.logger.info("Guiding starts...")
            # Grab if needed:
            # await self.env.controller.grab(0, ExpTime, 4, output_dir=raw_save_path)

            self.env.logger.info("Astrometry preprocessing...")
            self.env.astrometry.preproc()

            self.env.logger.info("Calculating guider offsets...")
            fdx, fdy, fwhm = self.env.guider.exe_cal()

            # Deleting raw and processed files
            self.env.logger.info("Clearing raw and processed files after guiding...")
            self.env.astrometry.clear_raw_and_processed_files()

            msg = f"Offsets: fdx={fdx}, fdy={fdy}, FWHM={fwhm:.5f} arcsec"
            return self._generate_response("success", msg, fdx=fdx, fdy=fdy, fwhm=fwhm)

        except Exception as e:
            self.env.logger.error(f"Error during guiding: {e}")
            return self._generate_response("error", f"Error during guiding: {e}")

    def status(self) -> Dict[str, Any]:
        try:
            self.env.logger.info("Checking status of all cameras.")
            status_info = self.env.controller.status()
            return self._generate_response("success", status_info)
        except Exception as e:
            self.env.logger.error(f"Error checking status: {e}")
            return self._generate_response("error", f"Error checking status: {e}")

    def ping(self, CamNum: int = 0) -> Dict[str, Any]:
        try:
            if CamNum == 0:
                self.env.logger.info("Pinging all cameras.")
                for i in range(1, self.env.camera_count + 1):
                    self.env.controller.ping(i)
                return self._generate_response("success", "Pinged all cameras.")
            else:
                self.env.logger.info(f"Pinging camera {CamNum}.")
                self.env.controller.ping(CamNum)
                return self._generate_response("success", f"Pinged camera {CamNum}.")
        except Exception as e:
            self.env.logger.error(f"Error pinging camera(s): {e}")
            return self._generate_response("error", f"Error pinging camera(s): {e}")

    def cam_params(self, CamNum: int = 0) -> Dict[str, Any]:
        try:
            if CamNum == 0:
                self.env.logger.info("Retrieving parameters for all cameras.")
                messages = []
                for i in range(1, self.env.camera_count + 1):
                    param = self.env.controller.cam_params(i)
                    messages.append(f"Cam{i}: {param}")
                return self._generate_response("success", "\n".join(messages))
            else:
                self.env.logger.info(f"Retrieving parameters for camera {CamNum}.")
                param = self.env.controller.cam_params(CamNum)
                return self._generate_response("success", f"Cam{CamNum}: {param}")
        except Exception as e:
            self.env.logger.error(f"Error retrieving parameters: {e}")
            return self._generate_response("error", f"Error retrieving parameters: {e}")

    def shutdown(self):
        """
        Call this to cleanly close cameras before exiting.
        """
        self.env.shutdown()
        self.env.logger.info("GFAActions shutdown complete.")
