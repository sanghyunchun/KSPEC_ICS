import asyncio
import json
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u
from astropy.coordinates import Angle

import numpy as np
from ADC.kspec_adc_controller.src.adc_calc_angle import ADCCalc

AAO_LOCATION = EarthLocation(lat=-31.27118, lon=149.06256, height=1165*u.m)

"""Command module for handling ADC-related functionalities.

This module provides functions to execute commands related to the ADC device, such as initialization,
connection, adjustment, and various operational controls. It includes utilities for printing, message
handling, and managing asynchronous tasks.
"""

# Global task tracker
adcadjust_task = None


ADC_COMMAND_SPECS = {
    'adcconnect': {},
    'adcdisconnect': {},
    'adcpoweroff': {},
    'adcstatus': {},
    'adcstop': {},
    'adcpark': {},
    'adcactivate': {
        'args': (('zdist', float),),
        'validators': (
            (
                'zdist',
                lambda value: 0.0 <= value < 60.0,
                'Zenith distance should be greater than or equal to 0 and less than 60 degree.',
            ),
        ),
    },
    'adcadjust': {
        'args': (('RA', str), ('DEC', str)),
    },
    'adcrotate1': {
        'args': (('pcount', int), ('vel', int)),
        'fixed': {'lens': 1},
    },
    'adcrotate2': {
        'args': (('pcount', int), ('vel', int)),
        'fixed': {'lens': 2},
    },
    'adcctrotate': {
        'args': (('pcount', int), ('vel', int)),
        'fixed': {'lens': 0},
    },
    'adccorotate': {
        'args': (('pcount', int), ('vel', int)),
        'fixed': {'lens': -1},
    },
    'adchome': {
        'args': (('vel', int),),
    },
    'adczero': {
        'args': (('vel', int),),
    },
}


def printing(message):
    """Utility function for consistent printingging.

    Args:
        message (str): The message to be printingged.
    """
    print(f"\033[32m[ADC] {message}\033[0m")


def is_missing_parameter(value):
    return value is None or value == '' or value == 'None'


def parse_adc_command(func, dict_data):
    spec = ADC_COMMAND_SPECS.get(func)
    if spec is None:
        return None, f"Unknown ADC command: {func}"

    parsed = dict(spec.get('fixed', {}))
    for name, value_type in spec.get('args', ()):
        raw_value = dict_data.get(name)
        if is_missing_parameter(raw_value):
            return None, f"'{func}' command needs '{name}' parameter."

        try:
            parsed[name] = value_type(raw_value)
        except (TypeError, ValueError):
            return (
                None,
                f"'{func}' command parameter '{name}' should be {value_type.__name__}. "
                f"input value: {raw_value}",
            )

    for name, validator, message in spec.get('validators', ()):
        if not validator(parsed[name]):
            return None, f"{message} input value: {parsed[name]}"

    return parsed, None


async def send_adc_response(ADC_server, result=None, *, log=True, **updates):
    reply_data = mkmsg.adcmsg()
    if result is not None:
        reply_data.update(result)
    reply_data.update(updates)

    rsp = json.dumps(reply_data)
    if log and reply_data.get('message'):
        printing(reply_data['message'])
    await ADC_server.send_message('ICS', rsp)
    return reply_data


async def stop_adcadjust_task(adc_action, reason):
    global adcadjust_task

    if not adcadjust_task or adcadjust_task.done():
        return False, None

    printing(f"Stopping adcadjust task before {reason}...")
    stop_result = await adc_action.stop(0)

    adcadjust_task.cancel()
    try:
        await adcadjust_task
    except asyncio.CancelledError:
        printing("adcadjust task stopped.")
    finally:
        adcadjust_task = None

    return True, stop_result

