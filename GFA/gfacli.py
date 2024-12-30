import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
#import argh
#import uuid
#from .gfacore import *
import asyncio
import threading

def gfa_status():
    cmd_data=mkmsg.gfamsg()
    comment = 'GFA status'
    cmd_data.update(func='gfastatus',message=comment)
    GFAmsg=json.dumps(cmd_data)
    return GFAmsg

def gfa_cexp(exptime,chip):
    "Exposure specific GFA camera with desired exposure time"
    comment='GFA camera exposure start'

    cmd_data=mkmsg.gfamsg()
    cmd_data.update(time=exptime,chip=chip,message=comment)
    GFAmsg=json.dumps(cmd_data)
    return GFAmsg

def gfa_allexp(exptime):
    "Exposure all GFA camera with desired exposure time"
    comment='All GFA camera exposure start'

    cmd_data=mkmsg.gfamsg()
    cmd_data.update(time=exptime,func='gfaallexp',message=comment)
    GFAmsg=json.dumps(cmd_data)
#    GFAmsg=gfa_allexpfun(time)
    return GFAmsg

def gfa_autoguide():
    "Run auto guide system"
    comment='Autoguiding running'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='autoguide',message=comment)
    GFAmsg=json.dumps(cmd_data)
    return GFAmsg

def autoguide_stop():
    "Exposure stop"
    comment='All GFA camera exposure stop'

    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='autoguidestop',message=comment)
    GFAmsg=json.dumps(cmd_data)
    return GFAmsg

def endo_guide(expt):
    comment='Endoscope exposure start'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endoguide',time=expt,message=comment)
    GFAmsg=json.dumps(cmd_data)
    return GFAmsg

def endo_stop():
    comment='Endoscope exposure stop'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endostop',message=comment)
    GFAmsg=json.dumps(cmd_data)
    return GFAmsg

def endo_focus(fc):
    comment=f'Endoscope focus set to {fc}'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endofocus',message=comment)
    cmd_data.update(focus=fc)
    GFAmsg=json.dumps(cmd_data)
    return GFAmsg

def endo_expset(exptime):
    comment=f'Endoscope exposure time set to {exptime}'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endoexpset',time=exptime,message=comment)
    GFAmsg=json.dumps(cmd_data)
    return GFAmsg

def endo_test(exptime):
    comment='Endoscope exposure Test'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endotest',time=exptime,message=comment)
    GFAmsg=json.dumps(cmd_data)
    return GFAmsg



