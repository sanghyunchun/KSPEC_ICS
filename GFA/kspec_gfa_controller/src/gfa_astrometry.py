#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Yongmin Yoon, Mingyeong Yang (yyoon@kasi.re.kr, mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: gfa_astrometry.py

import os
import sys
import time
import json
import glob
import numpy as np
import shutil
import subprocess
import logging
from typing import Optional, List, Union
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from astropy.io import fits
from astropy.table import Table, vstack
from astropy.utils.data import get_pkg_data_filename


def _get_default_config_path() -> str:
    """
    Returns the default configuration path for astrometry.
    Raises FileNotFoundError if the file does not exist.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(script_dir, "etc", "astrometry_params.json")
    if not os.path.isfile(default_path):
        raise FileNotFoundError(
            f"Default config file not found at: {default_path}. "
            "Please adjust `_get_default_config_path()` or place your config file there."
        )
    return default_path


def _get_default_logger() -> logging.Logger:
    """
    Returns a simple default logger if none is provided.
    """
    logger = logging.getLogger("gfa_astrometry_default")
    # Only set handler/formatter if not already set
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


class GFAAstrometry:
    """
    A class to perform astrometry operations on GFA images.

    Attributes
    ----------
    logger : logging.Logger
        Logger for logging messages.
    inpar : dict
        Dictionary containing parameters loaded from a JSON file.
    raws : list of str
        List of raw image filenames.
    """

    def __init__(self, config: str = None, logger: logging.Logger = None):
        """
        Initializes the gfa_astrometry class.

        Parameters
        ----------
        config : str, optional
            Path to the configuration JSON file. If None, a default path is used.
        logger : logging.Logger, optional
            Logger instance for logging. If None, a default logger is created.
        """
        # Use default config if none provided
        if config is None:
            config = _get_default_config_path()
        # Use default logger if none provided
        if logger is None:
            logger = _get_default_logger()

        self.logger = logger
        self.logger.info("Initializing gfa_astrometry class.")

        # Load parameters from JSON config
        with open(config, "r") as file:
            self.inpar = json.load(file)

        base_dir = os.path.abspath(os.path.dirname(__file__))

        # Extract directories from config
        self.dir_path = os.path.join(
            base_dir, self.inpar["paths"]["directories"]["raw_images"]
        )
        self.processed_dir = os.path.join(
            base_dir, self.inpar["paths"]["directories"]["processed_images"]
        )
        self.temp_dir = os.path.join(
            base_dir, self.inpar["paths"]["directories"]["temp_files"]
        )
        self.final_astrometry_dir = os.path.join(
            base_dir, self.inpar["paths"]["directories"]["final_astrometry_images"]
        )
        self.star_catalog_path = os.path.join(
            base_dir, self.inpar["paths"]["directories"]["star_catalog"]
        )
        self.cutout_path = os.path.join(
            base_dir,
            self.inpar["paths"]["directories"].get("cutout_directory", "cutout"),
        )

        # Create directories if they don't exist
        for directory in [
            self.dir_path,
            self.processed_dir,
            self.temp_dir,
            self.final_astrometry_dir,
            self.cutout_path,
        ]:
            os.makedirs(directory, exist_ok=True)

    def process_file(self, flname: str):
        """
        Processes a FITS file: subtracts sky values, crops the image,
        and saves the processed file.

        Parameters
        ----------
        flname : str
            Name of the FITS file to process.

        Returns
        -------
        tuple or None
            A tuple (ra_in, dec_in, dir_out, newname) if successful,
            otherwise None if the file was not found or an error occurred.
        """
        full_path = next(
            (p for p in self.input_paths if os.path.basename(p) == flname), None
        )
        if full_path is None:
            self.logger.error(f"Full path for {flname} not found.")
            return None

        # This might happen for each file, so let's move it to debug.
        self.logger.debug(f"Processing file: {flname}")
        data_in_path = full_path

        if not os.path.exists(data_in_path):
            self.logger.error(f"File not found: {data_in_path}")
            return None

        with fits.open(data_in_path, mode="update") as hdu_list:
            ori = hdu_list[0].data
            header = hdu_list[0].header
            ra_in, dec_in = header.get("RA"), header.get("DEC")

            # Extract sky values safely
            try:
                sky1 = ori[
                    self.inpar["settings"]["image_processing"]["skycoord"][
                        "pre_skycoord1"
                    ][0],
                    self.inpar["settings"]["image_processing"]["skycoord"][
                        "pre_skycoord1"
                    ][1],
                ]
                sky2 = ori[
                    self.inpar["settings"]["image_processing"]["skycoord"][
                        "pre_skycoord2"
                    ][0],
                    self.inpar["settings"]["image_processing"]["skycoord"][
                        "pre_skycoord2"
                    ][1],
                ]
            except IndexError:
                raise ValueError("Invalid sky coordinate indices in config.")

            # Subtract sky values in specified regions
            sub1 = tuple(
                self.inpar["settings"]["image_processing"]["sub_indices"]["sub_ind1"]
            )
            sub2 = tuple(
                self.inpar["settings"]["image_processing"]["sub_indices"]["sub_ind2"]
            )

            ori[sub1[0] : sub1[1], sub1[2] : sub1[3]] -= sky1
            ori[sub2[0] : sub2[1], sub2[2] : sub2[3]] -= sky2

            # Crop the image
            crop = tuple(self.inpar["settings"]["image_processing"]["crop_indices"])
            orif = ori[crop[0] : crop[1], crop[2] : crop[3]]

            # Define output directory and filename
            dir_out = self.processed_dir
            os.makedirs(dir_out, exist_ok=True)
            newname = f"proc_{flname}"
            data_file_path = os.path.join(dir_out, newname)

            # Write to a new FITS file
            fits.writeto(data_file_path, orif, hdu_list[0].header, overwrite=True)

            # Close the original FITS file
            hdu_list.close()

            return ra_in, dec_in, dir_out, newname

    def astrometry(self, ra_in: float, dec_in: float, dir_out: str, newname: str):
        """
        Performs astrometry on the processed FITS file.
        """
        self.logger.info(f"Starting astrometry process for {newname}.")

        solve_field_path = shutil.which("solve-field")
        if not solve_field_path:
            raise FileNotFoundError(
                "solve-field not found! Ensure it is installed and in PATH."
            )

        # Detailed path -> debug
        self.logger.debug(f"Using solve-field from: {solve_field_path}")

        scale_low, scale_high = self.inpar["astrometry"]["scale_range"]
        radius = self.inpar["astrometry"]["radius"]
        cpu_limit = self.inpar["settings"]["cpu"]["limit"]

        input_file_path = os.path.join(dir_out, newname)
        if not os.path.exists(input_file_path):
            self.logger.error(
                f"Input file for solve-field not found: {input_file_path}"
            )
            raise FileNotFoundError(
                f"Input file for solve-field not found: {input_file_path}"
            )

        # This is the actual system command => debug
        input_command = (
            f"{solve_field_path} --cpulimit {cpu_limit} --dir {self.temp_dir} --scale-units degwidth "
            f"--scale-low {scale_low} --scale-high {scale_high} "
            f"--no-verify --no-plots --crpix-center -O --ra {ra_in} --dec {dec_in} --radius {radius} {input_file_path}"
        )

        self.logger.debug(f"Running command: {input_command}")

        try:
            result = subprocess.run(
                input_command, shell=True, capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as e:
            self.logger.error(f"solve-field execution failed for {newname}")
            self.logger.error(f"solve-field stderr: {e.stderr}")
            raise RuntimeError(f"solve-field execution failed for {newname}") from e

        # Checking generated files => debug
        self.logger.debug(
            f"Checking generated files in {self.temp_dir} after solve-field execution."
        )
        list_files_command = f"ls -lh {self.temp_dir}"
        list_files = subprocess.run(
            list_files_command, shell=True, capture_output=True, text=True
        )
        self.logger.debug(f"Files in temp directory:\n{list_files.stdout}")

        solved_file_pattern = os.path.join(
            self.temp_dir, newname.replace(".fits", ".new")
        )
        solved_files = glob.glob(solved_file_pattern)

        if not solved_files:
            self.logger.error(
                f"Astrometry output file not found in {self.temp_dir}. "
                f"Expected pattern: {solved_file_pattern}"
            )
            self.logger.error(f"Files in directory: {os.listdir(self.temp_dir)}")
            raise FileNotFoundError(
                f"Astrometry output file not found: {solved_file_pattern}"
            )

        new_fits_file = solved_files[0]
        converted_fits_file = new_fits_file.replace(".new", ".fits")

        # Renaming can be debug
        self.logger.debug(f"Renaming {new_fits_file} to {converted_fits_file}")
        os.rename(new_fits_file, converted_fits_file)

        os.makedirs(self.final_astrometry_dir, exist_ok=True)
        dest_file_name = f"astro_{newname}"
        dest_path = os.path.join(self.final_astrometry_dir, dest_file_name)

        os.rename(converted_fits_file, dest_path)
        self.logger.info(f"Astrometry results moved to {dest_path}.")

        # Read the FITS header and extract CRVAL1, CRVAL2
        try:
            image_data_p, header = fits.getdata(dest_path, ext=0, header=True)
            crval1 = header["CRVAL1"]
            crval2 = header["CRVAL2"]
        except Exception as e:
            self.logger.error(f"Failed to read CRVAL1, CRVAL2 from {dest_path}: {e}")
            raise RuntimeError(
                f"Failed to extract astrometry data from {dest_path}"
            ) from e

        self.logger.info(
            f"Astrometry completed with CRVAL1: {crval1}, CRVAL2: {crval2}."
        )
        return crval1, crval2

    def star_catalog(self):
        """
        Combines multiple star catalog files into a single catalog.
        """
        self.logger.info("Starting star catalog generation.")

        if not self.temp_dir:
            self.logger.error("Temp directory is not set.")
            return

        if not self.star_catalog_path:
            self.logger.error("Star catalog path is not set.")
            return

        filepre = glob.glob(os.path.join(self.temp_dir, "*.corr"))
        # Move to debug so it's not spammy
        self.logger.debug(f"Found {len(filepre)} .corr files in {self.temp_dir}.")

        if not filepre:
            self.logger.error("No .corr files found in the temp directory.")
            return

        star_files_p = [os.path.basename(file) for file in filepre]
        star_files_p.sort()
        star_files = [os.path.join(self.temp_dir, file) for file in star_files_p]

        tables = []
        for file in star_files:
            # Moved to debug
            self.logger.debug(f"Processing .corr file: {file}")
            try:
                with fits.open(file) as hdul:
                    table_data = Table(hdul[1].data)
                    tables.append(table_data)
            except Exception as e:
                self.logger.error(f"Error reading {file}: {e}")

        if tables:
            combined_table = vstack(tables)
            combined_table.write(self.star_catalog_path, overwrite=True)
            self.logger.info(
                f"Star catalog generated and saved to {self.star_catalog_path}."
            )
        else:
            self.logger.warning(
                "No valid tables found for stacking. Skipping star catalog generation."
            )

    def rm_tempfiles(self):
        """
        Removes temporary files in `temp_dir`.
        """
        self.logger.info("Removing temporary files.")
        try:
            shutil.rmtree(self.temp_dir)
            os.makedirs(self.temp_dir, exist_ok=True)
            self.logger.debug(f"Temporary files removed from {self.temp_dir}.")
        except Exception as e:
            self.logger.error(f"Error removing temporary files: {e}")

    def combined_function(self, flname: str):
        """
        Combines process_file and astrometry for a single FITS file.
        """
        # Large repetitive steps => debug
        self.logger.debug(f"Starting combined function for file: {flname}.")

        result = self.process_file(flname)
        if result is None:
            raise RuntimeError(f"Processing failed for {flname}. Stopping execution.")

        try:
            ra_in, dec_in, dir_out, newname = result
        except TypeError as e:
            raise RuntimeError(
                f"Unexpected result format from process_file({flname}): {result}. Error: {e}"
            ) from e

        astrometry_result = self.astrometry(ra_in, dec_in, dir_out, newname)
        if astrometry_result is None:
            raise RuntimeError(f"Astrometry failed for {flname}. Stopping execution.")

        try:
            crval1, crval2 = astrometry_result
        except TypeError as e:
            raise RuntimeError(
                f"Unexpected result format from astrometry({newname}): {astrometry_result}. Error: {e}"
            ) from e

        self.logger.info(
            f"Combined function completed for {flname}. CRVAL1: {crval1}, CRVAL2: {crval2}."
        )
        return crval1, crval2

    def delete_all_files_in_dir(self, dir_path: str) -> int:
        """
        Delete all files in the specified directory using self.logger.

        Parameters
        ----------
        dir_path : str
            Path to the directory whose contents will be deleted.

        Returns
        -------
        int
            Number of files successfully deleted.
        """
        deleted_count = 0

        if not os.path.isdir(dir_path):
            self.logger.warning(f"Directory not found: {dir_path}")
            return deleted_count

        for filename in os.listdir(dir_path):
            file_path = os.path.join(dir_path, filename)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    deleted_count += 1
                    self.logger.debug(f"Deleted file: {file_path}")
                else:
                    self.logger.debug(f"Skipped non-file item: {file_path}")
            except Exception as e:
                self.logger.error(f"Failed to delete file {file_path}: {e}")

        self.logger.info(f"Deleted {deleted_count} files in directory: {dir_path}")
        return deleted_count

    def preproc(self, input_files: Optional[List[Union[str, Path]]] = None):
        """
        Preprocess FITS files.

        Parameters
        ----------
        input_files : list of str or Path, optional
            Full paths to FITS files to process. If not given, defaults to self.dir_path.

        Behavior
        --------
        - If astrometry results don't exist, performs astrometric processing via combined_function.
        - Otherwise, processes raw files via process_file.
        - Builds star catalog and removes temp files if full astrometry was run.
        """

        start_time = time.time()

        if input_files is None:
            filepre = glob.glob(os.path.join(self.dir_path, "*.fits"))
        else:
            filepre = [str(f) for f in input_files]
            self.dir_path = os.path.dirname(filepre[0])  # ✅ 여기에 위치해야 안전

        self.input_paths = sorted(filepre)  # full path
        self.raws = [os.path.basename(f) for f in filepre]
        self.logger.debug(f"Loaded {len(self.raws)} FITS files.")

        if not self.raws:
            self.logger.warning("No FITS files provided or found.")
            return

        self.logger.info(f"Starting preprocessing for {len(self.raws)} files.")

        # CASE 1: No astrometry output exists → run combined_function
        if not os.path.exists(self.final_astrometry_dir) or not os.listdir(
            self.final_astrometry_dir
        ):
            self.logger.info(
                "No astrometry results found. Running full astrometric solution."
            )

            crval1_results, crval2_results = [], []
            failed_files = []

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {
                    executor.submit(self.combined_function, flname): flname
                    for flname in self.raws
                }

                for future in as_completed(futures):
                    flname = futures[future]
                    try:
                        result = future.result()
                        if result is not None:
                            crval1, crval2 = result
                            crval1_results.append(crval1)
                            crval2_results.append(crval2)
                            self.logger.debug(
                                f"Processed {flname} → CRVAL1: {crval1}, CRVAL2: {crval2}"
                            )
                        else:
                            self.logger.warning(
                                f"Skipping {flname} due to processing error."
                            )
                            failed_files.append(flname)
                    except Exception as e:
                        self.logger.error(f"Error processing {flname}: {e}")
                        failed_files.append(flname)

            if failed_files:
                self.logger.warning(f"{len(failed_files)} files failed: {failed_files}")

            self.star_catalog()
            self.rm_tempfiles()

        # CASE 2: astrometry 이미 있음 → process_file만 실행
        else:
            self.logger.info(
                "Astrometry data already exists. Processing raw images separately."
            )
            failed_files = []

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {
                    executor.submit(self.process_file, flname): flname
                    for flname in self.raws
                }

                for future in as_completed(futures):
                    flname = futures[future]
                    try:
                        result = future.result()
                        if result is not None:
                            self.logger.debug(f"Processed {flname}")
                        else:
                            self.logger.warning(f"Skipping {flname} due to error.")
                            failed_files.append(flname)
                    except Exception as e:
                        self.logger.error(f"Error processing {flname}: {e}")
                        failed_files.append(flname)

            if failed_files:
                self.logger.warning(f"{len(failed_files)} files failed: {failed_files}")

        self.logger.info(
            f"Preprocessing completed in {time.time() - start_time:.2f} seconds."
        )

    def clear_raw_and_processed_files(self) -> None:
        """
        Delete all files in self.dir_path and self.processed_dir, and log the results.
        """
        self.logger.info("Deleting raw and processed files.")

        deleted_raw = self.delete_all_files_in_dir(self.dir_path)
        deleted_processed = self.delete_all_files_in_dir(self.processed_dir)

        self.logger.info(
            f"Deleted {deleted_raw} raw files and {deleted_processed} processed files."
        )
