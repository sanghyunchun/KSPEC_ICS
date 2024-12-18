import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
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

def obj_exp(exptime):
    comment='Exposure Start!!!'
    cmd_data=mkmsg.specmsg()
    cmd_data.update(func='objexp',time=exptime,message=comment)
    SPECmsg=json.dumps(cmd_data)
    return SPECmsg

def spec_status():
    comment='Spectrograph ststus'
    cmd_data=mkmsg.specmsg()
    cmd_data.update(func='specstatus',message=comment)
    SPECmsg=json.dumps(cmd_data)
    return SPECmsg

def bias_exp(nframe):
    comment='Bias Exposure Start!!!'
    cmd_data=mkmsg.specmsg()
    cmd_data.update(func='biasexp',numframe=nframe,message=comment)
    SPECmsg=json.dumps(cmd_data)
    return SPECmsg

def flat_exp(exptime,nframe):
    comment='Flat Exposure Start!!!'
    cmd_data=mkmsg.specmsg()
    cmd_data.update(func='flatexp',time=exptime,numframe=nframe,message=comment)
    SPECmsg=json.dumps(cmd_data)
    return SPECmsg

def arc_exp(exptime,nframe):
    comment='Arc Exposure Start!!!'
    cmd_data=mkmsg.specmsg()
    cmd_data.update(func='arcexp',time=exptime,numframe=nframe,message=comment)
    SPECmsg=json.dumps(cmd_data)
    return SPECmsg
