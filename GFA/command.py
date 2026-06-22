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
        deleted = clear_astrometry_outputs(path_astroimg)
        printing(f"Deleted {deleted} astrometry output files from {path_astroimg}")

        await send_gfa_response(
            GFA_server,
            process='START',
            message='Start calculating Telescope pointing offset.',
            status='success',
            subinst='POINT',
            log=False,
        )

        max_try = 3
        min_required = 5

        for attempt in range (1, max_try+1):
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
                (float(crval1), float(crval2))
                for crval1, crval2 in zip(crval1_list, crval2_list)
                if is_finite_number(crval1) and is_finite_number(crval2)
            ]

            valid_crval1 = [crval1 for crval1, _ in valid_crval_pairs]
            valid_crval2 = [crval2 for _, crval2 in valid_crval_pairs]

            # Success condition
            if len(valid_crval1) >= min_required:
                printing(f"Astrometry success with {len(valid_crval1)} valid CRVAL pairs")
                ra_c, dec_c = get_boresight(valid_crval1, valid_crval2)    # Boresight coordinate
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
                    process='Done',
                    status='success',
                    subinst='POINT',
                )
                break

            printing(f"Only {len(valid_crval1)} valid CRVAL pairs (try {attempt}/{max_try}) → retrying...")

            if attempt == max_try:
                msg = "Astrometry failed: insufficient valid CRVAL pairs (less than 5). Increase exposure time or Wait for good weather."
                await send_gfa_response(
                    GFA_server,
                    message=msg,
                    process='Done',
                    status='fail',
                    subinst='POINT',
                )
                return

            await asyncio.sleep(1)


        
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
            await send_gfa_response(GFA_server, result, process='ING')

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
