import os, sys
import argparse
import json
import redis
import shutil
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import asyncio
import math
import re
import shlex
import numpy as np
import pandas as pd
from astropy.coordinates import Angle, SkyCoord
import astropy.units as u
from astropy.io import fits
from datetime import datetime, timezone

from GFA.gfacli import handle_gfa
from MTL.mtlcli import handle_mtl, mtl_start
from FBP.fbpcli import handle_fbp
from ADC.adccli import handle_adc
from LAMP.lampcli import handle_lamp
from SPECTRO.speccli import handle_spec, spec_queue
from SCIOBS.sciobscli import sciobscli
import Lib.process as processes
from Lib.make_spec_header import set_header_info
from Lib.reply import wait_reply
from TCS.tcscli import handle_telcom
from script import starscan


SPEC_FRAME_OVERHEAD_S = 180.     # readout, export and copy per frame, on top of the exposure
ILLUMINATION_TIMEOUT_S = 120.    # IsoPlane stage move (~15-20 s) and light switching
MTL_TRIAL_TIMEOUT_S = 600.
FBP_OFFSET_TIMEOUT_S = 600.
MAX_MTL_TRIALS = 20              # backstop only: the MTL run stops at its own max_trial
FBP_MOVEALL_TIMEOUT_S = 1800.    # a planner path of ~50-800 steps
TILE_LOAD_TIMEOUT_S = 300.


def printing(message):
    """Utility function for consistent printinging."""
    print(f"\n\033[32m[ICS] {message}\033[0m\n",flush=True)


def log_or_print(logging, message, level):
    if logging is not None:
        logging(message, level=level)
    else:
        printing(message)


def spec_command_timeout(command):
    """Seconds to wait for the Done reply of a getbias/getdark/getflat/getarc/getobj command."""
    cmd, *params = command.split()
    try:
        if cmd == 'getbias':
            exptime, nframe = 0., int(params[-1])
        else:
            exptime, nframe = float(params[0]), int(params[1])
    except (IndexError, ValueError):
        return SPEC_FRAME_OVERHEAD_S
    return (exptime + SPEC_FRAME_OVERHEAD_S) * max(nframe, 1)


def mtl_json_on_ics(filename):
    """The MTL server's trial JSON as this ICS sees it (shared KSPEC.ini MTL.mtlfilepath)."""
    with open('./Lib/KSPEC.ini', 'r') as f:
        mtlfilepath = json.load(f)['MTL']['mtlfilepath']
    return os.path.join(os.path.expanduser(mtlfilepath), os.path.basename(str(filename)))


def load_obsplan_tile(sciobs, filename, tile_id):
    """Load a tile of an observation plan as the GUI Deploy does (KSPECRUN_gui.py).

    The .path.txt files hold geometric arm angles starting at (30, 150); FBP takes
    -angle + (alpha_offset_deg, beta_offset_deg), so the motion plan must be inverted
    (power-on pose = command (0, 0)). Calibration plans use zenith angle 0.
    """
    calibration_plan = re.fullmatch(r'Calib_obsplan_(?:\d{8}|YYYYMMDD)\.txt', filename) is not None
    return sciobs.loadtile(
        tile_id, invert_motion_angles=True,
        zenith_angle_override=0.0 if calibration_plan else None,
    )


class ScanArgsError(ValueError):
    pass


class _ScanArgumentParser(argparse.ArgumentParser):
    def error(self, message):              # a bad option must not close the ICS
        raise ScanArgsError(f'{self.format_usage().strip()}\nrunscan: {message}')

    def exit(self, status=0, message=None):
        raise ScanArgsError(message or self.format_help())


def parse_scan_args(params):
    """Options of runscan (see Lib/command.txt and handle_scan)."""
    p = _ScanArgumentParser(prog='runscan', allow_abbrev=False,
                            description='Zero-order star scan of a tile.')
    p.add_argument('assign', help='<project>_2627_<tile>.assign.txt (class 1 = on a star)')
    p.add_argument('path', help='planner .path.txt of the same tile (geometric angles)')
    p.add_argument('--info', help='<project>_2627.info.txt with the tile RA/Dec '
                   '(default: next to the assign file)')
    p.add_argument('--pattern', default='grid', choices=('grid', 'cross', 'line-x', 'line-y'))
    p.add_argument('--step', type=float, default=1.4, help='step size (default 1.4 = half the '
                   '2.80" fibre core)')
    p.add_argument('--unit', default='arcsec', choices=('arcsec', 'um'))
    p.add_argument('--npts', type=int, default=5, help='points per axis (odd)')
    p.add_argument('--no-centre-repeats', dest='centre_repeats', action='store_false',
                   help='do not repeat the centre at the start, middle and end')
    p.add_argument('--scale', type=float, default=starscan.UM_PER_ARCSEC,
                   help='focal-plane scale [um/arcsec]')
    p.add_argument('--exptime', type=float, default=4.0, help='getobj exposure [s]')
    p.add_argument('--fibres', help='comma-separated holes to scan (default: class 1 of the '
                   'assign file)')
    p.add_argument('--monitors', default='', help='comma-separated holes on stars kept at the '
                   'centre (transparency / seeing monitors)')
    p.add_argument('--centre', help='command-angle JSON of the scan centre; skips tile load, '
                   'fbpmoveall and the MTL loop (default: the converged MTL trial JSON)')
    p.add_argument('--no-move', dest='move', action='store_false',
                   help='skip fbpmoveall (positioners already at the path end)')
    p.add_argument('--no-guide', dest='guide', action='store_false', help='no GFA guiding')
    p.add_argument('--guide-settle', type=float, default=30.0,
                   help='seconds of guiding before the first scan frame')
    p.add_argument('--arms', default='mtl', choices=('mtl', 'design'),
                   help='arm lengths for the offsets: kspec_metrology (measured where known) '
                   'or design 5.2 / 11.6 mm')
    p.add_argument('--quantum', type=float, default=0.0,
                   help='round command angles to multiples of this [deg] (PLC step; 0 = off)')
    p.add_argument('--max-offset-um', type=float, default=150.0,
                   help='refuse patterns reaching farther than this from the centre')
    p.add_argument('--max-delta-deg', type=float, default=3.0,
                   help='refuse offsets turning any axis more than this from the centre')
    p.add_argument('--mtl-check', action='store_true',
                   help='after the return: back illumination IN, one mtltest image, OUT')
    p.add_argument('--mtl-exptime', type=float, default=0.03, help='mtltest exposure [s]')
    p.add_argument('--zenith-angle', type=float, help='zenith angle for MTL (default: from '
                   'the tile RA/Dec now)')
    p.add_argument('--outdir', help='scan records (default ../DATA/STARSCAN/<UTC date>)')
    p.add_argument('--dry-run', action='store_true',
                   help='print what would be sent and write the JSON files; send nothing')
    opts = p.parse_args(params)
    if opts.npts < 1 or opts.npts % 2 == 0:
        raise ScanArgsError('runscan: --npts must be odd and positive')
    if opts.step <= 0 or opts.exptime <= 0:
        raise ScanArgsError('runscan: --step and --exptime must be positive')
    return opts


