import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json


def create_endo_command(func,**kwargs):
    """Helper function to create ADC commands."""
    cmd_data = mkmsg.endomsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)

def endo_guide(): return create_endo_command('endoguide', message='Start Endoscope autoguiding')
def endo_stop(): return create_endo_command('endostop', message = 'Stop Endoscope autoguiding')

def endo_focus(fc):
    return create_endo_command('endofocus',focus=fc,message=f'Set Endoscope focus to {fc}')

def endo_expset(exptime):
    return create_endo_command('endoexpset',time=exptime,message=f'Set Endoscope exposure time to {exptime}')

def endo_test(): return create_endo_command('endotest',message='Start test exposure')

def endo_clear(): return create_endo_command('endoclear',message='Remove all Endoscope images')

async def handle_endo(arg,ICS_client):
    """Handle Endoscope commands."""
    cmd, *params = arg.split()
    command_map = {
            'endofocus': lambda : endo_focus(params[0]), 
            'endoexpset': lambda: endo_expset(params[0]), 
            'endotest': endo_test, 'endoclear': endo_clear,
            'endoguide': endo_guide, 'endostop': endo_stop

    }
    if cmd in command_map:
        endomsg = command_map[cmd]()
        print(endomsg)
        await ICS_client.send_message("ENDO", endomsg)





