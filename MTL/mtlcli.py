import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json


def create_mtl_command(func, **kwargs):
    """Helper function to create ADC commands."""
    cmd_data = mkmsg.mtlmsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)

def mtl_status(): return create_mtl_command('mtlstatus',message='Show Metrology status')
def mtl_cal(): return create_mtl_command('mtlcal',message='Calculate offset between Target and Fiber position')
def mtl_exp(exptime): 
    return create_mtl_command('mtlexp',time=exptime,message=f'Exposure Metrology camera {exptime} seconds')


async def handle_mtl(arg, ICS_client):
    """Handle MTL commands with error checking."""
    cmd, *params = arg.split()

    # Basic command without parameters
    command_map = {
        'mtlstatus': mtl_status, 'mtlcal': mtl_cal
    }

    if cmd == 'mtlexp':
        if len(params) != 1:
            print("Error: 'mtlexp' need one exposure time value. ex) mtlexp 10 ")
            return
        try:
            exptime = float(params[0])
        except ValueError:
            print(f"Error: Input parameters of 'mtlexp' should be float. input value: {params[0]}")
            return
        command_map[cmd] = lambda: mtl_exp(exptime)

    # Right command
    if cmd in command_map:
        mtlmsg = command_map[cmd]()
        await ICS_client.send_message("MTL", mtlmsg)
    else:
        print(f"Error: '{cmd}' is not right command for MTL")



