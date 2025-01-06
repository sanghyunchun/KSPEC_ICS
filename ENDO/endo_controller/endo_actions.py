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

def median_combine_fits(files):
    data_list = []
    for file in files:
        with fits.open(file) as hdul:
            data_list.append(hdul[0].data)
    
    median_data = np.median(data_list, axis=0)

    output_filename = os.path.join('./ENDO/endo_controller/data/', 'median_' + os.path.basename(files[0]))

    if not os.path.isfile(output_filename):
        hdu = fits.PrimaryHDU(median_data)
        hdu.writeto(output_filename, overwrite=True)
        print(f"Median combined FITS file saved as {output_filename}")
    

def combine_fits_files():
    files = sorted(glob.glob(os.path.join('./ENDO/endo_controller/data/', 'E*.fits')))
   
    # median combine when 5 fits files are saved 
    while len(files) >= 5:
        files_to_combine = files[:5]
        median_combine_fits(files_to_combine)
        
        # remove used 5 files in list
        files = files[5:]

class endo_actions:

    def __init__(self):
        pass

    def endo_clear(self):
        if os.path.exists('./ENDO/endo_controller/data'):
            for file in os.scandir('./ENDO/endo_controller/data'):
                os.remove(file.path)
            rsp = 'Endoscope images are removed'
            return rsp
        
    def endo_connect(self):
        self.cam=cv2.VideoCapture(0)
        if not self.cam.isOpened():
            print("Could not open video device")
        else:
            print("Endoscope open")

        expt_default=self.cam.get(cv2.CAP_PROP_EXPOSURE)
        focus_default=self.cam.get(cv2.CAP_PROP_FOCUS)
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 2544)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 1944)
        print(f'Default exposure time : {expt_default}')
        print(f'Default focus : {focus_default}')
        

    def endo_focus(self,focus):
        self.cam.set(cv2.CAP_PROP_FOCUS,focus)
        rsp=f'Endoscope focus is set to {focus}'
        return rsp

    def endo_expset(self,expt):
        self.cam.set(cv2.CAP_PROP_EXPOSURE,expt)
        rsp=f'Endoscope exposure time is set to {expt}'
        return rsp

    async def endo_guide(self,subserver):
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
        
#        plt.imshow(img_data)
#        plt.savefig('./ENDO/endo_controller/data/'+filename2)       
        final.writeto('./ENDO/endo_controller/data/'+filename,overwrite=True)

        msg=random.randrange(1,11)
        if msg < 7:
            reply=mkmsg.gfamsg()
            comment='Autoguiding continue.......'
            dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': comment, 'thred': msg}
            reply.update(dict_data)
#        rsp=json.dumps(reply)
            rsp=reply
        else:
            reply=mkmsg.gfamsg()
            comment=f'Telescope offset {msg}'
            print('\033[32m'+'[GFA]', comment+'\033[0m')
            dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': comment, 'thred': msg}
            reply.update(dict_data)
#        rsp=json.dumps(reply)
            rsp=reply
        
        combine_fits_files()
            
        return rsp

    def endo_test(self):
        ret,frame=self.cam.read()
        frame =  frame[:,:,::-1]
        
        plt.imshow(frame)
        plt.savefig('./ENDO/endo_controller/data/temp.jpg')
        
        r_data = np.array(frame[:,:,0])
        r_data=r_data[::-1]
        g_data = np.array(frame[:,:,1])
        g_data=g_data[::-1]
        b_data = np.array(frame[:,:,2])
        b_data=b_data[::-1]

        #red = fits.PrimaryHDU(data=r_data)
        #rfilename='red.fits'
        #red.writeto('./ENDO/endo_controller/data/'+filename,overwrite=True)
        
        green = fits.PrimaryHDU(data=g_data)
        utc=datetime.utcnow()
        surf=utc.strftime("%Y%m%d_%H%M%S")
        gfilename='test_'+surf+'.fits'
        green.writeto('./ENDO/endo_controller/data/'+gfilename,overwrite=True)
        
        #blue = fits.PrimaryHDU(data=b_data)
        #bfilename='blue.fits'
        #blue.writeto('./ENDO/endo_controller/data/'+filename,overwrite=True)
        
        return gfilename+' is saved'



