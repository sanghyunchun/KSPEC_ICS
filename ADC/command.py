import asyncio
import json
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u
import numpy as np
from .kspec_adc_controller.src.adc_calc_angle import ADCCalc
from .kspec_adc_controller.src.adc_logger import AdcLogger

"""Command module for handling ADC-related functionalities.

This module provides functions to execute commands related to the ADC device, such as initialization,
connection, adjustment, and various operational controls. It includes utilities for printing, message
handling, and managing asynchronous tasks.
"""

# Global task tracker
adcadjust_task = None

def printing(message):
    """Utility function for consistent printingging.

    Args:
        message (str): The message to be printingged.
    """
    print(f"\033[32m[ADC] {message}\033[0m")

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
    dict_data = json.loads(cmd)
    func = dict_data['func']

    printing(f"{func}")

    if func == 'adcinit':
        comment = 'ADC initialized.'
        reply_data = mkmsg.adcmsg()
        reply_data.update(message=comment, process='Done')
        rsp = json.dumps(reply_data)
        printing(comment)
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcconnect':
        reply_data = mkmsg.adcmsg()
        result = adc_action.connect()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        printing(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcdisconnect':
        reply_data = mkmsg.adcmsg()
        result = adc_action.disconnect()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        printing(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcpoweroff':
        reply_data = mkmsg.adcmsg()
        result = adc_action.power_off()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        printing(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcstatus':
        reply_data = mkmsg.adcmsg()
        result = adc_action.status()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        printing(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcactivate':
        if adcadjust_task and not adcadjust_task.done():
            comment="Please cancel first the running task..."
            printing("Please cancel first the running task...")
            reply_data = mkmsg.adcmsg()
            reply_data.update(message=comment, process='Done')
            rsp = json.dumps(reply_data)
            await ADC_server.send_message('ICS', rsp)
        
        else:
            zdist = float(dict_data['zdist'])
            result = await adc_action.activate(zdist)
            reply_data = mkmsg.adcmsg()
            reply_data.update(result)
            reply_data.update(process='Done')
            rsp = json.dumps(reply_data)
            printing(reply_data['message'])
            await ADC_server.send_message('ICS', rsp)

    elif func == 'adcadjust':
        ra = float(dict_data['RA'])
        dec = float(dict_data['DEC'])

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
        reply_data = mkmsg.adcmsg()
        result = await adc_action.stop(0)
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        printing(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

        # Cancel the adcadjust task if it's running
        if adcadjust_task and not adcadjust_task.done():
            printing("Stopping adcadjust task...")
            adcadjust_task.cancel()
            try:
                await adcadjust_task
            except asyncio.CancelledError:
                printing("adcadjust task stopped.")
        else:
            printing("No adcadjust task is currently running.")

    elif func in {'adcrotate1', 'adcrotate2', 'adcrotateop','adcrotatesame'}:
        count = int(dict_data['pcount'])
        lens = dict_data['lens']
        result = await adc_action.move(lens, count)
        reply_data = mkmsg.adcmsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        printing(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adchome':
        result = await adc_action.homing()
        reply_data = mkmsg.adcmsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        printing(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adczero':
        result = await adc_action.zeroing()
        reply_data = mkmsg.adcmsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        printing(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcpark':
        result = await adc_action.parking()
        reply_data = mkmsg.adcmsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        printing(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

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
        logger = AdcLogger(__file__)
        print('ssss')
        calculator = ADCCalc(logger)
        print('tttt')
        ini_count = calculator.degree_to_count(calculator.calc_from_za(ini_zdist))
        delcount = ini_count
        prev_count=ini_count

        while True:
            comment=f"ADC is now rotating by {delcount} counts."
            printing(comment)
            reply_data=mkmsg.adcmsg()
            reply_data.update(message=comment)
            rsp=json.dumps(reply_data)
            await ADC_server.send_message('ICS',rsp)

            result = await adc_action.move(0,delcount)
            motor_1, motor_2 = result['motor_1'], result['motor_2']
            comment1=result['message']  
            comment=f'{comment1} ADC lens rotated {motor_1}, {motor_2} counts successfully.'
            reply_data=mkmsg.adcmsg()
            reply_data.update(result)
            reply_data.update(message=comment,process='In process')

            rsp=json.dumps(reply_data)
            print('\033[32m'+'[ADC]', comment+'\033[0m')
            await ADC_server.send_message('ICS',rsp)

            await asyncio.sleep(60)                       # Wait for exposure time
            zdist = calculate_zenith_distance(ra, dec)
            next_count = calculator.degree_to_count(calculator.calc_from_za(zdist))
            delcount = next_count - prev_count
            prev_count = next_count

    except asyncio.CancelledError:
        printing("handle_adcadjust task was cancelled.")
        raise
    except Exception as e:
        comment=f"Error in handle_adcadjust: {e}"
        printing(comment)
        reply_data=mkmsg.adcmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await ADC_server.send_message('ICS',rsp)
    else:
        printing("handle_adcadjust completed successfully.")


def calculate_zenith_distance(ra_obj, dec_obj):
    """Calculate the zenith distance for a given RA and DEC.

    Args:
        ra_obj (float): Right Ascension in degrees.
        dec_obj (float): Declination in degrees.

    Returns:
        float: The zenith distance in degrees.
    """
    location = EarthLocation(lat=-31.27118, lon=149.06256, height=1165*u.m)  # AAO coordinates
    object_coord = SkyCoord(ra=ra_obj * u.deg, dec=dec_obj * u.deg)
    current_time = Time.now()
    times = current_time + np.arange(0, 2) * u.minute
    altaz_frame = AltAz(obstime=times, location=location)
    zenith_distance = 90. - object_coord.transform_to(altaz_frame).alt.degree
    ele=object_coord.transform_to(altaz_frame).alt.degree
    print(f'Current UT time: {current_time}')
    print(f'Mean Zenith distance for 1 min. : {zenith_distance} degree')
    return np.mean(zenith_distance)