async def identify_execute(ADC_server, adc_action, cmd):
    """Identify and execute the requested ADC command.

    Args:
        ADC_server (AMQclass): The ADC server instance.
        adc_action (AdcActions): Instance of ADC action handler.
        cmd (str): JSON string containing the command details.

    Raises:
        ValueError: If the provided command is not recognized.
    """
    global adcadjust_task
    try:
        dict_data = json.loads(cmd)
    except json.JSONDecodeError as e:
        await send_adc_response(
            ADC_server,
            message=f"Invalid ADC command JSON: {e}",
            process='Done',
            status='error',
        )
        return

    if not isinstance(dict_data, dict):
        await send_adc_response(
            ADC_server,
            message='Invalid ADC command: JSON payload should be an object.',
            process='Done',
            status='error',
        )
        return

    func = dict_data.get('func')
    if is_missing_parameter(func):
        await send_adc_response(
            ADC_server,
            message="Invalid ADC command: 'func' is required.",
            process='Done',
            status='error',
        )
        return

    printing(f"{func}")

    parsed_args, parse_error = parse_adc_command(func, dict_data)
    if parse_error:
        await send_adc_response(
            ADC_server,
            message=parse_error,
            process='Done',
            status='error',
        )
        return

    if func == 'adcconnect':
        result = adc_action.connect()
        await send_adc_response(ADC_server, result, process='Done')

    elif func == 'adcdisconnect':
        task_was_running, stop_result = await stop_adcadjust_task(adc_action, 'ADC disconnect')

        result = adc_action.disconnect()
        message = result.get("message", "Disconnected from devices.")
        status = result.get("status", "success")

        if task_was_running:
            message = f"ADC adjust task stopped before disconnect. {message}"
            if stop_result and stop_result.get("status") == "error":
                status = "error"
                message = f"{message} Motor stop failed: {stop_result.get('message')}"

        await send_adc_response(ADC_server, result, message=message, process='Done', status=status)

    elif func == 'adcpoweroff':
        task_was_running, stop_result = await stop_adcadjust_task(adc_action, 'ADC power off')

        result = adc_action.power_off()
        message = result.get("message", "Power off and devices disconnected.")
        status = result.get("status", "success")

        if task_was_running:
            message = f"ADC adjust task stopped before power off. {message}"
            if stop_result and stop_result.get("status") == "error":
                status = "error"
                message = f"{message} Motor stop failed: {stop_result.get('message')}"

        await send_adc_response(ADC_server, result, message=message, process='Done', status=status)

    elif func == 'adcstatus':
        result = adc_action.status()
        await send_adc_response(ADC_server, result, process='Done')

    elif func == 'adcactivate':
        await send_adc_response(
            ADC_server,
            message='ADC activation starts.',
            process='ING',
            status='success',
            log=False,
        )

        if adcadjust_task and not adcadjust_task.done():
            comment="Please cancel first the running task..."
            printing("Please cancel first the running task...")
            await send_adc_response(ADC_server, message=comment, process='Done', log=False)
        
        else:
            zdist = parsed_args['zdist']
            result = await adc_action.activate(zdist)
            await send_adc_response(ADC_server, result, process='Done')

    elif func == 'adcadjust':
        ra = parsed_args['RA']
        dec = parsed_args['DEC']
        await send_adc_response(
            ADC_server,
            message='ADC adjusting starts.',
            process='ING',
            status='success',
            log=False,
        )

        # Cancel any running task before starting a new one
        if adcadjust_task and not adcadjust_task.done():
            printing("Cancelling the running adcadjust task...")
            adcadjust_task.cancel()
            try:
                await adcadjust_task
            except asyncio.CancelledError:
                printing("Previous adcadjust task cancelled.")

        # Start a new adcadjust task
        adcadjust_task = asyncio.create_task(handle_adcadjust(ADC_server, adc_action, ra, dec))
        printing("New adcadjust task started.")

    elif func == 'adcstop':
        task_was_running, stop_result = await stop_adcadjust_task(adc_action, 'ADC stop')
        result = stop_result if stop_result is not None else await adc_action.stop(0)

        if task_was_running:
            message = "ADC stopped and ADC adjust task stopped."
        else:
            printing("No adcadjust task is currently running.")
            message = result.get("message", "ADC stopped.")

        await send_adc_response(
            ADC_server,
            result,
            message=message,
            process="Done",
            status=result.get("status", "success"),
        )

    elif func in {'adcrotate1', 'adcrotate2', 'adcctrotate','adccorotate'}:
        await send_adc_response(
            ADC_server,
            process='ING',
            message='ADC rotation starts.',
            status='success',
        )

        count = parsed_args['pcount']
        lens = parsed_args['lens']
        velocity = parsed_args['vel']
        result = await adc_action.move(lens, count, vel_set=velocity)
        await send_adc_response(ADC_server, result, process='Done')

    elif func == 'adchome':
        await send_adc_response(
            ADC_server,
            process='ING',
            message='ADC Homing starts.',
            status='success',
            log=False,
        )

        velocity = parsed_args['vel']
        result = await adc_action.homing(homing_vel=velocity)
        await send_adc_response(ADC_server, result, process='Done')

    elif func == 'adczero':
        await send_adc_response(
            ADC_server,
            process='ING',
            message='ADC Zeroing starts.',
            status='success',
            log=False,
        )

        velocity = parsed_args['vel']
        result = await adc_action.zeroing(zeroing_vel=velocity)
        await send_adc_response(ADC_server, result, process='Done')

    elif func == 'adcpark':
        await send_adc_response(
            ADC_server,
            process='ING',
            message='ADC Parking starts.',
            status='success',
            log=False,
        )
        
        result = await adc_action.parking()
        await send_adc_response(ADC_server, result, process='Done')