def stage_scan_tile(assign_file, path_file, info_file, workdir):
    """Copy a tile's files under the names sciobscli.loadtile reads; return (sciobs, tile_id).

    The planner's files keep their own names (ZOSCAN_2627_0005.coarse.path.txt,
    ASPECS_2627.0005.assign.txt); loadtile wants <project>_2627_<tile:04d>.assign.txt /
    .path.txt and <project>_2627.info.txt in its targetpath / motionpath.
    """
    project, tile_id = starscan.parse_tile_name(assign_file)
    if starscan.parse_tile_name(path_file) != (project, tile_id):
        raise ValueError(f'{path_file} is not the path of {project} tile {tile_id}')
    if info_file is None:
        info_file = os.path.join(os.path.dirname(os.path.abspath(assign_file)),
                                 f'{project}_2627.info.txt')
    os.makedirs(workdir, exist_ok=True)
    for source, name in ((assign_file, f'{project}_2627_{tile_id:04d}.assign.txt'),
                         (path_file, f'{project}_2627_{tile_id:04d}.path.txt'),
                         (info_file, f'{project}_2627.info.txt')):
        shutil.copyfile(source, os.path.join(workdir, name))
    sciobs = sciobscli()
    sciobs.project = project
    sciobs.filename = os.path.basename(assign_file)
    sciobs.targetpath = sciobs.motionpath = workdir
    return sciobs, tile_id


def zero_order_fluxes(zoflux, holes):
    """{hole: flux} of a zoflux reply (None for a hole not on the slit or a failed frame)."""
    if not isinstance(zoflux, dict) or not zoflux.get('ok'):
        return {h: None for h in holes}
    fib = zoflux.get('fibres') or {}
    table = dict(zip(fib.get('label', []), fib.get('flux', [])))
    return {h: table.get(h) for h in holes}


