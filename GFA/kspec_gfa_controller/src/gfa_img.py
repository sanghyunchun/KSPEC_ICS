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
        header["COMMENT"] = "FITS file created with custom header fields"
        self.logger.debug(f"FITS header details: {header}")

        # 5. Create and write FITS
        hdu = fits.PrimaryHDU(data=image_array, header=header)
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
        """
        Save an image array to a PNG file using zscale by default.
        """

        if bit_depth not in (8, 16):
            raise ValueError("bit_depth must be 8 or 16")

        # 1. Output directory
        if output_directory is None:
            output_directory = os.getcwd()

        if not os.path.exists(output_directory):
            try:
                os.makedirs(output_directory)
            except OSError as e:
                self.logger.error(f"Error creating directory {output_directory}: {e}")
                raise

        # 2. Ensure filename ends with .png
        if not filename.lower().endswith(".png"):
            filename += ".png"

        filename = filename.replace(":", "-")
        filepath = os.path.join(output_directory, filename)

        self.logger.debug(f"PNG file will be saved to: {filepath}")
        self.logger.debug(f"Image array shape: {image_array.shape}")

        # 3. Prepare image
        img = image_array.astype(np.float32)
        img = np.nan_to_num(img)

        # ---- zscale if vmin/vmax not provided ----
        if vmin is None or vmax is None:
            zscale = ZScaleInterval(contrast=0.25)
            try:
                vmin, vmax = zscale.get_limits(img)
                self.logger.debug(f"Using zscale limits: vmin={vmin}, vmax={vmax}")
            except Exception as e:
                self.logger.warning(
                    f"zscale failed ({e}), falling back to min/max"
                )
                vmin = np.nanmin(img)
                vmax = np.nanmax(img)

        if vmax <= vmin:
            self.logger.error("Invalid normalization range (vmax <= vmin)")
            raise ValueError("Invalid normalization range")

        # 4. Normalize
        img = np.clip(img, vmin, vmax)
        img = (img - vmin) / (vmax - vmin)

        if bit_depth == 8:
            img = (img * 255).astype(np.uint8)
            mode = "L"
        else:
            img = (img * 65535).astype(np.uint16)
            mode = "I;16"

        # 5. Save PNG
        try:
            pil_img = Image.fromarray(img, mode=mode)
            pil_img.save(filepath)
            self.logger.info(f"PNG file successfully saved to {filepath}")
        except OSError as e:
            self.logger.error(f"Error writing PNG file {filepath}: {e}")
            raise
