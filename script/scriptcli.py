import os, sys
import json
import redis
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import asyncio
import numpy as np
import pandas as pd
from astropy.coordinates import Angle, SkyCoord
import astropy.units as u
from astropy.io import fits

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



def printing(message):
    """Utility function for consistent printinging."""
    print(f"\n\033[32m[ICS] {message}\033[0m\n",flush=True)


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
    new_coord = coord.spherical_offsets_by(offset_ra * u.arcsec,offset_dec * u.arcsec)
    return new_coord.to_string('hmsdms', sep=":", precision=2)


def update_fits(fits_file,updates,output_file=None):
    """Update FITS file header with provided key-value pairs."""
    try:
        with fits.open(fits_file, mode='update' if output_file is None else 'readonly') as hdul:
            header = hdul[0].header
            for key, value in updates.items():
                header[key] = value
                print(f"Updated {key} to {value}")

            if output_file:
                hdul.writeto(output_file, overwrite=True)
                print(f"Updated FITS file saved as {output_file}")
            else:
                hdul.flush()
                print("Original FITS file updated.")
    except Exception as e:
        print(f"FITS header update failed: {e}")


async def clear_queue(queue):
    """Clear all items from an asyncio Queue."""
    while not queue.empty():
        queue.get_nowait()
        queue.task_done()


