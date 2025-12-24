#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: gfa_actions.py

import os
import asyncio
import shutil
from datetime import datetime
from typing import Union, List, Dict, Any, Optional

from .gfa_logger import GFALogger
from .gfa_environment import create_environment, GFAEnvironment
from .gfa_getcrval import get_crvals_from_images

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
        packet_size: int = None,
        cam_ipd: int = None,
        cam_ftd_base: int = 0,
        ra: str = None,
        dec: str = None
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
            GigE packet size. If None, use cams.json per camera.
        cam_ipd : int, optional
            Inter-packet delay. If None, use cams.json per camera.
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
#                    ra=ra,
#                    dec=dec
#                )
#                timeout_cameras.extend(result)
                msg = f"Image grabbed from camera {CamNum}."
#                if timeout_cameras:
#                    msg += f" Timeout: {timeout_cameras[0]}"
                return self._generate_response("success", msg)

            if isinstance(CamNum, int) and CamNum == 0:
                self.env.logger.info("Grabbing from all plate cameras...")

                tasks = []
                for cam_id in self.env.camera_ids:
                    self.env.logger.info(
                        f"Grabbing from Cam{cam_id} (ExpTime={ExpTime}, Binning={Binning})"
                    )
#                    task = self.env.controller.grabone(
#                        CamNum=cam_id,
#                        ExpTime=ExpTime,
#                        Binning=Binning,
#                        output_dir=grab_save_path,
#                        packet_size=packet_size,
#                        ipd=cam_ipd,
#                        ftd_base=cam_ftd_base,
#                        ra=ra,
#                        dec=dec
#                    )
#                    tasks.append(task)

                # Run all camera grabs concurrently
#                results = await asyncio.gather(*tasks)
                timeout_cameras = []
#                for res in results:
#                    timeout_cameras.extend(res)

                msg = "Images grabbed from all cameras."
                if timeout_cameras:
                    msg += f" Timeout: {timeout_cameras}"
                return self._generate_response("success", msg)

            if isinstance(CamNum, list):
                self.env.logger.info(
                    f"Grabbing from cameras {CamNum} (ExpTime={ExpTime}, Binning={Binning})"
                )
                tasks = []
                for cam_id in CamNum:
                    self.env.logger.info(
                        f"Grabbing from Cam{cam_id} (ExpTime={ExpTime}, Binning={Binning})"
                    )
#                    task = self.env.controller.grabone(
#                        CamNum=cam_id,
#                        ExpTime=ExpTime,
#                        Binning=Binning,
#                        output_dir=grab_save_path,
#                        packet_size=packet_size,
#                        ipd=cam_ipd,
#                        ftd_base=cam_ftd_base,
#                        ra=ra,
#                        dec=dec
#                    )
#                    tasks.append(task)

                # Run all camera grabs concurrently
#                results = await asyncio.gather(*tasks)
                timeout_cameras = []
#                for res in results:
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


    async def guiding(self, ExpTime: float = 1.0, save: bool = False, ra: str = None, dec: str = None) -> Dict[str, Any]:
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

        try:
            self.env.logger.info("Starting guiding sequence...")

            os.makedirs(raw_save_path, exist_ok=True)
            self.env.logger.info("Grabbing raw image...")
#            self.env.controller.grab(0, ExpTime, 4, output_dir=raw_save_path, ra=ra, dec=dec)

            print(save)

            if save:
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
#            self.env.astrometry.clear_raw_and_processed_files()
            
