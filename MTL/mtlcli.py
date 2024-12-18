import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import threading
import json


def mtl_status():
    comment='Metrology status' 
    cmd_data=mkmsg.mtlmsg()
    cmd_data.update(func='mtlstatus',message=comment)
    MTLmsg=json.dumps(cmd_data)
    return MTLmsg

def mtl_exp(exptime):
#    MTL_client=Client('MTL')
    comment='Metrology camera exposure start'
    cmd_data=mkmsg.mtlmsg()
    cmd_data.update(func='mtlexp',time=exptime,message=comment)
    MTLmsg=json.dumps(cmd_data)
    return MTLmsg


def mtl_cal():
    comment='Metrology calculates offset between Target and Fiber position'
    cmd_data=mkmsg.mtlmsg()
    cmd_data.update(func='mtlcal',message=comment)
    MTLmsg=json.dumps(cmd_data)
    return MTLmsg



