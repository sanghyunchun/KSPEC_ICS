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

def fbp_zero() : return create_fbp_command('fbpzero',message='Move all positioners to zero position.')
def fbp_moveone(positioner: str = None, motor : str = None, angle: float= 0) : 
    return create_fbp_command('fbpmoveone', positioner = positioner, motor = motor, angle = angle, message=f'Move fiber positioners {positioner} {motor} by {angle}.')
def fbp_offset() : return create_fbp_command('fbpoffset',message='Offset fiber positioners to targets.')
def fbp_status(positioner: str = None) : 
    return create_fbp_command('fbpstatus',message='Show fiber positioner status.',positioner=positioner)
def fbp_moveall(): return create_fbp_command('fbpmoveall', message = 'Move all positioners to target position.')
def fbp_initial(): return create_fbp_command('fbpinitial', message = 'Move all positioners to initial position.')


async def handle_fbp(arg, ICS_client):
    """Handle Fiber positioner commands."""
    cmd, *params = arg.split()
    command_map = {
        'fbpzero': fbp_zero, 'fbpoffset': fbp_offset, 'fbpmoveall': fbp_moveall,
        'fbpinitial': fbp_initial
    }
    if cmd == 'fbpstatus':
        positioner = str(params[0])
        command_map[cmd] = lambda: fbp_status(positioner)

    if cmd == 'fbpmoveone':
        positioner = str(params[0])
        motor = str(params[1])
        angle = float(params[2])
        command_map[cmd] = lambda: fbp_moveone(positioner, motor, angle)


    if cmd in command_map:
        fbpmsg = command_map[cmd]()
        await ICS_client.send_message("FBP", fbpmsg)
