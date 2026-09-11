import os

from astropy.io import fits

from kspec_metrology.exposure.qhyccd import QHY_Camera
from kspec_metrology.logging.log import get_logger
from kspec_metrology.naming import image_path


def mtlexp(exptime
           , readmode=1
           , usb_traffic=40
           , gain=10
           , offset=30
           , nexposure=1
           , data_dir='./MTL/data/'
           , head='test'
           , extra_header=None):
    """metrology 카메라로 nexposure장을 찍어 저장한다.

    파일 이름은 {head}{i}.fits 로, findpeak이 같은 data_dir/head로 읽어간다.
    extra_header에 dict을 주면 FITS header에 그대로 더한다 (타일, trial 번호 등).

    반환:
        저장한 파일 경로 리스트
    """
    log = get_logger()

    os.makedirs(data_dir, exist_ok=True)

    qc = QHY_Camera()
    qc.sdk.InitQHYCCDResource()
    qc.OpenCam()

    qc.Initialize(readmode, usb_traffic)

    qc.CamSettings(gain, offset, exptime)

    paths = []
    try:
        for i in range(nexposure):
            im = qc.CamCapture()

            hdr = fits.Header()
            hdr['Gain'] = gain
            hdr['offset'] = offset
            hdr['texp'] = exptime
            hdr['IEXP'] = (i, 'exposure index within the trial')
            for key, value in (extra_header or {}).items():
                hdr[key] = value

            path = image_path(data_dir, head, i)
            fits.PrimaryHDU(header=hdr, data=im).writeto(path, overwrite=True)
            paths.append(path)

            log.info("Saved exposure %d/%d to %s", i+1, nexposure, path)
    finally:
        qc.CamExit()

    return paths
