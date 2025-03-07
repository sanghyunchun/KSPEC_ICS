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
from astropy.coordinates import Angle, SkyCoord
import astropy.units as u


autoguide_task = None

def printing(message):
    """Utility function for consistent printingging."""
    print(f"\033[32m[ICS] {message}\033[0m")

def convert_to_sexagesimal(ra_deg, dec_deg):
    """Converts RA and DEC from degrees to sexagesimal format."""
    ra = Angle(ra_deg, unit=u.degree)
    dec = Angle(dec_deg, unit=u.degree)

    ra_hms = ra.to_string(unit=u.hour, sep=':', precision=2, pad=True)
    dec_dms = dec.to_string(unit=u.degree, sep=':', alwayssign=True, precision=2)
    return ra_hms, dec_dms

def apply_offset(ra: str, dec: str, offset_ra: float, offset_dec: float):
    """Applies an offset in arcseconds to the given RA and DEC coordinates."""
    coord = SkyCoord(ra, dec, frame='icrs', unit=(u.hourangle, u.deg))
    
    new_coord = coord.spherical_offsets_by(
        offset_ra * u.arcsec,  
        offset_dec * u.arcsec
    )
    return new_coord.to_string('hmsdms',precision=2).replace('h', ':').replace('m', ':').replace('s', '').replace('d', ':')


async def obs_initial(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue):
    print('Start instruments intialize')
    await handle_endo('endostatus',ICSclient)
    await handle_gfa('gfastatus',ICSclient)
    await handle_fbp('fbpstatus',ICSclient)
    await handle_mtl('mtlstatus',ICSclient)
    await handle_adc('adchome',ICSclient)
    await handle_adc('adczero',ICSclient)
    await handle_adc('adcstatus',ICSclient)
    await handle_spec('specstatus',ICSclient)

async def run_calib(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue):
    """Starts the calibration process asynchronously."""
    script_task = asyncio.create_task(handle_calib(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue))

async def handle_calib(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue):
    """Handles the calibration process by controlling lamps and spectrometers."""
    printing("New Calibration task started.")

    await handle_lamp('flaton',ICSclient)
    await response_queue.get()
    
    await handle_spec('getflat 30 1',ICSclient)
    await response_queue.get()
    
    await handle_lamp('flatoff',ICSclient)
    await response_queue.get()
    
    await handle_lamp('arcon',ICSclient)
    await response_queue.get()
    
    await handle_spec('getarc 30 1',ICSclient)
    await response_queue.get()
    
    await handle_lamp('arcoff',ICSclient)
    await response_queue.get()

async def run_autoguide(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue):
    """Starts the autoguiding process asynchronously."""
    global autoguide_task
    autoguide_task = asyncio.create_task(handle_autoguide(ICSclient, send_udp_message, send_telcom_command, response_queue, GFA_response_queue))

async def handle_autoguide(ICSclient, send_udp_message, send_telcom_command, response_queue, GFA_response_queue):
    try:
        await handle_gfa('gfaguide',ICSclient)
        while True:
            response_data = await GFA_response_queue.get()
            fdx=response_data['fdx']
            fdy=response_data['fdy']
            ra= await send_telcom_command('getra')
            dec= await send_telcom_command('getdec')
            ra=ra.decode()
            dec=dec.decode()
            rahms,decdms=convert_to_sexagesimal(ra,dec)
            new_coord=apply_offset(rahms,decdms,fdx,fdy)
            messagetcs = 'KSPEC>TC ' + 'tmradec ' + new_coord
            await send_udp_message(messagetcs)

    except asyncio.CancelledError:
        print("Autoguide task was cancelled.")

async def autoguidestop(ICSclient):
    """Stops the autoguiding process if it is running."""
    global autoguide_task
    if autoguide_task and not autoguide_task.done():
        await handle_gfa("gfaguidestop", ICSclient)
        print("Stopping autoguiding task...")
        autoguide_task.cancel()
        try:
            await autoguide_task
        except asyncio.CancelledError:
            printing("Autoguiding task stopped.")
    else:
        printing("No Autoguiding task is currently running.")

