import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
import math
import numpy as np
from pathlib import Path
from .pointing import *


guiding_task = None

def printing(message):
    """Utility function for consistent printingging.

    Args:
        message (str): The message to be printingged.
    """
    print(f"\033[32m[GFA] {message}\033[0m")

def clear_astrometry_outputs(directory):
    path = Path(directory).expanduser().resolve()

    if path in (Path("/"), Path.home()):
        raise ValueError(f"Refusing to clear unsafe directory: {path}")

    path.mkdir(parents=True, exist_ok=True)

    deleted = 0
    for item in path.glob("astro_*.fits"):
        if item.is_file() or item.is_symlink():
            item.unlink()
            deleted += 1

    return deleted

def parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "y"):
            return True
        if normalized in ("false", "0", "no", "n"):
            return False
        raise ValueError(f"Invalid boolean value: {value}")

    return bool(value)

def parse_list(value):
    if isinstance(value, list):
        return value
    raise ValueError(f"Expected list, got {type(value).__name__}")

def is_missing_parameter(value):
    return value is None or value == '' or value == 'None'

GFA_COMMAND_SPECS = {
    'gfastatus': {},
    'gfaguidestop': {},
    'gfagrab': {
        'args': (
            ('CamNum', int),
            ('ExpTime', float),
            ('ExpNum', int),
        ),
        'optional_args': (
            ('ra', str, None),
            ('dec', str, None),
        ),
        'validators': (
            ('CamNum', lambda value: value >= 0, 'Camera number should be greater than or equal to 0.'),
            ('ExpTime', lambda value: value > 0, 'Exposure time should be greater than 0.'),
            ('ExpNum', lambda value: value >= 1, 'Exposure number should be greater than or equal to 1.'),
        ),
    },
    'gfaguide': {
        'args': (
            ('ExpTime', float),
            ('ExpNum', int),
            ('save', parse_bool),
        ),
        'optional_args': (
            ('ra', str, None),
            ('dec', str, None),
        ),
        'validators': (
            ('ExpTime', lambda value: value > 0, 'Exposure time should be greater than 0.'),
            ('ExpNum', lambda value: value >= 1, 'Exposure number should be greater than or equal to 1.'),
        ),
    },
    'pointing': {
        'args': (
            ('ExpTime', float),
            ('ExpNum', int),
            ('ra', str),
            ('dec', str),
        ),
        'optional_args': (
            ('SaveGrabRaw', parse_bool, True),
        ),
        'validators': (
            ('ExpTime', lambda value: value > 0, 'Exposure time should be greater than 0.'),
            ('ExpNum', lambda value: value >= 1, 'Exposure number should be greater than or equal to 1.'),
        ),
    },
    'loadguide': {
        'args': (
            ('ra', parse_list),
            ('dec', parse_list),
            ('mag', parse_list),
            ('xp', parse_list),
            ('yp', parse_list),
        ),
    },
}

def parse_gfa_command(func, dict_data):
    spec = GFA_COMMAND_SPECS.get(func)
    if spec is None:
        return None, f"Unknown GFA command: {func}"

    parsed = dict(spec.get('fixed', {}))

    for name, value_type in spec.get('args', ()):
        raw_value = dict_data.get(name)
        if is_missing_parameter(raw_value):
            return None, f"'{func}' command needs '{name}' parameter."

        try:
            parsed[name] = value_type(raw_value)
        except (TypeError, ValueError):
            value_type_name = getattr(value_type, '__name__', str(value_type))
            return (
                None,
                f"'{func}' command parameter '{name}' should be {value_type_name}. "
                f"input value: {raw_value}",
            )

    for name, value_type, default in spec.get('optional_args', ()):
        raw_value = dict_data.get(name, default)
        if is_missing_parameter(raw_value):
            parsed[name] = default
            continue

        try:
            parsed[name] = value_type(raw_value)
        except (TypeError, ValueError):
            value_type_name = getattr(value_type, '__name__', str(value_type))
            return (
                None,
                f"'{func}' command parameter '{name}' should be {value_type_name}. "
                f"input value: {raw_value}",
            )

    for name, validator, message in spec.get('validators', ()):
        if not validator(parsed[name]):
            return None, f"{message} input value: {parsed[name]}"

    return parsed, None

