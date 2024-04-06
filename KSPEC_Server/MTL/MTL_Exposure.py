import qhyccd
import json


def MTLexposure():
#    qc = qhyccd.QHY_Camera()
#    qc.sdk.InitQHYCCDResource()
#    qc.OpenCam()

#qc.TemperatureInfo()
#qc.TemperatureControl()

#    ReadMode = 1
#    USB_TRAFFIC = 40
#    qc.Initialize(ReadMode, USB_TRAFFIC)

#    gain = 10
#    offset = 30
#    texposure = 1000 #in microsecond unit

#    qc.CamSettings(gain, offset, texposure)
#    qc.CamCapture()

#    qc.CamExit()

    dx=10.9
    dy=5.3

    comments='Metrology calculated the offset'
    
    dict_data={'inst': 'MTL', 'func' : 'mtlexp', 'dx' : dx, 'dy': dy,
            'comments': comments}

    MTLrsp=json.dumps(dict_data)
    return MTLrsp
