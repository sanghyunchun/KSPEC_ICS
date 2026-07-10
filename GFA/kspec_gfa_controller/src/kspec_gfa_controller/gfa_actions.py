#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import asyncio
import shutil
from datetime import datetime
from typing import Union, List, Dict, Any, Optional, Tuple
from pathlib import Path
import glob

from astropy.io import fits
from collections import defaultdict

import numpy as np
from astropy.stats import sigma_clipped_stats
from photutils.detection import DAOStarFinder

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

    def __init__(
        self,
        env: Optional[GFAEnvironment] = None,
        save_root: Optional[str] = None,
    ):
        if env is None:
            env = create_environment(
                role="plate",
                save_root=save_root,
            )
        self.env = env

    def _generate_response(self, status: str, message: str, **kwargs) -> dict:
        response = {"status": status, "message": message}
        response.update(kwargs)
        return response

    def _get_save_root_and_dirs(self) -> Tuple[Path, Dict[str, Any]]:
        """
        Resolve save_root and directory config.

        Priority:
        1. self.env.save_root
        2. self.env.astrometry.inpar["paths"]["save_root"]
        3. ~/work/DATA/GFADATA/img
        """
        default_save_root = Path.home() / "work/DATA/GFADATA/img"

        dirs = {}
        save_root = getattr(self.env, "save_root", None)

        if hasattr(self.env, "astrometry") and self.env.astrometry is not None:
            inpar = getattr(self.env.astrometry, "inpar", {})
            paths_cfg = inpar.get("paths", {})
            dirs = paths_cfg.get("directories", {})

            if save_root is None:
                save_root = paths_cfg.get("save_root", None)

        save_root = Path(save_root or default_save_root).expanduser().resolve()
        save_root.mkdir(parents=True, exist_ok=True)

        return save_root, dirs

    def _debug_path_block(self, label: str, paths: Dict[str, Path]) -> None:
        """
        Log path information and test write permission.
        """
        self.env.logger.info(f"========== PATH DEBUG [{label}] ==========")

        for name, path in paths.items():
            p = Path(path).expanduser().resolve()
            self.env.logger.info(f"{name} = {p}")
            self.env.logger.info(f"type({name}) = {type(path)}")

            try:
                p.mkdir(parents=True, exist_ok=True)
                self.env.logger.info(f"{name} exists? {p.exists()}")
            except Exception as e:
                self.env.logger.error(f"{name} mkdir failed: {p}, error={e}")
                continue

            try:
                test_file = p / "debug_write_test.txt"
                with open(test_file, "w") as f:
                    f.write("debug")
                self.env.logger.info(f"{name} write test ok: {test_file}")
            except Exception as e:
                self.env.logger.error(f"{name} write test failed: {p}, error={e}")

        self.env.logger.info("=========================================")

    def _apply_clean_env_to_astrometry(self) -> None:
        """
        Ensure solve-field runs with a clean subprocess env (conda/venv collisions 방지).
        """
        clean_env = _make_clean_subprocess_env()
        if hasattr(self.env, "astrometry") and hasattr(
            self.env.astrometry, "set_subprocess_env"
        ):
            self.env.astrometry.set_subprocess_env(clean_env)

    def _ensure_astrometry_outputs_ready(self) -> List[str]:
        if not hasattr(self.env, "astrometry") or self.env.astrometry is None:
            raise RuntimeError("env.astrometry is not configured")

        if hasattr(self.env.astrometry, "ensure_astrometry_ready"):
            return self.env.astrometry.ensure_astrometry_ready()

        astro_dir = getattr(self.env.astrometry, "final_astrometry_dir", None)
        if astro_dir is None:
            raise RuntimeError("env.astrometry.final_astrometry_dir is not configured")

        astro_files = sorted(glob.glob(str(Path(astro_dir) / "astro_*.fits")))
        if astro_files:
            return astro_files

        if not hasattr(self.env.astrometry, "preproc"):
            raise RuntimeError(
                "env.astrometry has no preproc()/ensure_astrometry_ready()"
            )

        ok = self.env.astrometry.preproc()
        if not ok:
            raise RuntimeError("Astrometry preproc failed")

        astro_files = sorted(glob.glob(str(Path(astro_dir) / "astro_*.fits")))
        if not astro_files:
            raise RuntimeError(
                f"Astrometry expected outputs not found in {astro_dir} (astro_*.fits)"
            )

        return astro_files

    async def grab(
        self,
        CamNum: Union[int, List[int]] = 0,
        ExpTime: float = 1.0,
        ExpNum: int = 1,
        Binning: int = 4,
        *,
        packet_size: int = None,
        cam_ipd: int = None,
        cam_ftd_base: int = 0,
        ra: str = None,
        dec: str = None,
        path: str = None,
    ) -> Dict[str, Any]:
        save_root, dirs = self._get_save_root_and_dirs()
        date_str = datetime.now().strftime("%Y-%m-%d")

        if path:
            grab_save_path = Path(path).expanduser().resolve()
        else:
            grab_dir = dirs.get("grab_images", "grab")
            grab_save_path = save_root / grab_dir / date_str

        grab_save_path.mkdir(parents=True, exist_ok=True)

        if ExpTime > 10:
            raise ValueError(
                "ExpTime must be <= 10 seconds. Use ExpNum for longer total exposure."
            )

        if ExpNum < 1:
            raise ValueError("ExpNum must be >= 1")

        self.env.logger.info(f"[grab] save_root={save_root}")
        self.env.logger.info(f"[grab] dirs={dirs}")
        self._debug_path_block(
            "grab",
            {
                "save_root": save_root,
                "grab_save_path": grab_save_path,
            },
        )

        timeout_cameras: List[int] = []
        images_by_camera = defaultdict(list)
        serial_by_camera = {}

        self.env.logger.info("Open all plate cameras...")
        await self.env.controller.open_all_cameras()

        try:

            def _camera_list_from_camnum(camnum):
                if isinstance(camnum, int) and camnum == 0:
                    return list(self.env.camera_ids)
                if isinstance(camnum, int):
                    return [camnum]
                if isinstance(camnum, list):
                    return camnum
                raise ValueError(f"Invalid CamNum: {camnum}")

            cam_list = _camera_list_from_camnum(CamNum)

            for exp_idx in range(ExpNum):
                self.env.logger.info(
                    f"[grab] exposure {exp_idx + 1}/{ExpNum}, "
                    f"output_dir={grab_save_path}"
                )

                # Do not save individual pre-combine frames to disk.
                # Images are kept in memory and only the final FITS is saved below.
                save_intermediate = False

                tasks = [
                    self.env.controller.grabone(
                        CamNum=cam_id,
                        ExpTime=ExpTime,
                        Binning=Binning,
                        output_dir=str(grab_save_path),
                        packet_size=packet_size,
                        ipd=cam_ipd,
                        ftd_base=cam_ftd_base,
                        ra=ra,
                        dec=dec,
                        save=save_intermediate,
                    )
                    for cam_id in cam_list
                ]

                results = await asyncio.gather(*tasks)

                for result in results:
                    cam_num = result["cam_num"]

                    if result["timeout"]:
                        timeout_cameras.append(cam_num)
                        continue

                    serial_by_camera[cam_num] = result["serial"]
                    images_by_camera[cam_num].append(result["image"])

            grab_files = []
            timestamp = datetime.utcnow().strftime("D%Y%m%d_T%H%M%S")

            for cam_num, image_list in images_by_camera.items():
                if len(image_list) == 0:
                    continue

                serial = serial_by_camera.get(cam_num, f"cam{cam_num}")

                if ExpNum > 1:
                    filename = f"{timestamp}_{serial}_combined.fits"
                else:
                    filename = f"{timestamp}_{serial}_exp{int(ExpTime)}s.fits"

                self.env.controller.img_class.save_fits(
                    image_array=image_list,
                    filename=filename,
                    exptime=ExpTime * len(image_list),
                    output_directory=str(grab_save_path),
                    ra=ra,
                    dec=dec,
                )

                grab_files.append(str(grab_save_path / filename))

            if CamNum == 0:
                msg = f"Images grabbed from all cameras. ExpNum={ExpNum}."
            else:
                msg = f"Images grabbed from cameras {cam_list}. ExpNum={ExpNum}."

            if timeout_cameras:
                msg += f" Timeout: {timeout_cameras}"

            return self._generate_response(
                "success",
                msg,
                save_path=str(grab_save_path),
                grab_files=grab_files,
            )

        except Exception as e:
            self.env.logger.error(f"Grab failed: {e}")
            return self._generate_response(
                "error",
                f"Grab failed: {e}",
                save_path=str(grab_save_path),
            )

        finally:
            self.env.logger.info("Close all plate cameras...")
            try:
                await self.env.controller.close_all_cameras()
            except Exception as e:
                self.env.logger.warning(f"close_all_cameras failed: {e}")

    async def guiding(
        self,
        ExpTime: float = 1.0,
        ExpNum: int = 1,
        SaveGrabRaw: bool = True,
        ra: str = None,
        dec: str = None,
    ) -> Dict[str, Any]:
        import math

        save_root, dirs = self._get_save_root_and_dirs()
        date_str = datetime.now().strftime("%Y-%m-%d")

        raw_dir = dirs.get("raw_images", "raw")
        guiding_dir = dirs.get("guiding_save", "guiding_save")

        raw_save_path = save_root / raw_dir
        guiding_save_path = save_root / guiding_dir / date_str

        raw_save_path.mkdir(parents=True, exist_ok=True)
        guiding_save_path.mkdir(parents=True, exist_ok=True)

        self.env.logger.info(f"[guiding] save_root={save_root}")
        self.env.logger.info(f"[guiding] dirs={dirs}")
        self.env.logger.info(
            f"[guiding] SaveGrabRaw={SaveGrabRaw}, "
            f"raw_save_path={raw_save_path}, guiding_save_path={guiding_save_path}"
        )

        self._debug_path_block(
            "guiding",
            {
                "save_root": save_root,
                "raw_save_path": raw_save_path,
                "guiding_save_path": guiding_save_path,
            },
        )

        self.env.astrometry.clear_raw_files()

        try:
            self.env.logger.info("Starting guiding sequence...")

            grab_result = await self.grab(
                CamNum=0,
                ExpTime=ExpTime,
                ExpNum=ExpNum,
                Binning=4,
                path=str(raw_save_path),
                ra=ra,
                dec=dec,
            )

            if grab_result.get("status") != "success":
                return self._generate_response(
                    "error",
                    f"Guiding image grab failed: {grab_result.get('message')}",
                    raw_path=str(raw_save_path),
                    save_path=str(guiding_save_path),
                )

            if SaveGrabRaw:
                self.env.logger.info(f"Saving guiding images to {guiding_save_path}")

                exts = (".fits", ".fit", ".fts")
                pattern = str(raw_save_path / "**" / "*")
                copied = 0

                try:
                    self.env.logger.info(
                        f"raw contents: {os.listdir(str(raw_save_path))}"
                    )
                except Exception as e:
                    self.env.logger.warning(
                        f"Failed to list raw directory: {raw_save_path}, error={e}"
                    )

                for src in glob.glob(pattern, recursive=True):
                    if os.path.isfile(src) and src.lower().endswith(exts):
                        dst = guiding_save_path / os.path.basename(src)
                        self.env.logger.info(f"copying {src} to {dst}")
                        shutil.copy2(src, str(dst))
                        copied += 1

                self.env.logger.info(
                    f"[guiding] saved {copied} fits files to {guiding_save_path}"
                )

            self._apply_clean_env_to_astrometry()

            self.env.logger.info(
                "Ensuring astrometry outputs are ready (no procimg dependency)..."
            )
            astro_files = self._ensure_astrometry_outputs_ready()
            self.env.logger.info(f"Astrometry inputs ready: {len(astro_files)} files.")

            self.env.logger.info("Executing guider offset calculation...")
            fdx, fdy, fwhm = self.env.guider.exe_cal()

            self.env.astrometry.clear_raw_files()

            def _is_nan(x: Any) -> bool:
                try:
                    return x is None or (isinstance(x, float) and math.isnan(x))
                except Exception:
                    return True

            if _is_nan(fdx) or _is_nan(fdy) or _is_nan(fwhm):
                msg = (
                    "Guiding completed with WARNING: no reliable guide stars detected."
                )
                return self._generate_response(
                    "warning",
                    msg,
                    fdx=fdx,
                    fdy=fdy,
                    fwhm=fwhm,
                    raw_path=str(raw_save_path),
                    save_path=str(guiding_save_path),
                    astrometry_files=[os.path.basename(p) for p in astro_files],
                )

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
                raw_path=str(raw_save_path),
                save_path=str(guiding_save_path),
                astrometry_files=[os.path.basename(p) for p in astro_files],
            )

        except Exception as e:
            self.env.logger.error(f"Guiding failed: {str(e)}")
            return self._generate_response(
                "error",
                f"Guiding failed: {str(e)}",
                raw_path=str(raw_save_path),
                save_path=str(guiding_save_path),
            )

    def _evaluate_pointing_image_quality(
        self,
        fits_path: Path,
    ) -> Dict[str, Any]:
        """
        Relaxed pointing image filter.
        Reject only obviously bad images before astrometry.
        """
    
        cfg = self.env.astrometry.inpar["pointing_filter"]
    
        min_std_bg = cfg["min_std_bg"]
        min_peaks = cfg["min_peaks"]
        min_brightest_flux = cfg["min_brightest_flux"]
    
        fwhm = cfg["dao"]["fwhm"]
        sigma_threshold = cfg["dao"]["sigma_threshold"]
    
        reasons = []

        try:
            img = fits.getdata(str(fits_path))
            img = np.asarray(img, dtype=float)

            if img.ndim != 2:
                reasons.append(f"invalid_dimension={img.ndim}")
                return {
                    "passed": False,
                    "n_peaks": 0,
                    "brightest_flux": 0.0,
                    "std_bg": 0.0,
                    "reasons": reasons,
                }

            finite_fraction = np.mean(np.isfinite(img))
            if finite_fraction < 0.99:
                reasons.append(f"low_finite_fraction={finite_fraction:.3f}<0.99")

            mean_bg, median_bg, std_bg = sigma_clipped_stats(
                img,
                sigma=3.0,
            )

            n_peaks = 0
            brightest_flux = 0.0

            if std_bg > 0:
                finder = DAOStarFinder(
                    fwhm=fwhm,
                    threshold=sigma_threshold * std_bg,
                )

                sources = finder(img - median_bg)

                if sources is not None:
                    n_peaks = len(sources)

                    if n_peaks > 0 and "flux" in sources.colnames:
                        brightest_flux = float(np.max(sources["flux"]))

            if std_bg < min_std_bg:
                reasons.append(f"low_std_bg={std_bg:.2f}<MIN_STD_BG={min_std_bg}")

            if n_peaks < min_peaks:
                reasons.append(f"few_peaks={n_peaks}<MIN_PEAKS={min_peaks}")

            if brightest_flux < min_brightest_flux:
                reasons.append(
                    f"low_brightest_flux={brightest_flux:.2f}"
                    f"<MIN_BRIGHTEST_FLUX={min_brightest_flux}"
                )

            return {
                "passed": len(reasons) == 0,
                "n_peaks": n_peaks,
                "brightest_flux": brightest_flux,
                "std_bg": float(std_bg),
                "reasons": reasons,
            }

        except Exception as e:
            return {
                "passed": False,
                "n_peaks": 0,
                "brightest_flux": 0.0,
                "std_bg": 0.0,
                "reasons": [f"filter_error={e}"],
            }

    def _move_with_unique_name(self, src: Path, dst_dir: Path) -> Path:
        dst_dir.mkdir(parents=True, exist_ok=True)

        dst = dst_dir / src.name

        if not dst.exists():
            shutil.move(str(src), str(dst))
            return dst

        stem = src.stem
        suffix = src.suffix

        for i in range(1, 1000):
            candidate = dst_dir / f"{stem}_{i:03d}{suffix}"
            if not candidate.exists():
                shutil.move(str(src), str(candidate))
                return candidate

        raise RuntimeError(f"Failed to create unique filename for {src}")

    def _filter_pointing_raw_images(
        self,
        raw_path: Path,
        unclean_path: Path,
    ) -> Dict[str, Any]:
        """
        Filter FITS files in raw_path.
        Passed files remain in raw_path.
        Failed files are moved to unclean_path.
        """
        exts = (".fits", ".fit", ".fts")

        fits_files = [
            Path(p)
            for p in glob.glob(str(raw_path / "*"))
            if os.path.isfile(p) and p.lower().endswith(exts)
        ]

        passed_files = []
        failed_files = []

        self.env.logger.info(
            f"[pointing filter] found {len(fits_files)} raw FITS files"
        )

        for fits_file in sorted(fits_files):
            result = self._evaluate_pointing_image_quality(fits_file)

            if result["passed"]:
                passed_files.append(str(fits_file))
                self.env.logger.info(
                    f"[pointing filter PASS] {fits_file.name} | "
                    f"std_bg={result['std_bg']:.2f}, "
                    f"peaks={result['n_peaks']}, "
                    f"brightest_flux={result['brightest_flux']:.2f}"
                )
            else:
                moved_path = self._move_with_unique_name(fits_file, unclean_path)
                failed_files.append(str(moved_path))

                self.env.logger.warning(
                    f"[pointing filter FAIL] {fits_file.name} -> {moved_path} | "
                    f"std_bg={result['std_bg']:.2f}, "
                    f"peaks={result['n_peaks']}, "
                    f"brightest_flux={result['brightest_flux']:.2f}, "
                    f"reasons={'; '.join(result['reasons'])}"
                )

        return {
            "passed_files": passed_files,
            "failed_files": failed_files,
            "n_passed": len(passed_files),
            "n_failed": len(failed_files),
        }
    
    async def pointing(
        self,
        ra: str,
        dec: str,
        ExpTime: float = 1.0,
        ExpNum: int = 1,
        Binning: int = 4,
        CamNum: int = 0,
        SaveGrabRaw: bool = True,
        clear_dir: bool = True,
        MaxGrabRetry: int = 3,
    ) -> Dict[str, Any]:
        save_root, dirs = self._get_save_root_and_dirs()
        date_str = datetime.now().strftime("%Y-%m-%d")

        raw_dir = dirs.get("raw_images", "raw")
        pointing_dir = dirs.get("pointing_save", "pointing_save")
        unclean_dir = dirs.get("unclean_images", "unclean")

        pointing_raw_path = save_root / raw_dir
        pointing_save_path = save_root / pointing_dir / date_str

        pointing_raw_path.mkdir(parents=True, exist_ok=True)
        pointing_save_path.mkdir(parents=True, exist_ok=True)

        self.env.logger.info(f"[pointing] save_root={save_root}")
        self.env.logger.info(f"[pointing] dirs={dirs}")
        self.env.logger.info(
            f"[pointing] SaveGrabRaw={SaveGrabRaw}, "
            f"raw_save_path={pointing_raw_path}, pointing_save_path={pointing_save_path}"
        )

        self._debug_path_block(
            "pointing",
            {
                "save_root": save_root,
                "pointing_raw_path": pointing_raw_path,
                "pointing_save_path": pointing_save_path,
            },
        )

        def _get_crvals_from_fits(
            fits_files: List[Path],
        ) -> Tuple[List[float], List[float]]:
            cr1_list, cr2_list = [], []
            for p in fits_files:
                try:
                    with fits.open(str(p)) as hdul:
                        hdr = hdul[0].header
                        cr1_list.append(float(hdr.get("CRVAL1", float("nan"))))
                        cr2_list.append(float(hdr.get("CRVAL2", float("nan"))))
                except Exception as e:
                    self.env.logger.warning(f"Failed to read CRVAL from {p}: {e}")
                    cr1_list.append(float("nan"))
                    cr2_list.append(float("nan"))
            return cr1_list, cr2_list

        try:
            self.env.logger.info("Starting pointing sequence...")
            self.env.logger.info(f"Target RA/DEC: {ra}, {dec}")
            date_str = datetime.now().strftime("%Y-%m-%d")
            run_timestamp = datetime.now().strftime("D%Y%m%d_T%H%M%S")

            cfg = self.env.astrometry.inpar["pointing_filter"]
            min_valid_images = cfg["min_valid_images"]

            filter_result = None
            grab_result = None

            for attempt in range(1, MaxGrabRetry + 1):
                pointing_unclean_path = (
                    save_root
                    / unclean_dir
                    / date_str
                    / run_timestamp
                    / f"attempt{attempt:02d}"
                )
                
                pointing_unclean_path.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                self.env.logger.info(
                    f"[pointing] grab/filter attempt {attempt}/{MaxGrabRetry}"
                )

                if clear_dir:
                    self.env.astrometry.clear_raw_files()

                grab_result = await self.grab(
                    CamNum=CamNum,
                    ExpTime=ExpTime,
                    ExpNum=ExpNum,
                    Binning=Binning,
                    path=str(pointing_raw_path),
                    ra=ra,
                    dec=dec,
                )

                if grab_result.get("status") != "success":
                    return self._generate_response(
                        "error",
                        f"Pointing image grab failed: {grab_result.get('message')}",
                        raw_path=str(pointing_raw_path),
                        save_path=str(pointing_save_path),
                    )

                filter_result = self._filter_pointing_raw_images(
                    raw_path=pointing_raw_path,
                    unclean_path=pointing_unclean_path,
                )

                self.env.logger.info(
                    f"[pointing filter] attempt={attempt}, "
                    f"passed={filter_result['n_passed']}, "
                    f"failed={filter_result['n_failed']}"
                )

                if filter_result["n_passed"] >= min_valid_images:
                    self.env.logger.info(
                        f"[pointing filter] pass: "
                        f"{filter_result['n_passed']} images available for astrometry"
                    )
                    break

                self.env.logger.warning(
                    f"[pointing filter] only {filter_result['n_passed']} valid images. "
                    f"Need at least {min_valid_images}. Retrying grab..."
                )

            if filter_result is None or filter_result["n_passed"] < min_valid_images:
                msg = (
                    "Pointing failed: not enough valid images after filtering. "
                    f"valid={0 if filter_result is None else filter_result['n_passed']}, "
                    f"required={min_valid_images}, retries={MaxGrabRetry}"
                )
                self.env.logger.error(msg)

                return self._generate_response(
                    "error",
                    msg,
                    raw_path=str(pointing_raw_path),
                    unclean_path=str(pointing_unclean_path),
                    save_path=str(pointing_save_path),
                    filter_result=filter_result,
                )

            if SaveGrabRaw:
                self.env.logger.info(f"Saving filtered pointing images to {pointing_save_path}")

                copied = 0

                for src in filter_result["passed_files"]:
                    src_path = Path(src)
                    dst = pointing_save_path / src_path.name
                    self.env.logger.info(f"copying filtered image {src_path} to {dst}")
                    shutil.copy2(str(src_path), str(dst))
                    copied += 1

                self.env.logger.info(
                    f"[pointing] saved {copied} filtered FITS files to {pointing_save_path}"
                )

            self._apply_clean_env_to_astrometry()

            self.env.logger.info(
                "Ensuring astrometry outputs are ready (no procimg dependency)..."
            )
            astro_files = self._ensure_astrometry_outputs_ready()
            astro_files = list(astro_files) if astro_files else []

            self.env.logger.info(f"Astrometry inputs ready: {len(astro_files)} files.")

            if not astro_files:
                msg = "Pointing failed: no astrometry FITS outputs found."
                self.env.logger.error(msg)
                return self._generate_response(
                    "error",
                    msg,
                    images=[],
                    crval1=[],
                    crval2=[],
                    raw_path=str(pointing_raw_path),
                    save_path=str(pointing_save_path),
                )

            image_list = [Path(p) for p in astro_files]
            image_names = [p.name for p in image_list]

            crval1_list, crval2_list = _get_crvals_from_fits(image_list)

            msg = f"Pointing completed. Computed CRVALs for {len(image_list)} images."
            return self._generate_response(
                "success",
                msg,
                images=image_names,
                crval1=crval1_list,
                crval2=crval2_list,
                raw_path=str(pointing_raw_path),
                save_path=str(pointing_save_path),
            )

        except Exception as e:
            self.env.logger.error(f"Pointing failed: {str(e)}")
            return self._generate_response(
                "error",
                f"Pointing failed: {str(e)}",
                raw_path=str(pointing_raw_path),
                save_path=str(pointing_save_path),
            )

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
