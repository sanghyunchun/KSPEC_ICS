import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json
import requests
import xml.etree.ElementTree as ET


ILLUMI_WEBRELAY_URL = 'http://192.168.15.201:80/state.xml'


async def set_illumination(state):
    """Set the back illumination relay and verify its reported state."""
    response = await asyncio.to_thread(
        requests.get, ILLUMI_WEBRELAY_URL,
        params={'relay1': int(state)}, timeout=3,
    )
    response.raise_for_status()
    value = ET.fromstring(response.text).findtext('relay1')
    if value not in ('0', '1'):
        raise ValueError(f'Invalid WebRelay relay1 response: {value!r}')
    relay_state = int(value)
    if relay_state != int(state):
        raise ValueError(f'Back illumination requested {int(state)}, received {relay_state}')
    return relay_state



ILLUMINATION_COMMANDS = {
    'illuon': 'Back illumination on (stage in, light on).',
    'illuoff': 'Back illumination off (light off, stage out).',
    'illulighton': 'Back illumination light on (stage stays in).',
    'illulightoff': 'Back illumination light off (stage stays in).',
}


def spec_queue():
    """Queue of the spectrograph server: 'SPEC' (main) or 'ISOPLANE' (KSPEC.ini SPEC.queue)."""
    with open('./Lib/KSPEC.ini', 'r') as f:
        kspecinfo = json.load(f)
    return kspecinfo['SPEC'].get('queue', 'SPEC')


def create_spec_command(func, **kwargs):
    """Helper function to create SPECTROGRAPH commands."""
    cmd_data = mkmsg.specmsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)


def spec_status(): return create_spec_command('specstatus', message ='Show spectrograph status.')

def spec_stop(): return create_spec_command('specstop', message ='Emergency stop of the spectrograph.')

def spec_initial(dir_name, experiment=None):
    extra = {'experiment': experiment} if experiment else {}
    return create_spec_command('specinitial', dirname=dir_name, message = f'Initialize Spectrograph', **extra)

def get_obj(exptime,nframe, header):
    return create_spec_command('getobj', time=exptime, numframe=nframe, header=header, message =f'Exposure {exptime} seconds for objects.')

def get_bias(nframe, header): 
    return create_spec_command('getbias', numframe=nframe, header=header, message =f'Get {nframe} bias images.')

def get_flat(exptime,nframe, header): 
    return create_spec_command('getflat', time=exptime, numframe=nframe, header=header, message =f'Get {nframe} flat images by {exptime} senconds exposure.')

def get_arc(exptime,nframe, header):
    return create_spec_command('getarc', time=exptime, numframe=nframe, header=header, message =f'Get {nframe} arc images by {exptime} senconds exposure.')

def get_dark(exptime,nframe, header):
    return create_spec_command('getdark', time=exptime, numframe=nframe, header=header, message =f'Get {nframe} dark images by {exptime} senconds exposure.')


# OBSTYPE (GUI combo, scripts, header) -> SPEC frame command
FRAME_COMMANDS = {'Bias': 'getbias', 'Dark': 'getdark', 'Flat': 'getflat', 'Arc': 'getarc',
                  'Object': 'getobj'}


def frame_command(obstype, exptime, nframe):
    """SPEC command line for one frame type: 'getbias <n>', else 'get<type> <t> <n>'.

    ValueError for an unknown or unset type (the GUI's 'None') and for a bad time or count, so
    a frame is never taken with the wrong command (e.g. a bias with the shutter open).
    """
    if obstype not in FRAME_COMMANDS:
        raise ValueError(f"select a frame type ({', '.join(FRAME_COMMANDS)}), not {obstype!r}")
    try:
        n = int(nframe)
        t = 0.0 if obstype == 'Bias' else float(exptime)
    except (TypeError, ValueError):
        raise ValueError(f"bad exposure time {exptime!r} or count {nframe!r}") from None
    if n < 1 or t < 0:
        raise ValueError(f"exposure time {t:g} and count {n} must be >= 0 and >= 1")
    cmd = FRAME_COMMANDS[obstype]
    return f'{cmd} {n}' if cmd == 'getbias' else f'{cmd} {t:g} {n}'


async def handle_spec(arg, ICS_client, header=None):
    cmd, *params = arg.split()
    if header is None:
        header = {}

    queue = spec_queue()
    if cmd in ILLUMINATION_COMMANDS:
        if params:
            raise ValueError(f"'{cmd}' does not take parameters")
        light_on = cmd in ('illuon', 'illulighton')
        if queue == 'SPEC':
            # Main spectrograph: one WebRelay light, no stage, so the light-only pair is the same.
            return await set_illumination(light_on)
        # IsoPlane: the server moves the stage in the grating turret, interlocked with the
        # grating; its Done reply (func=cmd) arrives on the ICS queue. Return the requested
        # state; callers that need the outcome wait for that reply.
        await ICS_client.send_message(queue, create_spec_command(cmd, message=ILLUMINATION_COMMANDS[cmd]))
        return int(light_on)

    command_map = {
        'specstatus': spec_status,
        'specstop': spec_stop,
    }

    print(header)

    print(params)
    if cmd == 'specinitial':
        if len(params) not in (1, 2):
            print("Error: 'specinitial' needs a directory name and optionally a LightField experiment (IsoPlane). ex) 20250918")
            return
        command_map[cmd] = lambda: spec_initial(*map(str, params))

    if cmd == 'getobj':
        if len(params) != 2:
            print("Error: 'getobj' needs two parameters: exposure time and number of exposures. ex) getobj 300 6 ")
            return
        try:
            ExpT, obsnum = float(params[0]), int(params[1])
        except ValueError:
            print(f"Error: Input parameters of 'getobj' should be float and int. input value: {params[0]} {params[1]}")
            return
        command_map[cmd] = lambda: get_obj(ExpT, obsnum, header)

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
        command_map[cmd] = lambda: get_bias(obsnum, header)

    if cmd == 'getflat':
        if len(params) != 2:
            print("Error: 'getflat' needs two parameters: exposure time and number of exposures. ex) getflat 15 10 ")
            return
        try:
            ExpT, obsnum = float(params[0]), int(params[1])
        except ValueError:
            print(f"Error: Input parameters of 'getflat' should be float and int. input value: {params[0]} {params[1]}")
            return
        command_map[cmd] = lambda: get_flat(ExpT,obsnum, header)

    if cmd == 'getarc':
        if len(params) != 2:
            print("Error: 'getarc' needs two parameters: exposure time and number of exposures. ex) getarc 3 10 ")
            return
        try:
            ExpT, obsnum = float(params[0]), int(params[1])
        except ValueError:
            print(f"Error: Input parameters of 'getarc' should be float and int. input value: {params[0]} {params[1]}")
            return
        command_map[cmd] = lambda: get_arc(ExpT,obsnum, header)

    if cmd == 'getdark':
        if len(params) != 2:
            print("Error: 'getdark' needs two parameters: exposure time and number of exposures. ex) getdark 600 5 ")
            return
        try:
            ExpT, obsnum = float(params[0]), int(params[1])
        except ValueError:
            print(f"Error: Input parameters of 'getdark' should be float and int. input value: {params[0]} {params[1]}")
            return
        command_map[cmd] = lambda: get_dark(ExpT,obsnum, header)

    if cmd in command_map:
        specmsg = command_map[cmd]()
        await ICS_client.send_message(queue, specmsg)
    else:
        print(f"Error: '{cmd}' is not right command for SPECTROGRAPH.")
