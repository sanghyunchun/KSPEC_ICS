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

class endo_actions:

    def __init__(self):
        pass

    def endo_clear(self):
        if os.path.exists('./ENDO/endo_controller/data'):
            for file in os.scandir('./ENDO/endo_controller/data'):
                os.remove(file.path)
            rsp = 'Endoscope images are removed'
            return rsp
#        else:
#            rsp = 'There are no files'
#            return rsp
        
    def endo_connect(self):
        self.cam=cv2.VideoCapture(0)
        if not self.cam.isOpened():
            print("Could not open video device")
        else:
            print("Endoscope open")

        self.cam.set(cv2.CAP_PROP_EXPOSURE,1000)
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 2544)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 1944)

    def endo_focus(self,focus):
        self.cam.set(cv2.CAP_PROP_FOCUS,focus)
        rsp=f'Endoscope focus is set to {focus}'
        return rsp

    def endo_expset(self,expt):
        self.cam.set(cv2.CAP_PROP_EXPOSURE,expt)
        rsp=f'Endoscope exposure time is set to {expt}'
        return rsp

    async def endo_guide(self,subserver):
    #    self.cam.set(cv2.CAP_PROP_EXPOSURE,expt)
    #    extt=self.cam.get(cv2.CAP_PROP_EXPOSURE)
    #    print(extt)
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
        
        plt.imshow(img_data)
        plt.savefig('./ENDO/endo_controller/data/'+filename2)
        
         
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
        return rsp

    def endo_test(self):
    #    self.cam.set(cv2.CAP_PROP_EXPOSURE,exptime)
       # extt=self.cam.get(cv2.CAP_PROP_EXPOSURE)
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

        green = fits.PrimaryHDU(data=g_data)
        filename='Test.fits'
        green.writeto('./ENDO/endo_controller/data/'+filename,overwrite=True)
        return filename+'is saved'



