import json

from TCS.tcscli import *

telcom=Telcomclass()
telcom.TelcomConnect()
ra=telcom.RequestRA()
print(ra.decode())