class script():
    def __init__(self):
        self.autoguide_task = None
        self.script_task = None
        self.fwhm = None

    async def obs_initial(self,ICSclient,send_udp_message, send_telcom_command, 
            response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue):
        """Initialize all instruments."""
        print('Start instruments intialization')
        await handle_endo('endostatus',ICSclient)
        await response_queue.get()
        await handle_gfa('gfastatus',ICSclient)
        await response_queue.get()
        await handle_fbp('fbpstatus',ICSclient)
        await response_queue.get()
        await handle_mtl('mtlstatus',ICSclient)
        await response_queue.get()
        await handle_adc('adcconnect',ICSclient)
        await response_queue.get()
        await handle_adc('adchome',ICSclient)
        await response_queue.get()
        await handle_adc('adczero',ICSclient)
        await response_queue.get()
        await handle_adc('adcstatus',ICSclient)
        await response_queue.get()
        await handle_spec('specstatus',ICSclient)
        await response_queue.get()

    async def run_calib(self,ICSclient,send_udp_message, send_telcom_command, 
            response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue):
        """Starts the calibration process asynchronously."""
        self.script_task = asyncio.create_task(
                self.handle_calib(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue)
        )

    async def handle_calib(self,ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue):
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

        printing("All Calibration images were obtained.")
    

    async def run_autoguide(self,ICSclient,send_udp_message, send_telcom_command, 
            response_queue, GFA_response_queue, exptime: float = 1.0):
        """Starts the autoguiding process asynchronously."""
        if self.autoguide_task and not self.autoguide_task.done():
            print("Autoguide task is already running. Ignoring duplicate start.")
            return
        self.autoguide_task = asyncio.create_task(
                self.handle_autoguide(exptime, ICSclient, send_udp_message, send_telcom_command, response_queue, GFA_response_queue)
        )

    async def handle_autoguide(self,exptime,ICSclient, send_udp_message, send_telcom_command, response_queue, GFA_response_queue):
        try:
            await handle_gfa(f'gfaguide {exptime}',ICSclient)
            while True:
                try:
                    response_data = await asyncio.wait_for(GFA_response_queue.get(),timeout=70)
                except asyncio.TimeoutError:
                    print("No GFA response")
                    continue

                fdx=response_data['fdx']
                fdy=response_data['fdy']
                self.fwhm=response_data['fwhm']
         #       ra= await send_telcom_command('getra')
         #       dec= await send_telcom_command('getdec')
         #       ra=ra.decode()
         #       dec=dec.decode()
         #       rahms,decdms=convert_to_sexagesimal(ra,dec)
         #       new_coord=apply_offset(rahms,decdms,fdx,fdy)
         #       messagetcs = 'KSPEC>TC ' + 'tmradec ' + new_coord
                print('ttttt')
              #  await send_udp_message(messagetcs)

        except asyncio.CancelledError:
            print("Autoguide task was cancelled.")
            raise

        finally:
            print("Autoguide task finished.")
            self.autoguide_task = None

    async def autoguidestop(self,ICSclient):
        """Stops the autoguiding process if it is running."""
        await handle_gfa("gfaguidestop", ICSclient)
        print("Stopping autoguiding task...")

        if self.autoguide_task:
            if not self.autoguide_task.done():
                printing("Cancelling autoguiding task...")
                self.autoguide_task.cancel()
                try:
                    await self.autoguide_task
                  #  await clear_queue(GFA_response_queue)
                except asyncio.CancelledError:
                    printing("Autoguiding task was successfully cancelled.")
            else:
                printing("Autoguiding task already completed.")
            self.autoguide_task = None
        else:
            printing("No Autoguiding task is currently running.")

    async def run_obs(self,ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue):
        self.script_task = asyncio.create_task(self.handle_obs(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue))

    async def handle_obs(self,ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue):
        await clear_queue(response_queue)
        await clear_queue(GFA_response_queue)
        await clear_queue(ADC_response_queue)
        await clear_queue(SPEC_response_queue)
        
        printing('###### Observation Script Start!!! ######')
        with open('./Lib/KSPEC.ini','r') as fs:
            kspecinfo=json.load(fs)
        fs.close()
        obsplanpath=kspecinfo['SCIOBS']['obsplanpath']

        
        while True:
            filename=input('\nPlease insert Observation sequence file (ex. ASPECS_obs_250217.txt): ')
            filepath=os.path.join(obsplanpath,filename)
            if not filename:
                continue
            if os.path.exists(filepath):
                break
            print(f'These is no {filename} in observation plan directory.')

        sciobs=sciobscli()
        wild=filename.split('_')
        sciobs.project=wild[0]
        sciobs.obsdate=wild[-1].split('.')[0]

        printing(f'Project Name: {sciobs.project}')
        printing(f'Observation Date: {sciobs.obsdate}')
        
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
        await asyncio.sleep(2)

        await ICSclient.send_message("MTL", objmsg)
        await response_queue.get()
        await asyncio.sleep(2)

        await ICSclient.send_message("FBP", objmsg)
        await response_queue.get()
        await asyncio.sleep(2)

        await ICSclient.send_message("FBP", motionmsg1)
        await response_queue.get()
        await asyncio.sleep(2)

        await ICSclient.send_message("FBP", motionmsg2)
        await response_queue.get()
        await asyncio.sleep(2)
        
        await asyncio.sleep(2)
        printing(f'ADC Adjust Start')
        message=f'adcadjust {ra} {dec}'
        message=f'adcadjust 04:34:56.44 -31:34:55.67'
        await handle_adc(message,ICSclient)
        await asyncio.sleep(2)

        printing(f'Fiber positioner Moving Start')
        await handle_fbp('fbpmove',ICSclient)
        await response_queue.get()
        sys.stdout.flush()
        await asyncio.sleep(0)

        messagetcs = 'KSPEC>TC ' + 'tmradec ' + ra +' '+dec
        printing(f'Slew Telescope to RA={ra}, DEC={dec}.')
        await send_udp_message(messagetcs)
        print('Telescope is slewing now.', end=' ',flush=True)

        while True:
            r=redis.Redis(host='localhost',port=6379,decode_responses=True)

            value=r.get('dome_error')

            if value.decode() == '0001':
                print('Telescope slew finished')
                break
            print('.',end=' ', flush=True)
            await asyncio.sleep(5)
        
        printing(f'Autoguiding Start')
        await self.run_autoguide(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue)
        
        await asyncio.sleep(2)
        await handle_spec('illuon',ICSclient)
        await response_queue.get()
        await asyncio.sleep(2)

        await handle_lamp('fiducialon',ICSclient)
        await response_queue.get()
        await asyncio.sleep(2)

        await handle_mtl('mtlexp 10',ICSclient)
        await response_queue.get()
        await asyncio.sleep(2)

        await handle_mtl('mtlcal',ICSclient)
        aaa=await response_queue.get()
        await asyncio.sleep(2)

        await handle_fbp('fbpoffset',ICSclient)
        await response_queue.get()
        await asyncio.sleep(2)

        await handle_spec('illuoff',ICSclient)
        await response_queue.get()
        await asyncio.sleep(2)

        await handle_lamp('fiducialoff',ICSclient)
        await response_queue.get()
        await asyncio.sleep(2)

        
        print(f'FHWM is {self.fwhm:.5f}.')

        obs_num=3
        printing(f'KSPEC starts {obs_num} exposures with 300 seconds.')
        for i in range(int(obs_num)):
            await clear_queue(SPEC_response_queue)
            await handle_spec(f'getobj 30 1', ICSclient)
            printing(f'{i+1}/{obs_num}: 30 seconds exposure start.')
            spec_rsp=await response_queue.get()
            fram=f'{i+1}/{obs_num}'
            header_data = {"PROJECT": sciobs.project, "EXPTIME": 20, "FRAME": fram, "Tile": select_tile, "PRORA": ra, "PRODEC": dec}
            update_fits(spec_rsp["file"],header_data)
            printing("Fits header updated")


        printing('All exposures are completed.')
        await handle_adc('adcstop',ICSclient)
        await response_queue.get()
        await self.autoguidestop(ICSclient)
        await response_queue.get()
        await handle_adc('adczero',ICSclient)
        await response_queue.get()

        await asyncio.sleep(3)
        printing(f'###### Observation Script for Tile ID {select_tile} END!!! ######')
        


async def handle_script(arg, ICSclient, send_udp_message, send_telcom_command, 
        response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue):
    """ Handle script with error checking. """
    cmd, *params = arg.split()
    scriptrun=script()
    command_map = {
            'obsinitial': scriptrun.obs_initial, 'runcalib': scriptrun.run_calib, 'runobs': scriptrun.run_obs
    }

    if cmd in command_map:
        await command_map[cmd](ICSclient,send_udp_message, send_telcom_command, 
                response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue)
    elif cmd == 'autoguide':
        if not params:
            await scriptrun.run_autoguide(ICSclient, send_udp_message, send_telcom_command, response_queue, GFA_response_queue)
        else:
            await scriptrun.run_autoguide(ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, params[0])

    elif cmd == 'autoguidestop':
        await scriptrun.autoguidestop(ICSclient)
    else:
        print(f"Error: '{cmd}' is not right command for SCRIPT")


