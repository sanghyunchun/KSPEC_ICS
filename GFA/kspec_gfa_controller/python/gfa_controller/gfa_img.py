#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-08-09
# @Filename: gfa_img.py

import os
from astropy.io import fits
from datetime import datetime

__all__ = ["gfa_img"]

class gfa_img:
    def __init__(self, logger):
        self.logger = logger
    
    def save_fits(
        self,
        image_array,
        filename,
        exptime,
        telescope="KMTNET",
        instrument="KSPEC-GFA",
        observer="Mingyeong",
        object_name="Unknown",
        date_obs=None,
        time_obs=None,
        ra=None,
        dec=None,
        output_directory=None,
    ):
        """
        Save an image array to a FITS file with an extended header.

        Parameters
        ----------
        image_array : numpy.ndarray
            The image data to save, should be a 2D array.
        filename : str
            The name of the FITS file to save.
        exptime : float
            The exposure time of the image in seconds.
        telescope : str, optional
            The name of the telescope (default is "KMTNET").
        instrument : str, optional
            The name of the instrument (default is "KSPEC-GFA").
        observer : str, optional
            The name of the observer (default is "Mingyeong").
        object_name : str, optional
            The name of the observed object (default is "Unknown").
        date_obs : str, optional
            The observation date in "YYYY-MM-DD" format
            (default is None, which means "UNKNOWN").
        time_obs : str, optional
            The observation time in "HH:MM:SS" format
            (default is None, which means "UNKNOWN").
        ra : str, optional
            The right ascension of the observed object
            (default is None, which means "UNKNOWN").
        dec : str, optional
            The declination of the observed object
            (default is None, which means "UNKNOWN").
        output_directory : str, optional
            The directory where the FITS file will be saved (default is "save").

        Raises
        ------
        OSError
            If the directory for saving the FITS file cannot be created or written to.
        """
        # Ensure output directory exists
        if not os.path.exists(output_directory):
            try:
                os.makedirs(output_directory)
            except OSError as e:
                self.logger.error(f"Error creating directory {output_directory}: {e}")
                raise

        # Define full path for the FITS file
        filepath = os.path.join(output_directory, filename)
        self.logger.debug(f"FITS file will be saved to: {filepath}")

        # Log the image array size
        self.logger.debug(f"Image array shape: {image_array.shape}")

        # 현재 날짜와 시간을 가져옵니다.
        now = datetime.now()

        # 날짜와 시간을 포맷팅합니다.
        date_str = now.strftime("%Y-%m-%d")  # 예: 2024-08-09
        time_str = now.strftime("%H:%M:%S")  # 예: 15:54:47

        # Create a FITS header
        header = fits.Header()
        header["SIMPLE"] = True
        header["BITPIX"] = -32
        header["NAXIS"] = 2
        header["NAXIS1"] = image_array.shape[1]
        header["NAXIS2"] = image_array.shape[0]
        header["CTYPE1"] = "PIXEL"
        header["CTYPE2"] = "PIXEL"

        # Additional header information
        header["TELESCOP"] = telescope
        header["INSTRUME"] = instrument
        header["OBSERVER"] = observer
        header["OBJECT"] = object_name
        header["DATE-OBS"] = date_str if date_obs is None else date_obs
        header["TIME-OBS"] = time_str if time_obs is None else time_obs
        header["RA"] = ra if ra is not None else "UNKNOWN"
        header["DEC"] = dec if dec is not None else "UNKNOWN"
        header["EXPTIME"] = exptime
        header["COMMENT"] = "FITS file created with custom header fields"
        
        # 망원경 point 방향 (ra, dec)
        
        # Log header details
        self.logger.debug(f"FITS header details: {header}")
        
        # Create a PrimaryHDU object with the image data and header
        hdu = fits.PrimaryHDU(data=image_array, header=header)

        # Create an HDUList and write it to a FITS file
        hdul = fits.HDUList([hdu])
        try:
            hdul.writeto(filepath, overwrite=True)
            self.logger.info(f"FITS file successfully saved to {filepath}")
        except OSError as e:
            self.logger.error(f"Error writing FITS file {filepath}: {e}")
            raise
