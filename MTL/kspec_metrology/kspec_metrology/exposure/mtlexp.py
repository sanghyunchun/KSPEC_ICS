from kspec_metrology.exposure.qhyccd import QHY_Camera
import numpy as np
from astropy.io import fits
from pathlib import Path
import json

def mtlexp(exptime,filename : str                                  # Need filename 
           , readmode=1
           , usb_traffic=40
           , gain=10
           , offset=30
           , nexposure=1
           , data_dir='./MTL/data/'):
    
    current_file_path = Path(__file__).resolve().parents[3]
    print(current_file_path)


    qc = QHY_Camera()
    qc.sdk.InitQHYCCDResource()
    qc.OpenCam()

    qc.Initialize(readmode, usb_traffic)

    qc.CamSettings(gain, offset, exptime*1000000)

    filehead=filename.split(".fits")[0]

    for i in range(nexposure):
        im = qc.CamCapture()

        hdr = fits.Header()
        hdr['Gain'] = gain
        hdr['offset'] = offset
        hdr['texp'] = exptime

        empty_primary = fits.PrimaryHDU(header=hdr, data=im)
#        empty_primary.writeto(data_dir+f'test{i}.fits', overwrite=True)
        empty_primary.writeto(data_dir+f'{name}{i].fits', overwrite=True)

    qc.CamExit()
    msg=f'Metrology {exptime} seconds {nexposure} exposures finished.'     # Need to edit in real observation
    return 'success', msg