def convert_to_sexagesimal(ra_deg, dec_deg):
    """Converts RA and DEC from degrees to sexagesimal format."""
    ra = Angle(ra_deg, unit=u.degree)
    dec = Angle(dec_deg, unit=u.degree)

    ra_hms = ra.to_string(unit=u.hour, sep=':', precision=2, pad=True)
    dec_dms = dec.to_string(unit=u.degree, sep=':', alwayssign=True, precision=2)
    return ra_hms, dec_dms


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
        self.MTLexpT = 0.03    # default MTL fiber exposure time [s]
        self.GFAexpT = 5.    # default GFA exposure time
        self.GFAexpN = 1    # default GFA exposure count
        self.MTLexpN = 1
        self.MTLimgname = None
        self.uttime = None
        self.obslog = None
        self.last_mtl_trial = None     # Done reply of the last successful mtltrial (runscan)

    def configure_cordinate(self, project, obsdate, tileid, value1, value2, obsnum, expT, object_name=None):
        self.project = project
        self.obsdate = obsdate
        self.TileID = tileid
        self.object = object_name
        self.ra = value1    # RA in sexagesimal
        self.dec = value2   # DEC in sexagesimal
        self.obsnum = obsnum
        self.expT = expT
        print(f'{self.TileID}, {self.ra}, {self.dec}')

    def initialize_dependencies(self, ICSclient, send_udp_message, send_telcom_command,
            response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue,
            show_status, dir_name, obslog=None, lamp_state_callback=None):
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
        self.lamp_state_callback = lamp_state_callback

    def MTL_set(self,exptime, expnum, mtlfile):
        self.MTLexpT = exptime
        self.MTLexpN = expnum
        self.MTLimgname = mtlfile
    #    print(f'MTL exposure time is {self.MTLexpT}')


    def GFA_set(self, exptime, expnum=1):
        exptime, count = float(exptime), float(expnum)
        if not math.isfinite(exptime) or exptime <= 0:
            raise ValueError('GFA exposure time must be finite and greater than zero.')
        if not math.isfinite(count) or count < 1 or not count.is_integer():
            raise ValueError('GFA exposure count must be a positive integer.')
        self.GFAexpT = exptime
        self.GFAexpN = int(count)

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
            object_name=self.object,
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
        spec_rsp = await wait_reply(scriptrun.response_queue, 'SPEC', command.split()[0],
                                    timeout=spec_command_timeout(command), logging=logging)

        if spec_rsp.get("status") != "success":
            log_or_print(logging, f"{command} did not succeed ({spec_rsp.get('status')}): "
                         f"{spec_rsp.get('message')}", 'error')
        elif spec_rsp.get("backend") != 'ISOPLANE':
            log_comment = comments or spec_rsp.get("filename") or spec_rsp.get("message", "")
            await self.add_obslog(
                obstype,
                exptime,
                expnum,
                comments=log_comment,
                logging=logging,
            )

        return spec_rsp

    async def obs_initial(self, scriptrun, logging, *, include_fbp=True):
        """Initialize instruments; GUI can defer FBP until Runtime is ready."""
        print('Start instruments intialization')
        await clear_queue(scriptrun.response_queue)
        await clear_queue(scriptrun.GFA_response_queue)
        await clear_queue(scriptrun.ADC_response_queue)
        await clear_queue(scriptrun.SPEC_response_queue)
        # await handle_gfa('gfastatus',scriptrun.ICSclient, logging)
        # await scriptrun.response_queue.get()
        # await asyncio.sleep(2)
        # if include_fbp:
        #     await handle_fbp('fbpstatus',scriptrun.ICSclient, logging=logging)
        #     await scriptrun.response_queue.get()
        # await handle_mtl('mtlstatus',scriptrun.ICSclient, logging=logging)
        # await scriptrun.response_queue.get()
        # await asyncio.sleep(2)
        await handle_adc('adcconnect',scriptrun.ICSclient, logging=logging)
        await scriptrun.response_queue.get()
        # await asyncio.sleep(2)
        # await handle_adc('adchome 1',scriptrun.ICSclient, logging=logging)
        # await scriptrun.response_queue.get()
        # await asyncio.sleep(2)
        # await handle_adc('adczero 4',scriptrun.ICSclient, logging=logging)
        # await scriptrun.response_queue.get()
        # await asyncio.sleep(2)
        # await handle_adc('adcstatus',scriptrun.ICSclient, logging=logging)
        # await scriptrun.response_queue.get()
        # await asyncio.sleep(2)
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
            logging(f"Sent getbias {calinfo['Bias']['exptime']} {calinfo['Bias']['expnum']}.", level='send')

        await self.send_spec_and_log(
            f"getbias {calinfo['Bias']['expnum']}",
            'Bias',
            calinfo['Bias']['exptime'],
            calinfo['Bias']['expnum'],
            scriptrun,
            logging=logging,
        )

        # Arc
        await handle_lamp(
            'arcon', scriptrun.ICSclient, logging=logging,
            state_callback=getattr(scriptrun, 'lamp_state_callback', None),
        )
        
        if logging != None:
            logging(f"Sent getarc {calinfo['Arc']['exptime']} {calinfo['Arc']['expnum']}.",level='send')

        await self.send_spec_and_log(
            f"getarc {calinfo['Arc']['exptime']} {calinfo['Arc']['expnum']}",
            'Arc',
            calinfo['Arc']['exptime'],
            calinfo['Arc']['expnum'],
            scriptrun,
            logging=logging,
        )

        await handle_lamp(
            'arcoff', scriptrun.ICSclient, logging=logging,
            state_callback=getattr(scriptrun, 'lamp_state_callback', None),
        )

        # Flat
        await handle_lamp(
            'flaton', scriptrun.ICSclient, logging=logging,
            state_callback=getattr(scriptrun, 'lamp_state_callback', None),
        )
    
        if logging != None:
            logging(f"Sent getflat {calinfo['Flat']['exptime']} {calinfo['Flat']['expnum']}.", level='send')

        exptime = 10
        expnum = 10
        await self.send_spec_and_log(
            f"getflat {calinfo['Flat']['exptime']} {calinfo['Flat']['expnum']}",
            'Flat',
            calinfo['Flat']['exptime'],
            calinfo['Flat']['expnum'],
            scriptrun,
            logging=logging,
        )
        
        await handle_lamp(
            'flatoff', scriptrun.ICSclient, logging=logging,
            state_callback=getattr(scriptrun, 'lamp_state_callback', None),
        )
        
        printing("All Calibration images were obtained.")
        self.scrpt_task = None
        if logging != None:
            logging("All Calibration images were obtained.", level='send')
            scriptrun.show_status('LAMP','normal')
            scriptrun.show_status('SPEC','normal')
            logging('Run Calibration Task finished', level='normal')

    async def run_dark(self, scriptrun, logging):
        """Starts the dark sequence asynchronously (before the night starts and after it ends)."""
        self.script_task = asyncio.create_task(
                self.handle_dark(scriptrun, logging)
        )

    async def handle_dark(self, scriptrun, logging):
        """Darks grouped by exposure time, from Calibinfo.json "Dark":
        [{"exptime": <s>, "expnum": <n>}, ...], taken in that order with getdark.

        Darks are taken at the object exposure times of the night, as a block before the night
        starts and another after it ends, not inside runcalib: they can take hours. The arc and
        flat lamps are switched off first. A group whose getdark does not succeed ends the
        sequence (specstop interrupts the running exposure).
        """
        printing("New Dark task started.")
        await clear_queue(scriptrun.response_queue)
        await clear_queue(scriptrun.SPEC_response_queue)

        with open('./Lib/Calibinfo.json', 'r') as f:
            calinfo = json.load(f)
        groups = calinfo.get('Dark') or []
        if isinstance(groups, dict):
            groups = [groups]
        groups = [(float(g['exptime']), int(g['expnum'])) for g in groups if int(g.get('expnum', 0)) > 0]
        if not groups:
            log_or_print(logging, 'No dark groups in Calibinfo.json "Dark": nothing to take.', 'warning')
            return

        total_min = sum(t * n for t, n in groups) / 60
        log_or_print(logging, 'Dark sequence: ' + ', '.join(f'{n} x {t:g} s' for t, n in groups)
                     + f' ({total_min:.0f} min of exposure).', 'send')

        for lamp in ('arcoff', 'flatoff'):
            await handle_lamp(
                lamp, scriptrun.ICSclient, logging=logging,
                state_callback=getattr(scriptrun, 'lamp_state_callback', None),
            )

        for exptime, expnum in groups:
            if logging != None:
                logging(f"Sent getdark {exptime:g} {expnum}.", level='send')
            rsp = await self.send_spec_and_log(
                f"getdark {exptime:g} {expnum}", 'Dark', exptime, expnum, scriptrun, logging=logging,
            )
            if rsp.get("status") != "success":
                log_or_print(logging, f'Dark sequence stopped after the {exptime:g} s group.', 'error')
                break
        else:
            printing("All dark images were obtained.")
            if logging != None:
                logging("All dark images were obtained.", level='send')

        self.script_task = None
        if logging != None:
            scriptrun.show_status('SPEC', 'normal')
            logging('Run Dark Task finished', level='normal')

    async def spec_illumination(self, cmd, scriptrun, logging=None):
        """illuon / illuoff / illulighton / illulightoff; True when the reply says success."""
        try:
            await handle_spec(cmd, scriptrun.ICSclient)
        except Exception as error:   # WebRelay (main spectrograph) answers synchronously
            log_or_print(logging, f'{cmd} failed: {error}', 'error')
            return False
        if spec_queue() == 'SPEC':
            return True
        rsp = await wait_reply(scriptrun.response_queue, 'SPEC', cmd,
                               timeout=ILLUMINATION_TIMEOUT_S, logging=logging)
        ok = rsp.get('status') == 'success'
        log_or_print(logging, f"{cmd}: {rsp.get('message')}", 'receive' if ok else 'error')
        return ok

    async def run_metrology(self, scriptrun, logging):
        """Starts the metrology loop asynchronously."""
        self.script_task = asyncio.create_task(self.handle_metrology(scriptrun, logging))

    async def handle_metrology(self, scriptrun, logging):
        """Metrology iterations for a tile whose MTL run is initialized (loadtile, mtlstart).

        The back-illumination stage stays IN for the whole loop; the light is on only while
        the MTL camera exposes, and off while the positioners move:

            fiducialon, illuon
            repeat: [illulighton] mtltrial, illulightoff, stop if converged, fbpoffset
            illuoff, fiducialoff

        illuoff and fiducialoff run also when a step fails. Returns True when converged.
        """
        await clear_queue(scriptrun.response_queue)
        lamp_callback = getattr(scriptrun, 'lamp_state_callback', None)
        log_or_print(logging, '###### Metrology loop starts ######', 'comment')
        try:
            await handle_lamp('fiducialon', scriptrun.ICSclient, logging=logging,
                              state_callback=lamp_callback)
        except Exception as error:
            log_or_print(logging, f'fiducialon failed: {error}; metrology not started.', 'error')
            return False
        converged = False
        try:
            if not await self.spec_illumination('illuon', scriptrun, logging):
                return False
            light_on = True
            for _ in range(MAX_MTL_TRIALS):
                if not light_on:
                    if not await self.spec_illumination('illulighton', scriptrun, logging):
                        return False
                    light_on = True

                await handle_mtl('mtltrial', scriptrun.ICSclient, logging=logging)
                trial = await wait_reply(scriptrun.response_queue, 'MTL', 'mtltrial',
                                         timeout=MTL_TRIAL_TIMEOUT_S, logging=logging)
                if not await self.spec_illumination('illulightoff', scriptrun, logging):
                    return False
                light_on = False

                if trial.get('status') != 'success':
                    log_or_print(logging, f"MTL trial failed: {trial.get('message')}", 'error')
                    return False
                self.last_mtl_trial = trial
                log_or_print(logging, f"MTL trial {trial.get('itrial')}: error max "
                             f"{trial.get('err_max')}, median {trial.get('err_median')}.",
                             'receive')
                if trial.get('converged'):
                    converged = True
                    break
                if not trial.get('should_continue'):
                    log_or_print(logging, 'Metrology did not converge within max_trial.',
                                 'warning')
                    break

                trial_json = mtl_json_on_ics(trial.get('filename'))
                sent = await handle_fbp(f'fbpoffset {shlex.quote(trial_json)}',
                                        scriptrun.ICSclient, logging=logging)
                if not sent:
                    log_or_print(logging, f'Could not send fbpoffset with {trial_json}.', 'error')
                    return False
                moved = await wait_reply(scriptrun.response_queue, 'FBP', 'fbpoffset',
                                         timeout=FBP_OFFSET_TIMEOUT_S, logging=logging)
                if moved.get('status') != 'success':
                    log_or_print(logging, f"fbpoffset failed: {moved.get('message')}", 'error')
                    return False
            return converged
        finally:
            await self.spec_illumination('illuoff', scriptrun, logging)
            try:
                await handle_lamp('fiducialoff', scriptrun.ICSclient, logging=logging,
                                  state_callback=lamp_callback)
            except Exception as error:
                log_or_print(logging, f'fiducialoff failed: {error}', 'error')
            log_or_print(logging, f'###### Metrology loop finished (converged: {converged}) ######',
                         'comment')

    async def run_scan(self, scriptrun, params, logging):
        """Starts the zero-order star scan asynchronously (runscan <assign> <path> [options])."""
        try:
            opts = parse_scan_args(params)
        except ScanArgsError as error:
            log_or_print(logging, str(error), 'error')
            return
        self.script_task = asyncio.create_task(self.handle_scan(scriptrun, logging, opts))

    async def _scan_request(self, scriptrun, logging, opts, inst, func, send, timeout, what=''):
        """send() and wait for the Done reply of inst/func; in a dry run only say so."""
        if opts.dry_run:
            log_or_print(logging, f'[dry-run] {inst} {func} {what}'.rstrip(), 'send')
            return {'inst': inst, 'func': func, 'process': 'Done', 'status': 'success',
                    'dry_run': True}
        await send()
        return await wait_reply(scriptrun.response_queue, inst, func, timeout=timeout,
                                logging=logging)

    async def _scan_fbpoffset(self, scriptrun, logging, opts, json_file):
        """fbpoffset with a command-angle JSON on this ICS; True when FBP replied success."""
        async def send():
            if not await handle_fbp(f'fbpoffset {shlex.quote(json_file)}', scriptrun.ICSclient,
                                    logging=logging):
                raise RuntimeError(f'could not send fbpoffset {json_file}')
        rsp = await self._scan_request(scriptrun, logging, opts, 'FBP', 'fbpoffset', send,
                                       FBP_OFFSET_TIMEOUT_S, os.path.basename(json_file))
        if rsp.get('status') != 'success':
            log_or_print(logging, f"fbpoffset {os.path.basename(json_file)} failed: "
                         f"{rsp.get('message')}", 'error')
        return rsp

    async def _scan_setup(self, scriptrun, logging, opts, sciobs, tile_id):
        """loadtile (motion inverted, as the GUI Deploy) -> MTL loadobj, mtlstart, FBP
        loadmotion -> fbpmoveall -> metrology loop. Returns the centre angles or None."""
        tilemsg, objmsg, motionmsg1, motionmsg2 = sciobs.loadtile(
            tile_id, invert_motion_angles=True, zenith_angle_override=opts.zenith_angle)
        tile = json.loads(tilemsg)
        self.ra, self.dec = convert_to_sexagesimal(tile['ra'], tile['dec'])
        obj = json.loads(objmsg)
        log_or_print(logging, f"Tile {sciobs.project} {tile_id}: RA {self.ra}, Dec {self.dec}, "
                     f"{len(obj['xp'])} targets, zenith angle {obj['zenith_angle']:.2f} deg. "
                     'The telescope must already point at the tile and track.', 'normal')

        client = scriptrun.ICSclient if not opts.dry_run else None
        steps = [('MTL', 'loadobj', lambda: client.send_message('MTL', objmsg), 60),
                 ('MTL', 'mtlstart',
                  lambda: client.send_message('MTL', mtl_start(exptime=self.MTLexpT,
                                                               nexposure=self.MTLexpN)),
                  TILE_LOAD_TIMEOUT_S),
                 ('FBP', 'loadmotion', lambda: client.send_message('FBP', motionmsg1), 60),
                 ('FBP', 'loadmotion', lambda: client.send_message('FBP', motionmsg2), 60)]
        if opts.move:
            steps.append(('FBP', 'fbpmoveall',
                          lambda: handle_fbp('fbpmoveall', client, logging=logging),
                          FBP_MOVEALL_TIMEOUT_S))
        for inst, func, send, timeout in steps:
            rsp = await self._scan_request(scriptrun, logging, opts, inst, func, send, timeout)
            if rsp.get('status') != 'success':
                log_or_print(logging, f"{inst} {func} failed: {rsp.get('message')}; "
                             'scan not started.', 'error')
                return None

        if opts.dry_run:
            log_or_print(logging, '[dry-run] metrology loop (runmtl): fiducialon, illuon, '
                         'mtltrial / fbpoffset until converged, illuoff, fiducialoff', 'send')
            path_end = starscan.read_path(opts.path)[1][-1]
            log_or_print(logging, '[dry-run] scan centre = the path end (stand-in for the '
                         'converged MTL trial JSON)', 'normal')
            return starscan.to_command(path_end, starscan.motion_offsets())

        self.last_mtl_trial = None
        if not await self.handle_metrology(scriptrun, logging):
            log_or_print(logging, 'Metrology did not converge; scan not started.', 'error')
            return None
        trial_json = mtl_json_on_ics(self.last_mtl_trial.get('filename'))
        log_or_print(logging, f'Scan centre: converged MTL trial {self.last_mtl_trial.get("itrial")}'
                     f' ({trial_json}).', 'normal')
        return starscan.read_angles(trial_json)

    async def handle_scan(self, scriptrun, logging, opts):
        """Zero-order star scan of one tile (design: proj-kspecdr research note
        2026-10-27-star-scan-design).

            loadtile (invert_motion_angles=True) -> MTL loadobj, mtlstart -> FBP loadmotion
            -> fbpmoveall -> metrology loop to convergence (centre A0 = last trial JSON)
            -> GFA guiding on
            -> for each offset (dx, dy) of the pattern: fbpoffset (absolute command angles of
               every positioner: A0, with the scanned fibres moved by inverse kinematics of
               their A0 position + (dx, dy)), getobj (IsoPlane at zero order), one record line
               with the per-fibre zero-order fluxes of the reply
            -> fbpoffset A0 [-> mtltest check] -> guiding off

        Every offset is computed before the first move, so a pose the kinematics refuse
        stops the scan before anything moves. After an FBP failure nothing else moves.
        Records: <outdir>/<project>_<tile>_scan.jsonl and one JSON per step.
        """
        log = logging if logging is not None else (lambda message, level='normal': printing(message))
        night = datetime.now(timezone.utc).strftime('%Y%m%d')
        outdir = os.path.abspath(opts.outdir or os.path.join('..', 'DATA', 'STARSCAN', night))
        log_or_print(logging, '###### Star scan starts' + (' (DRY RUN: nothing is sent)'
                     if opts.dry_run else '') + ' ######', 'comment')
        try:
            sciobs, tile_id = stage_scan_tile(opts.assign, opts.path, opts.info,
                                              os.path.join(outdir, 'tile'))
            if opts.dry_run:
                sciobs.obsinfofile = os.path.join(outdir, 'tile', 'obs_info.json')
            stem = f'{sciobs.project}_{tile_id:04d}'
            self.project, self.TileID, self.obsdate = sciobs.project, str(tile_id), night
            positioners = starscan.axis_map_positioners()
            assign = starscan.read_assign(opts.assign)
            monitors = [h for h in opts.monitors.split(',') if h]
            scanned = ([h for h in opts.fibres.split(',') if h] if opts.fibres
                       else [h for h, row in assign.items() if row['cls'] == 1])
            scanned = [h for h in scanned if h not in monitors]
            unknown = sorted(set(scanned + monitors) - set(positioners))
            if unknown or not scanned:
                raise ValueError(f'no fibres to scan, or not positioners: {unknown}')
            arms = starscan.mtl_arms(scanned) if opts.arms == 'mtl' else None
            if arms is None:
                if opts.arms == 'mtl':
                    log_or_print(logging, 'kspec_metrology does not import here: design arms '
                                 '5.2 / 11.6 mm.', 'warning')
                arms = starscan.DESIGN_ARMS
            step_um = opts.step * (opts.scale if opts.unit == 'arcsec' else 1.0)
            pattern = starscan.scan_pattern(opts.pattern, step_um, opts.npts, opts.centre_repeats)
            reach = max(math.hypot(s['dx'], s['dy']) for s in pattern)
            if reach > opts.max_offset_um:
                raise ValueError(f'pattern reaches {reach:.0f} um > --max-offset-um '
                                 f'{opts.max_offset_um:g}')
        except (OSError, ValueError) as error:
            log_or_print(logging, f'runscan: {error}', 'error')
            return

        record = starscan.JsonLog(os.path.join(outdir, f'{stem}_scan.jsonl'))
        record.write(kind='start', dry_run=opts.dry_run, assign=os.path.abspath(opts.assign),
                     path=os.path.abspath(opts.path), scanned=scanned, monitors=monitors,
                     pattern=opts.pattern, step_um=step_um, npts=opts.npts,
                     scale_um_per_arcsec=opts.scale, exptime=opts.exptime, quantum=opts.quantum,
                     arms=arms if isinstance(arms, tuple) else {h: arms[h] for h in scanned},
                     nsteps=len(pattern))
        log_or_print(logging, f'{len(scanned)} fibres scanned, {len(monitors)} monitors, '
                     f'{opts.pattern} {opts.npts} x {step_um:.1f} um ({step_um / opts.scale:.2f}"),'
                     f' {len(pattern)} frames of {opts.exptime:g} s.', 'normal')

        if opts.centre:
            centre = starscan.read_angles(opts.centre)
            log_or_print(logging, f'Scan centre from {opts.centre}; no tile load, move or MTL.',
                         'normal')
        else:
            centre = await self._scan_setup(scriptrun, logging, opts, sciobs, tile_id)
            if centre is None:
                record.write(kind='end', status='setup failed')
                return
        try:
            starscan.check_complete(centre, positioners)
            plan = []
            for k, s in enumerate(pattern):
                angles, achieved = starscan.offset_command(
                    centre, scanned, s['dx'], s['dy'], arms, offsets=starscan.motion_offsets(),
                    quantum=opts.quantum, max_delta_deg=opts.max_delta_deg)
                json_file = starscan.write_angles(
                    os.path.join(outdir, f'{stem}_scan{k:03d}.json'), angles)
                plan.append((k, s, achieved, json_file))
                turn = max(scanned, key=lambda h: max(abs(angles[f'{h}_{a}'] - centre[f'{h}_{a}'])
                                                      for a in ('a', 'b')))
                s['max_turn'] = (turn, max(abs(angles[f'{turn}_{a}'] - centre[f'{turn}_{a}'])
                                           for a in ('a', 'b')))
            centre_json = starscan.write_angles(os.path.join(outdir, f'{stem}_centre.json'),
                                                centre)
        except (OSError, ValueError) as error:
            log_or_print(logging, f'runscan: {error}; nothing moved for the scan.', 'error')
            record.write(kind='end', status=f'plan refused: {error}')
            return
        turn = max((s['max_turn'] for s in pattern), key=lambda t: t[1])
        log_or_print(logging, f'Plan: {len(plan)} poses within {reach:.0f} um of the centre; '
                     f'largest axis turn {turn[1]:.3f} deg ({turn[0]}).', 'normal')
        record.write(kind='centre', json=centre_json,
                     mtl_trial={k: (self.last_mtl_trial or {}).get(k) for k in
                                ('filename', 'itrial', 'err_max', 'err_median', 'converged',
                                 'offsetx', 'offsety')} if not opts.centre else None)

        guiding = False
        if opts.guide:
            if opts.dry_run:
                log_or_print(logging, f'[dry-run] autoguide {self.GFAexpT:g} {self.GFAexpN}, '
                             f'settle {opts.guide_settle:g} s', 'send')
            else:
                await self.run_autoguide(scriptrun, self.GFAexpT, self.GFAexpN, False, logging=log)
                guiding = True
                await asyncio.sleep(opts.guide_settle)
                if self.autoguide_task is None or self.autoguide_task.done():
                    log_or_print(logging, 'GFA guiding is not running; scan not started.', 'error')
                    record.write(kind='end', status='guiding failed')
                    return

        moved, fbp_failed, status = False, False, 'interrupted'
        n = len(plan)
        try:
            for k, s, achieved, json_file in plan:
                d_e, d_n = starscan.sky_offset(s['dx'], s['dy'], opts.scale)
                log_or_print(logging, f'Scan {k + 1}/{n}: dx {s["dx"]:+.1f} um, dy {s["dy"]:+.1f}'
                             f' um (E {d_e:+.2f}", N {d_n:+.2f}")', 'normal')
                moved = True
                fbp = await self._scan_fbpoffset(scriptrun, logging, opts, json_file)
                if fbp.get('status') != 'success':
                    fbp_failed, status = True, 'fbpoffset failed'
                    break
                self.object = f'{stem} scan {k + 1}/{n}'
                if opts.dry_run:
                    log_or_print(logging, f'[dry-run] SPEC getobj {opts.exptime:g} 1', 'send')
                    spec = {'status': 'success', 'dry_run': True}
                else:
                    spec = await self.send_spec_and_log(f'getobj {opts.exptime:g} 1', 'Object',
                                                        opts.exptime, f'{k + 1}/{n}', scriptrun,
                                                        logging=logging)
                zoflux = spec.get('zoflux')
                if spec.get('status') == 'success' and not opts.dry_run and zoflux is None:
                    log_or_print(logging, 'getobj reply has no zoflux: is the IsoPlane at zero '
                                 'order (specinitial ... KSPEC_150_0) with zero_order set?',
                                 'warning')
                fluxes = zero_order_fluxes(zoflux, scanned + monitors)
                record.write(kind='step', step=k, nsteps=n, dx_um=s['dx'], dy_um=s['dy'],
                             dE_arcsec=d_e, dN_arcsec=d_n, centre=s['centre'], json=json_file,
                             max_turn_deg=s['max_turn'],
                             achieved_um=achieved, fbp_status=fbp.get('status'),
                             spec_status=spec.get('status'), filename=spec.get('filename'),
                             fwhm=self.fwhm, guiding=bool(self.autoguide_task
                                                          and not self.autoguide_task.done()),
                             flux=fluxes, zoflux=zoflux)
                if spec.get('status') != 'success':
                    status = f"getobj failed: {spec.get('message')}"
                    break
                got = [f for f in (fluxes[h] for h in scanned) if f is not None]
                if not opts.dry_run:
                    log_or_print(logging, f'Scan {k + 1}/{n}: {len(got)}/{len(scanned)} fluxes'
                                 + (f', median {sorted(got)[len(got) // 2]:.0f} ADU' if got
                                    else ''), 'receive')
            else:
                status = 'done'
        finally:
            if moved and not fbp_failed:
                log_or_print(logging, 'Scan: back to the centre.', 'normal')
                back = await self._scan_fbpoffset(scriptrun, logging, opts, centre_json)
                record.write(kind='return', json=centre_json, fbp_status=back.get('status'))
                if back.get('status') == 'success' and opts.mtl_check:
                    await self._scan_mtl_check(scriptrun, logging, opts, stem, record)
            elif fbp_failed:
                log_or_print(logging, 'Positioners are left where FBP stopped; check fbpstatus '
                             f'before any move (centre: fbpoffset {centre_json}).', 'error')
            if guiding:
                await self.autoguidestop(scriptrun, logging)
            record.write(kind='end', status=status)
            self.script_task = None
            log_or_print(logging, f'###### Star scan finished ({status}); records in '
                         f'{record.path} ######', 'comment')

    async def _scan_mtl_check(self, scriptrun, logging, opts, stem, record):
        """One back-illuminated MTL image at the centre (open-loop return check)."""
        lamp_callback = getattr(scriptrun, 'lamp_state_callback', None)
        name = f'{stem}_scan_return'
        if opts.dry_run:
            log_or_print(logging, f'[dry-run] fiducialon, illuon, MTL mtltest '
                         f'{opts.mtl_exptime:g} 1 {name}, illuoff, fiducialoff', 'send')
            return
        try:
            await handle_lamp('fiducialon', scriptrun.ICSclient, logging=logging,
                              state_callback=lamp_callback)
            if await self.spec_illumination('illuon', scriptrun, logging):
                await handle_mtl(f'mtltest {opts.mtl_exptime:g} 1 {name}', scriptrun.ICSclient,
                                 logging=logging)
                rsp = await wait_reply(scriptrun.response_queue, 'MTL', 'mtltest',
                                       timeout=MTL_TRIAL_TIMEOUT_S, logging=logging)
                record.write(kind='mtl_check', status=rsp.get('status'), images=rsp.get('images'))
        except Exception as error:
            log_or_print(logging, f'MTL check failed: {error}', 'error')
        finally:
            await self.spec_illumination('illuoff', scriptrun, logging)
            try:
                await handle_lamp('fiducialoff', scriptrun.ICSclient, logging=logging,
                                  state_callback=lamp_callback)
            except Exception as error:
                log_or_print(logging, f'fiducialoff failed: {error}', 'error')

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
            await handle_gfa(f'gfaguide {exptime} {expnum} {save} {rahms_t} {decdms_t}',scriptrun.ICSclient, logging=logging)
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
        await handle_gfa("gfaguidestop", scriptrun.ICSclient, logging=logging)
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
        # CLI: ask for the plan and tile before KSPECRUN.py prompts for the next command,
        # so the two never read stdin at the same time.
        obsplan = await self.select_obsplan_tile() if logging == None else None
        self.script_task = asyncio.create_task(self.handle_obs(scriptrun, logging, obsplan))

    async def select_obsplan_tile(self):
        """CLI: ask for an observation plan file and a Tile ID in it; return (sciobs, filename)."""
        loop = asyncio.get_running_loop()
        ask = lambda prompt: loop.run_in_executor(None, input, prompt)

        printing('###### Observation Script Start!!! ######')
        with open('./Lib/KSPEC.ini','r') as fs:
            kspecinfo=json.load(fs)
        obsplanpath=kspecinfo['SCIOBS']['obsplanpath']

        while True:
            filename=await ask('\nPlease insert Observation sequence file (ex. ASPECS_obs_250217.txt): ')
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

        data=np.loadtxt(obsplanpath+filename,skiprows=1,dtype=str,ndmin=2)

        print('### Load tile information ###')
        print("\t".join(header))
        for row in data:
            print("\t".join(row), flush=True)

        tile_ids = set(row[0] for row in data)
        while True:
            self.TileID=(await ask('\nPlease select Tile ID above you want to runscript.: ')).strip()
            if self.TileID in tile_ids:
                printing(f'Tile ID {self.TileID} is selected from observation plan.')
                for row in data:
                    if row[0] == self.TileID:
                        print(row)
                        obs_num=row[2]
                        print(f'Observation number of exposure: {obs_num}')
                break
            else:
                print(f'Tile ID {self.TileID} was not found. Please enter a valid ID.')
        return sciobs, filename

    async def handle_obs(self,scriptrun,logging,obsplan=None):
        await clear_queue(scriptrun.response_queue)
        await clear_queue(scriptrun.GFA_response_queue)
        await clear_queue(scriptrun.ADC_response_queue)
        await clear_queue(scriptrun.SPEC_response_queue)

        if logging != None:
            logging(f'###### Observation for Tile ID {self.TileID} starts ######',level='comment')
        printing(f'###### Observation for Tile ID {self.TileID} starts ######')
        
        if logging == None:
            ### Start CLI version: plan and tile from select_obsplan_tile ###
            sciobs, filename = obsplan
            tilemsg,objmsg,motionmsg1,motionmsg2=load_obsplan_tile(sciobs, filename, self.TileID)
            tile_data=json.loads(tilemsg)
            self.ra,self.dec=convert_to_sexagesimal(tile_data['ra'],tile_data['dec'])

            printing(f'RA and DEC of Tile ID {self.TileID}: {self.ra} {self.dec}')

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

        # printing(f'Fiber positioner Moving Start')
        # await handle_fbp('fbpmoveall',scriptrun.ICSclient, logging=logging)
        # await scriptrun.response_queue.get()

        messagetcs = 'KSPEC>TC ' + 'tmradec ' + self.ra +' '+ self.dec
        printing(f'Slew Telescope to RA={self.ra}, DEC={self.dec}.')
        await scriptrun.send_udp_message(messagetcs)
        print('Telescope is slewing now.', end=' ',flush=True)
        await asyncio.sleep(2)

        while True:
            print('Telescope is slewing......')
            if logging != None:
                logging('Telescope is slewing.....', level='receive')
        #    r=redis.Redis(host='192.168.15.121',port=6379,decode_responses=True)     # Set IP address of KMTNet redis server
            r=redis.Redis(host='127.0.0.1',port=6379,decode_responses=True)     # For simulation. Remove or comment in real observation

            value=r.get('dome_error')
        #    print(value)                                                        # Remove or comment in real observation

            if value != '0002':
                print('Telescope slew finished')
                if logging != None:
                    logging('Telescope slew finished.', level='receive')
                break
            print('.',end=' ', flush=True)
            await asyncio.sleep(5)

        # await scriptrun.response_queue.get()                                    # Wait for Fiber movement finish

        ### 이부분에 Cal Offset, Pointing 부분이 iteration으로 들어가야함. Pointing이 끝나면 Autoguiding

        # await asyncio.sleep(3)
        # printing(f'Autoguiding Start')
        # logging(f'GFA guiding. Exposure time is {self.GFAexpT} s, exposure count is {self.GFAexpN}.', level='receive')
        # await self.run_autoguide(scriptrun, self.GFAexpT, self.GFAexpN, logging=logging)
        # await asyncio.sleep(2)

        # Metrology iterations: fiducials and back illumination on, mtltrial / fbpoffset until
        # converged, back illumination and fiducials off (handle_metrology).
    #     if not await self.handle_metrology(scriptrun, logging):
    #         logging('Metrology did not converge; observation stopped.', level='error')
    #         return

    #     printing(f'ADC Adjust Start')
    # #    message=f'adcadjust {self.ra} {self.dec}'
    # #    print(message)
    #     message=f'adcadjust 02:34:56.44 -31:34:55.67'                           # Just for simulation. Remove or comment when real observation
    #     await handle_adc(message,scriptrun.ICSclient, logging=logging)
    #     await asyncio.sleep(2)

    
    # #    print(f'FHWM is {self.fwhm:.5f}.')                                     # Remove in real observation
  
    #     obs_num=self.obsnum
    #     printing(f'KSPEC starts {obs_num} exposures with {self.expT} seconds.')
        
    #     for i in range(int(obs_num)):
    #         await clear_queue(scriptrun.SPEC_response_queue)
    #         fram=f'{i+1}/{obs_num}'
    #         printing(f'**** {i+1}/{obs_num}: {self.expT} seconds exposure start. ****')
    #         logging(f'**** {i+1}/{obs_num}: {self.expT} seconds exposure start. ****', level='receive')
    #         spec_rsp = await self.send_spec_and_log(
    #             f'getobj {self.expT} 1',
    #             'Object',
    #             self.expT,
    #             fram,
    #             scriptrun,
    #             logging=logging,
    #         )
    #         if isinstance(spec_rsp, dict) and spec_rsp.get("filename") not in (None, "None"):
    #             logging('Fits header and observation log updated', level='receive')
    #             printing("Fits header and observation log updated")


    #     printing('All exposures are completed.')
    #     logging('All exposures are completed.',level='receive')

    #     await handle_adc('adcstop',scriptrun.ICSclient, logging=logging)
    #     await scriptrun.response_queue.get()
    
    #     await self.autoguidestop(scriptrun,logging)
    #     await scriptrun.response_queue.get()

    #     await handle_adc('adczero 2',scriptrun.ICSclient, logging=logging)
    #     await scriptrun.response_queue.get()
    #     await scriptrun.response_queue.get()

    #     await handle_fbp('fbpzero',scriptrun.ICSclient, logging=logging)
    #     await scriptrun.response_queue.get()
    #     await scriptrun.response_queue.get()
        

        printing(f'###### Observation Script for Tile ID {self.TileID} END!!! ######')
        if logging != None:
            logging(f'###### Observation Script for Tile ID {self.TileID} END!!! ######',level='comment')
        
        



