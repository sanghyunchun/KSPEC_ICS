import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json


def create_fbp_command(func, **kwargs):
    """Helper function to create ADC commands."""
    cmd_data = mkmsg.fbpmsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)

def fbp_zero() : return create_fbp_command('fbpzero',message='Move fiber positioners to zero position.')
def fbp_move() : return create_fbp_command('fbpmove',message='Move fiber positioners to targets.')
def fbp_offset() : return create_fbp_command('fbpoffset',message='Offset fiber positioners to targets.')
def fbp_status() : return create_fbp_command('fbpstatus',message='Show fiber positioner status.')


async def handle_fbp(arg, ICS_client):
    """Handle Fiber positioner commands."""
    cmd, *params = arg.split()
    command_map = {
        'fbpzero': fbp_zero, 'fbpmove': fbp_move, 'fbpoffset': fbp_offset,
        'fbpstatus': fbp_status
    }
    if cmd in command_map:
        fbpmsg = command_map[cmd]()
        await ICS_client.send_message("FBP", fbpmsg)
