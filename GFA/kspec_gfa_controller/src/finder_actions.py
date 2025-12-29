#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: finder_actions.py

import os
import asyncio
import shutil
from datetime import datetime
from typing import Dict, Any, Optional

from .gfa_logger import GFALogger
from .gfa_environment import create_environment, GFAEnvironment

logger = GFALogger(__file__)

###############################################################################
# Finder GFA Actions Class
###############################################################################


class FinderGFAActions:
    """
    A class to handle GFA actions for the finder camera (Cam7).

    This is designed for single-camera operation such as focus image acquisition.
    """

    def __init__(self, env: Optional[GFAEnvironment] = None):
        """
        Initialize the FinderGFAActions with a finder-specific environment.

        Parameters
        ----------
        env : GFAEnvironment, optional
            A pre-initialized environment. If None, a default finder environment is created.
        """
        if env is None:
            env = create_environment(role="finder")
        self.env = env
        self.cam_id = 7

    def _generate_response(self, status: str, message: str, **kwargs) -> dict:
        """
        Create a structured response dictionary.

        Parameters
        ----------
        status : str
            The status string, e.g., "success" or "error".
        message : str
            Description of the result.
        kwargs : dict
            Additional data to include.

        Returns
        -------
        dict
            Structured response.
        """
        response = {"status": status, "message": message}
        response.update(kwargs)
        return response

    async def grab(
        self,
        ExpTime: float = 1.0,
        Binning: int = 1,
        *,
        packet_size: int = None,
        cam_ipd: int = None,
        cam_ftd_base: int = 0,
        ra: str = None,
        dec: str = None,
    ) -> Dict[str, Any]:
        """
        Grab a single image from the finder camera and save it.

        Parameters
        ----------
        ExpTime : float, optional
            Exposure time in seconds.
        Binning : int, optional
            Binning factor.
        packet_size : int, optional
            Packet size for image transmission. If None, use cams.json.
        cam_ipd : int, optional
            Inter-packet delay. If None, use cams.json.
        cam_ftd_base : int, optional
            Frame transmission delay base.

        Returns
        -------
        dict
            Result message and timeout info if any.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")
        grab_save_path = os.path.join(base_dir, "img", "grab_finder", date_str)
        self.env.logger.info(f"Saving finder image to: {grab_save_path}")

        try:
            self.env.logger.info(
                f"Grabbing from Cam{self.cam_id} (ExpTime={ExpTime}, Binning={Binning})"
            )
            result = await self.env.controller.grabone(
                CamNum=self.cam_id,
                ExpTime=ExpTime,
                Binning=Binning,
                output_dir=grab_save_path,
                packet_size=packet_size,
                ipd=cam_ipd,
                ftd_base=cam_ftd_base,
                ra=ra,
                dec=dec,
            )

            msg = f"Image grabbed from Cam{self.cam_id}."
            if result:
                msg += f" Timeout: {result}"
            return self._generate_response("success", msg)

        except Exception as e:
            self.env.logger.error(f"Grab failed: {e}")
            return self._generate_response("error", f"Grab failed: {e}")

    async def guiding(
        self, ExpTime: float = 1.0, save: bool = False, ra: str = None, dec: str = None
    ) -> Dict[str, Any]:
        """
        Acquire an image for focusing. For the finder camera, this replaces guiding.

        Parameters
        ----------
        ExpTime : float, optional
            Exposure time in seconds.
        save : bool, optional
            Whether to save the image to the grab path.

        Returns
        -------
        dict
            Result of the focus acquisition process.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")

        raw_save_path = os.path.join(base_dir, "img", "raw")
        grab_save_path = os.path.join(base_dir, "img", "grab_finder", date_str)

        try:
            self.env.logger.info("Starting guiding sequence...")

            os.makedirs(raw_save_path, exist_ok=True)
            self.env.logger.info("Grabbing raw image...")
            self.env.controller.grab(
                0, ExpTime, 4, output_dir=raw_save_path, ra=ra, dec=dec
            )

            if save:
                os.makedirs(grab_save_path, exist_ok=True)
                for fname in os.listdir(raw_save_path):
                    src = os.path.join(raw_save_path, fname)
                    dst = os.path.join(grab_save_path, fname)
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)
                self.env.logger.info(f"Images also copied to: {grab_save_path}")

            # self.env.logger.info("Running astrometry preprocessing...")
            # self.env.astrometry.preproc()

            # self.env.logger.info("Executing guider offset calculation...")
            # fdx, fdy, fwhm = self.env.guider.exe_cal()

            # self.env.logger.info("Clearing temp astrometry data...")
            # self.env.astrometry.clear_raw_and_processed_files()

            # msg = f"Offsets: fdx={fdx}, fdy={fdy}, FWHM={fwhm:.5f} arcsec"
            msg = "."
            fdx, fdy, fwhm = 0, 0, 0
            return self._generate_response("success", msg, fdx=fdx, fdy=fdy, fwhm=fwhm)

        except Exception as e:
            self.env.logger.error(f"Guiding failed: {e}")
            return self._generate_response("error", f"Guiding failed: {e}")

    def status(self) -> Dict[str, Any]:
        """
        Query the status of the finder camera.

        Returns
        -------
        dict
            Resulting status information.
        """
        try:
            self.env.logger.info("Checking finder camera status...")
            status_info = self.env.controller.status()
            return self._generate_response("success", status_info)
        except Exception as e:
            self.env.logger.error(f"Status check failed: {e}")
            return self._generate_response("error", f"Status check failed: {e}")

    def ping(self) -> Dict[str, Any]:
        """
        Ping the finder camera to check connectivity.

        Returns
        -------
        dict
            Ping result.
        """
        try:
            self.env.logger.info(f"Pinging Cam{self.cam_id}...")
            self.env.controller.ping(self.cam_id)
            return self._generate_response("success", f"Pinged Cam{self.cam_id}.")
        except Exception as e:
            self.env.logger.error(f"Ping failed: {e}")
            return self._generate_response("error", f"Ping failed: {e}")

    def cam_params(self) -> Dict[str, Any]:
        """
        Retrieve camera parameters for the finder camera.

        Returns
        -------
        dict
            Parameter information.
        """
        try:
            self.env.logger.info(f"Retrieving parameters for Cam{self.cam_id}...")
            param = self.env.controller.cam_params(self.cam_id)
            return self._generate_response("success", f"Cam{self.cam_id}: {param}")
        except Exception as e:
            self.env.logger.error(f"Parameter retrieval failed: {e}")
            return self._generate_response("error", f"Parameter retrieval failed: {e}")

    def shutdown(self) -> None:
        """
        Shutdown the environment and close the camera connection.
        """
        self.env.shutdown()
        self.env.logger.info("FinderGFAActions shutdown complete.")
