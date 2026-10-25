import os

from astropy.io import fits

from kspec_metrology.exposure.qhyccd import QHY_Camera
from kspec_metrology.logging.log import get_logger
from kspec_metrology.naming import image_path


def mtlexp(exptime_ms=None
           , readmode=1
           , usb_traffic=40
           , gain=10
           , offset=30
           , nexposure=1
           , data_dir='./MTL/data/'
           , head='test'
           , extra_header=None
           , exptime_us=None
           , exptime=None):
    """metrology 카메라로 nexposure장을 찍어 저장한다.

    exptime_ms : 노출시간 [ms]. 카메라 SDK(CONTROL_EXPOSURE, µs) 에는 1000 배 해서 넘긴다.
    exptime_us : 대신 µs 로 줄 때. exptime= (옛 키워드) 도 µs 로 받는다 (KSPEC_ICS 의 wire 단위;
                 경고를 내고 그대로 쓴다). 셋 중 하나만 준다.

    파일 이름은 {head}{i}.fits 로, findpeak이 같은 data_dir/head로 읽어간다.
    extra_header에 dict을 주면 FITS header에 그대로 더한다 (타일, trial 번호 등).

    반환:
        저장한 파일 경로 리스트
    """
    log = get_logger()
    given = [v is not None for v in (exptime_ms, exptime_us, exptime)]
    if sum(given) != 1:
        raise TypeError("mtlexp: give exactly one of exptime_ms, exptime_us, exptime(=us, legacy)")
    if exptime is not None:
        log.warning("mtlexp(exptime=%g) is the legacy keyword and is taken as microseconds; "
                    "use exptime_ms=%g instead", exptime, exptime/1e3)
        exptime_us = exptime
    if exptime_us is not None:
        exptime_ms = float(exptime_us)/1e3

    os.makedirs(data_dir, exist_ok=True)

    qc = QHY_Camera()
    qc.sdk.InitQHYCCDResource()
    qc.OpenCam()

    qc.Initialize(readmode, usb_traffic)

    qc.CamSettings(gain, offset, float(exptime_ms)*1e3)      # SDK 단위는 µs

    paths = []
    try:
        for i in range(nexposure):
            im = qc.CamCapture()

            hdr = fits.Header()
            hdr['Gain'] = gain
            hdr['offset'] = offset
            hdr['texp'] = (float(exptime_ms), 'exposure time [ms]')
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