async def send_gfa_response(GFA_server, result=None, *, log=True, **updates):
    reply_data = mkmsg.gfamsg()

    if result is not None:
        reply_data.update(result)

    reply_data.update(updates)

    rsp = json.dumps(reply_data)
    if log and reply_data.get('message'):
        printing(reply_data['message'])

    await GFA_server.send_message('ICS', rsp)
    return reply_data

async def identify_execute(GFA_server,gfa_actions,cmd):
    global guiding_task 
    try:
        dict_data=json.loads(cmd)
    except json.JSONDecodeError as e:
        await send_gfa_response(
            GFA_server,
            message=f"Invalid GFA command JSON: {e}",
            process='Done',
            status='error',
        )
        return

    if not isinstance(dict_data, dict):
        await send_gfa_response(
            GFA_server,
            message='Invalid GFA command: JSON payload should be an object.',
            process='Done',
            status='error',
        )
        return

    func=dict_data.get('func')
    if is_missing_parameter(func):
        await send_gfa_response(
            GFA_server,
            message="Invalid GFA command: 'func' is required.",
            process='Done',
            status='error',
        )
        return

    parsed_args, parse_error = parse_gfa_command(func, dict_data)
    if parse_error:
        await send_gfa_response(
            GFA_server,
            message=parse_error,
            process='Done',
            status='error',
        )
        return

    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    if func == 'gfastatus':
        result=gfa_actions.status()
        await send_gfa_response(GFA_server, result, process='Done')

    elif func == 'gfagrab':
        result = await gfa_actions.grab(
            parsed_args['CamNum'],
            parsed_args['ExpTime'],
            parsed_args['ExpNum'],
            ra=parsed_args['ra'],
            dec=parsed_args['dec'],
        )
        await send_gfa_response(GFA_server, result, process='Done')

    elif func == 'gfaguide':
        # Cancel any running task before starting a new one
        if guiding_task and not guiding_task.done():
            printing("Cancelling the running autoguiding task...")
            guiding_task.cancel()
            try:
                await guiding_task
            except asyncio.CancelledError:
                printing("Previous guiding task cancelled.")

        # A new guiding session needs its own reference WCS. Astrometry outputs left by
        # pointing (or an earlier guide) would otherwise be reused when the RA/DEC is
        # within the 30" session tolerance, and the first cycle would undo the pointing
        # correction just applied.
        path_astroimg=kspecinfo['GFA']['final_astrometry_images']
        deleted = clear_astrometry_outputs(path_astroimg)
        printing(f"Deleted {deleted} astrometry output files from {path_astroimg} (new guiding reference)")

        # Start a new adcadjust task
        printing("New guiding task started.")
        await send_gfa_response(
            GFA_server,
            process='START',
            message='Autoguide starts.',
            status='success',
            log=False,
        )
        guiding_task = asyncio.create_task(
            handle_guiding(
                GFA_server,
                gfa_actions,
                parsed_args['ExpTime'],
                parsed_args['ExpNum'],
                parsed_args['save'],
                ra=parsed_args['ra'],
                dec=parsed_args['dec'],
            )
        )

    elif func == 'gfaguidestop':
        if guiding_task and not guiding_task.done():
            printing("Stopping guiding task...")
            guiding_task.cancel()
            await send_gfa_response(
                GFA_server,
                process='Done',
                message='Autoguide Stop',
                status='success',
            )

            path_astroimg=kspecinfo['GFA']['final_astrometry_images']
            deleted = clear_astrometry_outputs(path_astroimg)
            printing(f"Deleted {deleted} astrometry output files from {path_astroimg}")

            try:
                await guiding_task
            except asyncio.CancelledError:
                printing("Guiding task stopped.")
        else:
            printing("No Guiding task is currently running.")
            await send_gfa_response(
                GFA_server,
                process='Done',
                message='No Guiding task is currently running.',
                status='normal',
            )

    elif func == 'loadguide':
        ra=parsed_args['ra']
        dec=parsed_args['dec']
        mag=parsed_args['mag']
        xp=parsed_args['xp']
        yp=parsed_args['yp']
        status, comment=savedata(ra,dec,xp,yp,mag)    # It would be removed, because guide stars are not necessary in current guiding system. 
        await send_gfa_response(
            GFA_server,
            message=comment,
            process='Done',
            status=status,
        )


