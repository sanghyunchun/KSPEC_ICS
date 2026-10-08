import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json
import requests
import xml.etree.ElementTree as ET

"""
def create_lamp_command(func, **kwargs):
#    Helper function to create lamps commands.

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

async def handle_lamp(arg, ICS_client, logging=None):
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
"""

def parse_relay1state(xml_text):
    root = ET.fromstring(xml_text)
    value = root.findtext("relay1state")

    if value is None:
        raise ValueError("relay1state not found in WebRelay response")

    return int(value)

async def handle_lamp(arg, ICS_client, logging=None, state_callback=None):
    """Await WebRelay, then notify the GUI of the confirmed lamp state."""
    parts = arg.split()
    if not parts:
        raise ValueError("Empty WebRelay command")
    cmd, *params = parts
    webrelay_IP = "127.0.0.1:8080"
    webrelay_user = None
    webrelay_pass = None

#    command_map = {
#        'lampstatus': lamp_status, 'arcon': arcon,
#        'arcoff' : arcoff,
#        'flaton' : flaton,
#        'flatoff': flatoff,
#        'fiducialon': fiducialon,
#        'fiducialoff': fiducialoff
#    }

#    print(cmd)
    if cmd == 'flaton':
        url = f"http://{webrelay_IP}/state.xml?relayState=1"
    elif cmd == 'flatoff':
        url = f"http://{webrelay_IP}/state.xml?relayState=0"
    elif cmd == 'arcon':
        url = f"http://{webrelay_IP}/state.xml?relayState=1"
    elif cmd == 'arcoff':
        url = f"http://{webrelay_IP}/state.xml?relayState=0"
    elif cmd == 'fiducialon':
        url = f"http://{webrelay_IP}/state.xml?relayState=1"
    elif cmd == 'fiducialoff':
        url = f"http://{webrelay_IP}/state.xml?relayState=0"
    elif cmd == 'lampstatus':
        url = f"http://{webrelay_IP}/state.xml"
    else:
        raise ValueError(f"Unknown WebRelay command: {cmd}")

    label = {
        'flaton': 'Flat lamp', 'flatoff': 'Flat lamp',
        'arcon': 'Arc lamp', 'arcoff': 'Arc lamp',
        'fiducialon': 'Fiducial LED', 'fiducialoff': 'Fiducial LED',
        'lampstatus': 'WebRelay relay 1',
    }[cmd]
    expected_state = None if cmd == 'lampstatus' else int(cmd.endswith('on'))
    if logging is not None:
        action = 'status query' if expected_state is None else ('ON' if expected_state else 'OFF')
        logging(f'{label}: sending {action} to WebRelay.', level='send')

    try:
        # requests is synchronous: keep HTTP I/O off the GUI event loop.
        auth = (webrelay_user, webrelay_pass) if webrelay_user is not None else None
        r = await asyncio.to_thread(requests.get, url, auth=auth, timeout=3)
        r.raise_for_status()
        relay1state = parse_relay1state(r.text)
        if relay1state not in (0, 1):
            raise ValueError(f'Invalid relay1state: {relay1state}')
        if logging is not None:
            logging(
                f'{label}: WebRelay response relay1state={relay1state} '
                f"({'ON' if relay1state else 'OFF'}).",
                level='receive',
            )
        if expected_state is not None and relay1state != expected_state:
            raise ValueError(f'{label}: requested state {expected_state}, received {relay1state}')
    except (requests.RequestException, ET.ParseError, ValueError) as error:
        if logging is not None:
            logging(f'{label}: WebRelay command failed: {error}', level='error')
        raise

    if state_callback is not None and cmd != 'lampstatus':
        subinst = {
            'flaton': 'FLAT', 'flatoff': 'FLAT',
            'arcon': 'ARC', 'arcoff': 'ARC',
            'fiducialon': 'FIDUCIAL', 'fiducialoff': 'FIDUCIAL',
        }[cmd]
        state_callback('LAMP', subinst, 'ING' if relay1state else 'Done')

    return relay1state

    #print(r.status_code)
    #print(r.text)
    #print(r.headers)

