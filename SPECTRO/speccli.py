import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json


def create_spec_command(func, **kwargs):
    """Helper function to create SPECTROGRAPH commands."""
    cmd_data = mkmsg.specmsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)


def spec_status(): return create_spec_command('specstatus', message ='Show spectrograph status.')

def illu_on(): return create_spec_command('illuon', message ='Turn on back-illumination light.')

def illu_off(): return create_spec_command('illuoff', message ='Turn off back-illumination light.')

def get_obj(exptime,nframe):
    return create_spec_command('getobj', time=exptime, numframe=nframe, message =f'Exposure {exptime} seconds for objects.')

def get_bias(nframe): 
    return create_spec_command('getbias', numframe=nframe, message =f'Get {nframe} bias images.')

def get_flat(exptime,nframe): 
    return create_spec_command('getflat', time=exptime, numframe=nframe, message =f'Get {nframe} flat images by {exptime} senconds exposure.')

def get_arc(exptime,nframe):
    return create_spec_command('getarc', time=exptime, numframe=nframe, message =f'Get {nframe} arc images by {exptime} senconds exposure.')


async def handle_spec(arg, ICS_client):
    cmd, *params = arg.split()
    command_map = {
        'specstatus': spec_status,
        'illuon' : illu_on,
        'illuoff' : illu_off
    }

    if cmd == 'getobj':
        if len(params) != 2:
            print("Error: 'getobj' needs two parameters: exposure time and number of exposures. ex) getobj 300 6 ")
            return
        try:
            ExpT, obsnum = float(params[0]), int(params[1])
        except ValueError:
            print(f"Error: Input parameters of 'getobj' should be float and int. input value: {params[0]} {params[1]}")
            return
        command_map[cmd] = lambda: get_obj(ExpT,obsnum)

    if cmd == 'getbias':
        if len(params) != 1:
            print("Error: 'getbias' needs one parameter: number of exposures. ex) getbias 10 ")
            return
        try:
            obsnum = int(params[0])
            print(obsnum)
        except ValueError:
            print(f"Error: Input parameters of 'getbias' should be int. input value: {params[0]}")
            return
        command_map[cmd] = lambda: get_bias(obsnum)

    if cmd == 'getflat':
        if len(params) != 2:
            print("Error: 'getflat' needs two parameters: exposure time and number of exposures. ex) getflat 15 10 ")
            return
        try:
            ExpT, obsnum = float(params[0]), int(params[1])
        except ValueError:
            print(f"Error: Input parameters of 'getflat' should be float and int. input value: {params[0]} {params[1]}")
            return
        command_map[cmd] = lambda: get_flat(ExpT,obsnum)

    if cmd == 'getarc':
        if len(params) != 2:
            print("Error: 'getarc' needs two parameters: exposure time and number of exposures. ex) getarc 3 10 ")
            return
        try:
            ExpT, obsnum = float(params[0]), int(params[1])
        except ValueError:
            print(f"Error: Input parameters of 'getarc' should be float and int. input value: {params[0]} {params[1]}")
            return
        command_map[cmd] = lambda: get_arc(ExpT,obsnum)

    if cmd in command_map:
        specmsg = command_map[cmd]()
        await ICS_client.send_message("SPEC", specmsg)
    else:
        print(f"Error: '{cmd}' is not right command for SPECTROGRAPH.")

