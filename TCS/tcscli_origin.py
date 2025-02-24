import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import asyncio
import socket

tele_num = 150
TELID = 'KMTNET'
SYSID = 'TCS'
PID = '123'

async def RequestRA(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} REQUEST RA'
    print('Telescope request cmd :', cmd)
    recv = await telcom_client.send_receive(cmd)
    return recv

async def RequestALL(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} REQUEST ALL'
    print('Telescope request cmd :', cmd)
    recv = await telcom_client.send_receive(cmd)
    return recv

async async def RequestHA(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} REQUEST HA'
    print('Telescope request cmd :', cmd)
    recv = await telcom_client.send_receive(cmd)
    return recv

async def RequestDEC(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} REQUEST DEC'
    print('Telescope request cmd :', cmd)
    recv = await telcom_client.send_receive(cmd)
    return recv

async def RequestEL(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} REQUEST EL'
    print('Telescope request cmd :', cmd)
    recv = await telcom_client.send_receive(cmd)
    return recv

async def RequestAZ(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} REQUEST AZ'
    print('Telescope request cmd :', cmd)
    recv = await telcom_client.send_receive(cmd)
    return recv

async def RequestSECZ(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} REQUEST SECZ'
    print('Telescope request cmd :', cmd)
    recv = await telcom_client.send_receive(cmd)
    return recv

async def CommandNEXTRA(telcom_client,ra):
    cmd = f'{TELID} {SYSID} {PID} COMMAND NEXTRA {ra}'
    print('Telescope request cmd :', cmd)
    return cmd

async def CommandNEXTDEC(telcom_client,dec):
    cmd = f'{TELID} {SYSID} {PID} COMMAND NEXTDEC {dec}'
    print('Telescope request cmd :', cmd)
    return cmd

#async def CommandMVNEXT(telcom_client):
#    cmd = f'{TELID} {SYSID} {PID} COMMAND MOVNEXT'
#    print('Telescope request cmd :', cmd)
#    recv = await telcom_client.send_receive(cmd)
#    return recv

async def CommandMVSTOW(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} COMMAND MOVSTOW'
    print('Telescope request cmd :', cmd)
    return cmd

async def CommandMVELAZ(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} COMMAND ELAZ'
    print('Telescope request cmd :', cmd)
    return cmd

async def CommandMVSTOP(telcom_client):
    cmd = f'{TELID} {SYSID} {PID} COMMAND CANCEL'
    print('Telescope request cmd :', cmd)
    return cmd

async def CommandTRACK(telcom_client,bools):
    cmd = f'{TELID} {SYSID} {PID} COMMAND TRACK {bools}'
    print('Telescope request cmd :', cmd)
    return cmd


async def handle_telcom(arg,telcom_client):
    cmd, *params = arg.split()
    command_map = {
            'getall': RequestAll, 'getra': RequestRA, 'getdec': RequestDEC, 'getha': RequestHA, 'getel': RequestEL,
            'getaz': RequestAZ, 'getsecz': RequestSECZ
    }
    
    if cmd == 'mvra':
        if len(params) != 1:
            print("Error: 'mvra' needs one parameter: RA. ex) mvra 00:40:32.03 ")
            return
        try:
            RA= params[0]
        except ValueError:
            print(f"Error: Input parameters of 'mvra' should be string. input value: {params[0]}")
            return
        command_map[cmd] = lambda: CommandNEXTRA(RA)


    if cmd in command_map:
        telcommsg = command_map[cmd]()
        recv = await telcom_client.send_receive(telcommsg)
        return recv
    else:
        print(f"Error: '{cmd}' is not right command for Telcom.")










