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
    cmd = create_command(action, param)
    return await telcom_client.send_receive(cmd)

command_map = {
    'getall': 'REQUEST ALL', 'getra': 'REQUEST RA', 'getdec': 'REQUEST DEC', 
    'getha': 'REQUEST HA', 'getel': 'REQUEST EL', 'getaz': 'REQUEST AZ', 'getsecz': 'REQUEST SECZ',
    'mvstow': 'COMMAND MOVSTOW', 'mvelaz': 'COMMAND ELAZ', 'mvstop': 'COMMAND CANCEL'
}

async def handle_telcom(arg, telcom_client):
    cmd, *params = arg.split()
    
    if cmd in command_map:
        return await send_command(command_map[cmd], telcom_client)
    
    elif cmd == 'mvra' and len(params) == 1:
        return await send_command('COMMAND NEXTRA', telcom_client, params[0])
    
    elif cmd == 'mvdec' and len(params) == 1:
        return await send_command('COMMAND NEXTDEC', telcom_client, params[0])
    
    elif cmd == 'track' and len(params) == 1:
        return await send_command('COMMAND TRACK', telcom_client, params[0])
    
    else:
        print(f"Error: Invalid command '{cmd}' or incorrect parameters.")

