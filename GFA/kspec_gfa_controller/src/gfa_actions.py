#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import asyncio
import shutil
from datetime import datetime
from typing import Union, List, Dict, Any, Optional
from pathlib import Path
import re

from .gfa_logger import GFALogger
from .gfa_environment import create_environment, GFAEnvironment
from .gfa_getcrval import get_crvals_from_images, get_crval_from_image

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
    ) -> Dict[str, Any]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")
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
        save: bool = False,
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

            await self.env.controller.open_all_cameras()
            try:
            # output_dir는 실제 raw_save_path로 통일하는 걸 권장
                await self.env.controller.grab(
                    0, ExpTime, 4,
                    output_dir="./img/raw",
                    ra=ra, dec=dec
                )
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

            # --- astrometry: clean env 적용 (해결책 핵심) ---
            clean_env = _make_clean_subprocess_env()
            if hasattr(self.env.astrometry, "set_subprocess_env"):
                self.env.astrometry.set_subprocess_env(clean_env)

            self.env.logger.info("Running astrometry preprocessing...")
            self.env.astrometry.preproc()

            self.env.logger.info("Executing guider offset calculation...")
            fdx, fdy, fwhm = self.env.guider.exe_cal()
            
            self.env.astrometry.clear_raw_and_processed_files()

            try:
                fwhm_val = float(fwhm)
            except Exception:
                fwhm_val = 0.0

            msg = f"Offsets: fdx={fdx}, fdy={fdy}, FWHM={fwhm_val} arcsec"
            return self._generate_response(
                "success", msg, fdx=fdx, fdy=fdy, fwhm=fwhm_val
            )

        except Exception as e:
            self.env.logger.error(f"Guiding failed: {str(e)}")
            return self._generate_response("error", f"Guiding failed: {str(e)}")


    async def guiding_from_saved_grab(
        self,
        *,
        grab_save_path: str = None,
        save: bool = False,
        ra: str = None,
        dec: str = None,
        num_images: int = 6,
    ) -> Dict[str, Any]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")

        raw_save_path = os.path.join(base_dir, "img", "raw")
        default_grab_save_path = os.path.join(base_dir, "img", "grab", date_str)
        grab_save_path = grab_save_path or default_grab_save_path
        os.makedirs(raw_save_path, exist_ok=True)

        # 예: D20260116_T124224_40103651_exp3s.fits
        # key = "20260116_124224"
        ts_re = re.compile(r"D(\d{8})_T(\d{6})_", re.IGNORECASE)

        try:
            self.env.logger.info("Starting guiding_from_saved_grab (same T-set) ...")
            self.env.logger.info(f"Using grab_save_path: {grab_save_path}")

            if not os.path.isdir(grab_save_path):
                msg = f"grab_save_path does not exist or is not a directory: {grab_save_path}"
                self.env.logger.error(msg)
                return self._generate_response("error", msg)

            # 1) 세트(T)가 같은 것끼리 그룹화
            groups = {}  # key -> [fullpath...]
            unparsable = []

            for fn in os.listdir(grab_save_path):
                fp = os.path.join(grab_save_path, fn)
                if not os.path.isfile(fp):
                    continue
                if not fn.lower().endswith((".fits", ".fit", ".fts")):
                    continue

                m = ts_re.search(fn)
                if not m:
                    unparsable.append(fn)
                    continue

                key = f"{m.group(1)}_{m.group(2)}"  # YYYYMMDD_HHMMSS
                groups.setdefault(key, []).append(fp)

            if not groups:
                msg = "No FITS images with parsable DYYYYMMDD_Txxxxxx pattern found."
                self.env.logger.error(msg)
                return self._generate_response("error", msg, unparsable=unparsable[:20])

            # 2) 가장 최근 key 선택 (문자열 정렬이 시간 정렬과 동일)
            latest_key = sorted(groups.keys())[-1]
            latest_files = groups[latest_key]

            if len(latest_files) < num_images:
                msg = f"Latest set {latest_key} has only {len(latest_files)} files (<{num_images})."
                self.env.logger.error(msg)
                return self._generate_response(
                    "error",
                    msg,
                    latest_key=latest_key,
                    latest_count=len(latest_files),
                    latest_files=[os.path.basename(p) for p in sorted(latest_files)],
                )

            # 3) 최신 세트 안에서 6개 선택
            # 세트 내 파일은 이름으로 정렬하면 (4010...) 순서가 안정적이라 재현성 좋음
            latest_files_sorted = sorted(latest_files)
            selected = latest_files_sorted[:num_images]

            self.env.logger.info(
                f"Selected set key={latest_key}, files=" +
                ", ".join(os.path.basename(p) for p in selected)
            )

            # 4) raw 폴더 정리(파일/링크만) 후 복사
            for name in os.listdir(raw_save_path):
                p = os.path.join(raw_save_path, name)
                if os.path.isfile(p) or os.path.islink(p):
                    try:
                        os.remove(p)
                    except Exception as e:
                        self.env.logger.warning(f"Failed to remove raw file {p}: {e}")

            copied_names = []
            for src in selected:
                dst = os.path.join(raw_save_path, os.path.basename(src))
                shutil.copy2(src, dst)
                copied_names.append(os.path.basename(src))

            if save:
                # 이미 grab_save_path가 존재/저장된 상태라 특별 동작 없음
                pass

            # --- guiding()와 동일: clean env 적용 ---
            clean_env = _make_clean_subprocess_env()
            if hasattr(self.env.astrometry, "set_subprocess_env"):
                self.env.astrometry.set_subprocess_env(clean_env)

            # 5) preproc -> exe_cal
            self.env.logger.info("Running astrometry preprocessing...")
            self.env.astrometry.preproc()

            self.env.logger.info("Executing guider offset calculation...")
            fdx, fdy, fwhm = self.env.guider.exe_cal()

            try:
                fwhm_val = float(fwhm)
            except Exception:
                fwhm_val = 0.0

            msg = f"Offsets: fdx={fdx}, fdy={fdy}, FWHM={fwhm_val} arcsec"
            return self._generate_response(
                "success",
                msg,
                fdx=fdx,
                fdy=fdy,
                fwhm=fwhm_val,
                grabbed_from=grab_save_path,
                selected_set_key=latest_key,
                selected_images=copied_names,
            )

        except Exception as e:
            self.env.logger.error(f"guiding_from_saved_grab failed: {str(e)}")
            return self._generate_response("error", f"guiding_from_saved_grab failed: {str(e)}")

        finally:
            # 요청: gfa_astrometry class 함수 실행
            try:
                if hasattr(self.env.astrometry, "Clear_raw_and_processed_files"):
                    self.env.astrometry.Clear_raw_and_processed_files()
                else:
                    self.env.logger.warning("env.astrometry has no Clear_raw_and_processed_files()")
            except Exception as e:
                self.env.logger.warning(f"Clear_raw_and_processed_files failed: {e}")


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
        base_dir = os.path.dirname(os.path.abspath(__file__))
        date_str = datetime.now().strftime("%Y-%m-%d")

        pointing_raw_path = (
            os.path.join(base_dir, "img", "pointing_raw", date_str)
            if save_by_date else
            os.path.join(base_dir, "img", "pointing_raw")
        )
        os.makedirs(pointing_raw_path, exist_ok=True)

        try:
            self.env.logger.info("Starting pointing sequence...")
            self.env.logger.info(f"Target RA/DEC: {ra}, {dec}")

            #if clear_dir:
            #    for fn in os.listdir(pointing_raw_path):
            #        fp = os.path.join(pointing_raw_path, fn)
            #        if os.path.isfile(fp):
            #            os.remove(fp)

            # --- camera open/grab/close ---
            await self.env.controller.open_all_cameras()
            try:
                await self.env.controller.grab(
                    CamNum, ExpTime, Binning,
                    output_dir="./test_raw",
                    ra=ra, dec=dec
                )
            finally:
                try:
                    await self.env.controller.close_all_cameras()
                except Exception as e:
                    self.env.logger.warning(f"close_all_cameras failed: {e}")

            #images = [
            #    os.path.join(pointing_raw_path, fn)
            #    for fn in sorted(os.listdir(pointing_raw_path))
            #    if fn.lower().endswith((".fits", ".fit", ".fts"))
            #]
            #if not images:
            #    msg = f"No FITS images found in {pointing_raw_path}"
            #    self.env.logger.error(msg)
            #    return self._generate_response(
            #        "error", msg, images=[], crval1=[], crval2=[]
            #    )

            # --- apply the same "clean env" fix BEFORE any solve-field runs ---
            #clean_env = _make_clean_subprocess_env()
            #if hasattr(self.env.astrometry, "set_subprocess_env"):
            #    self.env.astrometry.set_subprocess_env(clean_env)

            #self.env.logger.info(f"Found {len(images)} images for pointing.")
            self.env.logger.info(
                f"Solving astrometry for CRVALs (max_workers={max_workers})..."
            )

            raw_dir = Path("/home/GAFOL/work/kspec_gfa_controller/src/kspec_gfa_controller/img/raw")

            image_list = sorted(raw_dir.glob("*.fits"))
            image_names = [p.name for p in image_list]   # ✅ 파일명만

            crval1_list, crval2_list = get_crvals_from_images(
                image_list,
                max_workers=max_workers,
            )
            
            msg = f"Pointing completed. Computed CRVALs for {len(image_list)} images."

            return self._generate_response(
                "success",
                msg,
                images=image_names,      # ✅ 파일명 리스트로 반환
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
