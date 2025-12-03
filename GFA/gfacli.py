import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json

def create_gfa_command(func, **kwargs):
    """Helper function to create ADC commands."""
    cmd_data = mkmsg.gfamsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)

def gfa_status() : return create_gfa_command('gfastatus', message ='Show GFA status')
def gfa_guiding(expt: float = 1.0, save: str = False) : 
    return create_gfa_command('gfaguide', ExpTime=expt,save=save,message ='Autoguiding Start!')
def gfa_guidestop() : return create_gfa_command('gfaguidestop',message='Stop autoguiding')
def gfa_grab(cam,expt):
    return create_gfa_command('gfagrab',CamNum=cam,ExpTime=expt,message=f'Expose camera {cam} for {expt} seconds.')
def fd_grab(expt):
    return create_gfa_command('fdgrab',ExpTime=expt,message=f'Expose finder camera for {expt} seconds.')

async def handle_gfa(arg, ICS_client):
    cmd, *params = arg.split()
    command_map = {
        'gfastatus': gfa_status,
        'gfaguidestop' : gfa_guidestop
    }

    if cmd == 'gfagrab':
        if len(params) != 2:
            print("Error: 'gfagrab' needs two parameters: camera number and exposure time value. ex) gfagrab 1 10 ")
            return
        try:
            camNum, ExpT = int(params[0]), float(params[1])
        except ValueError:
            print(f"Error: Input parameters of 'gfagrab' should be int and float. input value: {params[0]} {params[1]}")
            return
        command_map[cmd] = lambda: gfa_grab(camNum, ExpT)

    elif cmd == 'gfaguide':
        if not params:
            command_map[cmd] = lambda: gfa_guiding()
        else:
            command_map[cmd] = lambda: gfa_guiding(params[0], params[1])

    elif cmd == 'fdgrab':
        if len(params) != 1:
            print("Error: 'fdgrab' needs one parameter: Exposure time value. ex) fdgrab 10 ")
            return
        try:
            ExpT = float(params[0])
        except ValueError:
            print(f"Error: Input parameters of 'fdgrab' should be float. input value: {params[0]}")
            return
        command_map[cmd] = lambda: fd_grab(ExpT)

    if cmd in command_map:
        gfamsg = command_map[cmd]()
        print(f'wwwwedde {gfamsg}')
        await ICS_client.send_message("GFA", gfamsg)
    else:
        print(f"Error: '{cmd}' is not right command for GFA.")

