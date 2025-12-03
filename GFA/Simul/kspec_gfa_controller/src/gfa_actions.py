#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: gfa_actions.py

import os
import asyncio
import shutil
import time
from datetime import datetime
from typing import Union, List, Dict, Any, Optional

from .gfa_logger import GFALogger
from .gfa_environment import create_environment, GFAEnvironment

logger = GFALogger(__file__)

###############################################################################
# GFA Actions Class
###############################################################################


class GFAActions:
    """
    A class to handle GFA actions such as grabbing images, guiding,
    and controlling the plate camera array (Cam1–6).
    """

    def __init__(self, env: Optional[GFAEnvironment] = None):
        """
        Initialize GFAActions with a GFA environment.

        Parameters
        ----------
        env : GFAEnvironment, optional
            The environment object for controlling GFA system.
        """
        if env is None:
            env = create_environment(role="plate")
        self.env = env
        self.file_index=0

    def _generate_response(self, status: str, message: str, **kwargs) -> dict:
        """
        Generate a structured response dictionary.

        Parameters
        ----------
        status : str
            Status string, e.g., "success" or "error".
        message : str
            Descriptive message.
        kwargs : dict
            Additional key-value pairs to include.

        Returns
        -------
        dict
            Response dictionary.
        """
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
        cam_ipd: int = 367318,
        cam_ftd_base: int = 0,
    ) -> Dict[str, Any]:
        """
        Grab images from one or more plate cameras.

        Parameters
        ----------
        CamNum : int or List[int], optional
            Target camera(s). If 0, grabs from all cameras.
        ExpTime : float, optional
            Exposure time in seconds.
        Binning : int, optional
            Binning factor.
        packet_size : int, optional
            GigE packet size.
        cam_ipd : int, optional
            Inter-packet delay.
        cam_ftd_base : int, optional
            Frame transmission delay base.

        Returns
        -------
        dict
            Result summary and timeout information.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")
        grab_save_path = os.path.join(base_dir, "img", "grab", date_str)
        self.env.logger.info(f"Image save path: {grab_save_path}")

        timeout_cameras: List[int] = []

        try:
            if isinstance(CamNum, int) and CamNum != 0:
                self.env.logger.info(
                    f"Grabbing from camera {CamNum} (ExpTime={ExpTime}, Binning={Binning})"
                )
#                result = await self.env.controller.grabone(
#                    CamNum=CamNum,
#                    ExpTime=ExpTime,
#                    Binning=Binning,
#                    output_dir=grab_save_path,
#                    packet_size=packet_size,
#                    ipd=cam_ipd,
#                    ftd_base=cam_ftd_base,
#                )
#                timeout_cameras.extend(result)
                msg = f"Image grabbed from camera {CamNum}."
#                if timeout_cameras:
#                    msg += f" Timeout: {timeout_cameras[0]}"
                return self._generate_response("success", msg)

            if isinstance(CamNum, int) and CamNum == 0:
                self.env.logger.info("Grabbing from all plate cameras...")
                for cam_id in self.env.camera_ids:
                    self.env.logger.info(
                        f"Grabbing from Cam{cam_id} (ExpTime={ExpTime}, Binning={Binning})"
                    )
#                    res = await self.env.controller.grabone(
#                        CamNum=cam_id,
#                        ExpTime=ExpTime,
#                        Binning=Binning,
#                        output_dir=grab_save_path,
#                        packet_size=packet_size,
#                        ipd=cam_ipd,
#                        ftd_base=cam_ftd_base,
#                    )
#                    timeout_cameras.extend(res)

                msg = "Images grabbed from all cameras."
                if timeout_cameras:
                    msg += f" Timeout: {timeout_cameras}"
                return self._generate_response("success", msg)

            if isinstance(CamNum, list):
                self.env.logger.info(
                    f"Grabbing from cameras {CamNum} (ExpTime={ExpTime}, Binning={Binning})"
                )
#                for num in CamNum:
#                    res = await self.env.controller.grabone(
#                        CamNum=num,
#                        ExpTime=ExpTime,
#                        Binning=Binning,
#                        output_dir=grab_save_path,
#                        packet_size=packet_size,
#                        ipd=cam_ipd,
#                        ftd_base=cam_ftd_base,
#                    )
#                    timeout_cameras.extend(res)

                msg = f"Images grabbed from cameras {CamNum}."
                if timeout_cameras:
                    msg += f" Timeout: {timeout_cameras}"
                return self._generate_response("success", msg)

            raise ValueError(f"Invalid CamNum: {CamNum}")

        except Exception as e:
            self.env.logger.error(f"Grab failed: {e}")
            return self._generate_response(
                "error", f"Grab failed: {e} (CamNum={CamNum}, ExpTime={ExpTime})"
            )

    async def guiding(self, ExpTime: float = 1.0, save: bool = False) -> Dict[str, Any]:
        """
        Execute guiding procedure using all plate cameras.

        Parameters
        ----------
        ExpTime : float, optional
            Exposure time in seconds.
        save : bool, optional
            Whether to also save images to grab directory.

        Returns
        -------
        dict
            Result with measured guider offsets and FWHM.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")

        raw_save_path = os.path.join(base_dir, "img", "raw")
        grab_save_path = os.path.join(base_dir, "img", "grab", date_str)