#    if func == 'fdgrab':
#        printing("Finder grab task started.")
#        reply_data=mkmsg.gfamsg()
#        reply_data.update(process='START',message='Finder grab starts.',status='success')
#        rsp=json.dumps(reply_data)
#        await GFA_server.send_message('ICS',rsp)
#        result = await finder_actions.grab(dict_data['ExpTime'])
#        reply_data=mkmsg.gfamsg()
#        reply_data.update(result)
#        reply_data.update(process='Done')
#        rsp=json.dumps(reply_data)
#        printing(reply_data['message'])
#        await GFA_server.send_message('ICS',rsp)


    elif func == 'pointing':
        path_astroimg=kspecinfo['GFA']['final_astrometry_images']
        geometry_path=os.path.join(kspecinfo['GFA']['gfafilepath'], BORESIGHT_GEOMETRY_FILE)

        await send_gfa_response(
            GFA_server,
            process='START',
            message='Start calculating Telescope pointing offset.',
            status='success',
            subinst='POINT',
            log=False,
        )

        max_try = 3
        # Solved cameras needed. compute_boresight works from 2 cameras (geometry) or 3
        # (ring centre), so one unsolved or broken camera no longer fails the pointing.
        min_required = 3

        for attempt in range (1, max_try+1):
            # Clear before every attempt: astrometry outputs that are still there are
            # reused instead of solving the frames grabbed in this attempt.
            deleted = clear_astrometry_outputs(path_astroimg)
            printing(f"Deleted {deleted} astrometry output files from {path_astroimg}")

            result = await gfa_actions.pointing(
                ra=parsed_args['ra'],
                dec=parsed_args['dec'],
                ExpTime=parsed_args['ExpTime'],
                ExpNum=parsed_args['ExpNum'],
                SaveGrabRaw=parsed_args['SaveGrabRaw'],
            )

            message1 = result.get('message', 'Unknown error')
            status = result.get('status','error')

            if status == 'error':
                msg =f'{message1}. Increase exposure time or Wait for good weather.'
                await send_gfa_response(
                    GFA_server,
                    message=msg,
                    process='Done',
                    status='fail',
                    subinst='POINT',
                )
                return

            img_list=result['images']
            crval1_list=result['crval1']
            crval2_list=result['crval2']


            def is_finite_number(value):
                try:
                    return value is not None and math.isfinite(float(value))
                except (TypeError, ValueError):
                    return False

            if len(crval1_list) != len(crval2_list):
                printing(
                    f"CRVAL list length mismatch: "
                    f"CRVAL1={len(crval1_list)}, CRVAL2={len(crval2_list)}"
                )

            valid_crval_pairs = [
                (img, float(crval1), float(crval2))
                for img, crval1, crval2 in zip(img_list, crval1_list, crval2_list)
                if is_finite_number(crval1) and is_finite_number(crval2)
            ]

            valid_images = [img for img, _, _ in valid_crval_pairs]
            valid_crval1 = [crval1 for _, crval1, _ in valid_crval_pairs]
            valid_crval2 = [crval2 for _, _, crval2 in valid_crval_pairs]

            # Success condition
            if len(valid_crval1) >= min_required:
                printing(f"Astrometry success with {len(valid_crval1)} valid CRVAL pairs")
                ra_c, dec_c, bs_method, bs_info = compute_boresight(
                    path_astroimg, valid_images, valid_crval1, valid_crval2, geometry_path
                )    # Boresight coordinate
                ra, dec = radec_str_to_deg(parsed_args['ra'], parsed_args['dec'])  # covert RA,DEC of Tile center to degree
                printing(f'Telescope Target: RA = {ra} DEC = {dec}')
                printing(f'Current Telescope pointing: RA = {ra_c} DEC= {dec_c}')

                sep = get_separation(ra_c,dec_c,ra,dec)

                printing(f'Separtation (arcsec.) : {sep}')

                delra,deldec = offsets_arcsec(ra_c,dec_c,ra,dec)  # calculate offset to move from ra_c, dec_c to ra, dec

                printing(f'Offset in (RA, DEC) : ({delra}, {deldec})')

                ra_deg, dec_deg = apply_offsets(ra,dec,delra,deldec)
                ra_new = ra_deg_to_hms(ra_deg)
                dec_new = dec_deg_to_dms(dec_deg)

                msg =f'{message1} Telescope Target: RA = {ra} DEC = {dec}. \
                    Current Telescope pointing: RA = {ra_c} DEC= {dec_c}.'

                await send_gfa_response(
                    GFA_server,
                    result,
                    message=msg,
                    sepsec=sep,
                    dra=delra,
                    ddec=deldec,
                    new_ra=ra_new,
                    new_dec=dec_new,
                    bsmethod=bs_method,
                    bsrms=bs_info.get('rms_arcsec'),
                    bscams=bs_info.get('used'),
                    bsringsep=bs_info.get('ring_sep_arcsec'),
                    bsstale=bs_info.get('stale'),
                    process='Done',
                    status='success',
                    subinst='POINT',
                )
                break

            printing(f"Only {len(valid_crval1)} valid CRVAL pairs (try {attempt}/{max_try}) → retrying...")

            if attempt == max_try:
                msg = f"Astrometry failed: insufficient valid CRVAL pairs (less than {min_required}). Increase exposure time or Wait for good weather."
                await send_gfa_response(
                    GFA_server,
                    message=msg,
                    process='Done',
                    status='fail',
                    subinst='POINT',
                )
                return

            await asyncio.sleep(1)


        