async def handle_adcadjust(ADC_server, adc_action, ra, dec):
    """Handle continuous ADC adjustment for a specified RA and DEC.

    Args:
        ADC_server (AMQclass): The ADC server instance.
        adc_action (AdcActions): Instance of ADC action handler.
        ra (float): Right Ascension in degrees.
        dec (float): Declination in degrees.

    Raises:
        asyncio.CancelledError: If the task is cancelled externally.
        Exception: For any unexpected errors during adjustment.
    """
    try:
        ini_zdist = calculate_zenith_distance(ra, dec)
        ini_count = adc_action.calculator.degree_to_count(adc_action.calculator.calc_from_za(ini_zdist))
        delcount = ini_count
        prev_count=ini_count

        while True:
            comment=f"ADC is now rotating by {delcount} counts."
            printing(comment)
            await send_adc_response(
                ADC_server,
                message=comment,
                process='ING',
                status='success',
                log=False,
            )

            result = await adc_action.move(0,delcount)
            motor_1, motor_2 = result['motor_1'], result['motor_2']
            comment1=result['message']  
            comment=f'{comment1} ADC lens rotated {motor_1}, {motor_2} counts successfully.'
            await send_adc_response(ADC_server, result, message=comment, process='ING')

            await asyncio.sleep(60)                       # Wait for exposure time
            zdist = calculate_zenith_distance(ra, dec)
            next_count = adc_action.calculator.degree_to_count(adc_action.calculator.calc_from_za(zdist))
            delcount = next_count - prev_count
            prev_count = next_count

    except asyncio.CancelledError:
        printing("handle_adcadjust task was cancelled.")
        raise
    except Exception as e:
        comment=f"Error in handle_adcadjust: {e}"
        printing(comment)
        await send_adc_response(ADC_server, message=comment, process='Done', log=False)
    else:
        printing("handle_adcadjust completed successfully.")


def calculate_zenith_distance(ra, dec):
    """Calculate the zenith distance for a given RA and DEC.

    Args:
        ra_obj (float): Right Ascension in degrees.
        dec_obj (float): Declination in degrees.

    Returns:
        float: The zenith distance in degrees.
    """
    ra_obj = Angle(ra, unit=u.hourangle).degree
    dec_obj = Angle(dec, unit=u.deg).degree
    object_coord = SkyCoord(ra=ra_obj, dec=dec_obj, unit=(u.deg,u.deg))
    current_time = Time.now()
    times = current_time + np.arange(0, 2) * u.minute
    altaz_frame = AltAz(obstime=times, location=AAO_LOCATION)
    altaz_coord = object_coord.transform_to(altaz_frame)
    zenith_distance = 90. - altaz_coord.alt.degree
    print(f'Current UT time: {current_time}')
    print(f'Mean Zenith distance for 1 min. : {zenith_distance} degree')
    return np.mean(zenith_distance)