#        src_dir = os.path.join(base_dir, "img", "GFA_data")

        try:
            self.env.logger.info("Starting guiding sequence...")

            os.makedirs(raw_save_path, exist_ok=True)
            self.env.logger.info("Grabbing raw image...")
#            self.env.controller.grab(0, ExpTime, 4, output_dir=raw_save_path)

#            self.copy_files(src_dir,raw_save_path)
            await asyncio.sleep(5)

            print(f'Save index is {save}')

            if save:
                print("Fits files saved")
                os.makedirs(grab_save_path, exist_ok=True)
                for fname in os.listdir(raw_save_path):
                    src = os.path.join(raw_save_path, fname)
                    dst = os.path.join(grab_save_path, fname)
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)
                self.env.logger.info(f"Images also copied to: {grab_save_path}")

            self.env.logger.info("Running astrometry preprocessing...")
#            self.env.astrometry.preproc()

            self.env.logger.info("Executing guider offset calculation...")
#            fdx, fdy, fwhm = self.env.guider.exe_cal()

            self.env.logger.info("Clearing temp astrometry data...")
            self.env.astrometry.clear_raw_and_processed_files()

            fdx=0.022
            fdy=-0.045
            fwhm=1.21

            msg = f"Offsets: fdx={fdx}, fdy={fdy}, FWHM={fwhm:.5f} arcsec."
            return self._generate_response("success", msg, fdx=fdx, fdy=fdy, fwhm=fwhm)

        except Exception as e:
            self.env.logger.error(f"Guiding failed: {e}")
            return self._generate_response("error", f"Guiding failed: {e}")


    def copy_files(self,src_dir,dest_dir):
        print(f'file index is {self.file_index}')
        prefix='KMTN'
        dates=['20230905T094050.0001','20230905T094259.0001','20230905T094503.0001']
#        dates=['20230905T094503.0001','20230905T094259.0001','20230905T094050.0001']
        filename1=prefix+'ge.'+dates[self.file_index]+'.fits'
        filename2=prefix+'gn.'+dates[self.file_index]+'.fits'
        filename3=prefix+'gs.'+dates[self.file_index]+'.fits'
#        filename4=prefix+'gw.'+dates[self.file_index]+'.fits'
        src_path1=os.path.join(src_dir,filename1)
        src_path2=os.path.join(src_dir,filename2)
        src_path3=os.path.join(src_dir,filename3)
#        src_path4=os.path.join(src_dir,filename4)
        dest_path=os.path.join(dest_dir)

        print(f'{filename1} copy')
        shutil.copy(src_path1,dest_path)
        print(f'{filename2} copy')
        shutil.copy(src_path2,dest_path)
        print(f'{filename3} copy')
        shutil.copy(src_path3,dest_path)
#        print(f'{filename4} copy')
#        shutil.copy(src_path4,dest_path)
        print('Fits image copyed')

        self.file_index +=1



    def status(self) -> Dict[str, Any]:
        """
        Retrieve current status of all plate cameras.

        Returns
        -------
        dict
            Status report from controller.
        """
        try:
            self.env.logger.info("Querying camera statuses...")
#            status_info = self.env.controller.status()
            time.sleep(5)
            return self._generate_response("success", 'GFA cameras are ready')
        except Exception as e:
            self.env.logger.error(f"Status query failed: {e}")
            return self._generate_response("error", f"Status query failed: {e}")

    def ping(self, CamNum: int = 0) -> Dict[str, Any]:
        """
        Ping specific or all plate cameras.

        Parameters
        ----------
        CamNum : int, optional
            If 0, ping all cameras. Else ping specific CamNum.

        Returns
        -------
        dict
            Ping result message.
        """
        try:
            if CamNum == 0:
                self.env.logger.info("Pinging all cameras...")
#                for cam_id in self.env.camera_ids:
#                    self.env.controller.ping(cam_id)
                return self._generate_response("success", "Pinged all cameras.")
            else:
                self.env.logger.info(f"Pinging Cam{CamNum}...")
#                self.env.controller.ping(CamNum)
                return self._generate_response("success", f"Pinged Cam{CamNum}.")
        except Exception as e:
            self.env.logger.error(f"Ping failed: {e}")
            return self._generate_response("error", f"Ping failed: {e}")

    def cam_params(self, CamNum: int = 0) -> Dict[str, Any]:
        """
        Retrieve camera parameters.

        Parameters
        ----------
        CamNum : int, optional
            If 0, retrieve all cameras. Else only for CamNum.

        Returns
        -------
        dict
            Parameter information.
        """
        try:
            if CamNum == 0:
                self.env.logger.info("Fetching parameters for all cameras...")
                messages = []
#                for cam_id in self.env.camera_ids:
#                    param = self.env.controller.cam_params(cam_id)
#                    messages.append(f"Cam{cam_id}: {param}")
#                return self._generate_response("success", "\n".join(messages))
            else:
                self.env.logger.info(f"Fetching parameters for Cam{CamNum}...")
#                param = self.env.controller.cam_params(CamNum)
#                return self._generate_response("success", f"Cam{CamNum}: {param}")
        except Exception as e:
            self.env.logger.error(f"Parameter fetch failed: {e}")
            return self._generate_response("error", f"Parameter fetch failed: {e}")

    def shutdown(self) -> None:
        """
        Shutdown and release resources.
        """
        self.env.shutdown()
        self.env.logger.info("GFAActions shutdown complete.")
