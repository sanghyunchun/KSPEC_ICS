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
            'endotest': endo_test, 'endoclear': endo_clear,
            'endoguide': endo_guide, 'endostop': endo_stop

    }
    if cmd == 'endofocus':
        if len(params) != 1:
            print("Error: 'endofocus' need one focus value between 0~255. ex) endofocus 220 ")
            return
        try:
            fc = int(params[0])
            if fc >= 255:
                print("Error: ENDO foucs value should be less than 255. input value: {fc}")
                return
        except ValueError:
            print(f"Error: Input parameters of 'endofocus' should be int. input value: {params[0]}")
            return
        command_map[cmd] = lambda: endo_focus(fc)

    elif cmd == 'endoexpset':
        if len(params) != 1:
            print("Error: 'endoexpset' need one exposure time between -12~0. ex) endoexpset -5 ")
            return
        try:
            expT = int(params[0])
            if expT > 0:
                print(f"Error: ENDO exposure time should be less than 0. input value: {params[0]}")
                return
        except ValueError:
            print(f"Error: Input parameters of 'endoexpset' should be int. input value: {params[0]}")
            return
        command_map[cmd] = lambda: endo_expset(expT)


    if cmd in command_map:
        endomsg = command_map[cmd]()
        print(endomsg)
        await ICS_client.send_message("ENDO", endomsg)

    else:
        print(f"Error: '{cmd}' is not right command for ENDO")
