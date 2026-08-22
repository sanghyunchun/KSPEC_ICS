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
def fbp_stop(): return create_fbp_command('fbpstop', message = ' Stop current positioners moving.')
def fbp_initial_from_stop(): return create_fbp_command('fbpinitial_from_stop', message = 'Move all positioners from stop to initial positions.')
def fbp_lock(positioner_list):
    return create_fbp_command('fbplock',positioners=positioner_list, message=f'Lock positioners {positioner_list}')


async def handle_fbp(arg, ICS_client):
    """Handle Fiber positioner commands."""
    parts = arg.strip().split(maxsplit=1)
    if not parts:
        return

    cmd = parts[0]
    raw_params = parts[1] if len(parts) > 1 else ''
    params = raw_params.split()

    command_map = {
        'fbpzero': fbp_zero, 'fbpoffset': fbp_offset, 'fbpmoveall': fbp_moveall,
        'fbpinitial': fbp_initial, 'fbpstop': fbp_stop, 'fbpinitial_from_stop': fbp_initial_from_stop
    }
    if cmd == 'fbpstatus':
        positioner = str(params[0])
        command_map[cmd] = lambda: fbp_status(positioner)

    if cmd == 'fbpmoveone':
        positioner = str(params[0])
        motor = str(params[1])
        angle = float(params[2])
        command_map[cmd] = lambda: fbp_moveone(positioner, motor, angle)

    if cmd == 'fbplock':
        command_map[cmd] = lambda: fbp_lock(raw_params.strip())

    if cmd in command_map:
        fbpmsg = command_map[cmd]()
        await ICS_client.send_message("FBP", fbpmsg)
