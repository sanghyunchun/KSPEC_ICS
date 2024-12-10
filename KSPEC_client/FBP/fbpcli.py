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

def fbp_move():
    comment='Fiber positioners start to move object target postion.'
    cmd_data=mkmsg.fbpmsg()
    cmd_data.update(func='fbpmove',message=comment)
    FBPmsg=json.dumps(cmd_data)
    return FBPmsg

def fbp_offset():
    comment='Fiber Positioners move offset.'
    cmd_data=mkmsg.fbpmsg()
    cmd_data.update(func='fbpoffset',message=comment)
    FBPmsg=json.dumps(cmd_data)
    return FBPmsg

def fbp_status():
    comment='Show the status of Fiber Positioners.'
    cmd_data=mkmsg.fbpmsg()
    cmd_data.update(func='fbpstatus',message=comment)
    FBPmsg=json.dumps(cmd_data)
    return FBPmsg
