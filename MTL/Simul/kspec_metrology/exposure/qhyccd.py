from ctypes import *
import numpy as np
from .libqhy import CONTROL_ID, QHYCCD_SUCCESS
from ..logging.log import get_logger
import sys
import os

class QHY_Camera:
    QHYCCD_SUCCESS = 0

    def __init__(self):
        current_dir = os.path.dirname(__file__)
#        lib_path = os.path.join(current_dir, "../lib", "libqhyccd.so")
        lib_path = './MTL/kspec_metrology/lib/libqhyccd.so'
        self.sdk = CDLL(lib_path)

        #Set function input and output dtype
        self.sdk.ScanQHYCCD.restype = c_int
        self.sdk.OpenQHYCCD.restype = c_void_p
        self.sdk.InitQHYCCD.argtypes = [c_void_p]

        self.sdk.SetQHYCCDReadMode.argtypes = [c_void_p, c_uint32]
        self.sdk.GetReadModesNumber.argtypes = [c_char_p, c_void_p]
        self.sdk.GetReadModeName.argtypes = [c_char_p, c_uint32, c_char_p]

        self.sdk.SetQHYCCDStreamMode.argtypes = [c_void_p, c_uint8]
        
        self.sdk.SetQHYCCDParam.argtypes = [c_void_p, c_int, c_double]
        self.sdk.SetQHYCCDResolution.argtypes = [c_void_p, c_uint32, c_uint32, c_uint32, c_uint32]
        self.sdk.SetQHYCCDBinMode.argtypes = [c_void_p, c_int, c_int]
        self.sdk.SetQHYCCDBitsMode = [c_void_p, c_uint]

        self.sdk.GetQHYCCDChipInfo.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p]
        self.sdk.GetQHYCCDParam.argtypes = [c_void_p, c_int]
        self.sdk.GetQHYCCDParam.restype = c_double

        self.sdk.CloseQHYCCD.restype = c_void_p
        self.sdk.CloseQHYCCD.argtypes = [c_void_p]

        self.sdk.ExpQHYCCDSingleFrame.argtypes = [c_void_p]
        self.sdk.GetQHYCCDMemLength.argtypes = [c_void_p]
        self.sdk.GetQHYCCDSingleFrame.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p]
        self.sdk.CancelQHYCCDExposingAndReadout.argtypes = [c_void_p]

    def OpenCam(self):
        log = get_logger()
        #self.sdk.InitQHYCCDResource()
        num = self.sdk.ScanQHYCCD()
        if num < 1:
            log.critical("No Camera Connected")
            sys.exit()
        type_char_array_32 = c_char*32
        self.CamID = type_char_array_32()
        ret = self.sdk.GetQHYCCDId(c_int(0), self.CamID)
        if ret != QHYCCD_SUCCESS:
            log.warning("QHYCCD ID not found")
            sys.exit()
        self.Cam = self.sdk.OpenQHYCCD(self.CamID)
        if self.Cam is None:
            log.critical("QHYCCD not opened")
            sys.exit()

        self.chipw = c_double()
        self.chiph = c_double()
        self.w = c_uint()
        self.h = c_uint()
        self.pixelw = c_double()
        self.pixelh = c_double() 
        self.bpp = c_uint()
        
        ret = self.sdk.GetQHYCCDChipInfo(self.Cam
                                       , byref(self.chipw), byref(self.chiph)
                                       , byref(self.w), byref(self.h)
                                       , byref(self.pixelw), byref(self.pixelh)
                                       , byref(self.bpp))

        log.info(f'Camera ID : {self.CamID}')
        log.info(f'Chip Width : {self.chipw.value}, Chip Height : {self.chiph.value}')
        log.info(f'Chip Width : {self.w.value}, Chip Height : {self.h.value}')
        log.info(f'Pixel size : {self.pixelw.value} x {self.pixelh.value}')

        self.ReadModeNumber = c_uint32()
        self.sdk.GetReadModesNumber(self.CamID, byref(self.ReadModeNumber))
        #print('Available Read modes are')
        for i in range(0, self.ReadModeNumber.value):
            ReadModeName = create_string_buffer(32)
            self.sdk.GetReadModeName(self.CamID, i, ReadModeName)
            log.info(f"Read mode {i} : {ReadModeName.value}")


    def Initialize(self, ReadMode, USB_TRAFFIC, STREAM_MODE=0):
        self.sdk.SetQHYCCDReadMode(self.Cam, c_uint32(ReadMode))
        self.sdk.SetQHYCCDStreamMode(self.Cam, STREAM_MODE)
        self.sdk.InitQHYCCD(self.Cam)

        self.sdk.SetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_USBTRAFFIC, c_double(USB_TRAFFIC))
        self.sdk.SetQHYCCDResolution(self.Cam, 0, 0, self.w, self.h )
        self.sdk.SetQHYCCDBinMode(self.Cam, c_int(1), c_int(1))
        #self.sdk.SetQHYCCDBitsMode(self.Cam, c_uint32(self.bpp) )
        self.sdk.SetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_TRANSFERBIT, c_double(self.bpp.value))

    def TemperatureControl(self, TargetTemperature):
        self.sdk.SetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_COOLER, c_double(TargetTemperature))
    
    def TemperatureInfo(self):
        CurrentTemperature = self.sdk.GetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_CURTEMP)
        CurrentFanSpeed = self.sdk.GetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_CURPWM)
        print(CurrentTemperature, CurrentFanSpeed)

    def CamSettings(self, gain, offset, texposure):
        self.sdk.SetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_GAIN, c_double(gain))
        self.sdk.SetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_OFFSET, c_double(offset))
        self.sdk.SetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_EXPOSURE, c_double(texposure) )

    def CamCapture(self):
        log.info("Exposure")
        self.sdk.GetQHYCCDMemLength(self.Cam)
        self.imgdata = (c_uint16 * self.w.value* self.h.value)()
        self.sdk.ExpQHYCCDSingleFrame(self.Cam)
        self.sdk.GetQHYCCDSingleFrame(self.Cam
                                    , byref(self.w), byref(self.h), byref(self.bpp)
                                    , byref(c_uint32(1)), self.imgdata)
        self.sdk.CancelQHYCCDExposingAndReadout(self.Cam)
        
        return np.asarray(self.imgdata)
       
    def CamExit(self):
        log = get_logger()
        self.sdk.CloseQHYCCD(self.Cam)
        self.sdk.ReleaseQHYCCDResource()
        log.info("Camera Closed Successfully!")

    def ERROR(self, retVal):
        if retVal != QHYCCD_SUCCESS:
            print("Error Occurred!")
            self.CamExit()
