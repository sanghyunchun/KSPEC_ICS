import os, sys
import json
#import redis
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import asyncio
import numpy as np
import pandas as pd
from astropy.coordinates import Angle, SkyCoord
import astropy.units as u
from astropy.io import fits

#from TCS import tcscli
from GFA.gfacli import handle_gfa
from MTL.mtlcli import handle_mtl
from FBP.fbpcli import handle_fbp
from ADC.adccli import handle_adc
from LAMP.lampcli import handle_lamp
from SPECTRO.speccli import handle_spec
from ENDO.ENDOcli import handle_endo
from SCIOBS.sciobscli import sciobscli
import Lib.process as processes
from TCS.tcscli import handle_telcom


def printing(message):
    """Utility function for consistent printinging."""
    print(f"\n\033[32m[ICS] {message}\033[0m\n",flush=True)


#def convert_to_sexagesimal(ra_deg, dec_deg):
#    """Converts RA and DEC from degrees to sexagesimal format."""
#    ra = Angle(ra_deg, unit=u.degree)
#    dec = Angle(dec_deg, unit=u.degree)

#    ra_hms = ra.to_string(unit=u.hour, sep=':', precision=2, pad=True)
#    dec_dms = dec.to_string(unit=u.degree, sep=':', alwayssign=True, precision=2)
#    return ra_hms, dec_dms

