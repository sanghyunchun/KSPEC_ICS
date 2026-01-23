#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-08-09
# @Filename: gfa_img.py

import os
from datetime import datetime
from typing import Optional

import numpy as np
from astropy.io import fits
from astropy.visualization import ZScaleInterval
import logging
from PIL import Image

from scipy.ndimage import maximum_filter, median_filter

__all__ = ["GFAImage"]


class GFAImage:
    """
    Class for handling GFA image data and saving it to FITS files with extended headers.

    Attributes
    ----------
    logger : logging.Logger
        A logger instance for logging messages.
    """

    def __init__(self, logger: logging.Logger) -> None:
        """
        Initialize the GFAImage object with a logger instance.

        Parameters
        ----------
        logger : logging.Logger
            A logger instance for logging messages.
        """
        self.logger = logger

    def save_fits(
        self,
        image_array: np.ndarray,
        filename: str,
        exptime: float,
        telescope: str = "KMTNET",
        instrument: str = "KSPEC-GFA",
        observer: str = "Mingyeong",
        object_name: str = "Unknown",
        date_obs: Optional[str] = None,
        time_obs: Optional[str] = None,
        ra: Optional[str] = None,
        dec: Optional[str] = None,
        output_directory: Optional[str] = None,
    ) -> None:
        """
        Save an image array to a FITS file with an extended header.

        Parameters
        ----------
        image_array : numpy.ndarray
            The 2D image data to save.
        filename : str
            The name of the FITS file (without extension or with .fits).
        exptime : float
            The exposure time of the image in seconds.
        telescope : str, optional
            The name of the telescope (default "KMTNET").
        instrument : str, optional
            The name of the instrument (default "KSPEC-GFA").
        observer : str, optional
            The name of the observer (default "Mingyeong").
        object_name : str, optional
            The name of the observed object (default "Unknown").
        date_obs : str, optional
            The observation date in "YYYY-MM-DD" format. If None, uses the current date.
        time_obs : str, optional
            The observation time in "HH:MM:SS" format. If None, uses the current time.
        ra : str, optional
            The right ascension of the observed object (default "UNKNOWN" if None).
        dec : str, optional
            The declination of the observed object (default "UNKNOWN" if None).
        output_directory : str, optional
            The directory where the FITS file will be saved. If None, uses the current
            working directory.

        Raises
        ------
        OSError
            If there is an error creating or writing to the specified output directory.
        """
        # 1. Determine output directory
        if output_directory is None:
            output_directory = os.getcwd()

        if not os.path.exists(output_directory):
            try:
                os.makedirs(output_directory)
            except OSError as e:
                self.logger.error(
                    f"Error creating directory {output_directory}: {e}. "
                    "Check permissions or path validity."
                )
                raise

        # 2. Ensure filename ends with .fits
        if not filename.lower().endswith(".fits"):
            filename += ".fits"

        filename = filename.replace(":", "-")  # Windows-safe

        filepath = os.path.join(output_directory, filename)
        self.logger.debug(f"FITS file will be saved to: {filepath}")
        self.logger.debug(f"Image array shape: {image_array.shape}")

        # 3. Default date/time if not provided
        now = datetime.now()
        if date_obs is None:
            date_obs = now.strftime("%Y-%m-%d")
            self.logger.warning("No date_obs provided. Using current date.")
        if time_obs is None:
            time_obs = now.strftime("%H:%M:%S")
            self.logger.warning("No time_obs provided. Using current time.")

        # 4. Construct FITS header
        header = fits.Header()
        header["SIMPLE"] = True
        header["BITPIX"] = -32
        header["NAXIS"] = 2
        header["NAXIS1"] = image_array.shape[1]
        header["NAXIS2"] = image_array.shape[0]
        header["CTYPE1"] = "PIXEL"
        header["CTYPE2"] = "PIXEL"

        header["TELESCOP"] = telescope
        header["INSTRUME"] = instrument
        header["OBSERVER"] = observer
        header["OBJECT"] = object_name
        header["DATE-OBS"] = date_obs
        header["TIME-OBS"] = time_obs
        header["RA"] = ra if ra is not None else "UNKNOWN"
        header["DEC"] = dec if dec is not None else "UNKNOWN"
        header["EXPTIME"] = exptime
        header["COMMENT"] = "FITS file created with custom header fields and hot pixel removed"
        self.logger.debug(f"FITS header details: {header}")

        # 5. Create and write FITS
        cleaned = self.hot_pixel_removal_median_ratio(image_array, factor=1.5, n_iter=2)
        hdu = fits.PrimaryHDU(data=cleaned, header=header)
        hdul = fits.HDUList([hdu])

        try:
            hdul.writeto(filepath, overwrite=True)
            self.logger.info(f"FITS file successfully saved to {filepath}")
        except OSError as e:
            self.logger.error(f"Error writing FITS file {filepath}: {e}")
            raise

    def save_png(
        self,
        image_array: np.ndarray,
        filename: str,
        output_directory: Optional[str] = None,
        vmin: Optional[float] = None,
        vmax: Optional[float] = None,
        bit_depth: int = 8,
    ) -> None:

        if bit_depth not in (8, 16):
            raise ValueError("bit_depth must be 8 or 16")

        if output_directory is None:
            output_directory = os.getcwd()

        os.makedirs(output_directory, exist_ok=True)

        if not filename.lower().endswith(".png"):
            filename += ".png"

        filename = filename.replace(":", "-")
        filepath = os.path.join(output_directory, filename)

        # --- prepare image ---
        img = image_array.astype(np.float32)
        img = np.nan_to_num(img)

        img_min = np.nanmin(img)
        img_max = np.nanmax(img)

        # =====================================================
        # 1. FLAT IMAGE DETECTION (강력 추천)
        # =====================================================
        if img_max == img_min:
            self.logger.warning(
                f"Flat image detected (value={img_min}); saving black image"
            )

            if bit_depth == 8:
                out = np.zeros_like(img, dtype=np.uint8)
                mode = "L"
            else:
                out = np.zeros_like(img, dtype=np.uint16)
                mode = "I;16"

            Image.fromarray(out, mode=mode).save(filepath)
            return

        # =====================================================
        # 2. Determine vmin / vmax (zscale safe)
        # =====================================================
        if vmin is None or vmax is None:
            try:
                zscale = ZScaleInterval(contrast=0.25)
                vmin, vmax = zscale.get_limits(img)

                if vmax <= vmin:
                    self.logger.warning(
                        f"zscale returned invalid range "
                        f"(vmin={vmin}, vmax={vmax}); falling back to min/max"
                    )
                    vmin, vmax = img_min, img_max

            except Exception as e:
                self.logger.warning(
                    f"zscale failed ({e}); falling back to min/max"
                )
                vmin, vmax = img_min, img_max

        # final safety guard
        if vmax <= vmin:
            self.logger.error(
                f"Invalid normalization range even after fallback "
                f"(vmin={vmin}, vmax={vmax})"
            )
            raise ValueError("Invalid normalization range")

        # =====================================================
        # 3. Normalize
        # =====================================================
        img = np.clip(img, vmin, vmax)
        img = (img - vmin) / (vmax - vmin)

        if bit_depth == 8:
            img = (img * 255).astype(np.uint8)
            mode = "L"
        else:
            img = (img * 65535).astype(np.uint16)
            mode = "I;16"

        # =====================================================
        # 4. Save PNG
        # =====================================================
        Image.fromarray(img, mode=mode).save(filepath)
        self.logger.info(f"PNG file saved: {filepath}")

    @staticmethod
    def hot_pixel_removal_median_ratio(
        img: np.ndarray,
        factor: float = 5.0,            # 주변 median의 몇 배 이상이면 제거할지
        n_iter: int = 1,
        mode: str = "mirror",
        saturated_value: int | float | None = None,
        eps: float = 1e-6,              # median이 0 근처일 때 0나눔/과잉검출 방지
        abs_threshold: float | None = None,  # (선택) |P - median|이 이것보다 커야 제거
        keep_dtype: bool = True,
    ):
        """
        주변 8픽셀 median을 기준으로:
        P > median_neighbors * factor  이면 핫픽셀로 보고,
        해당 픽셀을 median_neighbors로 치환.

        abs_threshold를 같이 쓰면 (P - median) 절대 차이도 커야 제거되므로
        어두운 배경에서 과잉 검출되는 것을 줄일 수 있습니다.
        """
        img = np.asarray(img)
        work = img.astype(np.float32, copy=True)

        # 중앙 제외한 8-neighbor footprint
        footprint = np.array([[1, 1, 1],
                            [1, 0, 1],
                            [1, 1, 1]], dtype=np.uint8)

        for _ in range(max(1, int(n_iter))):
            med_nb = median_filter(work, footprint=footprint, mode=mode)

            # ratio 조건: P > median * factor
            denom = np.maximum(np.abs(med_nb), eps)   # median이 0일 때 폭주 방지
            mask = work > denom * float(factor)

            # (선택) 절대 차이 조건도 추가
            if abs_threshold is not None:
                mask &= (work - med_nb) > float(abs_threshold)

            # saturation 값은 제외하고 싶다면
            if saturated_value is not None:
                mask &= (work != float(saturated_value))

            # 치환
            work[mask] = med_nb[mask]

        # dtype 복구
        if keep_dtype:
            if np.issubdtype(img.dtype, np.integer):
                info = np.iinfo(img.dtype)
                work = np.clip(np.rint(work), info.min, info.max).astype(img.dtype)
            else:
                work = work.astype(img.dtype)

        return work
