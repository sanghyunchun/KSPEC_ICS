from ctypes import *
import numpy as np
from libqhy import *
import sys

class QHY_Camera:
    QHYCCD_SUCCESS = 0

    def __init__(self):
        #self.sdk = CDLL("/usr/local/lib/libqhyccd.so")
        #self.sdk = CDLL("../../sdk_linux64_23.10.11/usr/local/lib/libqhyccd.so")
        self.sdk = CDLL("./libqhyccd.so")

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
        #self.sdk.InitQHYCCDResource()
        num = self.sdk.ScanQHYCCD()
        if num < 1:
            print("No Camera Connected")
            sys.exit()
        type_char_array_32 = c_char*32
        self.CamID = type_char_array_32()
        ret = self.sdk.GetQHYCCDId(c_int(0), self.CamID)
        if ret != QHYCCD_SUCCESS:
            sys.exit()
        self.Cam = self.sdk.OpenQHYCCD(self.CamID)
        if self.Cam is None:
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

        print('Camera ID : ', self.CamID)
        print(self.chipw.value, self.chiph.value)
        print(self.w.value, self.h.value)
        print(self.pixelw.value, self.pixelh.value)
        print(self.bpp.value)

        self.ReadModeNumber = c_uint32()
        self.sdk.GetReadModesNumber(self.CamID, byref(self.ReadModeNumber))
        print('Available Read modes are')
        for i in range(0, self.ReadModeNumber.value):
            ReadModeName = create_string_buffer(32)
            self.sdk.GetReadModeName(self.CamID, i, ReadModeName)
            print(i, ReadModeName.value)


    def Initialize(self, ReadMode, USB_TRAFFIC):
        self.sdk.SetQHYCCDReadMode(self.Cam, c_uint32(ReadMode))
        self.sdk.SetQHYCCDStreamMode(self.Cam, 0)
        self.sdk.InitQHYCCD(self.Cam)

        self.sdk.SetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_USBTRAFFIC, c_double(USB_TRAFFIC))
        self.sdk.SetQHYCCDResolution(self.Cam, 0, 0, self.w, self.h )
        self.sdk.SetQHYCCDBinMode(self.Cam, c_int(1), c_int(1))
        #self.sdk.SetQHYCCDBitsMode(self.Cam, c_uint32(self.bpp) )
        self.sdk.SetQHYCCDParam(self.Cam, CONTROL_ID.CONTROL_TRANSFERBIT, c_double(self.bpp))

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
        self.sdk.GetQHYCCDMemLength(self.Cam)
        self.imgdata = (ctypes.c_uint16 * self.w.value* self.h.value)()
        self.sdk.ExpQHYCCDSingleFrame(self.Cam)
        self.sdk.GetQHYCCDSingleFrame(self.Cam
                                    , byref(self.w), byref(self.h), byref(self.bpp)
                                    , byref(c_uint32(1)), self.imgdata)
        self.sdk.CancelQHYCCDExposingAndReadout(self.Cam)
       
    def CamExit(self):
        self.sdk.CloseQHYCCD(self.Cam)
        self.sdk.ReleaseQHYCCDResource()

    def ERROR(self, retVal):
        if retVal != QHYCCD_SUCCESS:
            print("Error Occurred!")
            self.CamExit()