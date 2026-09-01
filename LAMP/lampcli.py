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

async def handle_lamp(arg, ICS_client):
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

async def handle_lamp(arg, ICS_client):
    cmd, *params = arg.split()
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
    else:
        raise ValueError(f"Unknown WebRelay command: {cmd}")

    r = requests.get(url, auth=(webrelay_user, webrelay_pass), timeout=3)
    r.raise_for_status()


    relay1state = parse_relay1state(r.text)

    return relay1state

    #print(r.status_code)
    #print(r.text)
    #print(r.headers)




