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

def parse_relay_state(xml_text, tag):
    root = ET.fromstring(xml_text)
    value = root.findtext(tag)

    if value is None:
        raise ValueError(f"{tag} not found in WebRelay response")

    return int(value)

async def handle_lamp(arg, ICS_client, logging=None, state_callback=None):
    """Control one lamp, or return all three relay states for lampstatus."""
    parts = arg.split()
    if not parts:
        raise ValueError("Empty WebRelay command")
    cmd, *params = parts
    webrelay_user = None
    webrelay_pass = None

    # 수정요구
    relay_ips = {
        'FLAT': '192.168.15.161:8061',
        'ARC': '192.0.2.2:8080',
        'FIDUCIAL': '192.168.15.200:80',
    }
    relay_protocols = {
        'FLAT': ('relay1', 'relay1'),
        'ARC': ('relay1', 'relay1'),
        'FIDUCIAL': ('relay1state', 'relay1State'),
    }

#    command_map = {
#        'lampstatus': lamp_status, 'arcon': arcon,
#        'arcoff' : arcoff,
#        'flaton' : flaton,
#        'flatoff': flatoff,
#        'fiducialon': fiducialon,
#        'fiducialoff': fiducialoff
#    }

#    print(cmd)
    command_lamp = {
        'flaton': 'FLAT', 'flatoff': 'FLAT',
        'arcon': 'ARC', 'arcoff': 'ARC',
        'fiducialon': 'FIDUCIAL', 'fiducialoff': 'FIDUCIAL',
    }
    if cmd != 'lampstatus' and cmd not in command_lamp:
        raise ValueError(f"Unknown WebRelay command: {cmd}")

    required_lamps = relay_ips if cmd == 'lampstatus' else (command_lamp[cmd],)
    for lamp in required_lamps:
        if not relay_ips[lamp]:
            raise ValueError(f'{lamp}_WEBRELAY_IP is not configured')

    async def query_relay(lamp, expected_state=None):
        label = {'FLAT': 'Flat lamp', 'ARC': 'Arc lamp', 'FIDUCIAL': 'Fiducial LED'}[lamp]
        response_tag, request_param = relay_protocols[lamp]
        url = f"http://{relay_ips[lamp]}/state.xml"
        if expected_state is not None:
            url += f'?{request_param}={expected_state}'
        if logging is not None:
            action = 'status query' if expected_state is None else ('ON' if expected_state else 'OFF')
            logging(f'{label}: sending {action} to WebRelay.', level='send')

        try:
            # requests is synchronous: keep HTTP I/O off the GUI event loop.
            auth = (webrelay_user, webrelay_pass) if webrelay_user is not None else None
            r = await asyncio.to_thread(requests.get, url, auth=auth, timeout=3)
            r.raise_for_status()
            relay_state = parse_relay_state(r.text, response_tag)
            if relay_state not in (0, 1):
                raise ValueError(f'Invalid {response_tag}: {relay_state}')
            if logging is not None:
                logging(
                    f'{label}: WebRelay response {response_tag}={relay_state} '
                    f"({'ON' if relay_state else 'OFF'}).",
                    level='receive',
                )
            if expected_state is not None and relay_state != expected_state:
                raise ValueError(f'{label}: requested state {expected_state}, received {relay_state}')
        except (requests.RequestException, ET.ParseError, ValueError) as error:
            if logging is not None:
                logging(f'{label}: WebRelay command failed: {error}', level='error')
            raise
        return relay_state

    if cmd == 'lampstatus':
        return {lamp: await query_relay(lamp) for lamp in relay_ips}

    subinst = command_lamp[cmd]
    relay_state = await query_relay(subinst, int(cmd.endswith('on')))

    if state_callback is not None and cmd != 'lampstatus':
        state_callback('LAMP', subinst, 'ING' if relay_state else 'Done')

    return relay_state

    #print(r.status_code)
    #print(r.text)
    #print(r.headers)
