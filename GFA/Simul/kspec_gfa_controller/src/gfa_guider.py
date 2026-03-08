#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Yongmin Yoon, Mingyeong Yang (yyoon@kasi.re.kr, mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: gfa_guider.py
#
# UPDATED (2026-01):
# - Compatible with the new astrometry class that builds combined_star.fits under
#   inpar["paths"]["directories"]["star_catalog"] (dir OR file path).
# - No longer hardcodes "img/combined_star.fits".
# - Adds robust catalog path resolution + helpful diagnostics.
# - Keeps RA hour->deg heuristic/override.

import os
import sys
import json
import glob
import math
import warnings
import logging
from typing import Optional, Tuple, List, Union
import traceback

import re
import glob
import os
from typing import Optional

import numpy as np
from scipy.optimize import curve_fit

from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clip
from astropy.utils.exceptions import AstropyWarning

import photutils.detection as pd


###############################################################################
# Helper Functions
###############################################################################
def _get_default_config_path() -> str:
    """
    Return the default path for the guider configuration file.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(script_dir, "etc", "astrometry_params.json")
    if not os.path.isfile(default_path):
        raise FileNotFoundError(
            f"Default config file not found at: {default_path}. "
            "Please adjust `_get_default_config_path()` accordingly."
        )
    return default_path


def _get_default_logger() -> logging.Logger:
    """
    Returns a simple default logger if none is provided.
    """
    logger = logging.getLogger("gfa_guider_default")
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


###############################################################################
# Main GFAGuider Class
###############################################################################
class GFAGuider:
    """
    A class for guide star operations using GFA data.
    Reads parameters from `astrometry_params.json` and performs star detection,
    offset calculation, and seeing (FWHM) measurements.

    NOTE (2026-01):
    - procimg(processed_dir) 의존성 제거.
    - astrometry 결과물(astro_*.fits)의 data를 그대로 사용하여 background/peak/centroid 수행.
    - combined_star.fits는 astrometry class가 생성( .corr vstack )한 결과를 사용.
    """

    def __init__(
        self, config: Optional[str] = None, logger: Optional[logging.Logger] = None
    ) -> None:
        if config is None:
            config = _get_default_config_path()
        if logger is None:
            logger = _get_default_logger()

        self.logger = logger
        self.logger.info("Initializing GFAGuider...")

        # Load the JSON configuration
        try:
            with open(config, "r") as f:
                self.inpar = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            self.logger.error(f"Error loading JSON file: {exc}")
            raise RuntimeError("Failed to load configuration file.") from exc

        # 1) Directory paths from config
        base_dir = os.path.abspath(os.path.dirname(__file__))
        dirs = self.inpar["paths"]["directories"]

        self.final_astrometry_dir = os.path.join(base_dir, dirs["final_astrometry_images"])
        self.cutout_path = os.path.join(base_dir, dirs["cutout_directory"])

        # ✅ NEW: raw images dir (processed 없이 raw만 사용)
        # config 키가 raw_images 이면 그걸 쓰고, 혹시 raw가 있으면 fallback
        raw_key = "raw_images" if "raw_images" in dirs else ("raw" if "raw" in dirs else None)
        if raw_key is None:
            raise KeyError(
                "Config paths.directories에 raw_images (또는 raw) 키가 필요합니다."
            )
        self.raw_dir = os.path.join(base_dir, dirs[raw_key])

        # ✅ star_catalog path (dir OR file) - must match astrometry class
        self.star_catalog_root = os.path.join(base_dir, dirs["star_catalog"])

        self.logger.debug(f"Raw dir       : {self.raw_dir}")
        self.logger.debug(f"Final astro dir: {self.final_astrometry_dir}")
        self.logger.debug(f"Cutout dir    : {self.cutout_path}")
        self.logger.debug(f"Star catalog  : {self.star_catalog_root}")

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.final_astrometry_dir, exist_ok=True)
        os.makedirs(self.cutout_path, exist_ok=True)
        os.makedirs(os.path.dirname(self._resolve_combined_star_path()), exist_ok=True)

        # 2) Guide star detection / selection parameters
        self.boxsize = self.inpar["detection"]["box_size"]
        self.crit_out = self.inpar["detection"]["criteria"]["critical_outlier"]
        self.peakmax = self.inpar["detection"]["peak_detection"]["max"]
        self.peakmin = self.inpar["detection"]["peak_detection"]["min"]
        self.ang_dist = self.inpar["catalog_matching"]["tolerance"]["angular_distance"]
        self.pixel_scale = self.inpar["settings"]["image_processing"]["pixel_scale"]

        self.logger.info("GFAGuider setup complete.")


    def _astro_to_raw_path(self, astro_file: str) -> Optional[str]:
        """
        astro_*.fits -> raw 매칭을 '카메라 토큰'으로 수행

        파일명 예:
        raw : D20260121_T171409_40103651_exp5s.fits
        astro: astro_D20260121_T171409_40103651_exp5s.fits

        매칭 규칙:
        1) astro 파일명에서 cam_token(예: 40103651)을 추출
        2) raw_dir에서 *_{cam_token}_*.fits 를 찾음
        3) 여러 개면 가장 최신 수정(mtime) 파일 선택
        """

        base = os.path.basename(astro_file)

        # astro_ prefix 제거 (있든 없든 처리)
        if base.startswith("astro_"):
            base2 = base[len("astro_"):]
        else:
            base2 = base

        # cam_token 추출: DYYYYMMDD_T######_<CAMTOKEN>_...
        # 예: D20260121_T171409_40103651_exp5s.fits -> 40103651
        m = re.match(r"^D\d{8}_T\d{6}_(\d+)_", base2)
        if not m:
            self.logger.warning(f"[match] Cannot parse cam token from astro filename: {base}")
            return None

        cam_token = m.group(1)

        # raw_dir에서 해당 cam_token을 가진 파일 찾기
        candidates = []
        patterns = [
            os.path.join(self.raw_dir, f"*_{cam_token}_*.fits"),
            os.path.join(self.raw_dir, f"*_{cam_token}_*.fit"),
            os.path.join(self.raw_dir, f"*_{cam_token}_*.fts"),
            os.path.join(self.raw_dir, "**", f"*_{cam_token}_*.fits"),
            os.path.join(self.raw_dir, "**", f"*_{cam_token}_*.fit"),
            os.path.join(self.raw_dir, "**", f"*_{cam_token}_*.fts"),
        ]
        for patt in patterns:
            candidates.extend(glob.glob(patt, recursive=True))

        # 혹시 같은 토큰이 다른 확장자/케이스로 올 경우
        candidates = [p for p in candidates if os.path.isfile(p) and p.lower().endswith((".fits", ".fit", ".fts"))]

        if not candidates:
            return None

        # 여러 개면 최신 파일 선택
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]



    # ---------------------------------------------------------------------
    # ✅ NEW: combined_star.fits 경로 해석 (astrometry class와 동일 규칙)
    # ---------------------------------------------------------------------
    def _resolve_combined_star_path(self) -> str:
        base_dir = os.path.abspath(os.path.dirname(__file__))
        root = self.inpar["paths"]["directories"]["star_catalog"]
        root_path = os.path.join(base_dir, root)

        # 과거 호환: star_catalog가 combined_star.fits를 직접 가리키면 그대로 사용
        if root_path.lower().endswith(".fits"):
            return root_path

        # 정상 구조: 디렉토리면 그 안의 combined_star.fits
        return os.path.join(root_path, "combined_star.fits")


    def load_image_and_wcs(self, image_file: str) -> Tuple[np.ndarray, fits.Header, WCS]:
        """
        Load image data and WCS from a FITS file.
        """
        self.logger.debug(f"Loading image and WCS from: {image_file}")
        warnings.filterwarnings("ignore", category=AstropyWarning)

        try:
            image_data_p, header = fits.getdata(image_file, ext=0, header=True)
            wcs_obj = WCS(header)
            return image_data_p, header, wcs_obj
        except FileNotFoundError:
            self.logger.error(f"File not found: {image_file}")
            raise
        except Exception as e:
            self.logger.error(f"Error reading FITS file: {e}")
            raise

    def load_only_image(self, image_file: str) -> np.ndarray:
        """
        Load only the image data from a FITS file (no WCS).
        """
        self.logger.debug(f"Loading image data from file: {image_file}")
        warnings.filterwarnings("ignore", category=AstropyWarning)
        return fits.getdata(image_file, ext=0)

    def background(self, image_data_p: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Perform sigma clipping to derive background and standard deviation.
        """
        self.logger.info("Performing sigma clipping to derive background and stddev.")
        image_data = np.zeros_like(image_data_p, dtype=float)
        x_split = 511

        # Left region
        region1 = image_data_p[:, :x_split]
        sigclip1 = sigma_clip(region1, sigma=3, maxiters=False, masked=False)
        avg1 = np.mean(sigclip1)
        image_data[:, :x_split] = region1 - avg1

        # Right region
        region2 = image_data_p[:, x_split:]
        sigclip2 = sigma_clip(region2, sigma=3, maxiters=False, masked=False)
        avg2 = np.mean(sigclip2)
        image_data[:, x_split:] = region2 - avg2

        # Full image
        sigclip = sigma_clip(image_data, sigma=3, maxiters=False, masked=False)
        stddev = float(np.std(sigclip))

        self.logger.debug(f"Background subtraction done. Stddev={stddev:.4f}")
        return image_data, stddev

    def load_star_catalog(
        self, crval1: float, crval2: float
    ) -> Tuple[
        float, float, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
    ]:
        """
        Load the guide star catalog and return star positions/flux.

        Compatibility changes:
        - Uses config dirs["star_catalog"] (dir OR file path) to locate combined_star.fits.
        - No longer uses hardcoded "img/combined_star.fits".

        RA unit handling:
        - If catalog RA looks like hours (0~24), convert to degrees by *15.
        - Or force via config:
            inpar["catalog_matching"]["fields"]["ra_unit"] in {"deg","hour"}
        """
        star_catalog_path = self._resolve_combined_star_path()

        self.logger.debug(f"Using star catalog file: {star_catalog_path}")

        if not os.path.exists(star_catalog_path):
            # helpful diagnostics: show what exists in the directory
            parent = os.path.dirname(star_catalog_path)
            listing = []
            try:
                if os.path.isdir(parent):
                    listing = sorted(os.listdir(parent))[:50]
            except Exception:
                pass
            self.logger.error(
                f"Star catalog file not found: {star_catalog_path}\n"
                f"Parent dir={parent}, listing(sample)={listing}\n"
                f"→ astrometry class에서 build_combined_star_from_corr()가 실행되어 생성됐는지 확인."
            )
            raise FileNotFoundError(f"Star catalog file not found: {star_catalog_path}")
        
        p = self._resolve_combined_star_path()
        if os.path.isdir(p):
            raise IsADirectoryError(f"Expected FITS file but got directory: {p}")


        with fits.open(star_catalog_path, memmap=True) as hdul:
            if len(hdul) < 2 or hdul[1].data is None:
                raise RuntimeError(f"Invalid combined_star.fits (no table HDU[1]): {star_catalog_path}")

            data = hdul[1].data
            ra_col = self.inpar["catalog_matching"]["fields"]["ra_column"]
            dec_col = self.inpar["catalog_matching"]["fields"]["dec_column"]
            flux_col = self.inpar["catalog_matching"]["fields"]["mag_flux"]

            if ra_col not in data.columns.names or dec_col not in data.columns.names:
                raise KeyError(
                    f"Catalog columns missing. "
                    f"Have={data.columns.names}, need ra_col={ra_col}, dec_col={dec_col}"
                )
            if flux_col not in data.columns.names:
                raise KeyError(
                    f"Catalog flux/mag column missing. Have={data.columns.names}, need flux_col={flux_col}"
                )

            ra_p = np.array(data[ra_col], dtype=float)
            dec_p = np.array(data[dec_col], dtype=float)
            flux = np.array(data[flux_col], dtype=float)

        # -------------------------
        # ✅ RA unit handling (hour -> deg)
        # -------------------------
        fields_cfg = self.inpar.get("catalog_matching", {}).get("fields", {})
        ra_unit = (fields_cfg.get("ra_unit", "") or "").strip().lower()  # "deg" or "hour" or ""

        ra_min = float(np.nanmin(ra_p)) if ra_p.size else float("nan")
        ra_max = float(np.nanmax(ra_p)) if ra_p.size else float("nan")

        looks_like_hours = (ra_p.size > 0) and (ra_max <= 24.0) and (ra_min >= -0.1)

        if ra_unit == "hour" or (ra_unit == "" and looks_like_hours):
            self.logger.info(
                f"[catalog] RA appears to be in HOURS (min={ra_min:.3f}, max={ra_max:.3f}) -> converting RA*15 to degrees."
            )
            ra_p = ra_p * 15.0
        else:
            self.logger.debug(
                f"[catalog] RA treated as DEGREES (min={ra_min:.3f}, max={ra_max:.3f}), ra_unit='{ra_unit or 'auto'}'"
            )

        # Convert to radians for matching
        ra1_rad = math.radians(crval1)
        dec1_rad = math.radians(crval2)
        ra2_rad = np.radians(ra_p)
        dec2_rad = np.radians(dec_p)

        self.logger.debug(
            f"Star catalog loaded with {len(ra_p)} stars from {star_catalog_path}."
        )
        return ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux

    def select_stars(
        self,
        ra1_rad: float,
        dec1_rad: float,
        ra2_rad: np.ndarray,
        dec2_rad: np.ndarray,
        ra_p: np.ndarray,
        dec_p: np.ndarray,
        flux: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Select guide stars based on angular distance and brightness thresholds.
        """
        self.logger.debug("Selecting stars based on angular distance and flux.")

        delta_sigma = np.arccos(
            np.sin(dec1_rad) * np.sin(dec2_rad)
            + np.cos(dec1_rad) * np.cos(dec2_rad) * np.cos(ra1_rad - ra2_rad)
        )
        angular_distance_degrees = np.degrees(delta_sigma)

        valid_flux = np.nan_to_num(flux, nan=0.0)

        tol = self.inpar.get("catalog_matching", {}).get("tolerance", {})
        mag_flux_min = tol.get("mag_flux_min", None)

        # -------------------------
        # ✅ DEBUG / DIAGNOSTICS
        # -------------------------
        try:
            self.logger.debug(
                f"[catalog] ang_dist(deg)={self.ang_dist}, mag_flux_min={mag_flux_min}"
            )

            if angular_distance_degrees.size > 0:
                closest = float(np.min(angular_distance_degrees))
                within_dist = int(np.sum(angular_distance_degrees < self.ang_dist))
                self.logger.debug(
                    f"[catalog] closest_dist(deg)={closest:.6f}, "
                    f"within_ang_dist={within_dist}/{angular_distance_degrees.size}"
                )

            if valid_flux.size > 0:
                fmin = float(np.min(valid_flux))
                fmed = float(np.median(valid_flux))
                fmax = float(np.max(valid_flux))
                self.logger.debug(
                    f"[catalog] flux stats: min={fmin:.3f}, median={fmed:.3f}, max={fmax:.3f}"
                )

                is_mag_like = (fmax < 100.0 and fmin >= -5.0)
                self.logger.debug(
                    f"[catalog] flux_column_heuristic="
                    f"{'MAG-like (bright=smaller)' if is_mag_like else 'FLUX-like (bright=larger)'}"
                )

                if mag_flux_min is not None:
                    n_gt = int(np.sum(valid_flux > float(mag_flux_min)))
                    n_lt = int(np.sum(valid_flux < float(mag_flux_min)))
                    self.logger.debug(
                        f"[catalog] brightness cut check vs mag_flux_min={mag_flux_min}: "
                        f"count(>min)={n_gt}/{valid_flux.size}, count(<min)={n_lt}/{valid_flux.size}"
                    )
        except Exception as e:
            self.logger.debug(f"[catalog] debug logging failed: {e}")

        # -------------------------
        # ✅ SELECTION
        # -------------------------
        if mag_flux_min is None:
            self.logger.warning(
                "catalog_matching.tolerance.mag_flux_min not found in config; "
                "selecting stars by angular distance only."
            )
            mask = (angular_distance_degrees < self.ang_dist)
        else:
            mask = (angular_distance_degrees < self.ang_dist) & (valid_flux > float(mag_flux_min))

        ra_selected = ra_p[mask]
        dec_selected = dec_p[mask]
        flux_selected = valid_flux[mask]

        self.logger.debug(
            f"[catalog] Selected {len(ra_selected)} stars after filtering "
            f"(mask true count={int(np.sum(mask))})."
        )
        return ra_selected, dec_selected, flux_selected

    def radec_to_xy_stars(
        self, ra: np.ndarray, dec: np.ndarray, wcs: WCS
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        self.logger.debug("Converting RA/DEC arrays to X/Y pixel positions via WCS (np.round).")

        x_pix, y_pix = wcs.world_to_pixel_values(ra, dec)

        dra = np.round(x_pix).astype(int) + 1
        ddec = np.round(y_pix).astype(int) + 1

        dra_f = x_pix + 1.0
        ddec_f = y_pix + 1.0

        self.logger.debug("Conversion to X/Y positions completed (vectorized).")
        return dra, ddec, dra_f, ddec_f

    def cal_centroid_offset(
        self,
        dra: np.ndarray,
        ddec: np.ndarray,
        dra_f: np.ndarray,
        ddec_f: np.ndarray,
        stddev: float,
        wcs: WCS,
        fluxn: np.ndarray,
        file_counter: int,
        cutoutn_stack: List[np.ndarray],
        image_data: np.ndarray,
    ) -> Tuple[List[float], List[float], List[float], List[np.ndarray]]:

        self.logger.debug("==== Starting centroid offset calculation ====")
        dx, dy, peakc = [], [], []

        max_flux = max((val for val in fluxn if val < 30000), default=None)
        boxsize = self.boxsize

        # ✅ per-file threshold scalar (현재 로직: 5*stddev)
        thr_val = float(5.0 * stddev)

        # ✅ stats counters for logging
        cnt_ok = 0
        cnt_nopeak = 0
        cnt_oob = 0
        cnt_edge = 0
        cnt_badflux = 0
        cnt_exc = 0

        # ✅ store peak_values only for OK detections (for min/med/max)
        ok_peak_values: List[float] = []

        self.logger.debug(f"Number of input stars: {len(dra)}")
        self.logger.debug(f"Standard deviation for thresholding: {stddev:.3f}")
        self.logger.debug(f"Box size: {boxsize}")
        self.logger.debug(f"Max flux among stars (cutoff 30000): {max_flux}")

        ny, nx = image_data.shape

        for i in range(len(dra)):
            try:
                # -------------------------
                # ✅ bounds check (image)
                # -------------------------
                # dra/ddec는 1-based로 들어오니까 0-based로 변환해서 체크
                x0 = int(dra[i] - 1)
                y0 = int(ddec[i] - 1)
                if x0 < 0 or x0 >= nx or y0 < 0 or y0 >= ny:
                    cnt_oob += 1
                    dx.append(0)
                    dy.append(0)
                    peakc.append(-1)
                    continue

                # -------------------------
                # cutout #1
                # -------------------------
                y1 = int(ddec[i] - 1 - boxsize / 2)
                y2 = int(ddec[i] - 1 + boxsize / 2 + 1)
                x1 = int(dra[i] - 1 - boxsize / 2)
                x2 = int(dra[i] - 1 + boxsize / 2 + 1)

                # ✅ edge check (cutout boundary)
                if y1 < 0 or x1 < 0 or y2 > ny or x2 > nx:
                    cnt_edge += 1
                    dx.append(0)
                    dy.append(0)
                    peakc.append(-1)
                    continue

                cutout = image_data[y1:y2, x1:x2]

                # threshold array
                threshold = np.full(cutout.shape, thr_val, dtype=float)
                peaks = pd.find_peaks(cutout, threshold, box_size=boxsize / 4, npeaks=1)

                # ✅ photutils가 None/empty table을 돌려주는 케이스 방어
                if peaks is None or len(peaks) == 0:
                    cnt_nopeak += 1
                    dx.append(0)
                    dy.append(0)
                    peakc.append(-1)
                    continue

                # 정상 peak
                x_peak = float(peaks["x_peak"][0])
                y_peak = float(peaks["y_peak"][0])
                peak_val = float(peaks["peak_value"][0])
                peakc.append(peak_val)

                cnt_ok += 1
                ok_peak_values.append(peak_val)

                nra = int(dra[i] - (0.5 * boxsize - x_peak))
                ndec = int(ddec[i] - (0.5 * boxsize - y_peak))

                # -------------------------
                # cutout #2 (centroid)
                # -------------------------
                y1b = int(ndec - 1 - boxsize / 4)
                y2b = int(ndec - 1 + boxsize / 4 + 1)
                x1b = int(nra - 1 - boxsize / 4)
                x2b = int(nra - 1 + boxsize / 4 + 1)

                if y1b < 0 or x1b < 0 or y2b > ny or x2b > nx:
                    cnt_edge += 1
                    dx.append(0)
                    dy.append(0)
                    peakc[-1] = -1
                    continue

                cutout2 = image_data[y1b:y2b, x1b:x2b]

                if fluxn[i] == max_flux:
                    cutoutnp = image_data[
                        int(ndec - 1 - boxsize / 2) : int(ndec - 1 + boxsize / 2 + 1),
                        int(nra - 1 - boxsize / 2) : int(nra - 1 + boxsize / 2 + 1),
                    ]
                    if cutoutnp.size > 0 and np.max(cutoutnp) != 0:
                        cutoutn = cutoutnp / np.max(cutoutnp) * 1000
                        fits_file = os.path.join(self.cutout_path, f"cutout_fluxmax_{file_counter}.fits")
                        fits.writeto(fits_file, cutoutn, overwrite=True)
                        cutoutn_stack.append(cutoutn)

                total_flux = float(np.sum(cutout2))
                if not np.isfinite(total_flux) or total_flux <= 0:
                    cnt_badflux += 1
                    dx.append(0)
                    dy.append(0)
                    peakc[-1] = -1
                    continue

                # centroid
                xcs, ycs = 0.0, 0.0
                for row in range(cutout2.shape[0]):
                    for col in range(cutout2.shape[1]):
                        val = float(cutout2[row, col])
                        xcs += val * col
                        ycs += val * row

                xc = xcs / total_flux
                yc = ycs / total_flux

                fra = nra - (boxsize / 4 - xc)
                fdec = ndec - (boxsize / 4 - yc)

                # arcsec per pixel components
                ra1, dec1 = wcs.pixel_to_world_values(fra, fdec)
                ra2, dec2 = wcs.pixel_to_world_values(fra + 1, fdec)
                x1d = (ra2 - ra1) * 3600.0
                x2d = (dec2 - dec1) * 3600.0

                ra1, dec1 = wcs.pixel_to_world_values(fra, fdec)
                ra2, dec2 = wcs.pixel_to_world_values(fra, fdec + 1)
                y1d = (ra2 - ra1) * 3600.0
                y2d = (dec2 - dec1) * 3600.0

                dx_val = ((fra - dra_f[i]) * x1d) + ((fdec - ddec_f[i]) * x2d)
                dy_val = ((fra - dra_f[i]) * y1d) + ((fdec - ddec_f[i]) * y2d)
                dx.append(dx_val)
                dy.append(dy_val)

            except Exception as exc:
                cnt_exc += 1
                dx.append(0)
                dy.append(0)
                peakc.append(-1)
                self.logger.debug(f"Finding peaks exception for star {i+1}: {exc}")

        # ✅ per-file summary: thr + peak stats
        if ok_peak_values:
            pmin = float(np.min(ok_peak_values))
            pmed = float(np.median(ok_peak_values))
            pmax = float(np.max(ok_peak_values))
            peak_stats = f"peak(min/med/max)={pmin:.2f}/{pmed:.2f}/{pmax:.2f}"
        else:
            peak_stats = "peak(min/med/max)=NA"

        self.logger.info(
            f"[peaks][file#{file_counter}] stars={len(dra)} ok={cnt_ok} nopeak={cnt_nopeak} "
            f"oob={cnt_oob} edge={cnt_edge} badflux={cnt_badflux} exc={cnt_exc} "
            f"thr={thr_val:.2f} {peak_stats}"
        )

        self.logger.debug("==== Finished centroid offset calculation ====")
        return dx, dy, peakc, cutoutn_stack


    def peak_select(
        self, dx: List[float], dy: List[float], peakc: List[float]
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Select stars whose peak values are within [peakmin, peakmax].

        Raises
        ------
        RuntimeError
            If no peaks are selected (i.e., peak selection fails).
        ValueError
            If inputs are empty or lengths mismatch.
        """

        # -------------------------
        # ✅ Input validation
        # -------------------------
        if dx is None or dy is None or peakc is None:
            raise ValueError("peak_select(): dx, dy, peakc must not be None.")

        if not (len(dx) == len(dy) == len(peakc)):
            raise ValueError(
                f"peak_select(): input length mismatch: len(dx)={len(dx)}, "
                f"len(dy)={len(dy)}, len(peakc)={len(peakc)}"
            )

        if len(peakc) == 0:
            raise ValueError("peak_select(): empty input (no stars/peaks provided).")

        peak_array = np.array(peakc, dtype=float)

        # -------------------------
        # ✅ classification + diagnostics
        # -------------------------
        n_total = int(peak_array.size)
        n_invalid = int(np.sum(peak_array <= 0))   # -1 포함 (nopeak/실패)
        n_low = int(np.sum((peak_array > 0) & (peak_array < self.peakmin)))
        n_high = int(np.sum(peak_array > self.peakmax))
        n_kept = int(np.sum((peak_array >= self.peakmin) & (peak_array <= self.peakmax)))

        valid_peaks = peak_array[peak_array > 0]
        if valid_peaks.size > 0:
            pmin = float(np.min(valid_peaks))
            pmed = float(np.median(valid_peaks))
            pmax = float(np.max(valid_peaks))
            dist = f"valid_peak(min/med/max)={pmin:.2f}/{pmed:.2f}/{pmax:.2f}"
        else:
            dist = "valid_peak(min/med/max)=NA"

        self.logger.info(
            f"[peak_select] total={n_total} kept={n_kept} "
            f"invalid(<=0)={n_invalid} low(<{self.peakmin})={n_low} high(>{self.peakmax})={n_high} "
            f"{dist} (peakmin={self.peakmin}, peakmax={self.peakmax})"
        )

        # -------------------------
        # ✅ selection
        # -------------------------
        valid_indices = np.where((peak_array >= self.peakmin) & (peak_array <= self.peakmax))
        pindn = valid_indices[0]

        # -------------------------
        # ✅ FAIL FAST: no peak selected -> raise
        # -------------------------
        if pindn.size == 0:
            # dx/dy/peak 원본 요약도 같이 남기면 디버깅이 훨씬 쉬움
            msg = (
                "peak_select() failed: no peaks within threshold. "
                f"(peakmin={self.peakmin}, peakmax={self.peakmax}, "
                f"total={n_total}, invalid={n_invalid}, low={n_low}, high={n_high}; {dist})"
            )
            self.logger.error(msg)
            raise RuntimeError(msg)

        dxn = np.array([dx[i] for i in pindn], dtype=float)
        dyn = np.array([dy[i] for i in pindn], dtype=float)

        return dxn, dyn, pindn


    def cal_final_offset(
        self, dxp: np.ndarray, dyp: np.ndarray, pindp: np.ndarray
    ) -> Tuple[Union[float, str], Union[float, str]]:
        self.logger.debug("Calculating final offset using selected guide stars.")
        if len(pindp) < 1:
            self.logger.warning("No guide stars available for offset calculation.")
            return "Warning", "Warning"

        distances = np.sqrt(dxp**2 + dyp**2)
        clipped = sigma_clip(distances, sigma=3, maxiters=False)
        cdx = dxp[~clipped.mask]
        cdy = dyp[~clipped.mask]

        if len(cdx) > 4:
            max_index = np.argmax(np.sqrt(cdx**2 + cdy**2))
            min_index = np.argmin(np.sqrt(cdx**2 + cdy**2))
            cdx = np.delete(cdx, [min_index, max_index])
            cdy = np.delete(cdy, [min_index, max_index])

        fdx = float(np.mean(cdx)) if len(cdx) else 0.0
        fdy = float(np.mean(cdy)) if len(cdy) else 0.0

        if math.hypot(fdx, fdy) > self.crit_out:
            self.logger.info(f"Final offset: fdx={fdx:.4f}, fdy={fdy:.4f}")
            return fdx, fdy
        else:
            self.logger.warning("Offsets within critical threshold; returning 0, 0.")
            return 0.0, 0.0
            
    @staticmethod
    def isotropic_gaussian_2d(
        xy: Tuple[np.ndarray, np.ndarray],
        amp: float,
        x0: float,
        y0: float,
        sigma: float,
        offset: float,
    ) -> np.ndarray:
        x, y = xy
        g = offset + amp * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2 * sigma**2))
        return g.ravel()

    def cal_seeing(self, cutoutn_stack: List[np.ndarray]) -> float:
        if not cutoutn_stack:
            self.logger.warning("No cutouts available for FWHM calculation. Returning NaN.")
            return float("nan")

        averaged_cutoutn = np.median(cutoutn_stack, axis=0)
        fits_file = os.path.join(self.cutout_path, "averaged_cutoutn.fits")

        try:
            fits.writeto(fits_file, averaged_cutoutn, overwrite=True)
        except Exception as exc:
            self.logger.error(f"Error saving averaged cutout: {exc}")

        y_size, x_size = averaged_cutoutn.shape
        xgrid, ygrid = np.meshgrid(np.arange(x_size), np.arange(y_size))
        initial_guess = (
            float(np.max(averaged_cutoutn)),
            float(x_size // 2),
            float(y_size // 2),
            1.0,
            0.0,
        )

        try:
            params, _ = curve_fit(
                self.isotropic_gaussian_2d,
                (xgrid, ygrid),
                averaged_cutoutn.ravel(),
                p0=initial_guess,
            )
            _, _, _, sigma, _ = params
            fwhm = 2.0 * math.sqrt(2.0 * math.log(2.0)) * sigma
            return fwhm * self.pixel_scale
        except Exception as exc:
            self.logger.error(f"Gaussian fitting failed: {exc}")
            return float("nan")

# gfa_guider.py (GFAGuider.exe_cal) - 수정본
    def exe_cal(self) -> Tuple[float, float, float]:
        """
        Soft-fail version:
        - 내부에서 어떤 문제가 생겨도 예외를 밖으로 raise 하지 않음
        - 실패 시 (nan, nan, nan) 반환
        - peak_select 실패는 해당 파일만 skip
        """
        try:
            self.logger.info("========== Starting guide star calibration process ==========")

            astro_dir = self.final_astrometry_dir
            if not astro_dir:
                self.logger.error("Astrometry directory path missing.")
                return math.nan, math.nan, math.nan

            astro_files = sorted(glob.glob(os.path.join(astro_dir, "astro_*.fits")))
            if not astro_files:
                self.logger.error(f"No astrometry FITS files found in {astro_dir} (astro_*.fits).")
                return math.nan, math.nan, math.nan

            # combined_star.fits 존재 체크
            cat_path = self._resolve_combined_star_path()
            if not os.path.exists(cat_path):
                self.logger.error(
                    f"combined_star.fits not found at: {cat_path}\n"
                    f"→ astrometry preproc에서 build_combined_star_from_corr()가 실행되도록 "
                    f"ensure_astrometry_ready(build_star_catalog=True) 사용 필요."
                )
                return math.nan, math.nan, math.nan

            self.logger.info(f"Found {len(astro_files)} astrometry files.")
            self.logger.info(f"Raw dir (centroid source): {self.raw_dir}")
            self.logger.info(f"Using combined_star.fits: {cat_path}")

            dxpp, dypp, pindpp = [], [], []
            cutoutn_stack: List[np.ndarray] = []
            file_counter = 1
            skipped = 0

            for astro_file in astro_files:
                raw_file = self._astro_to_raw_path(astro_file)
                if raw_file is None:
                    skipped += 1
                    self.logger.warning(
                        f"[skip] No matching RAW file for astro={os.path.basename(astro_file)} "
                        f"in raw_dir={self.raw_dir}"
                    )
                    continue

                try:
                    self.logger.info(f"\n-- Processing pair #{file_counter}:")
                    self.logger.info(f"  astro(WCS): {astro_file}")
                    self.logger.info(f"  raw(img) : {raw_file}")

                    # 1) WCS는 astro_file에서
                    _, header, wcs_obj = self.load_image_and_wcs(astro_file)
                    crval1, crval2 = header["CRVAL1"], header["CRVAL2"]
                    self.logger.debug(f"  CRVAL1: {crval1:.6f}, CRVAL2: {crval2:.6f}")

                    # 2) centroid는 raw에서 (background 포함)
                    raw_data_p = self.load_only_image(raw_file)
                    image_data, stddev = self.background(raw_data_p)
                    self.logger.debug(f"  Raw background stddev: {stddev:.4f}")

                    # 3) catalog 로드 + 필드 주변 별 선택
                    ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux = self.load_star_catalog(
                        crval1, crval2
                    )

                    ra_sel, dec_sel, flux_sel = self.select_stars(
                        ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux
                    )

                    if len(ra_sel) == 0:
                        self.logger.warning("No catalog stars selected for this field (after cuts).")
                        file_counter += 1
                        continue

                    # 4) catalog RA/DEC -> pixel 예상 위치 (astro WCS로 투영)
                    dra, ddec, dra_f, ddec_f = self.radec_to_xy_stars(ra_sel, dec_sel, wcs_obj)

                    # 5) raw 이미지에서 peak/centroid 찾고 arcsec offset 계산
                    dx_vals, dy_vals, peak_vals, cutoutn_stack = self.cal_centroid_offset(
                        dra,
                        ddec,
                        dra_f,
                        ddec_f,
                        stddev,
                        wcs_obj,
                        flux_sel,
                        file_counter,
                        cutoutn_stack,
                        image_data,   # raw background-subtracted image
                    )

                    # 6) peak 조건으로 별 필터링
                    #    ✅ peak_select에서 예외 발생해도 해당 파일만 skip
                    try:
                        dxn, dyn, pindn = self.peak_select(dx_vals, dy_vals, peak_vals)
                    except Exception as e:
                        self.logger.warning(
                            f"[skip] peak_select failed for {os.path.basename(astro_file)}: {e}"
                        )
                        file_counter += 1
                        continue

                    # (혹시 soft-fail 형태로 빈 배열 리턴하는 구현이 섞여 있어도 안전)
                    if pindn is None or len(pindn) == 0:
                        self.logger.warning(
                            f"[skip] peak_select returned no valid peaks for {os.path.basename(astro_file)}"
                        )
                        file_counter += 1
                        continue

                    dxpp.append(dxn)
                    dypp.append(dyn)
                    pindpp.append(pindn)

                    file_counter += 1

                except Exception as exc:
                    self.logger.error(f"Error processing astro={astro_file} raw={raw_file}: {exc}")
                    try:
                        self.logger.debug(traceback.format_exc())
                    except Exception:
                        pass
                    # ✅ critical이라도 전체를 죽이지 않고 soft-fail로 처리: 해당 파일만 skip
                    self.logger.warning(f"[skip] Critical error in this pair; skipping file.")
                    file_counter += 1
                    continue

            if skipped:
                self.logger.warning(f"Skipped {skipped} astro files due to missing raw matches.")

            if not dxpp or not dypp or not pindpp:
                self.logger.error("No valid guide star data collected. Calibration failed.")
                return math.nan, math.nan, math.nan

            dxp = np.concatenate(dxpp) if len(dxpp) else np.array([])
            dyp = np.concatenate(dypp) if len(dypp) else np.array([])
            pindp = np.concatenate(pindpp) if len(pindpp) else np.array([])

            self.logger.info(f"Total valid guide star offsets: {len(dxp)}")

            fdx, fdy = self.cal_final_offset(dxp, dyp, pindp)
            self.logger.info(f"Computed final offset: ΔX = {fdx} arcsec, ΔY = {fdy} arcsec")

            fwhm = self.cal_seeing(cutoutn_stack)
            self.logger.info(f"Estimated FWHM from cutouts: {fwhm} arcsec")

            self.logger.info("========== Guide star calibration completed successfully ==========")
            return fdx, fdy, fwhm

        except Exception as e:
            self.logger.error(f"exe_cal failed: {e}")
            try:
                self.logger.debug(traceback.format_exc())
            except Exception:
                pass
            return math.nan, math.nan, math.nan
