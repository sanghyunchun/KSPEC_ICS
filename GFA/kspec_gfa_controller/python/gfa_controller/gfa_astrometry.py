import os
import glob
import json
import numpy as np
from astropy.io import fits
from astropy.table import Table, vstack
from astropy.utils.data import get_pkg_data_filename
from concurrent.futures import ThreadPoolExecutor, as_completed


class gfa_astrometry:
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
        
        with open(config, 'r') as file:
            self.inpar = json.load(file)
        
        # Extract directories from config
        self.dir_path = self.inpar['paths']['directories']['raw_images']
        self.processed_dir = self.inpar['paths']['directories']['processed_images']
        self.temp_dir = self.inpar['paths']['directories']['temp_files']
        self.final_astrometry_dir = self.inpar['paths']['directories']['final_astrometry_images']
        self.star_catalog_path = self.inpar['paths']['directories']['star_catalog']
        
        # Load raw image files
        filepre = glob.glob(os.path.join(self.dir_path, '*.fits'))
        self.raws = [os.path.basename(file) for file in filepre]
        self.raws.sort()
        self.logger.info(f"Loaded {len(self.raws)} FITS files.")

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
        sky1 = ori[self.inpar['settings']['image_processing']['skycoord']['pre_skycoord1'][0],
                   self.inpar['settings']['image_processing']['skycoord']['pre_skycoord1'][1]]
        sky2 = ori[self.inpar['settings']['image_processing']['skycoord']['pre_skycoord2'][0],
                   self.inpar['settings']['image_processing']['skycoord']['pre_skycoord2'][1]]

        # Subtract sky values
        self.logger.info("Subtracting sky values.")
        ori[self.inpar['settings']['image_processing']['sub_indices']['sub_ind1'][0]:
            self.inpar['settings']['image_processing']['sub_indices']['sub_ind1'][1],
            self.inpar['settings']['image_processing']['sub_indices']['sub_ind1'][2]:
            self.inpar['settings']['image_processing']['sub_indices']['sub_ind1'][3]] -= sky1
        ori[self.inpar['settings']['image_processing']['sub_indices']['sub_ind2'][0]:
            self.inpar['settings']['image_processing']['sub_indices']['sub_ind2'][1],
            self.inpar['settings']['image_processing']['sub_indices']['sub_ind2'][2]:
            self.inpar['settings']['image_processing']['sub_indices']['sub_ind2'][3]] -= sky2

        # Crop the image
        orif = ori[self.inpar['settings']['image_processing']['crop_indices'][0]:
                   self.inpar['settings']['image_processing']['crop_indices'][1],
                   self.inpar['settings']['image_processing']['crop_indices'][2]:
                   self.inpar['settings']['image_processing']['crop_indices'][3]]

        # Write the processed data to a new FITS file
        newname = 'proc_' + flname
        data_file_path = os.path.join(self.processed_dir, newname)
        fits.writeto(data_file_path, orif, hdu_list[0].header, overwrite=True)
        self.logger.info(f"Processed data written to {data_file_path}.")

        # Close the original FITS file
        hdu_list.close()
        self.logger.info(f"File {flname} processing completed.")

        return ra_in, dec_in, self.processed_dir, newname

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
        scale_low, scale_high = self.inpar['astrometry']['scale_range']
        radius = self.inpar['astrometry']['radius']
        cpu_limit = self.inpar['settings']['cpu']['limit']
        
        # Command to run astrometry with the proper scale and CPU limit
        input_command = (
            f"solve-field --cpulimit {cpu_limit} --dir {self.temp_dir} --scale-units degwidth "
            f"--scale-low {scale_low} --scale-high {scale_high} "
            f"--no-verify --no-plots --crpix-center -O --ra {ra_in} --dec {dec_in} --radius {radius} {dir_out}/{newname}"
        )
        self.logger.info(f"Running command: {input_command}")
        os.system(input_command)

        # Modify the saved name and use consistent underscores in all filenames
        savedname = newname[:-4] + '_new'  # Add underscores
        allnew = 'astro_' + newname  # Ensure consistent naming with underscores
        os.system(f'cp {self.temp_dir}/{savedname} {self.final_astrometry_dir}/{allnew}')
        self.logger.info(f"Astrometry results saved to {self.final_astrometry_dir}/{allnew}.")

        # Construct the full path of the saved FITS file
        image_file = os.path.join(self.final_astrometry_dir, allnew)
        image_data_p, header = fits.getdata(image_file, ext=0, header=True)

        # Extracting CRVAL1 and CRVAL2 from the header
        crval1 = header['CRVAL1']
        crval2 = header['CRVAL2']
        self.logger.info(f"Astrometry completed with CRVAL1: {crval1}, CRVAL2: {crval2}.")

        return crval1, crval2

    def star_catalog(self):
        """
        Combines multiple star catalog files into a single catalog.
        """
        self.logger.info("Starting star catalog generation.")
        
        # Check if temp_dir and star_catalog_path are set
        if not self.temp_dir:
            self.logger.error("Temp directory is not set.")
            return

        if not self.star_catalog_path:
            self.logger.error("Star catalog path is not set.")
            return
        
        # Get all files matching the '*.corr' pattern in the output directory
        filepre = glob.glob(os.path.join(self.temp_dir, '*.corr'))
        self.logger.info(f"Found {len(filepre)} .corr files in {self.temp_dir}.")
        
        if not filepre:
            self.logger.error("No .corr files found in the temp directory.")
            return
        
        star_files = [os.path.join(self.temp_dir, file) for file in filepre]
        tables = []
        
        for file in star_files:
            self.logger.info(f"Processing file: {file}")
            try:
                with fits.open(file) as hdul:
                    table_data = Table(hdul[1].data)
                    tables.append(table_data)
            except Exception as e:
                self.logger.error(f"Error reading {file}: {e}")
        
        if not tables:
            self.logger.error("No tables found to stack.")
            return
        
        combined_table = vstack(tables)
        combined_table.write(self.star_catalog_path, overwrite=True)
        self.logger.info(f"Star catalog generated and saved to {self.star_catalog_path}.")


    def rm_tempfiles(self):
        """
        Removes temporary files generated during the astrometry process.

        This method deletes all files in the directory specified by 'temp_dir'.

        Returns
        -------
        None
        """
        self.logger.info("Removing temporary files.")
        os.system(f'rm {self.temp_dir}/*')
        self.logger.info(f"Temporary files removed from {self.temp_dir}.")

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
    
    def preproc(self):
        # Check if the final astrometry directory contains any files
        if not os.path.exists(self.final_astrometry_dir) or not os.listdir(self.final_astrometry_dir):
            self.logger.info(f"No files found in {self.final_astrometry_dir}, proceeding with combined function.")

            # If no files exist, process with combined_function using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as executor:
                # Submit tasks to the executor and collect futures
                futures = [executor.submit(self.combined_function, flname) for flname in self.raws]
                
                # Prepare arrays to collect results
                crval1_results = []
                crval2_results = []
                
                # Wait for each future to complete and collect results
                for future in as_completed(futures):
                    crval1, crval2 = future.result()
                    crval1_results.append(crval1)
                    crval2_results.append(crval2)

            # Print results (can be replaced with any other processing)
            print(crval1_results)
            print(crval2_results)

            # Generate the star catalog
            self.star_catalog()    

            # Clean up temporary files
            self.rm_tempfiles()

        else:
            self.logger.info(f"Files found in {self.final_astrometry_dir}, processing raw files.")

            # If files are found, process files with process_file function
            with ThreadPoolExecutor(max_workers=8) as executor:
                # Submit tasks to the executor and collect futures
                futures = [executor.submit(self.process_file, flname) for flname in self.raws]
            
            # You can collect results or handle any other post-processing here if necessary