# Normal values on the commissioning frames: rms of the per-camera estimates ~3.5",
# geometry vs ring centre ~4".
RMS_CHECK_ARCSEC = 15.0
RING_CHECK_ARCSEC = 20.0


def compute_boresight(astro_dir, images, crval1_list, crval2_list, geometry_path):
    """Boresight (RA, DEC deg) of the solved GFA frames.

    1. Per-camera boresight geometry (GFA/etc/boresight_geometry.json, made by
       GFA/calib_boresight.py): works with any subset of cameras, ~3" with 5.
    2. Without it: centre of the camera ring fitted to >= 3 cameras (~5").
    3. Last resort: mean of the camera centres, correct only when every camera on the
       ring is solved; with one missing it is off by ~1060" (R/5, R = 1.47 deg).

    The geometry result is checked (info['stale']): per-camera estimates spread by more
    than RMS_CHECK_ARCSEC (or one rejected), or the result more than RING_CHECK_ARCSEC
    from the ring centre, mean the geometry no longer matches the cameras (remounted or
    reinstalled) and GFA/calib_boresight.py should be run again.

    Returns (ra_deg, dec_deg, method, info).
    """
    paths = [Path(astro_dir) / name for name in images]

    ring = None
    try:
        centres = [SkyCoord(c1 * u.deg, c2 * u.deg) for c1, c2 in zip(crval1_list, crval2_list)]
        ring, radii = ring_centre(centres)
    except Exception as e:
        printing(f"Ring centre unavailable ({e}).")

    try:
        geometry = load_boresight_geometry(geometry_path)
        ra_c, dec_c, info = boresight_from_astro_files(paths, geometry)
    except Exception as e:
        if ring is not None:
            printing(
                f"Boresight geometry unavailable ({e}); using the centre of the camera ring "
                f"({len(radii)} cameras, radius spread {np.ptp(radii):.1f} arcsec)."
            )
            return float(ring.ra.deg), float(ring.dec.deg), 'ring', {
                'used': [camera_serial(p) for p in paths], 'rms_arcsec': None,
            }
        printing(
            f"Boresight geometry unavailable ({e}); using the mean of the camera centres "
            "(correct only when all cameras are solved)."
        )
        ra_c, dec_c = get_boresight(crval1_list, crval2_list)
        return ra_c, dec_c, 'crval_mean', {}

    printing(
        f"Boresight from camera geometry: cameras={info['used']}, "
        f"rejected={info['rejected']}, rms={info['rms_arcsec']:.1f} arcsec"
    )
    reasons = []
    if info['rms_arcsec'] > RMS_CHECK_ARCSEC or info['rejected']:
        # e.g. the GFA plate turned: per-camera estimates spread around the boresight
        reasons.append(f"camera estimates disagree (rms {info['rms_arcsec']:.0f} arcsec, "
                       f"rejected {info['rejected']})")
    if ring is not None:
        info['ring_sep_arcsec'] = float(
            ring.separation(SkyCoord(ra_c * u.deg, dec_c * u.deg)).arcsec
        )
        if info['ring_sep_arcsec'] > RING_CHECK_ARCSEC:
            reasons.append(f"{info['ring_sep_arcsec']:.0f} arcsec from the camera ring centre")
    info['stale'] = bool(reasons)
    if reasons:
        printing(
            "WARNING: the boresight geometry may not match the cameras any more ("
            + "; ".join(reasons) + "). Re-run GFA/calib_boresight.py."
        )
    return ra_c, dec_c, 'geometry', info


