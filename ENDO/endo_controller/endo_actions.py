import cv2
import matplotlib.pyplot as plt
from PIL import Image
import numpy as np
from astropy.io import fits
from datetime import datetime
import asyncio
import random
import Lib.mkmessage as mkmsg
import os
import glob
from typing import Union, List, Dict, Any, Optional

def median_combine_fits(files):
    data_list = []
    for file in files:
        with fits.open(file) as hdul:
            data_list.append(hdul[0].data)
    
    median_data = np.median(data_list, axis=0)

    output_filename = os.path.join('./ENDO/data/', 'median_' + os.path.basename(files[0]))

    if not os.path.isfile(output_filename):
        hdu = fits.PrimaryHDU(median_data)
        hdu.writeto(output_filename, overwrite=True)
        print(f"Median combined FITS file saved as {output_filename}")
    

def combine_fits_files():
    files = sorted(glob.glob(os.path.join('./ENDO/data/', 'E*.fits')))
   
    # median combine when 5 fits files are saved 
    while len(files) >= 5:
        files_to_combine = files[:5]
        median_combine_fits(files_to_combine)
        
        # remove used 5 files in list
        files = files[5:]

class endo_actions:

    def __init__(self):
        pass

    def _generate_response(self,status: str,message: str, **kwargs) -> Dict[str, Any]:
        """
        Generate a standardized response dictionary.

        Parameters
        ----------
        status : str
            Status of the operation ('success' or 'error').
        message : str
            Message describing the operation result.

        Returns
        -------
        dict
            A dictionary representing the response.
        """
        response = {"status": status,"message": message}
        response.update(kwargs)
        return response

    def endo_clear(self):
        if os.path.exists('./ENDO/data'):
            for file in os.scandir('./ENDO/data'):
                os.remove(file.path)
            rsp = 'Endoscope images are removed'
            return self._generate_response("sucess", rsp) 
        
    def endo_connect(self):
        self.cam=cv2.VideoCapture(0)
        if not self.cam.isOpened():
            print("Could not open video device")
            rsp='Could not open video device'
            return self._generate_response("fail", rsp) 
        else:
            print("Endoscope open")

            expt_default=self.cam.get(cv2.CAP_PROP_EXPOSURE)
            focus_default=self.cam.get(cv2.CAP_PROP_FOCUS)
            self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 2544)
            self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 1944)
            print(f'Default exposure time : {expt_default}')
            print(f'Default focus : {focus_default}')
            rsp='Endocsope connected.'
            return self._generate_response("sucess", rsp) 

    def endo_status(self):
        if not self.cam.isOpened():
            print("Could not open video device")
            rsp='Could not open video device'
            return self._generate_response("fail", rsp)
        else:
            expt_default=self.cam.get(cv2.CAP_PROP_EXPOSURE)
            focus_default=self.cam.get(cv2.CAP_PROP_FOCUS)
            print(f'Default exposure time : {expt_default}')
            print(f'Default focus : {focus_default}')
            rsp=f'Endocsope connected. Default exposure time : {expt_default}. Default focus : {focus_default}.'
            return self._generate_response("sucess", rsp)
        
    def endo_focus(self,focus):
        self.cam.set(cv2.CAP_PROP_FOCUS,focus)
        rsp=f'Endoscope focus is set to {focus}'
        return self._generate_response("sucess", rsp) 

    def endo_expset(self,expt):
        self.cam.set(cv2.CAP_PROP_EXPOSURE,expt)
        rsp=f'Endoscope exposure time is set to {expt}'
        return self._generate_response("sucess", rsp) 

    async def endo_guide(self):
        ret,frame=self.cam.read()
        
        frame =  frame[:,:,::-1]
        
        r_data = np.array(frame[:,:,0])
        r_data=r_data[::-1]
        g_data = np.array(frame[:,:,1])
        g_data=g_data[::-1]
        b_data = np.array(frame[:,:,2])
        b_data=b_data[::-1]
        
        img_data=g_data

        final = fits.PrimaryHDU(data=img_data)
        utc=datetime.utcnow()
        surf=utc.strftime("%Y%m%d_%H%M%S")
        filename='E'+surf+'.fits'
        filename2='E'+surf+'.jpg'
        
        final.writeto('./ENDO/data/'+filename,overwrite=True)

        msg=random.randrange(1,11)
        if msg < 7:
            reply=mkmsg.gfamsg()
            rsp='Autoguiding continue.......'
        else:
            reply=mkmsg.gfamsg()
            rsp=f'Telescope offset {msg}'
            print('\033[32m'+'[GFA]', rsp+'\033[0m')
        
        combine_fits_files()
        return self._generate_response("sucess", rsp) 

    def endo_test(self):
        ret,frame=self.cam.read()
        frame =  frame[:,:,::-1]
        
        plt.imshow(frame)
        plt.savefig('./ENDO/data/temp.jpg')
        
        r_data = np.array(frame[:,:,0])
        r_data=r_data[::-1]
        g_data = np.array(frame[:,:,1])
        g_data=g_data[::-1]
        b_data = np.array(frame[:,:,2])
        b_data=b_data[::-1]

        green = fits.PrimaryHDU(data=g_data)
        utc=datetime.utcnow()
        surf=utc.strftime("%Y%m%d_%H%M%S")
        gfilename='test_'+surf+'.fits'
        green.writeto('./ENDO/data/'+gfilename,overwrite=True)
        
        #blue = fits.PrimaryHDU(data=b_data)
        #bfilename='blue.fits'
        #blue.writeto('./ENDO/endo_controller/data/'+filename,overwrite=True)
       
        rsp=f'{gfilename} is saved'
        return self._generate_response("sucess",rsp)



