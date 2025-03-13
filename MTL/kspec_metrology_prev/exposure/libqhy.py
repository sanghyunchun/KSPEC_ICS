import ctypes

"""
Just a copy from qhyccd-python github src
"qhyccdstruct.h"
"""

class CONTROL_ID:
    CONTROL_BRIGHTNESS = ctypes.c_int(0) # image brightness
    CONTROL_CONTRAST = ctypes.c_int(1)   # image contrast
    CONTROL_WBR  = ctypes.c_int(2)       # red of white balance
    CONTROL_WBB = ctypes.c_int(3)        # blue of white balance
    CONTROL_WBG = ctypes.c_int(4)        # the green of white balance
    CONTROL_GAMMA = ctypes.c_int(5)      # screen gamma
    CONTROL_GAIN = ctypes.c_int(6)       # camera gain
    CONTROL_OFFSET = ctypes.c_int(7)     # camera offset
    CONTROL_EXPOSURE = ctypes.c_int(8)   # expose time (us)
    CONTROL_SPEED = ctypes.c_int(9)      # transfer speed
    CONTROL_TRANSFERBIT = ctypes.c_int(10)  # image depth bits
    CONTROL_CHANNELS = ctypes.c_int(11)     # image channels
    CONTROL_USBTRAFFIC = ctypes.c_int(12)   # hblank
    CONTROL_ROWNOISERE = ctypes.c_int(13)   # row denoise
    CONTROL_CURTEMP = ctypes.c_int(14)      # current cmos or ccd temprature
    CONTROL_CURPWM = ctypes.c_int(15)       # current cool pwm
    CONTROL_MANULPWM = ctypes.c_int(16)     # set the cool pwm
    CONTROL_CFWPORT = ctypes.c_int(17)      # control camera color filter wheel port
    CONTROL_COOLER = ctypes.c_int(18)       # check if camera has cooler
    CONTROL_ST4PORT = ctypes.c_int(19)      # check if camera has st4port
    CAM_COLOR = ctypes.c_int(20)
    CAM_BIN1X1MODE = ctypes.c_int(21)       # check if camera has bin1x1 mode
    CAM_BIN2X2MODE = ctypes.c_int(22)       # check if camera has bin2x2 mode
    CAM_BIN3X3MODE = ctypes.c_int(23)       # check if camera has bin3x3 mode
    CAM_BIN4X4MODE = ctypes.c_int(24)       # check if camera has bin4x4 mode
    CAM_MECHANICALSHUTTER = ctypes.c_int(25)# mechanical shutter
    CAM_TRIGER_INTERFACE = ctypes.c_int(26) # triger
    CAM_TECOVERPROTECT_INTERFACE = ctypes.c_int(27)  # tec overprotect
    CAM_SINGNALCLAMP_INTERFACE = ctypes.c_int(28)    # singnal clamp
    CAM_FINETONE_INTERFACE = ctypes.c_int(29)        # fine tone
    CAM_SHUTTERMOTORHEATING_INTERFACE = ctypes.c_int(30)  # shutter motor heating
    CAM_CALIBRATEFPN_INTERFACE = ctypes.c_int(31)         # calibrated frame
    CAM_CHIPTEMPERATURESENSOR_INTERFACE = ctypes.c_int(32)# chip temperaure sensor
    CAM_USBREADOUTSLOWEST_INTERFACE = ctypes.c_int(33)    # usb readout slowest

    CAM_8BITS = ctypes.c_int(34)                          # 8bit depth
    CAM_16BITS = ctypes.c_int(35)                         # 16bit depth
    CAM_GPS = ctypes.c_int(36)                            # check if camera has gps

    CAM_IGNOREOVERSCAN_INTERFACE = ctypes.c_int(37)       # ignore overscan area

    QHYCCD_3A_AUTOBALANCE = ctypes.c_int(38)
    QHYCCD_3A_AUTOEXPOSURE = ctypes.c_int(39)
    QHYCCD_3A_AUTOFOCUS = ctypes.c_int(40)
    CONTROL_AMPV = ctypes.c_int(41)                       # ccd or cmos ampv
    CONTROL_VCAM = ctypes.c_int(42)                       # Virtual Camera on off
    CAM_VIEW_MODE = ctypes.c_int(43)

    CONTROL_CFWSLOTSNUM = ctypes.c_int(44)         # check CFW slots number
    IS_EXPOSING_DONE = ctypes.c_int(45)
    ScreenStretchB = ctypes.c_int(46)
    ScreenStretchW = ctypes.c_int(47)
    CONTROL_DDR = ctypes.c_int(48)
    CAM_LIGHT_PERFORMANCE_MODE = ctypes.c_int(49)

    CAM_QHY5II_GUIDE_MODE = ctypes.c_int(50)
    DDR_BUFFER_CAPACITY = ctypes.c_int(51)
    DDR_BUFFER_READ_THRESHOLD = ctypes.c_int(52)
    DefaultGain = ctypes.c_int(53)
    DefaultOffset = ctypes.c_int(54)
    OutputDataActualBits = ctypes.c_int(55)
    OutputDataAlignment = ctypes.c_int(56)

    CAM_SINGLEFRAMEMODE = ctypes.c_int(57)
    CAM_LIVEVIDEOMODE = ctypes.c_int(58)
    CAM_IS_COLOR = ctypes.c_int(59)
    hasHardwareFrameCounter = ctypes.c_int(60)
    CONTROL_MAX_ID = ctypes.c_int(71)
    CAM_HUMIDITY = ctypes.c_int(72) #check if camera has	 humidity sensor 

QHYCCD_READ_DIRECTLY = 0x2001
QHYCCD_DELAY_200MS   = 0x2000
QHYCCD_SUCCESS       = 0
QHYCCD_ERROR         = 0xFFFFFFFF


