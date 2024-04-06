import qhyccd

qc = qhyccd.QHY_Camera()
qc.sdk.InitQHYCCDResource()
qc.OpenCam()

#qc.TemperatureInfo()
#qc.TemperatureControl()

ReadMode = 1
USB_TRAFFIC = 40
qc.Initialize(ReadMode, USB_TRAFFIC)

gain = 10
offset = 30
texposure = 1000 #in microsecond unit

qc.CamSettings(gain, offset, texposure)
qc.CamCapture()

qc.CamExit()
