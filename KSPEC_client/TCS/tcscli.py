import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
#import argh
#import uuid
from .tcscore import *
import asyncio
import threading



def tcs_tra(ra,dec):
#    TCS_client=Client('kspecadmin','kasikspec','TCS')
    TCSmsg=tcs_trafun(ra,dec)
    return TCSmsg
#    asyncio.run(TCS_client.send_message('TCS',TCSmsg))
