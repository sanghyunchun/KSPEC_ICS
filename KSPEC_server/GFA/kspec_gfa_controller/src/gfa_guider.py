#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Yongmin Yoon (yyoon@kasi.re.kr), Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-08-29
# @Filename: gfa_guider.py

import os
import glob
import json
import warnings
import numpy as np
import photutils.detection as pd

from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clip
from astropy.utils.exceptions import AstropyWarning

class gfa_guider:
    """
    A class to handle guide star operations using GFA (Guide Focus Alignment) data.

    Attributes
    ----------
    logger : logging.Logger
        Logger for logging messages.
    inpar : dict
        Dictionary containing parameters loaded from a JSON file.
    boxsize : int
        Size of the box used for star centroiding.
    crit_out : float
        Critical threshold for offset computation.
    peakmax : float
        Maximum peak value for star selection.
    peakmin : float
        Minimum peak value for star selection.
    ang_dist : float
        Maximum angular distance for star selection.
    """

    def __init__(self, config_file, logger):
        """
        Initialize the gfa_guider class with a configuration file.

        Parameters
        ----------
        config_file : str
            Path to the JSON file containing the input parameters.
        logger : logging.Logger
            Logger instance for logging.
        """
        self.logger = logger
        self.logger.info("Initializing gfa_guider class.")
        
        # Load dictionary from JSON file
        with open(config_file, 'r') as file:
            self.inpar = json.load(file)

        # Default input for deriving offsets
        self.boxsize = self.inpar.get('boxsize')
        self.crit_out = self.inpar.get('crit_out')
        self.peakmax = self.inpar.get('peakmax')
        self.peakmin = self.inpar.get('peakmin')
        self.ang_dist = self.inpar.get('ang_dist')

    def load_image_and_wcs(self, image_file):
        """
        Load image data and WCS information from a FITS file.

        Parameters
        ----------
        image_file : str
            Path to the FITS file containing the image.

        Returns
        -------
        image_data_p : ndarray
            The image data array.
        header : Header
            The FITS header.
        wcs : WCS
            The WCS (World Coordinate System) object.
        """
        self.logger.info(f"Loading image and WCS from file: {image_file}")
        image_data_p, header = fits.getdata(image_file, ext=0, header=True)
        wcs = WCS(header)
        return image_data_p, header, wcs

    def load_only_image(self, image_file):
        """
        Load only the image data from a FITS file.

        Parameters
        ----------
        image_file : str
            Path to the FITS file containing the image.

        Returns
        -------
        image_data_p : ndarray
            The image data array.
        """
        self.logger.info(f"Loading image data from file: {image_file}")
        warnings.filterwarnings('ignore', category=AstropyWarning)
        image_data_p = fits.getdata(image_file, ext=0)
        return image_data_p

    def background(self, image_data_p):
        """
        Perform sigma clipping to derive background and its standard deviation.

        Parameters
        ----------
        image_data_p : ndarray
            The image data array.

        Returns
        -------
        image_data : ndarray
            The background-subtracted image data.
        stddev : float
            The standard deviation of the background.
        """
        self.logger.info("Performing sigma clipping to derive background and standard deviation.")
        image_data = np.zeros_like(image_data_p, dtype=float)
        x_split = 511

        region1 = image_data_p[:, :x_split]
        sigclip1 = sigma_clip(region1, sigma=3, maxiters=False, masked=False)
        avg1 = np.mean(sigclip1)
        image_data[:, :x_split] = region1 - avg1

        region2 = image_data_p[:, x_split:]
        sigclip2 = sigma_clip(region2, sigma=3, maxiters=False, masked=False)
        avg2 = np.mean(sigclip2)
        image_data[:, x_split:] = region2 - avg2

        sigclip = sigma_clip(image_data, sigma=3, maxiters=False, masked=False)
        stddev = np.std(sigclip)

        self.logger.info(f"Background subtraction completed with standard deviation: {stddev:.4f}")
        return image_data, stddev

    def load_star_catalog(self, crval1, crval2):
        """
        Load the guide star catalog.

        Parameters
        ----------
        crval1 : float
            The reference RA value from the WCS header.
        crval2 : float
            The reference DEC value from the WCS header.

        Returns
        -------
        ra1_rad : ndarray
            The reference RA value in radians.
        dec1_rad : ndarray
            The reference DEC value in radians.
        ra2_rad : ndarray
            The RA values from the star catalog in radians.
        dec2_rad : ndarray
            The DEC values from the star catalog in radians.
        ra_p : ndarray
            The RA values from the star catalog.
        dec_p : ndarray
            The DEC values from the star catalog.
        flux : ndarray
            The flux values from the star catalog.
        """
        self.logger.info("Loading guide star catalog.")
        file_name = self.inpar.get('starcata')
        with fits.open(file_name) as hdul:
            data = hdul[1].data
            ra_p = data[self.inpar.get('ra_c')]
            dec_p = data[self.inpar.get('dec_c')]
            flux = data[self.inpar.get('mag/flux')]

        ra1_rad = np.radians(crval1)
        dec1_rad = np.radians(crval2)
        ra2_rad = np.radians(ra_p)
        dec2_rad = np.radians(dec_p)

        self.logger.info(f"Guide star catalog loaded with {len(ra_p)} stars.")
        return ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux

    def select_stars(self, ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux):
        """
        Select stars based on angular distance and flux.

        Parameters
        ----------
        ra1_rad : ndarray
            The reference RA value in radians.
        dec1_rad : ndarray
            The reference DEC value in radians.
        ra2_rad : ndarray
            The RA values from the star catalog in radians.
        dec2_rad : ndarray
            The DEC values from the star catalog in radians.
        ra_p : ndarray
            The RA values from the star catalog.
        dec_p : ndarray
            The DEC values from the star catalog.
        flux : ndarray
            The flux values from the star catalog.

        Returns
        -------
        ra : ndarray
            Selected RA values.
        dec : ndarray
            Selected DEC values.
        """
        self.logger.info("Selecting stars based on angular distance and flux.")
        delta_sigma = np.arccos(
            np.sin(dec1_rad) * np.sin(dec2_rad) +
            np.cos(dec1_rad) * np.cos(dec2_rad) * np.cos(ra1_rad - ra2_rad)
        )
        angular_distance_degrees = np.degrees(delta_sigma)
        mask = (angular_distance_degrees < self.ang_dist) & (flux > self.inpar.get('mag/fluxmin'))
        ra = ra_p[mask]
        dec = dec_p[mask]
        self.logger.info(f"Selected {len(ra)} stars.")
        return ra, dec

    def radec_to_xy_stars(self, ra, dec, wcs):
        """
        Convert RA/DEC of guide stars into X/Y positions in the image.

        Parameters
        ----------
        ra : ndarray
            The RA values of the selected stars.
        dec : ndarray
            The DEC values of the selected stars.
        wcs : WCS
            The WCS (World Coordinate System) object.

        Returns
        -------
        dra : ndarray
            The X positions of the stars (rounded to nearest pixel).
        ddec : ndarray
            The Y positions of the stars (rounded to nearest pixel).
        dra_f : ndarray
            The precise X positions of the stars.
        ddec_f : ndarray
            The precise Y positions of the stars.
        """
        self.logger.info("Converting RA/DEC to X/Y positions in the image.")
        dra = np.zeros(len(ra), dtype=float)
        ddec = np.zeros(len(ra), dtype=float)
        dra_f = np.zeros(len(ra), dtype=float)
        ddec_f = np.zeros(len(ra), dtype=float)
        for ii in range(len(ra)):
            dra_p, ddec_p = wcs.world_to_pixel_values(ra[ii], dec[ii])
            dra[ii] = np.round(dra_p) + 1
            ddec[ii] = np.round(ddec_p) + 1
            dra_f[ii] = dra_p + 1
            ddec_f[ii] = ddec_p + 1
        self.logger.info("Conversion to X/Y positions completed.")
        return dra, ddec, dra_f, ddec_f

    def cal_centroid_offset(self, dra, ddec, dra_f, ddec_f, stddev, wcs, image_data):
        """
        Calculate the centroid offset for guide stars.

        Parameters
        ----------
        dra : ndarray
            The X positions of the stars (rounded to nearest pixel).
        ddec : ndarray
            The Y positions of the stars (rounded to nearest pixel).
        dra_f : ndarray
            The precise X positions of the stars.
        ddec_f : ndarray
            The precise Y positions of the stars.
        stddev : float
            The standard deviation of the background.
        wcs : WCS
            The WCS (World Coordinate System) object.
        image_data : ndarray
            The image data array.

        Returns
        -------
        dx : list
            List of X offsets.
        dy : list
            List of Y offsets.
        peakc : list
            List of peak values.
        """
        self.logger.info("Calculating centroid offsets for guide stars.")
        dx = []
        dy = []
        peakc = []
        for jj in range(len(dra)):
            try:
                cutout = image_data[
                    int(ddec[jj] - 1 - self.boxsize / 2): int(ddec[jj] - 1 + self.boxsize / 2 + 1),
                    int(dra[jj] - 1 - self.boxsize / 2): int(dra[jj] - 1 + self.boxsize / 2 + 1)
                ]

                thres = np.zeros((cutout.shape[0], cutout.shape[1]), dtype=float) + 5 * stddev
                peak = pd.find_peaks(cutout, thres, box_size=self.boxsize / 4, npeaks=1)

                x_peak = peak['x_peak'][0]
                y_peak = peak['y_peak'][0]
                peakv = peak['peak_value'][0]

                peakc.append(peakv)

                nra = int(dra[jj] - (0.5 * self.boxsize - x_peak))
                ndec = int(ddec[jj] - (0.5 * self.boxsize - y_peak))

                cutout2 = image_data[
                    int(ndec - 1 - self.boxsize / 4): int(ndec - 1 + self.boxsize / 4 + 1),
                    int(nra - 1 - self.boxsize / 4): int(nra - 1 + self.boxsize / 4 + 1)
                ]

                xcs = sum(cutout2[kk, ll] * ll for kk in range(cutout2.shape[0]) for ll in range(cutout2.shape[1]))
                ycs = sum(cutout2[kk, ll] * kk for kk in range(cutout2.shape[0]) for ll in range(cutout2.shape[1]))

                xc = xcs / np.sum(cutout2)
                yc = ycs / np.sum(cutout2)

                fra = nra - (self.boxsize / 4 - xc)
                fdec = ndec - (self.boxsize / 4 - yc)

                x1 = fra
                y1 = fdec
                x2 = fra + 1
                y2 = fdec
                ra1, dec1 = wcs.pixel_to_world_values(x1, y1)
                ra2, dec2 = wcs.pixel_to_world_values(x2, y2)
                x1d = (ra2 - ra1) * 3600
                x2d = (dec2 - dec1) * 3600

                x1 = fra
                y1 = fdec
                x2 = fra
                y2 = fdec + 1
                ra1, dec1 = wcs.pixel_to_world_values(x1, y1)
                ra2, dec2 = wcs.pixel_to_world_values(x2, y2)
                y1d = (ra2 - ra1) * 3600
                y2d = (dec2 - dec1) * 3600

                dx.append((fra - dra_f[jj]) * x1d + (fdec - ddec_f[jj]) * x2d)
                dy.append((fra - dra_f[jj]) * y1d + (fdec - ddec_f[jj]) * y2d)

            except Exception as e:
                dx.append(0)
                dy.append(0)
                peakc.append(-1)
                self.logger.warning(f"Error finding peaks: {e}")

        self.logger.info("Centroid offset calculation completed.")
        return dx, dy, peakc

    def peak_select(self, dx, dy, peakc):
        """
        Select guide stars based on peak values.

        Parameters
        ----------
        dx : list
            List of X offsets.
        dy : list
            List of Y offsets.
        peakc : list
            List of peak values.

        Returns
        -------
        dxn : ndarray
            Selected X offsets.
        dyn : ndarray
            Selected Y offsets.
        pindn : ndarray
            Indices of selected stars.
        """
        self.logger.info("Selecting guide stars based on peak values.")
        peakn = np.array(peakc)
        pind = np.where((peakn > self.peakmin) & (peakn < self.peakmax))
        pindn = pind[0]
        dxn = np.array([dx[i] for i in pindn])
        dyn = np.array([dy[i] for i in pindn])
        self.logger.info(f"Selected {len(dxn)} guide stars based on peaks.")
        return dxn, dyn, pindn

    def cal_final_offset(self, dxp, dyp, pindp):
        """
        Calculate the final offset using selected guide stars.

        Parameters
        ----------
        dxp : ndarray
            Selected X offsets.
        dyp : ndarray
            Selected Y offsets.
        pindp : ndarray
            Indices of selected stars.

        Returns
        -------
        fdx : float or str
            Final X offset or 'Warning' if the number of guide stars is insufficient.
        fdy : float or str
            Final Y offset or 'Warning' if the number of guide stars is insufficient.
        """
        self.logger.info("Calculating the final offset using selected guide stars.")
        if len(pindp) > 0.5:
            distances = np.sqrt(dxp ** 2 + dyp ** 2)
            clipped_data = sigma_clip(distances, sigma=3, maxiters=False)
            cdx = dxp[~clipped_data.mask]
            cdy = dyp[~clipped_data.mask]

            if len(cdx) > 4:
                filtered_distances = np.sqrt(cdx ** 2 + cdy ** 2)
                max_dist_index = np.argmax(filtered_distances)
                min_dist_index = np.argmin(filtered_distances)
                cdx = np.delete(cdx, [min_dist_index, max_dist_index])
                cdy = np.delete(cdy, [min_dist_index, max_dist_index])

            fdx = np.mean(cdx)
            fdy = np.mean(cdy)

            if np.sqrt(fdx ** 2 + fdy ** 2) > self.crit_out:
                self.logger.info(f"Final offset: fdx={fdx}, fdy={fdy}")
                return fdx, fdy
            else:
                self.logger.warning("Final offset is within critical threshold; returning 0, 0.")
                return 0, 0
        else:
            self.logger.warning("Insufficient guide stars for offset calculation; returning 'Warning'.")
            return 'Warning', 'Warning'
        
    def exe_cal(self):
        """
        Execute the full guide star calibration process.

        This method processes astrometric and guide star data, 
        calculates the offsets, and determines the final offsets.

        Returns
        -------
        fdx : float or str
            Final X offset or 'Warning'.
        fdy : float or str
            Final Y offset or 'Warning'.
        """
        self.logger.info("Starting the guide star calibration process.")
        astro_dir = self.inpar.get('off_astro_dir')
        filepre = glob.glob(os.path.join(astro_dir, '*.fits'))
        astro_files_p = [os.path.basename(file) for file in filepre]
        astro_files_p.sort()
        astro_files = [os.path.join(astro_dir, file) for file in astro_files_p]

        proc_dir = self.inpar.get('off_proc_dir')
        filepre = glob.glob(os.path.join(proc_dir, '*.fits'))
        proc_files_p = [os.path.basename(file) for file in filepre]
        proc_files_p.sort()
        proc_files = [os.path.join(proc_dir, file) for file in proc_files_p]
        
        dxpp = []
        dypp = []
        pindpp = []    
                
        for astro_file, proc_file in zip(astro_files, proc_files):
            self.logger.info(f"Processing files: {astro_file} and {proc_file}")
            image_file_a = astro_file        
            image_data_x, header, wcs = self.load_image_and_wcs(image_file_a)        
            crval1, crval2 = header['CRVAL1'], header['CRVAL2']       

            image_file = proc_file
            image_data_p = self.load_only_image(image_file)
            
            image_data, stddev = self.background(image_data_p)
            ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux = self.load_star_catalog(crval1, crval2)
            ra, dec = self.select_stars(ra1_rad, dec1_rad, ra2_rad, dec2_rad, ra_p, dec_p, flux)
            dra, ddec, dra_f, ddec_f = self.radec_to_xy_stars(ra, dec, wcs)
            dx, dy, peakc = self.cal_centroid_offset(dra, ddec, dra_f, ddec_f, stddev, wcs, image_data)
            dxn, dyn, pindn = self.peak_select(dx, dy, peakc)        

            dxpp.append(dxn)
            dypp.append(dyn)
            pindpp.append(pindn)

        dxp = np.concatenate(dxpp)
        dyp = np.concatenate(dypp)
        pindp = np.concatenate(pindpp)        
        fdx, fdy = self.cal_final_offset(dxp, dyp, pindp)

        self.logger.info(f"Guide star calibration process completed. Final offsets: fdx={fdx}, fdy={fdy}")
        return fdx, fdy
