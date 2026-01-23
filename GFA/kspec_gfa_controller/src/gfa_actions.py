#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import asyncio
import shutil
from datetime import datetime
from typing import Union, List, Dict, Any, Optional
from pathlib import Path
import re
import glob

from .gfa_logger import GFALogger
from .gfa_environment import create_environment, GFAEnvironment

# NOTE: pointing에서는 get_crvals_from_images를 쓰고 있으니 유지
from .gfa_getcrval import get_crvals_from_images, get_crval_from_image  # noqa: F401

logger = GFALogger(__file__)


def _make_clean_subprocess_env() -> dict:
    """
    외부 프로세스(solve-field 등)가 현재 프로세스의 env를 상속받아 깨지는 문제 방지용.
    - PYTHONHOME/PYTHONPATH 제거
    - 현재 실행 중인 파이썬 bin 경로를 PATH 최우선으로 배치 (conda/venv 대응)
    """
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)

    pybin = os.path.dirname(os.path.realpath(os.sys.executable))
    env["PATH"] = pybin + os.pathsep + env.get("PATH", "")
    return env


class GFAActions:
    """
    GFA actions: grab, guiding, pointing, camera status utilities.
    """

    def __init__(self, env: Optional[GFAEnvironment] = None):
        if env is None:
            env = create_environment(role="plate")
        self.env = env

    def _generate_response(self, status: str, message: str, **kwargs) -> dict:
        response = {"status": status, "message": message}
        response.update(kwargs)
        return response

    def _apply_clean_env_to_astrometry(self) -> None:
        """
        Ensure solve-field runs with a clean subprocess env (conda/venv collisions 방지).
        """
        clean_env = _make_clean_subprocess_env()
        if hasattr(self.env, "astrometry") and hasattr(self.env.astrometry, "set_subprocess_env"):
            self.env.astrometry.set_subprocess_env(clean_env)

    def _ensure_astrometry_outputs_ready(self) -> List[str]:
        """
        procimg 의존성 제거:
        - astrometry dir에 astro_*.fits가 있으면 그대로 사용
        - 없으면 raw dir의 FITS로 astrometry 실행 후 astro_*.fits 생성
        반환: astro_*.fits full paths
        """
        if not hasattr(self.env, "astrometry"):
            raise RuntimeError("env.astrometry is not configured")

        # 새 클래스에 ensure_astrometry_ready가 있으면 그걸 우선 사용
        if hasattr(self.env.astrometry, "ensure_astrometry_ready"):
            return self.env.astrometry.ensure_astrometry_ready()

        # (fallback) 구버전: preproc만 있는 경우에도 동작하도록
        base_dir = os.path.dirname(os.path.abspath(__file__))
        astro_dir = getattr(self.env.astrometry, "final_astrometry_dir", None)
        raw_dir = getattr(self.env.astrometry, "dir_path", None)
        if astro_dir is None:
            astro_dir = os.path.join(base_dir, "img", "astroimg")
        if raw_dir is None:
            raw_dir = os.path.join(base_dir, "img", "raw")

        astro_files = sorted(glob.glob(os.path.join(astro_dir, "astro_*.fits")))
        if astro_files:
            return astro_files

        # 없으면 preproc 수행
        if not hasattr(self.env.astrometry, "preproc"):
            raise RuntimeError("env.astrometry has no preproc()/ensure_astrometry_ready()")

        self.env.astrometry.preproc()

        astro_files = sorted(glob.glob(os.path.join(astro_dir, "astro_*.fits")))
        if not astro_files:
            raise RuntimeError(f"Astrometry expected outputs not found in {astro_dir} (astro_*.fits)")
        return astro_files

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
        dec: str = None,
        path: str = None
    ) -> Dict[str, Any]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")
        if path:
            grab_save_path = path
        else:
            grab_save_path = os.path.join(base_dir, "img", "grab", date_str)
        os.makedirs(grab_save_path, exist_ok=True)

        timeout_cameras: List[int] = []

        self.env.logger.info("Open all plate cameras...")
        await self.env.controller.open_all_cameras()

        try:
            if isinstance(CamNum, int) and CamNum != 0:
                res = await self.env.controller.grabone(
                    CamNum=CamNum,
                    ExpTime=ExpTime,
                    Binning=Binning,
                    output_dir=grab_save_path,
                    packet_size=packet_size,
                    ipd=cam_ipd,
                    ftd_base=cam_ftd_base,
                    ra=ra,
                    dec=dec,
                )
                timeout_cameras.extend(res)

                msg = f"Image grabbed from camera {CamNum}."
                if timeout_cameras:
                    msg += f" Timeout: {timeout_cameras[0]}"
                return self._generate_response("success", msg)

            if isinstance(CamNum, int) and CamNum == 0:
                tasks = [
                    self.env.controller.grabone(
                        CamNum=cam_id,
                        ExpTime=ExpTime,
                        Binning=Binning,
                        output_dir=grab_save_path,
                        packet_size=packet_size,
                        ipd=cam_ipd,
                        ftd_base=cam_ftd_base,
                        ra=ra,
                        dec=dec,
                    )
                    for cam_id in self.env.camera_ids
                ]
                results = await asyncio.gather(*tasks)
                for r in results:
                    timeout_cameras.extend(r)

                msg = "Images grabbed from all cameras."
                if timeout_cameras:
                    msg += f" Timeout: {timeout_cameras}"
                return self._generate_response("success", msg)

            if isinstance(CamNum, list):
                tasks = [
                    self.env.controller.grabone(
                        CamNum=cam_id,
                        ExpTime=ExpTime,
                        Binning=Binning,
                        output_dir=grab_save_path,
                        packet_size=packet_size,
                        ipd=cam_ipd,
                        ftd_base=cam_ftd_base,
                        ra=ra,
                        dec=dec,
                    )
                    for cam_id in CamNum
                ]
                results = await asyncio.gather(*tasks)
                for r in results:
                    timeout_cameras.extend(r)

                msg = f"Images grabbed from cameras {CamNum}."
                if timeout_cameras:
                    msg += f" Timeout: {timeout_cameras}"
                return self._generate_response("success", msg)

            raise ValueError(f"Invalid CamNum: {CamNum}")

        except Exception as e:
            self.env.logger.error(f"Grab failed: {e}")
            return self._generate_response("error", f"Grab failed: {e}")

        finally:
            self.env.logger.info("Close all plate cameras...")
            try:
                await self.env.controller.close_all_cameras()
            except Exception as e:
                self.env.logger.warning(f"close_all_cameras failed: {e}")

    async def guiding(
        self,
        ExpTime: float = 1.0,
        save: bool = True,
        ra: str = None,
        dec: str = None,
    ) -> Dict[str, Any]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")

        raw_save_path = os.path.join(base_dir, "img", "raw")
        grab_save_path = os.path.join(base_dir, "img", "grab", date_str)
        os.makedirs(raw_save_path, exist_ok=True)

        try:
            self.env.logger.info("Starting guiding sequence...")

            # (선택) 여기에서 실제 grab을 수행하도록 하려면 주석 해제
            await self.env.controller.open_all_cameras()
            try:
                await self.env.controller.grab(
                    0, ExpTime, 4,
                    output_dir=raw_save_path,
                    ra=ra, dec=dec
                )
                pass
            finally:
                try:
                    await self.env.controller.close_all_cameras()
                except Exception as e:
                    self.env.logger.warning(f"close_all_cameras failed: {e}")

            if save:
                os.makedirs(grab_save_path, exist_ok=True)
                for fname in os.listdir(raw_save_path):
                    src = os.path.join(raw_save_path, fname)
                    dst = os.path.join(grab_save_path, fname)
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)

            # --- astrometry: clean env 적용 ---
            self._apply_clean_env_to_astrometry()

            # --- procimg 없이: astro dir 있으면 사용 / 없으면 생성 ---
            self.env.logger.info("Ensuring astrometry outputs are ready (no procimg dependency)...")
            astro_files = self._ensure_astrometry_outputs_ready()
            self.env.logger.info(f"Astrometry inputs ready: {len(astro_files)} files.")

            # IMPORTANT:
            # guider.exe_cal() 내부가 procimg를 보던 로직이었다면, 이제는
            # final_astrometry_dir(astro_*.fits)를 읽도록 guider 쪽도 수정이 필요함.
            # 여기서는 최소 변경으로 'astrometry dir가 준비되어 있다'는 것만 보장.
            self.env.logger.info("Executing guider offset calculation...")
            fdx, fdy, fwhm = self.env.guider.exe_cal()

            self.env.astrometry.clear_raw_files()

            try:
                fwhm_val = float(fwhm)
            except Exception:
                fwhm_val = 0.0

            msg = f"Offsets: fdx={fdx}, fdy={fdy}, FWHM={fwhm_val} arcsec"
            return self._generate_response(
                "success", msg, fdx=fdx, fdy=fdy, fwhm=fwhm_val, astrometry_files=[os.path.basename(p) for p in astro_files]
            )

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
        save: bool = True,
    ) -> Dict[str, Any]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")

        grab_save_path = os.path.join(base_dir, "img", "grab", date_str)

        pointing_raw_path = (
            os.path.join(base_dir, "img", "pointing_raw", date_str)
            if save_by_date else
            os.path.join(base_dir, "img", "pointing_raw")
        )
        os.makedirs(pointing_raw_path, exist_ok=True)

        try:
            self.env.logger.info("Starting pointing sequence...")
            self.env.logger.info(f"Target RA/DEC: {ra}, {dec}")

            if clear_dir:
                for fn in os.listdir(pointing_raw_path):
                    fp = os.path.join(pointing_raw_path, fn)
                    if os.path.isfile(fp):
                        os.remove(fp)

            # --- camera open/grab/close ---
            await self.env.controller.open_all_cameras()
            try:
                await self.env.controller.grab(
                    CamNum, ExpTime, Binning,
                    output_dir=pointing_raw_path,
                    ra=ra, dec=dec
                )
            finally:
                try:
                    await self.env.controller.close_all_cameras()
                except Exception as e:
                    self.env.logger.warning(f"close_all_cameras failed: {e}")

            if save:
                os.makedirs(grab_save_path, exist_ok=True)
                for fname in os.listdir(pointing_raw_path):
                    src = os.path.join(pointing_raw_path, fname)
                    dst = os.path.join(grab_save_path, fname)
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)

            images = [
                os.path.join(pointing_raw_path, fn)
                for fn in sorted(os.listdir(pointing_raw_path))
                if fn.lower().endswith((".fits", ".fit", ".fts"))
            ]
            if not images:
                msg = f"No FITS images found in {pointing_raw_path}"
                self.env.logger.error(msg)
                return self._generate_response(
                    "error", msg, images=[], crval1=[], crval2=[]
                )

            # --- clean env 적용 ---
            self._apply_clean_env_to_astrometry()

            self.env.logger.info(
                f"Solving astrometry for CRVALs (max_workers={max_workers})..."
            )

            raw_dir = Path(pointing_raw_path)
            image_list = sorted(raw_dir.glob("*.fits"))
            image_names = [p.name for p in image_list]

            crval1_list, crval2_list = get_crvals_from_images(
                image_list,
                max_workers=max_workers,
            )

            msg = f"Pointing completed. Computed CRVALs for {len(image_list)} images."

            return self._generate_response(
                "success",
                msg,
                images=image_names,
                crval1=crval1_list,
                crval2=crval2_list,
            )

        except Exception as e:
            self.env.logger.error(f"Pointing failed: {str(e)}")
            return self._generate_response("error", f"Pointing failed: {str(e)}")

    def status(self) -> Dict[str, Any]:
        try:
            status_info = self.env.controller.status()
            return self._generate_response("success", status_info)
        except Exception as e:
            return self._generate_response("error", f"Status query failed: {e}")

    def ping(self, CamNum: int = 0) -> Dict[str, Any]:
        try:
            if CamNum == 0:
                for cam_id in self.env.camera_ids:
                    self.env.controller.ping(cam_id)
                return self._generate_response("success", "Pinged all cameras.")
            else:
                self.env.controller.ping(CamNum)
                return self._generate_response("success", f"Pinged Cam{CamNum}.")
        except Exception as e:
            return self._generate_response("error", f"Ping failed: {e}")

    def cam_params(self, CamNum: int = 0) -> Dict[str, Any]:
        try:
            if CamNum == 0:
                messages = []
                for cam_id in self.env.camera_ids:
                    param = self.env.controller.cam_params(cam_id)
                    messages.append(f"Cam{cam_id}: {param}")
                return self._generate_response("success", "\n".join(messages))
            else:
                param = self.env.controller.cam_params(CamNum)
                return self._generate_response("success", f"Cam{CamNum}: {param}")
        except Exception as e:
            return self._generate_response("error", f"Parameter fetch failed: {e}")

    def shutdown(self) -> None:
        self.env.shutdown()
        self.env.logger.info("GFAActions shutdown complete.")