async def run_obs(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue):
    filename=input('Please insert Observation sequence file (ex. ASPECS_obs_250217.txt): ')
    script_task = asyncio.create_task(handle_obs(ICSclient,transport,filename))
    script_task = None

async def handle_obs(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue):
    sciobs=sciobscli()
    wild=filename.split('_')
    sciobs.project=wild[0]
    sciobs.obsdate=wild[-1].split('.')[0]
    
    print('\n')
    printing(f'Project Name: {sciobs.project}')
    printing(f'Observation Date: {sciobs.obsdate}')
    with open('./Lib/KSPEC.ini','r') as fs:
        kspecinfo=json.load(fs)
    fs.close()

    obsplanpath=kspecinfo['SCIOBS']['obsplanpath']
    data=pd.read_csv(obsplanpath+filename)

    print('\n')
    print('### Load tile information ###')
    print(data)

    while True:
        select_tile=input('\nPlease select Tile ID above you want to runscript.: ')
        if select_tile.strip():
            printing(f'Tile ID {select_tile} is selected from observation plan.')
            break
        else:
            print('Tile ID was not selected.')

    sciobs=sciobscli()
    wild=filename.split('_')
    sciobs.project=wild[0]
    sciobs.obsdate=wild[-1].split('.')[0]

#    sciobs.loadtile(select_tile)
    tilemsg,guidemsg,objmsg,motionmsg1,motionmsg2=sciobs.loadtile(select_tile)
    ICSclient.stop_event = asyncio.Event()
    await ICSclient.send_message("GFA", guidemsg)
    await ICSclient.stop_event.wait()
    ICSclient.stop_event = asyncio.Event()
    await ICSclient.send_message("MTL", objmsg)
    await ICSclient.stop_event.wait()
    ICSclient.stop_event = asyncio.Event()
    await ICSclient.send_message("FBP", objmsg)
    await ICSclient.stop_event.wait()
    ICSclient.stop_event = asyncio.Event()
    await ICSclient.send_message("FBP", motionmsg1)
    await ICSclient.stop_event.wait()
    ICSclient.stop_event = asyncio.Event()
    await ICSclient.send_message("FBP", motionmsg2)
    await ICSclient.stop_event.wait()

#    await asyncio.sleep(1)
    tile_data=json.loads(tilemsg)
    ra,dec=convert_to_sexagesimal(tile_data['ra'],tile_data['dec'])
    
    printing(f"ICS sent message to device 'TCS'. message: Slew telescope to {ra}, {dec} ###")
    message=f'KSPEC>TC tmradec {ra} {dec}'
    transport.sendto(message.encode())
   

    ICSclient.stop_event = asyncio.Event()
    await handle_gfa('gfaguide',ICSclient)
    await ICSclient.stop_event.wait()

#    print(f'Telescope is slewing to {ra}, {dec}...')
#    await asyncio.sleep(15)
#    print(f'Telescope slewing finished.')
#    while True:
#        resume=input('Move to next sequence (yes/no)? ')
#        if resume == 'yes':
#            break

    
#    print('### Augoduding Start ###')
#    gfamsg=gfa_autoguide()
#    await ICS_client.send_message("GFA", gfamsg) 

#    print('### Fiducial and illumination lamp on ###')
#    lampmsg=fiducial_on()
#    await ICS_client.send_message("LAMP",lampmsg)

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


async def handle_script(arg, ICSclient, send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue):
    """ Handle script with error checking. """
    cmd, *params = arg.split()
    print(cmd)
#    global script_task
    command_map = {
            'obsinitial': obs_initial, 'runcalib': run_calib, 'runobs': run_obs, 'autoguide': run_autoguide
    }

    if cmd in command_map:
        await command_map[cmd](ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue)
    elif cmd == 'autoguidestop':
        await autoguidestop(ICSclient)
    else:
        print(f"Error: '{cmd}' is not right command for SCRIPT")






