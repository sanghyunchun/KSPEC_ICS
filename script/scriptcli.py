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
    print(f"\033[32m[ICS] {message}\033[0m",flush=True)

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
    await handle_adc('adcconnect',ICSclient)
    await response_queue.get()
    await handle_adc('adchome',ICSclient)
    await response_queue.get()
    await handle_adc('adczero',ICSclient)
    await response_queue.get()
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
    
    await handle_spec('getflat 10 10',ICSclient)
    await response_queue.get()
    
    await handle_lamp('flatoff',ICSclient)
    await response_queue.get()
    
    await handle_lamp('arcon',ICSclient)
    await response_queue.get()
    
    await handle_spec('getarc 10 10',ICSclient)
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
    global script_task
    script_task = asyncio.create_task(handle_obs(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue))

async def handle_obs(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue):
    printing('###### Observation Script Start!!! ######')
    filename=input('\nPlease insert Observation sequence file (ex. ASPECS_obs_250217.txt): ')
    sciobs=sciobscli()
    wild=filename.split('_')
    sciobs.project=wild[0]
    sciobs.obsdate=wild[-1].split('.')[0]

    printing(f'Project Name: {sciobs.project}')
    printing(f'Observation Date: {sciobs.obsdate}')
    with open('./Lib/KSPEC.ini','r') as fs:
        kspecinfo=json.load(fs)
    fs.close()

    obsplanpath=kspecinfo['SCIOBS']['obsplanpath']
    with open(obsplanpath+filename,'r') as f:
        header = f.readline().strip().split()

    data=np.loadtxt(obsplanpath+filename,skiprows=1,dtype=str)

    print('### Load tile information ###')
    print("\t".join(header))
    for row in data:
        print("\t".join(row), flush=True)

    tile_ids = set(row[0] for row in data)
    while True:
        select_tile=input('\nPlease select Tile ID above you want to runscript.: ')
        if select_tile.strip() in tile_ids:
            printing(f'Tile ID {select_tile} is selected from observation plan.')
            for row in data:
                if row[0] == select_tile:
                    print(row)
                    obs_num=row[2]
                    print(f'Observation number of exposure: {obs_num}')
            break
        else:
            print(f'Tile ID {select_tile} was not found. Please enter a valid ID.')

    tilemsg,guidemsg,objmsg,motionmsg1,motionmsg2=sciobs.loadtile(select_tile)
    tile_data=json.loads(tilemsg)
    ra,dec=convert_to_sexagesimal(tile_data['ra'],tile_data['dec'])

    printing(f'RA and DEC of Tile ID {select_tile}: {ra} {dec}')

    await ICSclient.send_message("GFA", guidemsg)
    await response_queue.get()

    await ICSclient.send_message("MTL", objmsg)
    await response_queue.get()

    await ICSclient.send_message("FBP", objmsg)
    await response_queue.get()

    await ICSclient.send_message("FBP", motionmsg1)
    await response_queue.get()

    await ICSclient.send_message("FBP", motionmsg2)
    await response_queue.get()

    await asyncio.sleep(3)
    
    messagetcs = 'KSPEC>TC ' + 'tmradec ' + ra +' '+dec
    printing(f'Slew Telescope to RA={ra}, DEC={dec}.')
    await send_udp_message(messagetcs)

    await asyncio.sleep(1)
    printing(f'ADC Adjust Start')
#    message=f'adcadjust {ra} {dec}'
    message=f'adcadjust 23:34:56.44 -31:34:55.67'
    await handle_adc(message,ICSclient)
    await asyncio.sleep(3)

    printing(f'Fiber positioner Moving Start')
    await handle_fbp('fbpmove',ICSclient)
    await response_queue.get()

    while True:
        user_input=input("Are you sure that telescope slewing finished? (yes/no): ")
        if user_input.lower() == "yes":
            print('Continue next process.....')
            break
        else:
            print("Wait until slewing finished and then insert 'yes'.")

    printing(f'Autoguiding Start')
    await run_autoguide(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue)
    
    await asyncio.sleep(2)
    await handle_spec('illuon',ICSclient)
    await response_queue.get()
    await handle_lamp('fiducialon',ICSclient)
    await response_queue.get()
    await handle_mtl('mtlexp 10',ICSclient)
    await response_queue.get()
    await handle_mtl('mtlcal',ICSclient)
    await response_queue.get()
    await handle_fbp('fbpoffset',ICSclient)
    await response_queue.get()
    await handle_spec('illuoff',ICSclient)
    await response_queue.get()
    await handle_lamp('fiducialoff',ICSclient)
    await response_queue.get()

    await handle_spec(f'getobj 300 {obs_num}', ICSclient)
    printing(' ###### Observation Script END!!! ######')
#    await response_queue.get()



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






