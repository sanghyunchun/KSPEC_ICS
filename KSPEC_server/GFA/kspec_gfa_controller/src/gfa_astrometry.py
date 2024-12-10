#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Yongmin Yoon (yyoon@kasi.re.kr), Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-08-29
# @Filename: gfa_astrometry.py

import os
import sys
import glob
import json
import numpy as np

from astropy.io import fits
from astropy.table import Table, vstack
from astropy.utils.data import get_pkg_data_filename

__all__ = ["gfa_astrometry"]

class gfa_astrometry:
    """
    A class to perform astrometry operations on GFA images.

    Attributes
    ----------
    logger : logging.Logger
        Logger for logging messages.
    dir_path : str
        Directory path for input files.
    astrometry_params : list of str
        List of filenames of astrometry parameter files.
    inpar : dict
        Dictionary containing parameters loaded from a JSON file.
    """

    def __init__(self, config, logger):
        """
        Initializes the gfa_astrometry class.

        Parameters
        ----------
        config : str
            Path to the configuration JSON file.
        logger : logging.Logger
            Logger instance for logging.
        """
        self.logger = logger
        self.logger.info("Initializing gfa_astrometry class.")
        self.astrometry_params = from_config(config)
        self.logger.info(f"Loaded {len(self.astrometry_params)} FITS files.")
        

    def process_file(self, flname):
        """
        Processes a FITS file: subtracts sky values, crops the image, 
        and writes the processed data to a new FITS file.

        Parameters
        ----------
        flname : str
            The name of the FITS file to process.

        Returns
        -------
        tuple
            A tuple containing:
            - RA (float): Right Ascension from the FITS file header.
            - DEC (float): Declination from the FITS file header.
            - dir_out (str): Output directory path.
            - newname (str): New filename for the processed FITS file.
        """
        self.logger.info(f"Processing file: {flname}.")
        data_in_path = os.path.join(self.dir_path, flname)
        
        # Read the FITS file    
        hdu_list = fits.open(data_in_path)
        ori = hdu_list[0].data  # Assuming the image data is in the primary HDU
        primary_header = hdu_list[0].header
        ra_in = primary_header['RA']
        dec_in = primary_header['DEC']

        # Get the sky values
        sky1 = ori[self.inpar.get('pre_skycoord1')[0], self.inpar.get('pre_skycoord1')[1]]
        sky2 = ori[self.inpar.get('pre_skycoord2')[0], self.inpar.get('pre_skycoord2')[1]]

        # Subtract sky values
        self.logger.info("Subtracting sky values.")
        ori[self.inpar.get('sub_ind1')[0]:self.inpar.get('sub_ind1')[1], self.inpar.get('sub_ind1')[2]:self.inpar.get('sub_ind1')[3]] -= sky1
        ori[self.inpar.get('sub_ind2')[0]:self.inpar.get('sub_ind2')[1], self.inpar.get('sub_ind2')[2]:self.inpar.get('sub_ind2')[3]] -= sky2

        # Crop the image
        orif = ori[self.inpar.get('crop_ind')[0]:self.inpar.get('crop_ind')[1], self.inpar.get('crop_ind')[2]:self.inpar.get('crop_ind')[3]]

        # Write the processed data to a new FITS file
        dir_out = self.inpar.get('pre_dir_out')
        newname = 'proc' + flname
        data_file_path = os.path.join(dir_out, newname)
        fits.writeto(data_file_path, orif, hdu_list[0].header, overwrite=True)
        self.logger.info(f"Processed data written to {data_file_path}.")

        # Close the original FITS file
        hdu_list.close()
        self.logger.info(f"File {flname} processing completed.")

        return ra_in, dec_in, dir_out, newname

    def astrometry(self, ra_in, dec_in, dir_out, newname):
        """
        Performs astrometry on the processed FITS file.

        Parameters
        ----------
        ra_in : float
            Right Ascension from the processed FITS file header.
        dec_in : float
            Declination from the processed FITS file header.
        dir_out : str
            Directory where the processed file is stored.
        newname : str
            Name of the processed FITS file.

        Returns
        -------
        tuple
            A tuple containing:
            - CRVAL1 (float): RA value from the astrometry result.
            - CRVAL2 (float): DEC value from the astrometry result.
        """
        self.logger.info("Starting astrometry process.")
        dir_output = self.inpar.get('ast_dir_out')
        input_command = (
            f"solve-field --cpulimit {self.inpar.get('cpulimit')} --dir {dir_output} --scale-units degwidth "
            f"--scale-low {self.inpar.get('ast_scale')[0]} --scale-high {self.inpar.get('ast_scale')[1]} "
            f"--no-verify --no-plots --crpix-center -O --ra {ra_in} --dec {dec_in} --radius {self.inpar.get('ast_radius')} {dir_out}/{newname}"
        )
        self.logger.info(f"Running command: {input_command}")
        os.system(input_command)

        savedname = newname[:-4] + 'new'
        dir_final = self.inpar.get('ast_dir_final')
        allnew = 'astro_' + newname
        os.system(f'cp {dir_output}/{savedname} {dir_final}{allnew}')
        self.logger.info(f"Astrometry results saved to {dir_final}{allnew}.")

        image_file = get_pkg_data_filename(dir_final + allnew)
        image_data_p, header = fits.getdata(image_file, ext=0, header=True)

        # Extracting CRVAL1 and CRVAL2 from the header
        crval1 = header['CRVAL1']
        crval2 = header['CRVAL2']
        self.logger.info(f"Astrometry completed with CRVAL1: {crval1}, CRVAL2: {crval2}.")

        return crval1, crval2

    def star_catalog(self):
        """
        Combines multiple star catalog files into a single catalog.

        This method reads the '.corr' files, combines them into one FITS table,
        and writes the combined table to a new FITS file.

        Returns
        -------
        None
        """
        self.logger.info("Starting star catalog generation.")
        dir_output = self.inpar.get('ast_dir_out')
        
        # Get all files matching the '*.corr' pattern in the output directory
        filepre = glob.glob(os.path.join(dir_output, '*.corr'))
        star_files_p = [os.path.basename(file) for file in filepre]
        star_files_p.sort()
        star_files = [os.path.join(dir_output, file) for file in star_files_p]
        
        tables = []
        for file in star_files:
            with fits.open(file) as hdul:
                table_data = Table(hdul[1].data)
                tables.append(table_data)

        combined_table = vstack(tables)
        output_file = self.inpar.get('starcata')
        combined_table.write(output_file, overwrite=True)
        self.logger.info(f"Star catalog generated and saved to {output_file}.")

    def rm_tempfiles(self):
        """
        Removes temporary files generated during the astrometry process.

        This method deletes all files in the directory specified by 'ast_dir_out'.

        Returns
        -------
        None
        """
        self.logger.info("Removing temporary files.")
        dir_output = self.inpar.get('ast_dir_out')
        os.system(f'rm {dir_output}/*')
        self.logger.info(f"Temporary files removed from {dir_output}.")

    def combined_function(self, flname):
        """
        Combines the process_file and astrometry methods.

        Parameters
        ----------
        flname : str
            The name of the FITS file to process.

        Returns
        -------
        tuple
            A tuple containing:
            - CRVAL1 (float): RA value from the astrometry result.
            - CRVAL2 (float): DEC value from the astrometry result.
        """
        self.logger.info(f"Starting combined function for file: {flname}.")
        ra_in, dec_in, dir_out, newname = self.process_file(flname)
        crval1, crval2 = self.astrometry(ra_in, dec_in, dir_out, newname)
        self.logger.info("Combined function completed.")
        return crval1, crval2

def from_config(config):
    """
    Loads configuration from a JSON file and returns the astrometry parameters.

    Parameters
    ----------
    config : str
        Path to the configuration JSON file.

    Returns
    -------
    list of str
        List of filenames of astrometry parameter files.
    """
    with open(config, 'r') as file:
        inpar = json.load(file)
        
    dir_path = inpar.get('pre_dir_path')
    filepre = glob.glob(os.path.join(dir_path, '*.fits'))
    astrometry_params = [os.path.basename(file) for file in filepre]
    astrometry_params.sort()
    
    return astrometry_params
