import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import asyncio
from GFA.gfacli import *
from MTL.mtlcli import *
from TCS import tcscli
from FBP.fbpcli import *
from ADC.adccli import *
from LAMP.lampcli import *
from SPECTRO.speccli import *
from SCIOBS.sciobscli import sciobscli
import Lib.process as processes
import numpy as np
import pandas as pd
import json


with open('./Lib/KSPEC.ini','r') as fs:
    kspecinfo=json.load(fs)

osbplanpath=kspecinfo['SCIOBS']['obsplanpath']

async def scriptrun(ICS_client,transport,filename):

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
    message=f'KSEPC>TC tmradec {ra} {dec}'
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


async def adc_run():
    ra=123.45
    dec=-34.56
    obsnum=6

    zdist=calculate_zenith_distance(ra,dec)
    current=zdist
    for i in range(6):
        next=calculate_zenith_distance(ra,dec)
        count=3456
        command=adc_activate(count)
        print(command)
        await asyncio.sleep(30)





