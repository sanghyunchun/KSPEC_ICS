import sys
import json
from tcscli import *


if __name__ == "__main__":
    telcom=Telcomclass()
    telcom.TelcomConnect()

    if sys.argv[1] == 'getall':
        data=telcom.RequestALL()
        print(data.decode())

    if sys.argv[1] == 'getha':
        data=telcom.RequestHA()
        print(data.decode())

    if sys.argv[1] == 'getra':
        data=telcom.RequestRA()
        print(data.decode())

    if sys.argv[1] == 'getdec':
        data=telcom.RequestDEC()
        print(data.decode())

    if sys.argv[1] == 'getel':
        data=telcom.RequestEL()
        print(data.decode())

    if sys.argv[1] == 'getaz':
        data=telcom.RequestAZ()
        print(data.decode())

    if sys.argv[1] == 'getsecz':
        data=telcom.RequestSECZ()
        print(data.decode())

