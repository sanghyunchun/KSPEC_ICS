import os,sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from SCIOBS.sciobscli import load_tile,tra
from GFA.gfacli import gfa_cexp, gfa_allexp,gfa_stop
from MTL.mtlcli import mtl_exp
from TCS.tcscli import *
import configparser as cp
from Lib.AMQ import *

cfg=cp.ConfigParser()
cfg.read('/media/shyunc/DATA/KSpec/KSPECICS_P4/Lib/KSPEC.ini')
ip_addr=cfg.get("MAIN","ip_addr")
idname=cfg.get("MAIN","idname")
pwd=cfg.get("MAIN",'pwd')

cmdlist=['','loadtile','gfacexp','gfaallexp','tra','tpark','gfastop','mtlexp']

async def identify(arg):
    ICS_client = Client(ip_addr,idname,pwd)
#    print(arg)
    cmd=arg.split(' ')

    if cmd[0] not in cmdlist:
        print('Please insert right command')

# Load tile information. Send tile information to GFA,Spectrograph,Metrology
    if cmd[0] == 'loadtile':
#        GFA_client = Client(ip_addr,idname,pwd)
        msg=load_tile(cmd[1])
        asyncio.run(ICS_client.send_message("TCS",msg))
        asyncio.run(ICS_client.send_message("GFA",msg))

# Slew telescope to ra & dec
#    if cmd[0] == 'tra':
#        tcsmsg=tcs_tra(cmd[1],cmd[2])
#        asyncio.run(ICS_client.send_message("TCS",tcsmsg))
    


### Command for Guide Camera ###############
# Start exposure specific guide camera
    if cmd[0] == 'gfacexp':
        gfamsg=gfa_cexp(cmd[1],cmd[2])
        asyncio.run(ICS_client.send_message("GFA", gfamsg))


# Start exposure all guide camera
    if cmd[0] == 'gfaallexp':
        gfamsg=gfa_allexp(cmd[1])
#        asyncio.run(ICS_client.send_message("GFA", gfamsg))
        await ICS_client.send_message("GFA", gfamsg)

# Stop GFA camera exposure
    if cmd[0] == 'gfastop':
        gfamsg=gfa_stop()
        asyncio.run(ICS_client.send_message("GFA", gfamsg))


### Command for Metrology #################
# Start Metrology exposure
    if cmd[0] == 'mtlexp':
        mtlmsg=mtl_exp()
        print(mtlmsg)
        await ICS_client.send_message("MTL", mtlmsg)


# Command for TCS
async def tcsidentify(arg,TCSclient):
    if cmd[0] == 'tra'
        await trafun(arg)
#        TCS_client=TCSclient()
#        asyncio.run(TCS_client.connect())
#        asyncio.run(TCS_client.send_message(arg))
#        asyncio.create_task(TCS_client.receive_message())
    if cmd[0] == 'tpark':
        trafun(arg)

    if cmd[0] == 'START':
        await tcsstart(arg)