def savedata(ra,dec,xp,yp,mag):
    with open('./Lib/KSPEC.ini','r') as f:
        inidata=json.load(f)

    gfafilepath=inidata['GFA']['gfafilepath']        # guide stars info. is saved in GFA/etc directory. It would not be necessary.

    try:
        with open(gfafilepath+'position.radec','w') as savefile:
            for i in range(len(ra)):
                savefile.write("%12.6f %12.6f %12.6f %12.6f %9.4f\n" % (ra[i],dec[i],xp[i],yp[i],mag[i]))
    except TypeError:
        return 'fail', "Non-numeric values encountered while formatting output."
    except OSError as e:
        return 'fail', f"Failed to write file: {e}"

    msg="'Guide stars are loaded.'"
    return 'success', msg



async def handle_guiding(GFA_server, gfa_actions, expt, expnum, save, ra: str=None, dec: str=None):
    try:
        while True:
            result = await gfa_actions.guiding(expt, expnum, SaveGrabRaw=save, ra=ra, dec=dec)

            status = result.get('status', 'error')
            stop_statuses = ('error', 'warning', 'fail')
            process = 'Done' if status in stop_statuses else 'ING'

            await send_gfa_response(GFA_server, result, process=process)

            if status in stop_statuses:
                printing(f"Guiding stopped because status is {status}.")
                return

            await asyncio.sleep(70)

    except asyncio.CancelledError:
        printing("handle_guiding task was cancelled.")
        raise
    except Exception as e:
        comment=f"Error in handle_guiding: {e}"
        printing(comment)
        await send_gfa_response(
            GFA_server,
            message=comment,
            process='Done',
            status='error',
            log=False,
        )
    else:
        printing("handle_guiding completed successfully.")