#async def handle_script(arg, ICSclient, send_udp_message, send_telcom_command, 
#        response_queue, GFA_response_queue, ADC_response_queue, SPEC_response_queue, scriptrun, logging=None):
async def handle_script(arg, scriptrun=None, logging=None):
    """ Handle script with error checking. """
    cmd, *params = arg.split()

    command_map = {
            'obsinitial': scriptrun.obs_initial, 'runcalib': scriptrun.run_calib, 'runobs': scriptrun.run_obs,
            'runmtl': scriptrun.run_metrology, 'rundark': scriptrun.run_dark
    }

    if cmd in command_map:
#        await command_map[cmd](scriptrun.ICSclient,scriptrun.send_udp_message, scriptrun.send_telcom_command, 
#                scriptrun.response_queue, scriptrun.GFA_response_queue, scriptrun.ADC_response_queue, scriptrun.SPEC_response_queue, scriptrun.logging)
        await command_map[cmd](scriptrun,logging)
    elif cmd == 'autoguide':
        await scriptrun.run_autoguide(scriptrun, float(params[0]), int(params[1]), params[2],logging=logging)

    elif cmd == 'autoguidestop':
        await scriptrun.autoguidestop(scriptrun,logging)

    elif cmd == 'runscan':
        try:
            params = shlex.split(arg)[1:]      # file names may hold spaces
        except ValueError as error:
            log_or_print(logging, f'runscan: {error}', 'error')
            return
        await scriptrun.run_scan(scriptrun, params, logging)
    else:
        print(f"Error: '{cmd}' is not right command for SCRIPT")
