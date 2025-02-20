import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json


def create_lamp_command(func, **kwargs):
    """Helper function to create lamps commands."""
    cmd_data = mkmsg.lampmsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)


def lamp_status(): return create_lamp_command('lampstatus',message='Show all lamps status')

def arcon(): return create_lamp_command('arcon',message='Arc lamp on')

def arcoff(): return create_lamp_command('arcoff',message='Arc lamp off')

def flaton(): return create_lamp_command('flaton',message='Flat lamp on')

def flatoff(): return create_lamp_command('flatoff',message='Flat lamp off')

def fiducialon(): return create_lamp_command('fiducialon',message='Fiducial led on')

def fiducialoff(): return create_lamp_command('fiducialoff',message='Fiducial led off')

async def handle_lamp(arg, ICS_client):
    print('tttttt')
    cmd, *params = arg.split()
    command_map = {
        'lampstatus': lamp_status, 'arcon': arcon,
        'arcoff' : arcoff,
        'flaton' : flaton,
        'flatoff': flatoff,
        'fiducialon': fiducialon,
        'fiducialoff': fiducialoff
    }

    if cmd in command_map:
        lampmsg = command_map[cmd]()
        await ICS_client.send_message("LAMP", lampmsg)





