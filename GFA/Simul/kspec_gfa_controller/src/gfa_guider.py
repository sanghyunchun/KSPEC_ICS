#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Yongmin Yoon, Mingyeong Yang (yyoon@kasi.re.kr, mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: gfa_guider.py

import os
import sys
import json
import glob
import math
import warnings
import logging
from typing import Optional, Tuple, List, Union

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

    Raises
    ------
    FileNotFoundError
        If the default config file does not exist.

    Notes
    -----
    You can adjust this path as needed for your environment.
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

    Notes
    -----
    - Configures a StreamHandler at INFO level by default.
    - Adjust log levels or handlers as needed for your environment.
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
    A class for guide star operations using GFA (Guide Focus Alignment) data.
    Reads parameters from `astrometry_params.json` and performs star detection,
    offset calculation, and seeing (FWHM) measurements.

    Attributes
    ----------
    logger : logging.Logger
        Logger instance for logging messages.
    inpar : dict
        Configuration parameters loaded from JSON.
    processed_dir : str
        Directory containing processed images.
    final_astrometry_dir : str
        Directory containing final astrometry images.
    cutout_path : str
        Directory where star cutouts are saved.
    boxsize : int
        Box size for star centroiding.
    crit_out : float
        Critical threshold for offset computation.
    peakmax : float
        Maximum peak value for star selection.
    peakmin : float
        Minimum peak value for star selection.
    ang_dist : float
        Maximum angular distance for star selection (in degrees).
    pixel_scale : float
        Pixel scale for converting FWHM from pixels to arcseconds.
    """

    def __init__(
        self, config: Optional[str] = None, logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Initialize the GFAGuider by reading paths and parameters from JSON.

        Parameters
        ----------
        config : str, optional
            Path to the JSON configuration file. Defaults to a built-in path.
        logger : logging.Logger, optional
            A logger instance. If None, a default logger is created.

        Raises
        ------
        RuntimeError
            If the configuration file cannot be loaded or is malformed.
        """
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
        self.processed_dir = os.path.join(base_dir, dirs["processed_images"])
        self.final_astrometry_dir = os.path.join(
            base_dir, dirs["final_astrometry_images"]
        )
        self.cutout_path = os.path.join(base_dir, dirs["cutout_directory"])

        self.logger.debug(f"Processed dir: {self.processed_dir}")
        self.logger.debug(f"Final astro dir: {self.final_astrometry_dir}")
        self.logger.debug(f"Cutout dir: {self.cutout_path}")

        # 2) Guide star detection parameters
        self.boxsize = self.inpar["detection"]["box_size"]
        self.crit_out = self.inpar["detection"]["criteria"]["critical_outlier"]
        self.peakmax = self.inpar["detection"]["peak_detection"]["max"]
        self.peakmin = self.inpar["detection"]["peak_detection"]["min"]
        self.ang_dist = self.inpar["catalog_matching"]["tolerance"]["angular_distance"]
        self.pixel_scale = self.inpar["settings"]["image_processing"]["pixel_scale"]

        self.logger.info("GFAGuider setup complete.")

    def load_image_and_wcs(
        self, image_file: str
    ) -> Tuple[np.ndarray, fits.Header, WCS]:
        """
        Load image data and WCS from a FITS file.

        Parameters
        ----------
        image_file : str
            Path to the FITS file.

        Returns
        -------
        image_data_p : np.ndarray
            Image data array.
        header : fits.Header
            FITS header with metadata.
        wcs : astropy.wcs.WCS
            World Coordinate System object.

        Raises
        ------
        FileNotFoundError
            If the FITS file is not found.
        Exception
            For any other I/O or FITS-reading errors.
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

        Parameters
        ----------
        image_file : str
            Path to the FITS file.

        Returns
        -------
        image_data_p : np.ndarray
            The image data array.

        Raises
        ------
        FileNotFoundError
            If the file is not found.
        Exception
            For any other I/O or FITS-reading errors.
        """
        self.logger.debug(f"Loading image data from file: {image_file}")
        warnings.filterwarnings("ignore", category=AstropyWarning)
        return fits.getdata(image_file, ext=0)

    def background(self, image_data_p: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Perform sigma clipping to derive background and standard deviation.

        Parameters
        ----------
        image_data_p : np.ndarray
            Original image data array.

        Returns
        -------
        image_data : np.ndarray
            Background-subtracted image.
        stddev : float
            Standard deviation of the background.
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

        Parameters
        ----------
        crval1 : float
            Reference RA from WCS header (degrees).
        crval2 : float
            Reference DEC from WCS header (degrees).

        Returns
        -------
        ra1_rad, dec1_rad : float
            Reference RA/DEC in radians.
        ra2_rad, dec2_rad : np.ndarray
            Star catalog RA/DEC in radians.
        ra_p, dec_p : np.ndarray
            Star catalog RA/DEC in degrees.
        flux : np.ndarray
            Flux (or magnitude) values from the catalog.

        Raises
        ------
        FileNotFoundError
            If the star catalog file is not found.
        """
        base_dir = os.path.abspath(os.path.dirname(__file__))
        star_catalog_path = os.path.join(base_dir, "img", "combined_star.fits")
        self.logger.debug(f"Using star catalog file: {star_catalog_path}")

        if not os.path.exists(star_catalog_path):
            self.logger.error(f"Star catalog file not found: {star_catalog_path}")
            raise FileNotFoundError(f"Star catalog file not found: {star_catalog_path}")

        with fits.open(star_catalog_path) as hdul:
            data = hdul[1].data
            ra_p = data[self.inpar["catalog_matching"]["fields"]["ra_column"]]
            dec_p = data[self.inpar["catalog_matching"]["fields"]["dec_column"]]
            flux = data[self.inpar["catalog_matching"]["fields"]["mag_flux"]]

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
        Select guide stars based on angular distance and flux thresholds.

        Parameters
        ----------
        ra1_rad, dec1_rad : float
            Reference RA/DEC in radians.
        ra2_rad, dec2_rad : np.ndarray
            Star catalog RA/DEC in radians.
        ra_p, dec_p : np.ndarray
            Star catalog RA/DEC in degrees.
        flux : np.ndarray
            Flux (or magnitude) values from the catalog.

        Returns
        -------
        ra_selected : np.ndarray
            Selected RA values (degrees).
        dec_selected : np.ndarray
            Selected DEC values (degrees).
        flux_selected : np.ndarray
            Flux of selected stars.
        """
        self.logger.debug("Selecting stars based on angular distance and flux.")
        delta_sigma = np.arccos(
            np.sin(dec1_rad) * np.sin(dec2_rad)
            + np.cos(dec1_rad) * np.cos(dec2_rad) * np.cos(ra1_rad - ra2_rad)
        )
        angular_distance_degrees = np.degrees(delta_sigma)

        valid_flux = np.nan_to_num(flux, nan=0.0)
        mag_flux_min = self.inpar["catalog_matching"]["tolerance"]["mag_flux_min"]

        # Create mask for stars within angular distance and flux limit
        mask = (angular_distance_degrees < self.ang_dist) & (valid_flux > mag_flux_min)

        ra_selected = ra_p[mask]
        dec_selected = dec_p[mask]
        flux_selected = valid_flux[mask]

        self.logger.debug(f"Selected {len(ra_selected)} stars after filtering.")
        return ra_selected, dec_selected, flux_selected

    def radec_to_xy_stars(
        self, ra: np.ndarray, dec: np.ndarray, wcs: WCS
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Convert arrays of RA/DEC values into X/Y pixel positions, using NumPy’s
        vectorized rounding approach.

        Parameters
        ----------
        ra : np.ndarray
            The RA values (degrees) for N stars.
        dec : np.ndarray
            The DEC values (degrees) for N stars.
        wcs : WCS
            The WCS object for coordinate transformations.

        Returns
        -------
        dra, ddec : np.ndarray
            Integer pixel positions (1-based) for each star.
        dra_f, ddec_f : np.ndarray
            Floating-point pixel positions for each star.
        """
        self.logger.debug(
            "Converting RA/DEC arrays to X/Y pixel positions via WCS (np.round)."
        )

        x_pix, y_pix = wcs.world_to_pixel_values(ra, dec)

        # Use np.round() + .astype(int) to avoid the built-in round() that fails on arrays
        dra = np.round(x_pix).astype(int) + 1
        ddec = np.round(y_pix).astype(int) + 1

        # Keep floating versions without rounding
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

        self.logger.debug(f"Number of input stars: {len(dra)}")
        self.logger.debug(f"Standard deviation for thresholding: {stddev:.3f}")
        self.logger.debug(f"Box size: {boxsize}")
        self.logger.debug(f"Max flux among stars (cutoff 30000): {max_flux}")

        for i in range(len(dra)):
            try:
                self.logger.debug(f"\n-- Processing star {i+1} --")
                self.logger.debug(f"Initial integer (dra, ddec): ({dra[i]}, {ddec[i]})")
                self.logger.debug(
                    f"Initial float (dra_f, ddec_f): ({dra_f[i]:.3f}, {ddec_f[i]:.3f})"
                )
                self.logger.debug(f"Flux: {fluxn[i]}")

                # Extract a cutout around the star
                cutout = image_data[
                    int(ddec[i] - 1 - boxsize / 2) : int(ddec[i] - 1 + boxsize / 2 + 1),
                    int(dra[i] - 1 - boxsize / 2) : int(dra[i] - 1 + boxsize / 2 + 1),
                ]
                self.logger.debug(f"Cutout shape: {cutout.shape}")

                threshold = np.full(cutout.shape, 5 * stddev, dtype=float)
                peaks = pd.find_peaks(cutout, threshold, box_size=boxsize / 4, npeaks=1)

                x_peak = peaks["x_peak"][0]
                y_peak = peaks["y_peak"][0]
                peak_val = peaks["peak_value"][0]
                self.logger.debug(
                    f"Peak found at: ({x_peak}, {y_peak}), value: {peak_val:.2f}"
                )
                peakc.append(peak_val)

                nra = int(dra[i] - (0.5 * boxsize - x_peak))
                ndec = int(ddec[i] - (0.5 * boxsize - y_peak))
                self.logger.debug(
                    f"Peak translated to image coord: (nra={nra}, ndec={ndec})"
                )

                # Smaller centroid cutout
                cutout2 = image_data[
                    int(ndec - 1 - boxsize / 4) : int(ndec - 1 + boxsize / 4 + 1),
                    int(nra - 1 - boxsize / 4) : int(nra - 1 + boxsize / 4 + 1),
                ]
                self.logger.debug(f"Centroid cutout shape: {cutout2.shape}")

                # Save cutout for max flux star
                if fluxn[i] == max_flux:
                    cutoutnp = image_data[
                        int(ndec - 1 - boxsize / 2) : int(ndec - 1 + boxsize / 2 + 1),
                        int(nra - 1 - boxsize / 2) : int(nra - 1 + boxsize / 2 + 1),
                    ]
                    cutoutn = cutoutnp / np.max(cutoutnp) * 1000
                    fits_file = os.path.join(
                        self.cutout_path, f"cutout_fluxmax_{file_counter}.fits"
                    )
                    fits.writeto(fits_file, cutoutn, overwrite=True)
                    cutoutn_stack.append(cutoutn)
                    self.logger.debug(f"Saved flux-max cutout to: {fits_file}")

                # Centroid computation
                xcs, ycs = 0.0, 0.0
                for row in range(cutout2.shape[0]):
                    for col in range(cutout2.shape[1]):
                        val = cutout2[row, col]
                        xcs += val * col
                        ycs += val * row
                total_flux = float(np.sum(cutout2))
                xc = xcs / total_flux
                yc = ycs / total_flux
                self.logger.debug(
                    f"Centroid (xc, yc): ({xc:.2f}, {yc:.2f}), total flux: {total_flux:.2f}"
                )

                fra = nra - (boxsize / 4 - xc)
                fdec = ndec - (boxsize / 4 - yc)
                self.logger.debug(
                    f"Fractional position: (fra={fra:.3f}, fdec={fdec:.3f})"
                )

                # WCS transformation for dx, dy
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
                self.logger.debug(f"Offset (dx, dy): ({dx_val:.3f}, {dy_val:.3f})")

            except Exception as exc:
                dx.append(0)
                dy.append(0)
                peakc.append(-1)
                self.logger.warning(f"Error finding peaks for star {i+1}: {exc}")

        self.logger.debug("==== Finished centroid offset calculation ====")
        return dx, dy, peakc, cutoutn_stack

    def peak_select(
        self, dx: List[float], dy: List[float], peakc: List[float]
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Filter stars by peak intensity, discarding low or saturated peaks.

        Parameters
        ----------
        dx : list of float
            X offsets for all stars.
        dy : list of float
            Y offsets for all stars.
        peakc : list of float
            Peak values for all stars.

        Returns
        -------
        dxn, dyn : np.ndarray
            Filtered X/Y offsets for selected stars.
        pindn : np.ndarray
            Indices of the selected stars.
        """
        self.logger.debug("Selecting guide stars based on peak values.")
        peak_array = np.array(peakc)
        valid_indices = np.where(
            (peak_array > self.peakmin) & (peak_array < self.peakmax)
        )
        pindn = valid_indices[0]
        dxn = np.array([dx[i] for i in pindn])
        dyn = np.array([dy[i] for i in pindn])

        self.logger.debug(f"Selected {len(dxn)} guide stars after peak filtering.")
        return dxn, dyn, pindn

    def cal_final_offset(
        self, dxp: np.ndarray, dyp: np.ndarray, pindp: np.ndarray
    ) -> Tuple[Union[float, str], Union[float, str]]:
        """
        Calculate the final offset based on selected guide stars.

        Parameters
        ----------
        dxp, dyp : np.ndarray
            X, Y offsets for the selected guide stars.
        pindp : np.ndarray
            Indices of the selected stars.

        Returns
        -------
        fdx, fdy : float or str
            The final X, Y offsets in arcseconds, or 'Warning' if insufficient.
        """
        self.logger.debug("Calculating final offset using selected guide stars.")
        if len(pindp) < 1:
            self.logger.warning("No guide stars available for offset calculation.")
            return "Warning", "Warning"

        distances = np.sqrt(dxp**2 + dyp**2)
        clipped = sigma_clip(distances, sigma=3, maxiters=False)
        cdx = dxp[~clipped.mask]
        cdy = dyp[~clipped.mask]

        # Optionally remove min/max if more than 4 remain
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
        """
        2D Isotropic Gaussian function for curve fitting.

        Parameters
        ----------
        xy : tuple of np.ndarray
            (X, Y) meshgrid arrays.
        amp : float
            Amplitude of the Gaussian.
        x0, y0 : float
            Center coordinates of the Gaussian.
        sigma : float
            Gaussian sigma (standard deviation).
        offset : float
            Constant background offset.

        Returns
        -------
        np.ndarray
            Flattened Gaussian function values at each (x, y) point.
        """
        x, y = xy
        g = offset + amp * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2 * sigma**2))
        return g.ravel()

    def cal_seeing(self, cutoutn_stack: List[np.ndarray]) -> float:
        """
        Calculate the Full-Width at Half-Maximum (FWHM) of a star from stacked cutouts.

        Parameters
        ----------
        cutoutn_stack : list of np.ndarray
            A list of image cutouts, typically for the brightest star(s).

        Returns
        -------
        float
            The calculated FWHM in arcseconds. Returns NaN if no cutouts exist.
        """
        if not cutoutn_stack:
            self.logger.warning(
                "No cutouts available for FWHM calculation. Returning NaN."
            )
            return float("nan")

        # Median stack
        averaged_cutoutn = np.median(cutoutn_stack, axis=0)
        fits_file = os.path.join(self.cutout_path, "averaged_cutoutn.fits")

        # Try saving the stacked cutout for debugging
        try:
            fits.writeto(fits_file, averaged_cutoutn, overwrite=True)
            self.logger.debug(f"Saved averaged cutout to {fits_file}")
        except Exception as exc:
            self.logger.error(f"Error saving averaged cutout: {exc}")

        # Prepare meshgrid
        y_size, x_size = averaged_cutoutn.shape
        xgrid, ygrid = np.meshgrid(np.arange(x_size), np.arange(y_size))
        initial_guess = (
            float(np.max(averaged_cutoutn)),
            float(x_size // 2),
            float(y_size // 2),
            1.0,
            0.0,
        )

        # Fit the Gaussian
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

    def exe_cal(self) -> Tuple[float, float, float]:
        self.logger.info(
            "========== Starting guide star calibration process =========="
        )

        astro_dir = self.final_astrometry_dir
        proc_dir = self.processed_dir

        if not astro_dir or not proc_dir:
            self.logger.error("Astrometry or processed directory path missing.")
            return math.nan, math.nan, math.nan

        astro_files = sorted(glob.glob(os.path.join(astro_dir, "*.fits")))
        proc_files = sorted(glob.glob(os.path.join(proc_dir, "*.fits")))

        if not astro_files:
            self.logger.error(f"No astrometry FITS files found in {astro_dir}.")
            return math.nan, math.nan, math.nan
        if not proc_files:
            self.logger.error(f"No processed FITS files found in {proc_dir}.")
            return math.nan, math.nan, math.nan

        self.logger.info(
            f"Found {len(astro_files)} astrometry and {len(proc_files)} processed files."
        )

        dxpp, dypp, pindpp = [], [], []
        cutoutn_stack: List[np.ndarray] = []
        file_counter = 1

        for astro_file, proc_file in zip(astro_files, proc_files):
            try:
                self.logger.info(f"\n-- Processing pair #{file_counter}:")
                self.logger.info(f"  Astrometry file: {astro_file}")
                self.logger.info(f"  Processed file:  {proc_file}")

                # Load image + WCS
                image_data_x, header, wcs_obj = self.load_image_and_wcs(astro_file)
                crval1, crval2 = header["CRVAL1"], header["CRVAL2"]
                self.logger.debug(f"  CRVAL1: {crval1:.6f}, CRVAL2: {crval2:.6f}")

                image_data_p = self.load_only_image(proc_file)
                image_data, stddev = self.background(image_data_p)
                self.logger.debug(f"  Background stddev: {stddev:.4f}")

                # Star catalog
                (ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux) = (
                    self.load_star_catalog(crval1, crval2)
                )
                self.logger.debug(f"  Loaded {len(ra_p)} stars from catalog.")

                ra_sel, dec_sel, flux_sel = self.select_stars(
                    ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux
                )
                self.logger.debug(
                    f"  Selected {len(ra_sel)} guide stars after filtering."
                )

                dra, ddec, dra_f, ddec_f = self.radec_to_xy_stars(
                    ra_sel, dec_sel, wcs_obj
                )
                self.logger.debug("  Converted RA/DEC to pixel coordinates.")

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
                    image_data,
                )
                self.logger.debug(f"  Centroid offset returned {len(dx_vals)} stars.")

                file_counter += 1

                dxn, dyn, pindn = self.peak_select(dx_vals, dy_vals, peak_vals)
                self.logger.debug(
                    f"  After peak filtering: {len(dxn)} offsets retained."
                )

                dxpp.append(dxn)
                dypp.append(dyn)
                pindpp.append(pindn)

            except Exception as exc:
                self.logger.error(
                    f"Error processing {astro_file} & {proc_file}: {exc}", exc_info=True
                )
                raise RuntimeError(
                    f"Critical error in guide star processing for {astro_file}"
                ) from exc

        if not dxpp or not dypp or not pindpp:
            self.logger.error("No valid guide star data collected. Calibration failed.")
            return math.nan, math.nan, math.nan

        dxp = np.concatenate(dxpp)
        dyp = np.concatenate(dypp)
        pindp = np.concatenate(pindpp)

        self.logger.info(f"Total valid guide star offsets: {len(dxp)}")

        fdx, fdy = self.cal_final_offset(dxp, dyp, pindp)
        self.logger.info(
            f"Computed final offset: ΔX = {fdx:.4f} arcsec, ΔY = {fdy:.4f} arcsec"
        )

        fwhm = self.cal_seeing(cutoutn_stack)
        self.logger.info(f"Estimated FWHM from cutouts: {fwhm:.3f} arcsec")

        self.logger.info(
            "========== Guide star calibration completed successfully =========="
        )
        return fdx, fdy, fwhm
