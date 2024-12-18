from .qhyccd import QHY_Camera
import numpy as np
from astropy.io import fits

def mtlexp(exptime
           , readmode=1
           , usb_traffic=40
           , gain=10
           , offset=30
           , nexposure=1
           , data_dir='./data/'):
    
    qc = QHY_Camera()
    qc.sdk.InitQHYCCDResource()
    qc.OpenCam()

    qc.Initialize(readmode, usb_traffic)

    qc.CamSettings(gain, offset, exptime)

    for i in range(nexposure):
        im = qc.CamCapture()

        hdr = fits.Header()
        hdr['Gain'] = gain
        hdr['offset'] = offset
        hdr['texp'] = exptime

        empty_primary = fits.PrimaryHDU(header=hdr, data=im)
        empty_primary.writeto(data_dir+f'test{i}.fits', overwrite=True)

    qc.CamExit()

    msg='Metrology exposure finished'
    return msg


if __name__ == "__main__":
    mtlexp(4)
