import json
from Lib.AMQ import *

#from TCS.tcscli import *

#telcom=Telcomclass()
#telcom.TelcomConnect()
#ra=telcom.RequestRA()
#print(ra.decode())


TCS=TCPClient("127.0.0.1",8888)

TCS.connect()
TCS.send('HI Server')
data=TCS.receive()

print(data)
