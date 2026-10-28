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
from pathlib import Path

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
        self,
        config: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        save_root: Optional[Union[str, Path]] = None,
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

        dirs = self.inpar["paths"]["directories"]

        default_root = self.inpar.get("paths", {}).get(
            "save_root", "~/work/DATA/GFADATA/img"
        )

        self.save_root = Path(save_root or default_root).expanduser().resolve()

        self.final_astrometry_dir = str(
            self.save_root / dirs["final_astrometry_images"]
        )
        self.cutout_path = str(self.save_root / dirs["cutout_directory"])
        self.raw_dir = str(self.save_root / dirs["raw_images"])
        self.star_catalog_root = str(self.save_root / dirs["star_catalog"])

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.final_astrometry_dir, exist_ok=True)
        os.makedirs(self.cutout_path, exist_ok=True)
        os.makedirs(os.path.dirname(self._resolve_combined_star_path()), exist_ok=True)

        self.logger.info("========== PATH DEBUG [guider] ==========")
        self.logger.info(f"save_root             = {self.save_root}")
        self.logger.info(f"raw_dir               = {self.raw_dir}")
        self.logger.info(f"final_astrometry_dir  = {self.final_astrometry_dir}")
        self.logger.info(f"cutout_path           = {self.cutout_path}")
        self.logger.info(f"star_catalog_root     = {self.star_catalog_root}")
        self.logger.info(
            f"combined_star_path    = {self._resolve_combined_star_path()}"
        )
        self.logger.info("=========================================")

        # 2) Guide star detection / selection parameters
        self.boxsize = self.inpar["detection"]["box_size"]
        self.crit_out = self.inpar["detection"]["criteria"]["critical_outlier"]
        self.peakmax = self.inpar["detection"]["peak_detection"]["max"]
        self.peakmin = self.inpar["detection"]["peak_detection"]["min"]
        self.ang_dist = self.inpar["catalog_matching"]["tolerance"]["angular_distance"]
        self.pixel_scale = self.inpar["settings"]["image_processing"]["pixel_scale"]
        self.sigma_threshold = self.inpar.get(
                "pointing_filter", {}
            ).get(
                "dao", {}
            ).get("sigma_threshold", 5.0)

        # Windowed centroid (cal_centroid_offset): starting PSF FWHM in pixels,
        # whether to measure the FWHM per frame, and the largest centroid shift
        # (px) a neighbour may cause before the guide star is rejected.
        centroid_par = self.inpar["detection"].get("centroid", {})
        self.centroid_fwhm = float(centroid_par.get("fwhm_px", 8.0))
        self.neighbour_max_bias = float(
            centroid_par.get("neighbour_max_bias_px", 0.05)
        )
        self.measure_fwhm = bool(centroid_par.get("measure_fwhm", True))
        if not (np.isfinite(self.centroid_fwhm) and self.centroid_fwhm > 0):
            raise ValueError(
                f"detection.centroid.fwhm_px must be > 0, got {self.centroid_fwhm}"
            )

        self.logger.info("GFAGuider setup complete.")

    def _astro_to_raw_path(self, astro_file: str) -> Optional[str]:
        """
        Match astro_*.fits to the corresponding raw FITS file.

        Priority
        --------
        1. Exact filename match after removing the ``astro_`` prefix
        2. Camera-token fallback match
        """

        base = os.path.basename(astro_file)

        if base.startswith("astro_"):
            raw_basename = base[len("astro_"):]
        else:
            raw_basename = base

        # ---------------------------------------------------------
        # 1. Exact filename match
        # ---------------------------------------------------------
        exact_candidates = [
            os.path.join(self.raw_dir, raw_basename),
            os.path.join(self.raw_dir, "**", raw_basename),
        ]

        for candidate_pattern in exact_candidates:
            matches = glob.glob(candidate_pattern, recursive=True)

            matches = [
                path
                for path in matches
                if os.path.isfile(path)
            ]

            if matches:
                matches.sort(
                    key=lambda path: os.path.getmtime(path),
                    reverse=True,
                )
                return matches[0]

        # ---------------------------------------------------------
        # 2. Camera-token fallback
        # ---------------------------------------------------------
        match = re.match(
            r"^D\d{8}_T\d{6}_(\d+)_",
            raw_basename,
        )

        if not match:
            self.logger.warning(
                "[match] Cannot parse camera token from "
                f"astro filename: {base}"
            )
            return None

        cam_token = match.group(1)

        patterns = [
            os.path.join(self.raw_dir, f"*_{cam_token}_*.fits"),
            os.path.join(self.raw_dir, f"*_{cam_token}_*.fit"),
            os.path.join(self.raw_dir, f"*_{cam_token}_*.fts"),
            os.path.join(self.raw_dir, "**", f"*_{cam_token}_*.fits"),
            os.path.join(self.raw_dir, "**", f"*_{cam_token}_*.fit"),
            os.path.join(self.raw_dir, "**", f"*_{cam_token}_*.fts"),
        ]

        candidates = []

        for pattern in patterns:
            candidates.extend(
                glob.glob(pattern, recursive=True)
            )

        candidates = [
            path
            for path in candidates
            if os.path.isfile(path)
            and path.lower().endswith(
                (".fits", ".fit", ".fts")
            )
        ]

        if not candidates:
            return None

        candidates = sorted(
            set(candidates),
            key=lambda path: os.path.getmtime(path),
            reverse=True,
        )

        self.logger.warning(
            "[match] Exact RAW filename was not found. "
            f"Using camera-token fallback: astro={base}, "
            f"raw={os.path.basename(candidates[0])}"
        )

        return candidates[0]
    # ---------------------------------------------------------------------
    # ✅ NEW: combined_star.fits 경로 해석 (astrometry class와 동일 규칙)
    # ---------------------------------------------------------------------
    def _resolve_combined_star_path(self) -> str:
        root_path = Path(self.star_catalog_root)

        if str(root_path).lower().endswith(".fits"):
            return str(root_path)

        return str(root_path / "combined_star.fits")

    def load_image_and_wcs(
        self, image_file: str
    ) -> Tuple[np.ndarray, fits.Header, WCS]:
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
        Estimate and subtract the global image background using sigma clipping.

        Parameters
        ----------
        image_data_p : np.ndarray
            Input image data.

        Returns
        -------
        image_data : np.ndarray
            Background-subtracted image.
        stddev : float
            Standard deviation of the sigma-clipped background pixels.
        """
        self.logger.info(
            "Performing global sigma clipping to derive background and stddev."
        )

        # Estimate the global background from the full image.
        sigclip = sigma_clip(
            image_data_p,
            sigma=3,
            maxiters=5,
            masked=True,
        )

        background_level = float(np.ma.mean(sigclip))
        stddev = float(np.ma.std(sigclip))

        # Subtract a single global background level from the full image.
        image_data = image_data_p.astype(float, copy=False) - background_level

        self.logger.debug(
            "Global background subtraction done. "
            f"Background={background_level:.4f}, Stddev={stddev:.4f}"
        )

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
                raise RuntimeError(
                    f"Invalid combined_star.fits (no table HDU[1]): {star_catalog_path}"
                )

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
        ra_unit = (
            (fields_cfg.get("ra_unit", "") or "").strip().lower()
        )  # "deg" or "hour" or ""

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

        cos_delta = (
            np.sin(dec1_rad) * np.sin(dec2_rad)
            + np.cos(dec1_rad)
            * np.cos(dec2_rad)
            * np.cos(ra1_rad - ra2_rad)
        )

        cos_delta = np.clip(cos_delta, -1.0, 1.0)
        delta_sigma = np.arccos(cos_delta)
        angular_distance_degrees = np.degrees(delta_sigma)

        valid_flux = np.nan_to_num(
                flux,
                nan=0.0,
                posinf=0.0,
                neginf=0.0,
            )

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

                is_mag_like = fmax < 100.0 and fmin >= -5.0
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
            mask = angular_distance_degrees < self.ang_dist
        else:
            mask = (angular_distance_degrees < self.ang_dist) & (
                valid_flux > float(mag_flux_min)
            )

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
        self.logger.debug(
            "Converting RA/DEC arrays to X/Y pixel positions via WCS (np.round)."
        )

        x_pix, y_pix = wcs.world_to_pixel_values(ra, dec)

        dra = np.round(x_pix).astype(int) + 1
        ddec = np.round(y_pix).astype(int) + 1

        dra_f = x_pix + 1.0
        ddec_f = y_pix + 1.0

        self.logger.debug("Conversion to X/Y positions completed (vectorized).")
        return dra, ddec, dra_f, ddec_f

    @staticmethod
    def _local_background(cutout: np.ndarray) -> float:
        """
        Sigma-clipped median (3 sigma, 5 iterations) of the finite pixels of a cutout.

        Stars and zeroed (hot) pixels are clipped, so this is the sky level next to
        the guide star. Returns 0.0 if the cutout has no finite pixel.
        """
        finite = cutout[np.isfinite(cutout)]
        if finite.size == 0:
            return 0.0
        clipped = sigma_clip(finite, sigma=3, maxiters=5, masked=True)
        level = float(np.ma.median(clipped))
        return level if np.isfinite(level) else 0.0

    @staticmethod
    def _window(image: np.ndarray, x: float, y: float, sigma_w: float):
        """
        Gaussian window (truncated at 4 sigma_w) centred on (x, y) and the pixel
        values under it (NaN -> 0), with offsets from (x, y); None at the edge.
        """
        ny, nx = image.shape
        half = int(math.ceil(4.0 * sigma_w))
        ix, iy = int(round(x)), int(round(y))
        if ix - half < 0 or iy - half < 0 or ix + half >= nx or iy + half >= ny:
            return None
        cut = image[iy - half: iy + half + 1, ix - half: ix + half + 1]
        yy, xx = np.mgrid[iy - half: iy + half + 1, ix - half: ix + half + 1]
        ddx = xx - x
        ddy = yy - y
        r2 = ddx**2 + ddy**2
        w = np.exp(-r2 / (2.0 * sigma_w**2))
        w[r2 > (4.0 * sigma_w) ** 2] = 0.0
        wi = w * np.nan_to_num(cut, nan=0.0, posinf=0.0, neginf=0.0)
        return wi, ddx, ddy

    @classmethod
    def windowed_centroid(
        cls,
        image: np.ndarray,
        x0: float,
        y0: float,
        sigma_w: float,
        max_shift: float,
        niter: int = 30,
        tol: float = 1e-3,
    ) -> Tuple[float, float]:
        """
        Iterative Gaussian-weighted (windowed) centroid, like SExtractor XWIN/YWIN.

        ``image`` is background-subtracted; NaN pixels get zero weight. The window
        is a circular Gaussian of width ``sigma_w`` truncated at 4 sigma_w,
        re-centred on each iteration with x <- x + 2 sum(w I dx) / sum(w I). The
        fixed point is the centre of any symmetric PSF, and a constant background
        error cancels to first order.

        Parameters
        ----------
        image : 2-D array, background-subtracted.
        x0, y0 : start position (0-based pixel coordinates).
        sigma_w : window sigma in pixels (PSF FWHM / 2.355).
        max_shift : the centroid may not wander further than this from (x0, y0).

        Returns
        -------
        (x, y) in 0-based pixel coordinates, or (nan, nan) if the window leaves
        the image, the weighted flux is not positive, or the centroid wanders off.
        """
        x, y = float(x0), float(y0)
        for _ in range(niter):
            win = cls._window(image, x, y, sigma_w)
            if win is None:
                return math.nan, math.nan
            wi, ddx, ddy = win
            s = float(wi.sum())
            if not np.isfinite(s) or s <= 0:
                return math.nan, math.nan
            xn = x + 2.0 * float((wi * ddx).sum()) / s
            yn = y + 2.0 * float((wi * ddy).sum()) / s
            if math.hypot(xn - x0, yn - y0) > max_shift:
                return math.nan, math.nan
            done = math.hypot(xn - x, yn - y) < tol
            x, y = xn, yn
            if done:
                break
        return x, y

    @classmethod
    def windowed_psf_sigma(
        cls, image: np.ndarray, x: float, y: float, sigma_w: float
    ) -> float:
        """
        PSF sigma (px) from the windowed second moment at a centroid (x, y).

        For a Gaussian PSF of width s under a Gaussian window of width sigma_w the
        weighted second moment per axis is m = s^2 sigma_w^2 / (s^2 + sigma_w^2),
        so s^2 = m sigma_w^2 / (sigma_w^2 - m). NaN if m >= 0.9 sigma_w^2 (PSF far
        wider than the window) or the window leaves the image.
        """
        win = cls._window(image, x, y, sigma_w)
        if win is None:
            return math.nan
        wi, ddx, ddy = win
        s = float(wi.sum())
        if not np.isfinite(s) or s <= 0:
            return math.nan
        m = 0.5 * float((wi * (ddx**2 + ddy**2)).sum()) / s
        sw2 = sigma_w**2
        if not (0.0 < m < 0.9 * sw2):
            return math.nan
        return math.sqrt(m * sw2 / (sw2 - m))

    def _centroid_star(
        self,
        image_data: np.ndarray,
        stddev: float,
        thr_val: float,
        i: int,
        dra: np.ndarray,
        ddec: np.ndarray,
        dra_f: np.ndarray,
        ddec_f: np.ndarray,
        fwhm: float,
    ) -> dict:
        """
        Measure catalogue star ``i`` (see ``cal_centroid_offset``).

        Returns a dict with ``status`` (ok, oob, edge, nopeak, neighbour, badflux)
        and, for ``ok``, the 1-based centroid ``fra``/``fdec``, the seed ``peak``
        above the local background and the PSF ``sigma`` from the windowed
        second moment.
        """
        boxsize = self.boxsize
        ny, nx = image_data.shape
        sigma_w = fwhm / (2.0 * math.sqrt(2.0 * math.log(2.0)))
        peak_footprint = 2 * int(fwhm / 2.0) + 1

        # 1. Validate expected catalog position (dra/ddec are 1-based)
        if not (
            np.isfinite(dra[i])
            and np.isfinite(ddec[i])
            and np.isfinite(dra_f[i])
            and np.isfinite(ddec_f[i])
        ):
            return {"status": "oob"}
        x0 = int(dra[i] - 1)
        y0 = int(ddec[i] - 1)
        if x0 < 0 or x0 >= nx or y0 < 0 or y0 >= ny:
            return {"status": "oob"}

        # 2. Cutout around the predicted position, local background
        y1 = int(ddec[i] - 1 - boxsize / 2)
        y2 = int(ddec[i] - 1 + boxsize / 2 + 1)
        x1 = int(dra[i] - 1 - boxsize / 2)
        x2 = int(dra[i] - 1 + boxsize / 2 + 1)
        if y1 < 0 or x1 < 0 or y2 > ny or x2 > nx:
            return {"status": "edge"}

        cutout = image_data[y1:y2, x1:x2].astype(float)
        if cutout.size == 0 or not np.any(np.isfinite(cutout)):
            return {"status": "nopeak"}

        local_bkg = self._local_background(cutout)
        cutout_sub = np.nan_to_num(
            cutout - local_bkg, nan=0.0, posinf=0.0, neginf=0.0
        )

        # 3. Sources in the box; seed on the one nearest the prediction
        threshold = np.full(cutout.shape, thr_val, dtype=float)
        peaks = pd.find_peaks(
            cutout_sub,
            threshold,
            box_size=peak_footprint,
            npeaks=50,
        )
        if peaks is None or len(peaks) == 0:
            return {"status": "nopeak"}

        px = np.asarray(peaks["x_peak"], dtype=float)
        py = np.asarray(peaks["y_peak"], dtype=float)
        pv = np.asarray(peaks["peak_value"], dtype=float)
        good = np.isfinite(px) & np.isfinite(py) & np.isfinite(pv) & (pv > 0)
        px, py, pv = px[good] + x1, py[good] + y1, pv[good]
        if px.size == 0:
            return {"status": "nopeak"}

        xp_cat = float(dra_f[i]) - 1.0
        yp_cat = float(ddec_f[i]) - 1.0
        dist = np.hypot(px - xp_cat, py - yp_cat)
        j = int(np.argmin(dist))
        x_peak, y_peak, peak_val = float(px[j]), float(py[j]), float(pv[j])

        # 4. Neighbour check. Peaks within 1 FWHM, or at the seed's value
        #    (saturated plateau), belong to the same source.
        sep = np.hypot(px - x_peak, py - y_peak)
        other = (sep > fwhm) & (np.abs(pv - peak_val) > 0.5)
        nb_bias = np.where(
            other,
            (pv / peak_val) * sep * np.exp(-(sep**2) / (4.0 * sigma_w**2)),
            0.0,
        )
        if np.any(nb_bias > self.neighbour_max_bias):
            k = int(np.argmax(nb_bias))
            self.logger.debug(
                f"[centroid] star {i + 1} rejected (neighbour): source at "
                f"{sep[k]:.1f} px with peak {pv[k]:.0f} vs {peak_val:.0f} "
                f"(expected shift {nb_bias[k]:.2f} px)"
            )
            return {"status": "neighbour"}

        cat_x = np.asarray(dra_f, dtype=float) - 1.0
        cat_y = np.asarray(ddec_f, dtype=float) - 1.0
        d_cat = np.hypot(cat_x - x_peak, cat_y - y_peak)
        # this star and its catalogue duplicates (within 0.5 FWHM) do not count
        d_cat[np.hypot(cat_x - xp_cat, cat_y - yp_cat) < 0.5 * fwhm] = np.inf
        d_cat[~np.isfinite(d_cat)] = np.inf
        if d_cat.size and float(np.min(d_cat)) < float(dist[j]):
            self.logger.debug(
                f"[centroid] star {i + 1} rejected (neighbour): seed nearer "
                f"another catalogue star ({np.min(d_cat):.1f} px vs "
                f"{dist[j]:.1f} px)"
            )
            return {"status": "neighbour"}

        # 5. Windowed centroid on the local-background-subtracted image. The
        #    window may move up to max_shift = FWHM from the seed.
        half = int(math.ceil(4.0 * sigma_w)) + int(math.ceil(fwhm)) + 1
        ixp, iyp = int(round(x_peak)), int(round(y_peak))
        wy1, wy2 = iyp - half, iyp + half + 1
        wx1, wx2 = ixp - half, ixp + half + 1
        if wy1 < 0 or wx1 < 0 or wy2 > ny or wx2 > nx:
            return {"status": "edge"}

        win = image_data[wy1:wy2, wx1:wx2].astype(float) - local_bkg
        win[~np.isfinite(win)] = np.nan
        # Zeroed hot pixels sit far below the sky: no weight.
        win[win < -5.0 * stddev] = np.nan

        xc_w, yc_w = self.windowed_centroid(
            win, x_peak - wx1, y_peak - wy1, sigma_w, max_shift=fwhm
        )
        if not np.isfinite(xc_w) or not np.isfinite(yc_w):
            self.logger.debug(
                f"[centroid] star {i + 1}: windowed centroid failed "
                f"(seed {x_peak:.0f},{y_peak:.0f}, peak {peak_val:.0f})"
            )
            return {"status": "badflux"}

        return {
            "status": "ok",
            "fra": xc_w + wx1 + 1.0,
            "fdec": yc_w + wy1 + 1.0,
            "peak": peak_val,
            "sigma": self.windowed_psf_sigma(win, xc_w, yc_w, sigma_w),
        }

    def _measured_fwhm(self, results: List[dict], stddev: float) -> float:
        """
        Median PSF FWHM (px) of the well-measured, unsaturated stars, NaN if
        fewer than 3 (peak within peak_detection min/max and >= 10 sigma).
        """
        sig = [
            r["sigma"]
            for r in results
            if r.get("status") == "ok"
            and np.isfinite(r.get("sigma", math.nan))
            and self.peakmin <= r["peak"] <= self.peakmax
            and r["peak"] >= 10.0 * stddev
        ]
        if len(sig) < 3:
            return math.nan
        fwhm = 2.0 * math.sqrt(2.0 * math.log(2.0)) * float(np.median(sig))
        return float(np.clip(fwhm, 2.0, max(2.0, self.boxsize / 2.0)))

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
        """
        Centroid every catalogue star and return its on-sky offset from the
        catalogue position.

        Per star, in a (box_size + 1)^2 box around the predicted position:

        1. The box's sigma-clipped median (local background) is subtracted.
        2. ``find_peaks`` (sigma_threshold x stddev, footprint ~ FWHM) lists the
           sources in the box; the seed is the peak nearest the predicted
           position, not the brightest.
        3. Neighbour check (``neighbour`` counter). Peaks within 1 FWHM of the
           seed, or at the seed's value (a saturated plateau), are the same
           source. Any other peak with peak ratio q to the seed at distance d
           shifts a windowed centroid by about q d exp(-d^2 / (4 sigma_w^2))
           (Gaussian PSF of width sigma_w); the star is rejected if that exceeds
           ``detection.centroid.neighbour_max_bias_px`` (0.05 px: q = 0.3 within
           1.9 FWHM, q = 1 within 2.1 FWHM, q = 3 within 2.3 FWHM). It is also
           rejected if the seed is nearer another catalogue star's predicted
           position than this one's.
        4. Windowed centroid (``windowed_centroid``, sigma_w = FWHM / 2.355)
           started at the seed. Pixels more than 5 sigma below the local
           background (zeroed hot pixels) get zero weight.

        FWHM starts at ``detection.centroid.fwhm_px`` (default 8 px). With
        ``detection.centroid.measure_fwhm`` (default true) the PSF FWHM is then
        measured from the stars' windowed second moments (``_measured_fwhm``);
        if it differs from the value used by more than 20 %, the stars are
        measured again with it (at most two more passes).

        Returns dx, dy (arcsec, east / north), the seed peak above the local
        background (-1 for failed stars), and ``cutoutn_stack`` with the
        normalized cutout of the brightest catalogue star appended.
        """
        self.logger.debug("==== Starting centroid offset calculation ====")

        n_stars = len(dra)
        finite_flux = [
            float(value)
            for value in fluxn
            if np.isfinite(value) and float(value) < 30000
        ]
        max_flux = max(finite_flux, default=None)
        boxsize = self.boxsize

        # Peak detection threshold: sigma_threshold x background standard deviation
        thr_val = float(self.sigma_threshold * stddev)

        self.logger.debug(f"Number of input stars: {n_stars}")
        self.logger.debug(f"Standard deviation for thresholding: {stddev:.3f}")
        self.logger.debug(f"Peak detection threshold: {thr_val:.3f}")
        self.logger.debug(
            f"Box size: {boxsize}, FWHM: {self.centroid_fwhm:.2f} px "
            f"(measure: {self.measure_fwhm}), "
            f"neighbour max bias: {self.neighbour_max_bias} px"
        )
        self.logger.debug(f"Max catalog flux among stars (cutoff 30000): {max_flux}")

        if not np.isfinite(stddev) or stddev <= 0:
            self.logger.error(
                f"Invalid background standard deviation: {stddev}. "
                "Returning failed measurements."
            )
            return (
                [0.0] * n_stars,
                [0.0] * n_stars,
                [-1.0] * n_stars,
                cutoutn_stack,
            )

        if image_data.ndim != 2:
            raise ValueError(
                f"image_data must be a 2D array, got shape={image_data.shape}"
            )

        ny, nx = image_data.shape

        def measure_all(fwhm: float) -> List[dict]:
            out = []
            for i in range(n_stars):
                try:
                    out.append(
                        self._centroid_star(
                            image_data, stddev, thr_val, i,
                            dra, ddec, dra_f, ddec_f, fwhm,
                        )
                    )
                except Exception as exc:
                    self.logger.debug(
                        f"Finding peaks/centroid exception for star {i + 1}: {exc}"
                    )
                    out.append({"status": "exc"})
            return out

        fwhm = float(self.centroid_fwhm)
        results = measure_all(fwhm)
        if self.measure_fwhm:
            for _ in range(2):
                fwhm_meas = self._measured_fwhm(results, stddev)
                if not np.isfinite(fwhm_meas) or abs(fwhm_meas / fwhm - 1.0) <= 0.2:
                    break
                self.logger.info(
                    f"[centroid][file#{file_counter}] measured FWHM "
                    f"{fwhm_meas:.2f} px (window was {fwhm:.2f} px): re-measuring"
                )
                fwhm = fwhm_meas
                results = measure_all(fwhm)

        dx: List[float] = []
        dy: List[float] = []
        peakc: List[float] = []
        counts = {
            k: 0
            for k in ("ok", "nopeak", "oob", "edge", "badflux", "neighbour", "exc")
        }
        ok_peak_values: List[float] = []

        for i, res in enumerate(results):
            status = res["status"]
            if status != "ok":
                counts[status] += 1
                dx.append(0.0)
                dy.append(0.0)
                peakc.append(-1.0)
                continue
            try:
                fra, fdec, peak_val = res["fra"], res["fdec"], res["peak"]

                # Normalized cutout of the brightest catalog star (centred on the
                # centroid pixel) for cal_seeing
                if (
                    max_flux is not None
                    and np.isfinite(fluxn[i])
                    and np.isclose(float(fluxn[i]), max_flux)
                ):
                    nra = int(round(fra))
                    ndec = int(round(fdec))
                    y1n = int(ndec - 1 - boxsize / 2)
                    y2n = int(ndec - 1 + boxsize / 2 + 1)
                    x1n = int(nra - 1 - boxsize / 2)
                    x2n = int(nra - 1 + boxsize / 2 + 1)

                    if y1n >= 0 and x1n >= 0 and y2n <= ny and x2n <= nx:
                        cutoutnp = image_data[y1n:y2n, x1n:x2n]
                        if cutoutnp.size > 0 and np.any(np.isfinite(cutoutnp)):
                            cutout_max = float(np.nanmax(cutoutnp))
                            if np.isfinite(cutout_max) and cutout_max > 0:
                                cutoutn = cutoutnp / cutout_max * 1000.0
                                fits_file = os.path.join(
                                    self.cutout_path,
                                    f"cutout_fluxmax_{file_counter}.fits",
                                )
                                try:
                                    fits.writeto(fits_file, cutoutn, overwrite=True)
                                    cutoutn_stack.append(cutoutn)
                                except Exception as exc:
                                    # Failure to save a seeing cutout should not
                                    # invalidate the centroid measurement.
                                    self.logger.warning(
                                        "Failed to save normalized cutout for "
                                        f"star {i + 1}: {exc}"
                                    )

                # Pixel offset -> on-sky angular offset.
                # Map both the measured centroid and the expected catalog
                # position to the sky through the reference WCS and take
                # their difference. fra/fdec and dra_f/ddec_f are 1-based.
                # dx is the east offset (dRA * cos(dec)) and dy the north
                # offset, both in arcsec, as the ICS applies them with
                # SkyCoord.spherical_offsets_by.
                ra_m, dec_m = wcs.pixel_to_world_values(fra - 1.0, fdec - 1.0)
                ra_c, dec_c = wcs.pixel_to_world_values(
                    dra_f[i] - 1.0, ddec_f[i] - 1.0
                )
                dra_deg = (float(ra_m) - float(ra_c) + 180.0) % 360.0 - 180.0
                dx_val = dra_deg * math.cos(math.radians(float(dec_c))) * 3600.0
                dy_val = (float(dec_m) - float(dec_c)) * 3600.0
                if not np.isfinite(dx_val) or not np.isfinite(dy_val):
                    raise ValueError(f"Non-finite offset: dx={dx_val}, dy={dy_val}")
            except Exception as exc:
                counts["exc"] += 1
                self.logger.debug(f"Offset exception for star {i + 1}: {exc}")
                dx.append(0.0)
                dy.append(0.0)
                peakc.append(-1.0)
                continue

            dx.append(float(dx_val))
            dy.append(float(dy_val))
            peakc.append(float(peak_val))
            counts["ok"] += 1
            ok_peak_values.append(float(peak_val))

        if ok_peak_values:
            peak_stats = (
                f"peak(min/med/max)="
                f"{np.min(ok_peak_values):.2f}/{np.median(ok_peak_values):.2f}/"
                f"{np.max(ok_peak_values):.2f}"
            )
        else:
            peak_stats = "peak(min/med/max)=NA"

        self.logger.info(
            f"[peaks][file#{file_counter}] "
            f"stars={n_stars} "
            f"ok={counts['ok']} "
            f"nopeak={counts['nopeak']} "
            f"oob={counts['oob']} "
            f"edge={counts['edge']} "
            f"badflux={counts['badflux']} "
            f"neighbour={counts['neighbour']} "
            f"exc={counts['exc']} "
            f"thr={thr_val:.2f} "
            f"fwhm={fwhm:.2f}px "
            f"{peak_stats}"
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
        n_invalid = int(np.sum(peak_array <= 0))  # -1 포함 (nopeak/실패)
        n_low = int(np.sum((peak_array > 0) & (peak_array < self.peakmin)))
        n_high = int(np.sum(peak_array > self.peakmax))
        n_kept = int(
            np.sum((peak_array >= self.peakmin) & (peak_array <= self.peakmax))
        )

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
        valid_indices = np.where(
            (peak_array >= self.peakmin) & (peak_array <= self.peakmax)
        )
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
        clipped = sigma_clip(
                    distances,
                    sigma=3,
                    maxiters=5,
                    masked=True,
                )
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

    @staticmethod
    def _wcs_pixel_scale(wcs_obj) -> Optional[float]:
        """
        Mean pixel scale (arcsec/pix) of a celestial WCS, or None if unavailable.
        """
        try:
            from astropy.wcs.utils import proj_plane_pixel_scales

            scale = float(np.mean(proj_plane_pixel_scales(wcs_obj))) * 3600.0
        except Exception:
            return None
        return scale if np.isfinite(scale) and scale > 0 else None

    def cal_seeing(
        self,
        cutoutn_stack: List[np.ndarray],
        pixel_scale: Optional[float] = None,
    ) -> float:
        """
        FWHM (arcsec) of the median-stacked cutouts from an isotropic Gaussian fit.

        ``pixel_scale`` (arcsec/pix) is normally measured from the astrometry WCS;
        the config value ``settings.image_processing.pixel_scale`` is the fallback.
        """
        if pixel_scale is None:
            pixel_scale = self.pixel_scale

        if not cutoutn_stack:
            self.logger.warning(
                "No cutouts available for FWHM calculation. Returning NaN."
            )
            return float("nan")

        averaged_cutoutn = np.nanmedian(cutoutn_stack, axis=0)
        fits_file = os.path.join(self.cutout_path, "averaged_cutoutn.fits")

        try:
            fits.writeto(fits_file, averaged_cutoutn, overwrite=True)
        except Exception as exc:
            self.logger.error(f"Error saving averaged cutout: {exc}")

        if not np.all(np.isfinite(averaged_cutoutn)):
            self.logger.warning(
                "Averaged cutout contains non-finite values. "
                "Replacing them with the median value."
            )
            median_value = float(np.nanmedian(averaged_cutoutn))
            averaged_cutoutn = np.nan_to_num(
                averaged_cutoutn,
                nan=median_value,
                posinf=median_value,
                neginf=median_value,
            )

        y_size, x_size = averaged_cutoutn.shape
        xgrid, ygrid = np.meshgrid(
            np.arange(x_size, dtype=float),
            np.arange(y_size, dtype=float),
        )

        initial_guess = (
            float(np.nanmax(averaged_cutoutn)),
            float(x_size / 2.0),
            float(y_size / 2.0),
            1.0,
            float(np.nanmedian(averaged_cutoutn)),
        )

        try:
            params, _ = curve_fit(
                self.isotropic_gaussian_2d,
                (xgrid, ygrid),
                averaged_cutoutn.ravel(),
                p0=initial_guess,
                maxfev=10000,
            )

            amplitude, x_center, y_center, sigma, offset = params
            sigma = abs(float(sigma))

            if not np.isfinite(sigma) or sigma <= 0.0:
                self.logger.error(
                    f"Invalid fitted Gaussian sigma: {sigma}. Returning NaN."
                )
                return float("nan")

            fwhm_pixel = (
                2.0
                * math.sqrt(2.0 * math.log(2.0))
                * sigma
            )
            fwhm_arcsec = fwhm_pixel * pixel_scale

            self.logger.debug(
                "Gaussian fitting completed. "
                f"Amplitude={amplitude:.4f}, "
                f"Center=({x_center:.4f}, {y_center:.4f}), "
                f"Sigma={sigma:.4f} pixel, "
                f"Offset={offset:.4f}, "
                f"FWHM={fwhm_pixel:.4f} pixel, "
                f"Seeing={fwhm_arcsec:.4f} arcsec"
            )

            return float(fwhm_arcsec)

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
            self.logger.info(
                "========== Starting guide star calibration process =========="
            )

            astro_dir = self.final_astrometry_dir
            if not astro_dir:
                self.logger.error("Astrometry directory path missing.")
                return math.nan, math.nan, math.nan

            astro_files = sorted(glob.glob(os.path.join(astro_dir, "astro_*.fits")))
            if not astro_files:
                self.logger.error(
                    f"No astrometry FITS files found in {astro_dir} (astro_*.fits)."
                )
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
            wcs_scales: List[float] = []
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

                    scale = self._wcs_pixel_scale(wcs_obj)
                    if scale is not None:
                        wcs_scales.append(scale)

                    # 2) centroid는 raw에서 (background 포함)
                    raw_data_p = self.load_only_image(raw_file)
                    image_data, stddev = self.background(raw_data_p)
                    self.logger.debug(f"  Raw background stddev: {stddev:.4f}")

                    # 3) catalog 로드 + 필드 주변 별 선택
                    ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux = (
                        self.load_star_catalog(crval1, crval2)
                    )

                    ra_sel, dec_sel, flux_sel = self.select_stars(
                        ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux
                    )

                    if len(ra_sel) == 0:
                        self.logger.warning(
                            "No catalog stars selected for this field (after cuts)."
                        )
                        file_counter += 1
                        continue

                    # 4) catalog RA/DEC -> pixel 예상 위치 (astro WCS로 투영)
                    dra, ddec, dra_f, ddec_f = self.radec_to_xy_stars(
                        ra_sel, dec_sel, wcs_obj
                    )

                    # 5) raw 이미지에서 peak/centroid 찾고 arcsec offset 계산
                    dx_vals, dy_vals, peak_vals, cutoutn_stack = (
                        self.cal_centroid_offset(
                            dra,
                            ddec,
                            dra_f,
                            ddec_f,
                            stddev,
                            wcs_obj,
                            flux_sel,
                            file_counter,
                            cutoutn_stack,
                            image_data,  # raw background-subtracted image
                        )
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
                    self.logger.error(
                        f"Error processing astro={astro_file} raw={raw_file}: {exc}"
                    )
                    try:
                        self.logger.debug(traceback.format_exc())
                    except Exception:
                        pass
                    # ✅ critical이라도 전체를 죽이지 않고 soft-fail로 처리: 해당 파일만 skip
                    self.logger.warning(
                        "[skip] Critical error in this pair; skipping file."
                    )
                    file_counter += 1
                    continue

            if skipped:
                self.logger.warning(
                    f"Skipped {skipped} astro files due to missing raw matches."
                )

            if not dxpp or not dypp or not pindpp:
                self.logger.error(
                    "No valid guide star data collected. Calibration failed."
                )
                return math.nan, math.nan, math.nan

            dxp = np.concatenate(dxpp) if len(dxpp) else np.array([])
            dyp = np.concatenate(dypp) if len(dypp) else np.array([])
            pindp = np.concatenate(pindpp) if len(pindpp) else np.array([])

            self.logger.info(f"Total valid guide star offsets: {len(dxp)}")

            fdx, fdy = self.cal_final_offset(dxp, dyp, pindp)
            self.logger.info(
                f"Computed final offset: ΔX = {fdx} arcsec, ΔY = {fdy} arcsec"
            )

            pixel_scale = (
                float(np.median(wcs_scales)) if wcs_scales else self.pixel_scale
            )
            self.logger.info(
                f"Pixel scale for FWHM: {pixel_scale:.4f} arcsec/pix "
                f"({'astrometry WCS' if wcs_scales else 'config fallback'})"
            )
            fwhm = self.cal_seeing(cutoutn_stack, pixel_scale=pixel_scale)
            self.logger.info(f"Estimated FWHM from cutouts: {fwhm} arcsec")

            self.logger.info(
                "========== Guide star calibration completed successfully =========="
            )
            return fdx, fdy, fwhm

        except Exception as e:
            self.logger.error(f"exe_cal failed: {e}")
            try:
                self.logger.debug(traceback.format_exc())
            except Exception:
                pass
            return math.nan, math.nan, math.nan