def bytes_to_sexagesimal(value: bytes, encoding="ascii") -> str:
        """
        b"453467.8"  -> "45:34:67.8"
        b"-453456.7" -> "-45:34:56.7"
        """
        # bytes → str
        s = value.decode(encoding).strip()

        sign = "-" if s.startswith("-") else ""
        s = s.lstrip("+-")

        if "." in s:
            integer, frac = s.split(".", 1)
            frac = "." + frac
        else:
            integer = s
            frac = ""

        if len(integer) < 6:
            raise ValueError(f"Not enough Digit for sexagesimal convert: {s}")

        h = integer[0:2]
        m = integer[2:4]
        sec = integer[4:] + frac

        return f"{sign}{h}:{m}:{sec}"


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
        self.ra = None
        self.dec = None
        self.select_tile = None
        self.project = None
        self.obsdate = None
        self.dir_name = None
        self.obsnum = None
        self.expT = None
        self.MTLexpT = 5.    # default MTL exposure time
        self.GFAexpT = 5.    # default GFA exposure time

    def configure_cordinate(self, project, obsdate, tileid, value1, value2, obsnum, expT):
        self.project = project
        self.obsdate = obsdate
        self.select_tile = tileid
        self.ra = value1
        self.dec = value2
        self.obsnum = obsnum
        self.expT = expT
        print(f'{self.select_tile}, {self.ra}, {self.dec}')

    def initialize_dependencies(self, ICSclient, send_udp_message, send_telcom_command,
            response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue, show_status, dir_name):
        self.ICSclient = ICSclient
        self.send_udp_message = send_udp_message 
        self.send_telcom_command = send_telcom_command
        self.response_queue = response_queue 
        self.GFA_response_queue = GFA_response_queue 
        self.ADC_response_queue = ADC_response_queue 
        self.SPEC_response_queue = SPEC_response_queue 
        self.show_status = show_status
        self.dir_name = dir_name

    def MTL_set(self,exptime):
        self.MTLexpT = exptime
    #    print(f'MTL exposure time is {self.MTLexpT}')


    def GFA_set(self,exptime):
        self.GFAexpT = exptime

    async def obs_initial(self,scriptrun,logging):
        """Initialize all instruments."""
        print('Start instruments intialization')
        await clear_queue(scriptrun.response_queue)
        await clear_queue(scriptrun.GFA_response_queue)
        await clear_queue(scriptrun.ADC_response_queue)
        await clear_queue(scriptrun.SPEC_response_queue)
        await handle_gfa('gfastatus',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await handle_fbp('fbpstatus',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await handle_mtl('mtlstatus',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await handle_adc('adcconnect',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await handle_adc('adchome',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await handle_adc('adczero',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await handle_adc('adcstatus',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await handle_spec(f'specinitial {self.dir_name}',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await handle_spec('specstatus',scriptrun.ICSclient)
        await scriptrun.response_queue.get()

    async def run_calib(self,scriptrun,logging):
        """Starts the calibration process asynchronously."""
        self.script_task = asyncio.create_task(
                self.handle_calib(scriptrun,logging)
        )

#    async def handle_calib(self,ICSclient,send_udp_message, send_telcom_command, response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue, logging):
    async def handle_calib(self,scriptrun,logging):
        """Handles the calibration process by controlling lamps and spectrometers."""
        printing("New Calibration task started.")
        await clear_queue(scriptrun.response_queue)
        await clear_queue(scriptrun.GFA_response_queue)
        await clear_queue(scriptrun.ADC_response_queue)
        await clear_queue(scriptrun.SPEC_response_queue)
        

        if logging != None:
            logging('Sent Flat on.', level='send')

        await handle_lamp('flaton',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
    
        if logging != None:
            logging('Sent getflat 10 10.', level='send')

        await handle_spec('getflat 10 10',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        
        if logging != None:
            logging('Sent Flat off.', level='send')

        await handle_lamp('flatoff',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        
        if logging != None:
            logging('Sent Arc on.',level='send')

        await handle_lamp('arcon',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        
        if logging != None:
            logging('Sent getarc 10 10.',level='send')

        await handle_spec('getarc 10 10',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        
        if logging != None:
            logging('Sent Arc off.',level='send')

        await handle_lamp('arcoff',scriptrun.ICSclient)
        await scriptrun.response_queue.get()

        printing("All Calibration images were obtained.")
        self.scrpt_task = None
        if logging != None:
            logging("All Calibration images were obtained.", level='send')
            scriptrun.show_status('LAMP','normal')
            scriptrun.show_status('SPEC','normal')
            logging('Run Calibration Task finished', level='normal')


    async def run_autoguide(self,scriptrun, exptime: float = 5.0, save: bool = False):
        """Starts the autoguiding process asynchronously."""
        if self.autoguide_task and not self.autoguide_task.done():
            print("Autoguide task is already running. Ignoring duplicate start.")
            return
        self.autoguide_task = asyncio.create_task(
                self.handle_autoguide(exptime, save, scriptrun)
        )

    async def handle_autoguide(self, exptime, save, scriptrun):
        try:
            await handle_gfa(f'gfaguide {exptime} {save}',scriptrun.ICSclient)
            while True:
                try:
                    response_data = await asyncio.wait_for(scriptrun.GFA_response_queue.get(),timeout=70)
                except asyncio.TimeoutError:
                    print("No GFA response")
                    continue
                
                if "fdx" in response_data:
                    fdx=response_data['fdx']
                    fdy=response_data['fdy']
                    self.fwhm=response_data['fwhm']
                    ra_bytes = await scriptrun.send_telcom_command('getra')
                    dec_bytes = await scriptrun.send_telcom_command('getdec')

                    rahms=bytes_to_sexagesimal(ra_bytes)
                    decdms=bytes_to_sexagesimal(dec_bytes) 
                    new_coord=apply_offset(rahms,decdms,fdx,fdy)
                    messagetcs = 'KSPEC>TC ' + 'tmradec ' + new_coord
                    await scriptrun.send_udp_message(messagetcs)

        except asyncio.CancelledError:
            print("Autoguide task was cancelled.")
            raise

        finally:
            print("Autoguide task finished.")
            self.autoguide_task = None

    async def autoguidestop(self,scriptrun):
        """Stops the autoguiding process if it is running."""
        await handle_gfa("gfaguidestop", scriptrun.ICSclient)
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

    async def run_obs(self, scriptrun, logging):
        self.script_task = asyncio.create_task(self.handle_obs(scriptrun, logging))

    async def handle_obs(self,scriptrun,logging):
        await clear_queue(scriptrun.response_queue)
        await clear_queue(scriptrun.GFA_response_queue)
        await clear_queue(scriptrun.ADC_response_queue)
        await clear_queue(scriptrun.SPEC_response_queue)

        logging(f'###### Observation for Tile ID {self.select_tile} strats ######',level='comment')
        printing(f'###### Observation for Tile ID {self.select_tile} strats ######')
        
        if logging == None:
            printing('###### Observation Script Start!!! ######')
            with open('./Lib/KSPEC.ini','r') as fs:
                kspecinfo=json.load(fs)
            fs.close()
            obsplanpath=kspecinfo['SCIOBS']['obsplanpath']

            ### Start CLI version ###
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
            self.project=wild[0]
            self.obsdate=wild[-1].split('.')[0]

            printing(f'Project Name: {self.project}')
            printing(f'Observation Date: {self.obsdate}')
        
            with open(obsplanpath+filename,'r') as f:
                header = f.readline().strip().split()

            data=np.loadtxt(obsplanpath+filename,skiprows=1,dtype=str)

            print('### Load tile information ###')
            print("\t".join(header))
            for row in data:
                print("\t".join(row), flush=True)

            tile_ids = set(row[0] for row in data)
            while True:
                self.select_tile=input('\nPlease select Tile ID above you want to runscript.: ')
                if self.select_tile.strip() in tile_ids:
                    printing(f'Tile ID {self.select_tile} is selected from observation plan.')
                    for row in data:
                        if row[0] == self.select_tile:
                            print(row)
                            obs_num=row[2]
                            print(f'Observation number of exposure: {obs_num}')
                    break
                else:
                    print(f'Tile ID {self.select_tile} was not found. Please enter a valid ID.')

        
            tilemsg,guidemsg,objmsg,motionmsg1,motionmsg2=sciobs.loadtile(self.select_tile)
            tile_data=json.loads(tilemsg)
            self.ra,self.dec=convert_to_sexagesimal(tile_data['ra'],tile_data['dec'])

            printing(f'RA and DEC of Tile ID {self.select_tile}: {self.ra} {self.dec}')

            await scriptrun.ICSclient.send_message("GFA", guidemsg)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            await scriptrun.ICSclient.send_message("MTL", objmsg)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            await scriptrun.ICSclient.send_message("FBP", objmsg)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            await scriptrun.ICSclient.send_message("FBP", motionmsg1)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            await scriptrun.ICSclient.send_message("FBP", motionmsg2)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            printing(f'All accessary files for observation of Tile ID {self.select_tile} are successfully loaded')
            ### End of CLI version ###
        
        await asyncio.sleep(2)
    
        printing(f'ADC Adjust Start')
        message=f'adcadjust {self.ra} {self.dec}'
        print(message)
        message=f'adcadjust 19:34:56.44 -31:34:55.67'                           # Just for simulation. Remove or comment when real observation
        await handle_adc(message,scriptrun.ICSclient)
        await asyncio.sleep(2)
        
        printing(f'Fiber positioner Moving Start')
        await handle_fbp('fbpmove',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
     #   sys.stdout.flush()

        messagetcs = 'KSPEC>TC ' + 'tmradec ' + self.ra +' '+ self.dec
        printing(f'Slew Telescope to RA={self.ra}, DEC={self.dec}.')
        await scriptrun.send_udp_message(messagetcs)
        print('Telescope is slewing now.', end=' ',flush=True)

        while True:
            r=redis.Redis(host='localhost',port=6379,decode_responses=True)     # Set IP address of KMTNet redis server

            value=r.get('dome_error')
            print(value)                                                        # Remove or comment in real observation

            if value != '2':
                print('Telescope slew finished')
                logging('Telescope slew finished.', level='receive')
                break
            print('.',end=' ', flush=True)
            await asyncio.sleep(5)

        await scriptrun.response_queue.get()                                    # ??? Remove in real observation ???

        await asyncio.sleep(5)
        printing(f'Autoguiding Start')
        logging(f'GFA guiding. Expoture time is {self.GFAexpT}', level='receive')
        await self.run_autoguide(scriptrun,self.GFAexpT)
        await asyncio.sleep(2)

        await handle_spec('illuon',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)

        await handle_lamp('fiducialon',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)

        await handle_mtl(f'mtlexp {self.MTLexpT}',scriptrun.ICSclient)                       # Change exposure time in real observation
        await scriptrun.response_queue.get()
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)

        await handle_mtl('mtlcal',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)

        await handle_fbp('fbpoffset',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)

        await handle_spec('illuoff',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)

        await handle_lamp('fiducialoff',scriptrun.ICSclient)
    
    #    print(f'FHWM is {self.fwhm:.5f}.')                                     # Remove in real observation
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)


        obs_num=self.obsnum
        printing(f'KSPEC starts {obs_num} exposures with {self.expT} seconds.')
        for i in range(int(obs_num)):
            await clear_queue(scriptrun.SPEC_response_queue)
            await handle_spec(f'getobj {self.expT} 1', scriptrun.ICSclient)
            printing(f'**** {i+1}/{obs_num}: 30 seconds exposure start. ****')
            logging(f'**** {i+1}/{obs_num}: 30 seconds exposure start. ****', level='receive')
            spec_rsp=await scriptrun.response_queue.get()
#            print(f'jhkjkjk {spec_rsp}')
            fram=f'{i+1}/{obs_num}'
            header_data = {"PROJECT": self.project, "EXPTIME": self.expT, "FRAME": fram, "Tile": self.select_tile, "PRORA": self.ra, "PRODEC": self.dec}
            update_fits(spec_rsp["filename"],header_data)
            logging('Fits header updated', level='receive')
            printing("Fits header updated")


        printing('All exposures are completed.')
        logging('All exposures are completed.',level='receive')

        await handle_adc('adcstop',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await self.autoguidestop(scriptrun)
        await scriptrun.response_queue.get()
        await handle_adc('adczero',scriptrun.ICSclient)
        await handle_fbp('fbpzero',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await scriptrun.response_queue.get()
        await scriptrun.response_queue.get()

        printing(f'###### Observation Script for Tile ID {self.select_tile} END!!! ######')
        logging(f'###### Observation Script for Tile ID {self.select_tile} END!!! ######',level='comment')



#async def handle_script(arg, ICSclient, send_udp_message, send_telcom_command, 
#        response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue, scriptrun, logging=None):
async def handle_script(arg, scriptrun=None, logging=None):
    """ Handle script with error checking. """
    cmd, *params = arg.split()
    print(params)
    command_map = {
            'obsinitial': scriptrun.obs_initial, 'runcalib': scriptrun.run_calib, 'runobs': scriptrun.run_obs
    }

    if cmd in command_map:
#        await command_map[cmd](scriptrun.ICSclient,scriptrun.send_udp_message, scriptrun.send_telcom_command, 
#                scriptrun.response_queue, scriptrun.GFA_response_queue, scriptrun.ADC_response_queue, scriptrun.SPEC_response_queue, scriptrun.logging)
        await command_map[cmd](scriptrun,logging)
    elif cmd == 'autoguide':
        if not params:
            await scriptrun.run_autoguide(scriptrun)
        else:
            await scriptrun.run_autoguide(scriptrun,float(params[0]),params[1])

    elif cmd == 'autoguidestop':
        await scriptrun.autoguidestop(scriptrun)
    else:
        print(f"Error: '{cmd}' is not right command for SCRIPT")


