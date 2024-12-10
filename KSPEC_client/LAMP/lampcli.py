import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
#import argh
#import uuid
#from .mtlcore import *
import asyncio
import threading
import json


def arcon():
#    MTL_client=Client('MTL')
    comment='Arc lamp on.'
    cmd_data=mkmsg.lampmsg()
    cmd_data.update(func='arcon',message=comment)
    LAMPmsg=json.dumps(cmd_data)
    return LAMPmsg

def arcoff():
    comment='Arc lamp off'
    cmd_data=mkmsg.lampmsg()
    cmd_data.update(func='arcoff',message=comment)
    LAMPmsg=json.dumps(cmd_data)
    return LAMPmsg

def flaton():
    comment='Flat lamp on'
    cmd_data=mkmsg.lampmsg()
    cmd_data.update(func='flaton',message=comment)
    LAMPmsg=json.dumps(cmd_data)
    return LAMPmsg

def flatoff():
    comment='Flat lamp off'
    cmd_data=mkmsg.lampmsg()
    cmd_data.update(func='flatoff',message=comment)
    LAMPmsg=json.dumps(cmd_data)
    return LAMPmsg

def fiducialon():
    comment='Fiducial lamp on'
    cmd_data=mkmsg.lampmsg()
    cmd_data.update(func='fiducialon',message=comment)
    LAMPmsg=json.dumps(cmd_data)
    return LAMPmsg

def fiducialoff():
    comment='Fiducial lamp off'
    cmd_data=mkmsg.lampmsg()
    cmd_data.update(func='fiducialoff',message=comment)
    LAMPmsg=json.dumps(cmd_data)
    return LAMPmsg






