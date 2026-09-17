import os, sys
import json
import redis
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import asyncio
import math
import numpy as np
import pandas as pd
from astropy.coordinates import Angle, SkyCoord
import astropy.units as u
from astropy.io import fits
from datetime import datetime, timezone

from GFA.gfacli import handle_gfa
from MTL.mtlcli import handle_mtl
from FBP.fbpcli import handle_fbp
from ADC.adccli import handle_adc
from LAMP.lampcli import handle_lamp
from SPECTRO.speccli import handle_spec
from SCIOBS.sciobscli import sciobscli
import Lib.process as processes
from Lib.make_spec_header import set_header_info
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


def bytes_to_sexagesimal(value: bytes, encoding='ascii') -> str:
    """
    바이트 문자열에서 마지막 토큰을 읽어 HH:MM:SS.SS 또는 ±DD:MM:SS.SS 형식으로 변환

    Parameters:
    - value: bytes 문자열 (e.g., b'... 234342.56\\n\\x00')
    - encoding: 바이트 인코딩 형식 (기본: 'utf-8')

    Returns:
    - str: 변환된 시각 또는 각도 문자열 (예: '23:43:42.56' 또는 '-03:45:06.78')
    """
    try:
        # 1. 바이트 → 문자열 디코딩
        text = value.decode(encoding, errors='ignore').strip().replace('\x00', '')
        tokens = text.split()
        if not tokens:
            return ''

        last = tokens[-1]
        num = float(last)

        # 2. 부호 분리 (DEC 대비)
        sign = '-' if num < 0 else ''
        num = abs(num)

        # 3. 시/도, 분, 초 분해
        hh = int(num // 10000)
        mm = int((num % 10000) // 100)
        ss = num % 100

        # 4. 형식화
        return f"{sign}{hh:02}:{mm:02}:{ss:05.2f}"

    except Exception as e:
        print(f"[ERROR] 변환 실패: {e}")
        return ''

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
        self.TileID = None
        self.object = None
        self.project = None
        self.obsdate = None
        self.obstype = None
        self.dir_name = None
        self.obsnum = None
        self.expT = None
        self.MTLexpT = 5.    # default MTL exposure time
        self.GFAexpT = 5.    # default GFA exposure time
        self.MTLexpN = 1
        self.MTLimgname = None
        self.uttime = None
        self.obslog = None

    def configure_cordinate(self, project, obsdate, tileid, value1, value2, obsnum, expT, object_name=None):
        self.project = project
        self.obsdate = obsdate
        self.TileID = tileid
        self.object = object_name
        self.ra = value1
        self.dec = value2
        self.obsnum = obsnum
        self.expT = expT
        print(f'{self.TileID}, {self.ra}, {self.dec}')

    def initialize_dependencies(self, ICSclient, send_udp_message, send_telcom_command,
            response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue,
            show_status, dir_name, obslog=None):
        self.ICSclient = ICSclient
        self.send_udp_message = send_udp_message 
        self.send_telcom_command = send_telcom_command
        self.response_queue = response_queue 
        self.GFA_response_queue = GFA_response_queue 
        self.ADC_response_queue = ADC_response_queue 
        self.SPEC_response_queue = SPEC_response_queue 
        self.show_status = show_status
        self.dir_name = dir_name
        self.obslog = obslog

    def MTL_set(self,exptime, expnum, mtlfile):
        self.MTLexpT = exptime
        self.MTLexpN = expnum
        self.MTLimgnmae = mtlfile
    #    print(f'MTL exposure time is {self.MTLexpT}')


    def GFA_set(self,exptime):
        self.GFAexpT = exptime

    def current_uttime(self):
        now = datetime.now(timezone.utc)
        return now.strftime("%H:%M:") + f"{now.second + now.microsecond / 1_000_000:05.2f}"

    def make_spec_header(self, obstype, exptime, expnum):
        return set_header_info(
            obsdate=self.obsdate or self.dir_name,
            obstype=obstype,
            TileID=self.TileID,
            obsra=self.ra,
            obsdec=self.dec,
            exptime=exptime,
            expnum=expnum,
            projID=self.project,
            fwhm=self.fwhm if self.fwhm is not None else 9.99,
        )

    async def add_obslog(self, obstype, exptime, expnum, comments="", logging=None):
        if self.obslog is None:
            return

        object_name = self.object or self.TileID
        try:
            await asyncio.to_thread(
                self.obslog.add_log,
                self.current_uttime(),
                self.project,
                self.TileID,
                obstype,
                object_name,
                exptime,
                expnum,
                comments,
            )
        except Exception as e:
            msg = f'Observation log update failed: {e}'
            if logging is not None:
                logging(msg, level='error')
            else:
                printing(msg)
            return

        if logging is not None:
            logging(self.obslog.message, level='receive')

    async def send_spec_and_log(
        self,
        command,
        obstype,
        exptime,
        expnum,
        scriptrun,
        logging=None,
        comments="",
    ):
        header = self.make_spec_header(obstype, exptime, expnum)
        await handle_spec(command, scriptrun.ICSclient, header)
        spec_rsp = await scriptrun.response_queue.get()

        if isinstance(spec_rsp, dict) and spec_rsp.get("status") == "success":
            log_comment = comments or spec_rsp.get("filename") or spec_rsp.get("message", "")
            await self.add_obslog(
                obstype,
                exptime,
                expnum,
                comments=log_comment,
                logging=logging,
            )

        return spec_rsp

    async def obs_initial(self,scriptrun,logging):
        """Initialize all instruments."""
        print('Start instruments intialization')
        await clear_queue(scriptrun.response_queue)
        await clear_queue(scriptrun.GFA_response_queue)
        await clear_queue(scriptrun.ADC_response_queue)
        await clear_queue(scriptrun.SPEC_response_queue)
    #    await handle_gfa('gfastatus',scriptrun.ICSclient)
    #    await scriptrun.response_queue.get()
    #    await asyncio.sleep(2)
    #    await handle_fbp('fbpstatus',scriptrun.ICSclient)
    #    await scriptrun.response_queue.get()
    #    await handle_mtl('mtlstatus',scriptrun.ICSclient)
    #    await scriptrun.response_queue.get()
    #    await asyncio.sleep(2)
    #    await handle_adc('adcconnect',scriptrun.ICSclient)
    #    await scriptrun.response_queue.get()
    #    await asyncio.sleep(2)
    #    await handle_adc('adchome 1',scriptrun.ICSclient)
    #    await scriptrun.response_queue.get()
    #    await asyncio.sleep(2)
    #    await handle_adc('adczero 4',scriptrun.ICSclient)
    #    await scriptrun.response_queue.get()
    #    await asyncio.sleep(2)
    #    await handle_adc('adcstatus',scriptrun.ICSclient)
    #    await scriptrun.response_queue.get()
    #    await asyncio.sleep(2)
    #    await handle_spec(f'specinitial {self.dir_name}',scriptrun.ICSclient)
    #    await scriptrun.response_queue.get()
    #    await asyncio.sleep(2)
    #    await handle_spec('specstatus',scriptrun.ICSclient)
    #    await scriptrun.response_queue.get()
    #    await asyncio.sleep(2)

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

        with open('./Lib/Calibinfo.json', 'r') as f:
            calinfo = json.load(f)
        
        print(calinfo)

        # Bias        
        if logging != None:
            logging(f'Sent getbias {calinfo['Bias']['exptime']} {calinfo['Bias']['expnum']}.', level='send')

        await self.send_spec_and_log(
            f'getbias {calinfo['Bias']['exptime']} {calinfo['Bias']['expnum']}',
            'Flat',
            calinfo['Bias']['exptime'],
            calinfo['Bias']['expnum'],
            scriptrun,
            logging=logging,
        )

        # Arc
        if logging != None:
            logging('Sent Arc on.',level='send')

        await handle_lamp('arcon',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        
        if logging != None:
            logging(f'Sent getarc {calinfo['Arc']['exptime']} {calinfo['Arc']['expnum']}.',level='send')

        await self.send_spec_and_log(
            f'getarc {calinfo['Arc']['exptime']} {calinfo['Arc']['expnum']}',
            'Arc',
            calinfo['Arc']['exptime'],
            calinfo['Arc']['expnum'],
            scriptrun,
            logging=logging,
        )

        if logging != None:
            logging('Sent Arc off.',level='send')

        await handle_lamp('arcoff',scriptrun.ICSclient)
        await scriptrun.response_queue.get()

        # Flat
        if logging != None:
            logging('Sent Flat on.', level='send')

        await handle_lamp('flaton',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
    
        if logging != None:
            logging(f'Sent getflat {calinfo['Flat']['exptime']} {calinfo['Flat']['expnum']}.', level='send')

        exptime = 10
        expnum = 10
        await self.send_spec_and_log(
            f'getflat {calinfo['Flat']['exptime']} {calinfo['Flat']['expnum']}',
            'Flat',
            calinfo['Flat']['exptime'],
            calinfo['Flat']['expnum'],
            scriptrun,
            logging=logging,
        )
        
        if logging != None:
            logging('Sent Flat off.', level='send')

        await handle_lamp('flatoff',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        
        printing("All Calibration images were obtained.")
        self.scrpt_task = None
        if logging != None:
            logging("All Calibration images were obtained.", level='send')
            scriptrun.show_status('LAMP','normal')
            scriptrun.show_status('SPEC','normal')
            logging('Run Calibration Task finished', level='normal')


    async def run_autoguide(self, scriptrun, exptime: float = 5.0, expnum: int = 1, save: bool = False, logging = None):
        """Starts the autoguiding process asynchronously."""
        if self.autoguide_task and not self.autoguide_task.done():
            print("Autoguide task is already running. Ignoring duplicate start.")
            return

        self.autoguide_task = asyncio.create_task(
                self.handle_autoguide(exptime, expnum, save, scriptrun, logging)
        )

    def format_decimal(self,x):
        from decimal import Decimal
        x = Decimal(str(x))
        sign = "-" if x < 0 else ""
        value = abs(x)
        return f"{sign}{int(value * 100):04d}"

    def _is_valid_guiding_number(self, value):
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    async def handle_autoguide(self, exptime, expnum, save, scriptrun, logging):
        try:
            ra_bytes = await scriptrun.send_telcom_command('getra')
            dec_bytes = await scriptrun.send_telcom_command('getdec')
            rahms_t=bytes_to_sexagesimal(ra_bytes)                   ## Current Telescope pointing position
            decdms_t=bytes_to_sexagesimal(dec_bytes)                 ## Current Telescope pointing position
#            print(rahms_t)
            logging(f'Current Telescope pointing position = (RA,DEC)=({rahms_t}, {decdms_t})', level='normal')
            await handle_gfa(f'gfaguide {exptime} {expnum} {save} {rahms_t} {decdms_t}',scriptrun.ICSclient)
            while True:
                try:
                    response_data = await asyncio.wait_for(scriptrun.GFA_response_queue.get(),timeout=300)
                except asyncio.TimeoutError:
                    print("No GFA response")
                    continue
                
                status = response_data.get('status', 'error')
                if status in ('warning', 'error', 'fail'):
                    msg = response_data.get('message', 'GFA guiding stopped.')
                    level = 'error' if status == 'error' else 'warning'
                    logging(f'Autoguiding stopped without applying offset: {msg}', level=level)
                    return

                if "fdx" not in response_data:
                    continue

                fdx=response_data.get('fdx')
                fdy=response_data.get('fdy')
                fwhm=response_data.get('fwhm')

                if not all(self._is_valid_guiding_number(value) for value in (fdx, fdy, fwhm)):
                    logging(
                        'Autoguiding stopped without applying offset: invalid guiding values received.',
                        level='warning',
                    )
                    return

                fdx = float(fdx)
                fdy = float(fdy)
                self.fwhm = float(fwhm)

                #### Simulation ### 
                #fdx = -0.78
                #fdy = 0.68
                #self.fwhm = 1.23

                ### Autoguiding using offset ###    
                #    xx = self.format_decimal(fdx)
                #    msg = f'stepra {xx}'
                #    result = await self.send_telcom_command(msg)
                #    print('\033[94m' + '[ICS] received: ', result.decode() + '\033[0m', flush=True)
                #    logging(f'RA offset {fdx} finished', level='receive')
                #    await asyncio.sleep(1)
                #    yy = self.format_decimal(fdy)
                #    msg = f'stepdec {yy}'
                #    result = await self.send_telcom_command(msg)
                #    print('\033[94m' + '[ICS] received: ', result.decode() + '\033[0m', flush=True)
                #    logging(f'DEC offset {fdy} finished', level='receive')

                ### Autoguiding using New coordinate ###
                logging(f'Calculated Offset (RA,DEC)=({fdx}, {fdy})', level='normal')
                ra_bytes = await scriptrun.send_telcom_command('getra')
                dec_bytes = await scriptrun.send_telcom_command('getdec')
                rahms=bytes_to_sexagesimal(ra_bytes)
                decdms=bytes_to_sexagesimal(dec_bytes)
                new_coord=apply_offset(rahms,decdms,fdx,fdy)
                logging(f'Applied Offset. New (RA,DEC) = {new_coord}', level='normal')
                messagetcs = 'KSPEC>TC ' + 'tmradec ' + new_coord
                await scriptrun.send_udp_message(messagetcs)

        except asyncio.CancelledError:
            print("Autoguide task was cancelled.")
            raise

        finally:
            print("Autoguide task finished.")
            self.autoguide_task = None

    async def autoguidestop(self,scriptrun,logging):
        """Stops the autoguiding process if it is running."""
        print("ddfdfd")
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

        logging(f'###### Observation for Tile ID {self.TileID} starts ######',level='comment')
        printing(f'###### Observation for Tile ID {self.TileID} starts ######')
        
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
                self.TileID=input('\nPlease select Tile ID above you want to runscript.: ')
                if self.TileID.strip() in tile_ids:
                    printing(f'Tile ID {self.TileID} is selected from observation plan.')
                    for row in data:
                        if row[0] == self.TileID:
                            print(row)
                            obs_num=row[2]
                            print(f'Observation number of exposure: {obs_num}')
                    break
                else:
                    print(f'Tile ID {self.TileID} was not found. Please enter a valid ID.')

        
            tilemsg,guidemsg,objmsg,motionmsg1,motionmsg2=sciobs.loadtile(self.TileID)
            tile_data=json.loads(tilemsg)
            self.ra,self.dec=convert_to_sexagesimal(tile_data['ra'],tile_data['dec'])

            printing(f'RA and DEC of Tile ID {self.TileID}: {self.ra} {self.dec}')

            await scriptrun.ICSclient.send_message("GFA", guidemsg)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            await scriptrun.ICSclient.send_message("MTL", objmsg)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            ##### In commission, FBP is not ready. #####
            await scriptrun.ICSclient.send_message("FBP", objmsg)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            await scriptrun.ICSclient.send_message("FBP", motionmsg1)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            await scriptrun.ICSclient.send_message("FBP", motionmsg2)
            await scriptrun.response_queue.get()
            await asyncio.sleep(2)

            printing(f'All accessary files for observation of Tile ID {self.TileID} are successfully loaded')
            ### End of CLI version ###
        
        await asyncio.sleep(2)

    
        printing(f'ADC Adjust Start')
    #    message=f'adcadjust {self.ra} {self.dec}'
    #    print(message)
        message=f'adcadjust 02:34:56.44 -31:34:55.67'                           # Just for simulation. Remove or comment when real observation
        await handle_adc(message,scriptrun.ICSclient)
        await asyncio.sleep(2)
  
        printing(f'Fiber positioner Moving Start')
        await handle_fbp('fbpmove',scriptrun.ICSclient)
        await scriptrun.response_queue.get()

        messagetcs = 'KSPEC>TC ' + 'tmradec ' + self.ra +' '+ self.dec
        printing(f'Slew Telescope to RA={self.ra}, DEC={self.dec}.')
        await scriptrun.send_udp_message(messagetcs)
        print('Telescope is slewing now.', end=' ',flush=True)
        await asyncio.sleep(2)

        while True:
        #    r=redis.Redis(host='192.168.15.121',port=6379,decode_responses=True)     # Set IP address of KMTNet redis server
            r=redis.Redis(host='127.0.0.1',port=6379,decode_responses=True)     # For simulation. Remove or comment in real observation

            value=r.get('dome_error')
            print(value)                                                        # Remove or comment in real observation

            if value != '0002':
                print('Telescope slew finished')
                logging('Telescope slew finished.', level='receive')
                break
            print('.',end=' ', flush=True)
            await asyncio.sleep(5)

        await scriptrun.response_queue.get()                                    # Wait for Fiber movement finish

        await asyncio.sleep(3)
        printing(f'Autoguiding Start')
        logging(f'GFA guiding. Expoture time is {self.GFAexpT}', level='receive')
        await self.run_autoguide(scriptrun,self.GFAexpT,logging=logging)
        await asyncio.sleep(2)

        await handle_lamp('fiducialon',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)
                
        await handle_mtl(f'mtlexp {self.MTLexpT} 1 "fiducial.fits"',scriptrun.ICSclient)                       # Change exposure time in real observation
        await scriptrun.response_queue.get()                                     # Start MTL exposure message
        await scriptrun.response_queue.get()                                     # Wait for MTL exposure finish
        await asyncio.sleep(2)

        await handle_spec('illuon',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)

        testfile = 'test.fits'
        await handle_mtl(f'mtlcal {testfile}',scriptrun.ICSclient)
        await scriptrun.response_queue.get()                                    # Start MTL calculation message
        await scriptrun.response_queue.get()                                    # Wait for MTL calculation finish
        await asyncio.sleep(2)

        await handle_fbp('fbpoffset',scriptrun.ICSclient)
        await scriptrun.response_queue.get()                                    # Start offset message
        await scriptrun.response_queue.get()                                    # Wait for FBP offset finish
        await asyncio.sleep(2)

        await handle_spec('illuoff',scriptrun.ICSclient)
        await scriptrun.response_queue.get()                                 
        await asyncio.sleep(2)

        await handle_lamp('fiducialoff',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await asyncio.sleep(2)

    
    #    print(f'FHWM is {self.fwhm:.5f}.')                                     # Remove in real observation
  
        obs_num=self.obsnum
        printing(f'KSPEC starts {obs_num} exposures with {self.expT} seconds.')
        
        for i in range(int(obs_num)):
            await clear_queue(scriptrun.SPEC_response_queue)
            fram=f'{i+1}/{obs_num}'
            printing(f'**** {i+1}/{obs_num}: {self.expT} seconds exposure start. ****')
            logging(f'**** {i+1}/{obs_num}: {self.expT} seconds exposure start. ****', level='receive')
            spec_rsp = await self.send_spec_and_log(
                f'getobj {self.expT} 1',
                'Object',
                self.expT,
                fram,
                scriptrun,
                logging=logging,
            )
            if isinstance(spec_rsp, dict) and spec_rsp.get("filename") not in (None, "None"):
                logging('Fits header and observation log updated', level='receive')
                printing("Fits header and observation log updated")


        printing('All exposures are completed.')
        logging('All exposures are completed.',level='receive')

        await handle_adc('adcstop',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
    
        await self.autoguidestop(scriptrun,logging)
        await scriptrun.response_queue.get()

        await handle_adc('adczero 2',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await scriptrun.response_queue.get()

        await handle_fbp('fbpzero',scriptrun.ICSclient)
        await scriptrun.response_queue.get()
        await scriptrun.response_queue.get()
        

        printing(f'###### Observation Script for Tile ID {self.TileID} END!!! ######')
        logging(f'###### Observation Script for Tile ID {self.TileID} END!!! ######',level='comment')
        
        



#async def handle_script(arg, ICSclient, send_udp_message, send_telcom_command, 
#        response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue, scriptrun, logging=None):
async def handle_script(arg, scriptrun=None, logging=None):
    """ Handle script with error checking. """
    cmd, *params = arg.split()

    command_map = {
            'obsinitial': scriptrun.obs_initial, 'runcalib': scriptrun.run_calib, 'runobs': scriptrun.run_obs
    }

    if cmd in command_map:
#        await command_map[cmd](scriptrun.ICSclient,scriptrun.send_udp_message, scriptrun.send_telcom_command, 
#                scriptrun.response_queue, scriptrun.GFA_response_queue, scriptrun.ADC_response_queue, scriptrun.SPEC_response_queue, scriptrun.logging)
        await command_map[cmd](scriptrun,logging)
    elif cmd == 'autoguide':
        await scriptrun.run_autoguide(scriptrun, float(params[0]), int(params[1]), params[2],logging=logging)

    elif cmd == 'autoguidestop':
        await scriptrun.autoguidestop(scriptrun,logging)
    else:
        print(f"Error: '{cmd}' is not right command for SCRIPT")