#            try:
#                fwhm_val = float(fwhm)
#            except ValueError:
#                fwhm_val = 0.0  # 또는 예외 처리

            fdx=0.022
            fdy=-0.045
            fwhm_val=1.21

            msg = f"Offsets: fdx={fdx}, fdy={fdy}, FWHM={fwhm_val} arcsec"
            return self._generate_response("success", msg, fdx=fdx, fdy=fdy, fwhm=fwhm_val)

        except Exception as e:
            self.env.logger.error(f"Guiding failed: {str(e)}")
            return self._generate_response("error", f"Guiding failed: {str(e)}")

    async def pointing(
        self,
        ra: str,
        dec: str,
        ExpTime: float = 1.0,
        Binning: int = 4,
        CamNum: int = 0,
        max_workers: int = 4,
        save_by_date: bool = True,
        clear_dir: bool = True,
    ) -> Dict[str, Any]:
        """
        Pointing procedure:
        1) Grab images (CamNum=0 default) with RA/DEC hint.
        2) Save to pointing_raw directory.
        3) Read images in that directory.
        4) Run get_crvals_from_images(images) to get CRVAL1/CRVAL2 lists.

        Parameters
        ----------
        ra, dec : float
            Requested reference pointing coordinates (passed to grab and written in header).
        ExpTime : float
            Exposure time.
        Binning : int
            Binning factor.
        CamNum : int
            Camera number (0 = all cameras).
        max_workers : int
            Parallel workers for solve-field runs.
        save_by_date : bool
            If True, save under img/pointing_raw/YYYY-MM-DD/.
        clear_dir : bool
            If True, delete existing files in pointing_raw directory before grabbing.

        Returns
        -------
        dict
            {status, message, images, crval1, crval2}
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")

        if save_by_date:
            pointing_raw_path = os.path.join(base_dir, "img", "pointing_raw", date_str)
        else:
            pointing_raw_path = os.path.join(base_dir, "img", "pointing_raw")

        try:
            self.env.logger.info("Starting pointing sequence...")
            self.env.logger.info(f"Target RA/DEC: {ra}, {dec}")
            self.env.logger.info(f"Pointing raw save path: {pointing_raw_path}")

            os.makedirs(pointing_raw_path, exist_ok=True)

            # (선택) 디렉토리 정리: 이전 프레임이 섞이면 결과 해석이 어려워서 권장
#            if clear_dir:
#                for fn in os.listdir(pointing_raw_path):
#                    fp = os.path.join(pointing_raw_path, fn)
#                    if os.path.isfile(fp):
#                        os.remove(fp)

            # 1) Grab images -> pointing_raw 저장
            # guiding()에서처럼 controller.grab을 사용 (동기 함수인 경우가 많음)
            self.env.logger.info(f"Grabbing pointing images (CamNum={CamNum}, ExpTime={ExpTime}, Binning={Binning})...")
#            self.env.controller.grab(CamNum, ExpTime, Binning, output_dir=pointing_raw_path, ra=ra, dec=dec)

            # 2) 디렉토리의 FITS 이미지 목록 읽기
            images = []
            for fn in sorted(os.listdir(pointing_raw_path)):
                if fn.lower().endswith((".fits", ".fit", ".fts")):
                    images.append(os.path.join(pointing_raw_path, fn))

            if not images:
                msg = f"No FITS images found in {pointing_raw_path}"
                self.env.logger.error(msg)
                return self._generate_response("error", msg, images=[], crval1=[], crval2=[])

            self.env.logger.info(f"Found {len(images)} images for pointing.")

            # 3) CRVAL 계산 (병렬 가능)
            self.env.logger.info(f"Solving astrometry for CRVALs (max_workers={max_workers})...")
#            crval1_list, crval2_list = get_crvals_from_images(
#                images,
#                max_workers=max_workers,
#            )

            # (옵션) NaN 제거 후 평균/중앙값 같은 요약이 필요하면 여기서 계산 가능
            # 지금은 요청대로 리스트 그대로 반환

#            msg = f"Pointing completed. Computed CRVALs for {len(images)} images."
#            return self._generate_response(
#                "success",
#                msg,
#                images=images,
#                crval1=crval1_list,
#                crval2=crval2_list,
#            )

            ### Simulation parts ####
            msg='Pointing completed.'
            return self._generate_response(
                "success",
                msg,
                images=images,
                crval1='None',
                crval2='None',
            )
            ### Simulation parts end ###
        except Exception as e:
            self.env.logger.error(f"Pointing failed: {str(e)}")
            return self._generate_response("error", f"Pointing failed: {str(e)}")


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
#            return self._generate_response("success", status_info)
            return self._generate_response("success", "GFA status below...")
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
