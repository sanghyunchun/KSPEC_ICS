import cv2
import matplotlib.pyplot as plt
from PIL import Image
import numpy as np
from astropy.io import fits
from datetime import datetime
import asyncio
import random
import Lib.mkmessage as mkmsg

class endo_actions:

    def __init__(self):
        pass

    def endo_connect(self):
        self.cam=cv2.VideoCapture(0)
        if not self.cam.isOpened():
            print("Could not open video device")
        else:
            print("Endoscope open")

        self.cam.set(cv2.CAP_PROP_EXPOSURE,1000)

    def endo_focus(self,focus):
        self.cam.set(cv2.CAP_PROP_FOCUS,focus)
        rsp=f'Endoscope focus is set to {focus}'
        return rsp

    def endo_expset(self,expt):
        self.cam.set(cv2.CAP_PROP_EXPOSURE,expt)
        rsp=f'Endoscope exposure time is set to {expt}'
        return rsp

    async def endo_guide(self,expt,subserver):
        self.cam.set(cv2.CAP_PROP_EXPOSURE,expt)
        extt=self.cam.get(cv2.CAP_PROP_EXPOSURE)
        print(extt)
        ret,frame=self.cam.read()

        plt.figure()
        plt.imshow(frame)
        plt.axis('off')
        plt.savefig('./temp.jpg')

        image = Image.open('./temp.jpg')   
        xsize, ysize = image.size
        r, g, b = image.split()
        g_data = np.array(g.getdata())
        g_data = g_data.reshape(ysize, xsize)
        green = fits.PrimaryHDU(data=g_data)
        utc=datetime.utcnow()
        surf=utc.strftime("%Y%m%d_%H%M%S")
        filename='E'+surf+'.fits'
        green.writeto('./GFA/endo_controller/data/'+filename,overwrite=True)

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

    def endo_test(self,exptime):
        self.cam.set(cv2.CAP_PROP_EXPOSURE,exptime)
       # extt=self.cam.get(cv2.CAP_PROP_EXPOSURE)
        ret,frame=self.cam.read()

        plt.figure()
        plt.imshow(frame)
        plt.axis('off')
        plt.savefig('./temp.jpg')

        image = Image.open('./temp.jpg')   
        xsize, ysize = image.size
        r, g, b = image.split()
        g_data = np.array(g.getdata())
        g_data = g_data.reshape(ysize, xsize)
        green = fits.PrimaryHDU(data=g_data)
        filename='Test.fits'
        green.writeto('./GFA/endo_controller/data/'+filename,overwrite=True)
        return filename+'is saved'



