import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
#import argh
#import uuid
from .speccore import *
import asyncio
import threading
import json


def spec_illu_on():
    comment='Back illumination turn on'
    cmd_data=mkmsg.specmsg()
    cmd_data.update(func='specilluon',message=comment)
    SPECmsg=json.dumps(cmd_data)
    return SPECmsg

def spec_illu_off():
    comment='Back illumination turn off'
    cmd_data=mkmsg.specmsg()
    cmd_data.update(func='specilluoff',message=comment)
    SPECmsg=json.dumps(cmd_data)
    return SPECmsg

def spec_exp(exptime):
    comment='Exposure Start!!!'
    cmd_data=mkmsg.specmsg()
    cmd_data.update(func='specexp',time=exptime,message=comment)
    SPECmsg=json.dumps(cmd_data)
    return SPECmsg

def spec_status():
    comment='Show spectrograph ststus'
    cmd_data=mkmsg.specmsg()
    cmd_data.update(func='specstatus',message=comment)
    SPECmsg=json.dumps(cmd_data)
    return SPECmsg


