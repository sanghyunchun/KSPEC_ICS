import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import asyncio
from TCS import tcscli
from GFA.gfacli import handle_gfa
from MTL.mtlcli import handle_mtl
from FBP.fbpcli import handle_fbp
from ADC.adccli import handle_adc
from LAMP.lampcli import handle_lamp
from SPECTRO.speccli import handle_spec
from ENDO.ENDOcli import handle_endo
from SCIOBS.sciobscli import sciobscli
import Lib.process as processes
import numpy as np
import pandas as pd
import json


with open('./Lib/KSPEC.ini','r') as fs:
    kspecinfo=json.load(fs)

osbplanpath=kspecinfo['SCIOBS']['obsplanpath']

async def run_script(ICS_client,transport,filename):

    data=pd.read_csv(obsplanpath+filename)
    print(data)
    select_tile=input('Please select Tile ID above you want to runscript.: ')
    print(f'Tile ID {select_tile} is selected from observation plan.')

    print('### Load tile information ###')
    tilemsg,guidemsg,objmsg,motionmsg1,motionmsg2=loadtile(select_tile)
    await ICS_client.send_message("GFA", guidemsg)
    await ICS_client.send_message("MTL", objmsg)
    await ICS_client.send_message("FBP", objmsg)
    await ICS_client.send_message("FBP", motionmsg1)
    await ICS_client.send_message("FBP", motionmsg2)

    await asyncio.sleep(1)
    tile_data=json.loads(tilemsg)
    ra=tile_data['ra']
    dec=tile_data['dec']
    print(f'### Slew telescope to {ra}, {dec} ###')
    message=f'KSPEC>TC tmradec {ra} {dec}'
    transport.sendto(message.encode())
    
    print(f'Telescope is slewing to {ra}, {dec}...')
    await asyncio.sleep(15)
    print(f'Telescope slewing finished.')
    while True:
        resume=input('Move to next sequence (yes/no)? ')
        if resume == 'yes':
            break

    
#    print('### Augoduding Start ###')
#    gfamsg=gfa_autoguide()
#    await ICS_client.send_message("GFA", gfamsg) 

    print('### Fiducial and illumination lamp on ###')
    lampmsg=fiducial_on()
    await ICS_client.send_message("LAMP",lampmsg)

#    specmsg=spec_illu_on()
#    await ICS_client.send_message("SPEC",specmsg)

#    mtlmsg=mtl_exp(3)
#    await ICS_client.send_message("MTL", mtlmsg)

#    ttt=tcscli.Telcomclass()
#    ttt.TelcomConnect()
#    RA=ttt.RequestRA()
#    print(RA)

#    gfamsg=gfa_allexp(10)
#    await ICS_client.send_message("GFA", gfamsg)

#    mtlmsg=mtl_exp()
#    await ICS_client.send_message("MTL", mtlmsg)


async def obs_initial(ICSclient,tcstransport):
    print('Start instruments intialize')
    await handle_endo('endostatus',ICSclient)
    await handle_gfa('gfastatus',ICSclient)
    await handle_fbp('fbpstatus',ICSclient)
    await handle_mtl('mtlstatus',ICSclient)
    await handle_adc('adchome',ICSclient)
    await handle_adc('adczero',ICSclient)
    await handle_adc('adcstatus',ICSclient)
    await handle_spec('specstatus',ICSclient)



async def run_calib(ICSclient,tcstransport):
    print('Get Calibration Frame')

    await handle_lamp('flaton',ICSclient)

    await handle_spec('getflat 2 10',ICSclient)

    await handle_lamp('flatoff',ICSclient)
    await handle_lamp('arcon',ICSclient)
    await handle_spec('getarc 2 10',ICSclient)
    await handle_lamp('arcoff',ICSclient)



async def handle_script(cmd, ICSclient,tcstransport):
    """ Handle script with error checking. """
    command_map = {
            'obsinitial': obs_initial, 'runcalib': run_calib
    }

    if cmd in command_map:
        await command_map[cmd](ICSclient,tcstransport)
    else:
        print(f"Error: '{cmd}' is not right command for SCRIPT")






