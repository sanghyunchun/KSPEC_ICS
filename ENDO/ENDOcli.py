import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio

def endo_guide():
    comment='Endoscope exposure start'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endoguide',message=comment)
    ENDOmsg=json.dumps(cmd_data)
    return ENDOmsg

def endo_stop():
    comment='Endoscope exposure stop'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endostop',message=comment)
    ENDOmsg=json.dumps(cmd_data)
    return ENDOmsg

def endo_focus(fc):
    comment=f'Endoscope focus set to {fc}'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endofocus',message=comment)
    cmd_data.update(focus=fc)
    ENDOmsg=json.dumps(cmd_data)
    return ENDOmsg

def endo_expset(exptime):
    comment=f'Endoscope exposure time set to {exptime}'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endoexpset',time=exptime,message=comment)
    ENDOmsg=json.dumps(cmd_data)
    return ENDOmsg

def endo_test():
    comment='Endoscope exposure Test'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endotest',message=comment)
    ENDOmsg=json.dumps(cmd_data)
    return ENDOmsg

def endo_clear():
    comment='Rmove Endoscope images'
    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='endoclear',message=comment)
    ENDOmsg=json.dumps(cmd_data)
    return ENDOmsg


