import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import asyncio
import socket


TELID, SYSID, PID = 'KMTNET', 'TCS', '123'

def create_command(action, param=None):
    """Helper function to create telescope commands."""
    cmd = f'{TELID} {SYSID} {PID} {action}'
    if param:
        cmd += f' {param}'
    print('Telescope request cmd :', cmd)
    return cmd

async def send_command(action, telcom_client, param=None):
    """Send command to telescope."""
    try:
        cmd = create_command(action, param)
        print(cmd)
        return await telcom_client.send_receive(cmd)
    except Exception as e:
        print(f"Error: Failed to send command '{action}'. Exception: {e}")
        return None

command_map = {
    'getall': 'REQUEST ALL', 'getra': 'REQUEST RA', 'getdec': 'REQUEST DEC', 
    'getha': 'REQUEST HA', 'getel': 'REQUEST EL', 'getaz': 'REQUEST AZ', 'getsecz': 'REQUEST SECZ',
    'telstow': 'COMMAND MOVSTOW', 'telstop': 'COMMAND CANCEL',
}

async def handle_telcom(arg, telcom_client):
    cmd, *params = arg.split()

    try:
        if cmd in command_map:
            return await send_command(command_map[cmd], telcom_client)

        elif cmd == 'telra':
            if len(params) != 1:
                print("Error: 'telra' requires one parameter (RA value). Example: mvra +/-ddmmss.s")
                return
            elif len(params[0]) not in [8, 9]:
                print("Error: RA value forms sholud be +/-ddmmss.s")
                return
            return await send_command('COMMAND NEXTRA', telcom_client, params[0])

        elif cmd == 'teldec':
            if len(params) != 1:
                print("Error: 'teldec' requires one parameter (DEC value). Example: mvdec +/-ddmmss.s")
                return
            elif len(params[0]) not in [8, 9]:
                print("Error: DEC value forms sholud be +/-ddmmss.s")
                return
            return await send_command('COMMAND NEXTDEC', telcom_client, params[0])

        elif cmd == 'teltrack':
            if len(params) != 1 or params[0] not in ['ON', 'OFF']:
                print("Error: 'teltrack' requires one parameter (ON or OFF). Example: track ON/OFF")
                return
            return await send_command('COMMAND TRACK', telcom_client, params[0])

        elif cmd == 'telelaz':
            if len(params) != 2:
                print("Error: 'telelaz' requires two parameter (EL and AZ). Example: telelaz ee.ee aaa.aa")
                return
            elif len(params[0]) not in [3, 4,5] or len(params[1]) not in [3,4,5,6]:
                print("Error: EL and AZ value forms sholud be +/-ee.ee aaa.aa")
                return
            return await send_command('COMMAND ELAZ', telcom_client, f'{params[0]} {params[1]}')

        else:
            print(f"Error: Invalid command '{cmd}' or incorrect parameters.")
    except ValueError:
        print(f"Error: Invalid parameter type for command '{cmd}'. Ensure parameters are correctly formatted.")
    except Exception as e:
        print(f"Error: Failed to process command '{cmd}'. Exception: {e}")


