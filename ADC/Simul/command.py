import asyncio
import json
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u
import numpy as np
from .kspec_adc_controller.src.adc_calc_angle import ADCCalc

# Global task tracker
adcadjust_task = None

def log(message):
    """Utility function for consistent logging."""
    print(f"\033[32m[ADC] {message}\033[0m")

async def identify_execute(ADC_server, adc_action, cmd):
    global adcadjust_task
    dict_data = json.loads(cmd)
    func = dict_data['func']

    log(f"Received command: {func}")

    if func == 'adcinit':
        comment = 'ADC initialized.'
        reply_data = mkmsg.adcmsg()
        reply_data.update(message=comment, process='Done')
        rsp = json.dumps(reply_data)
        log(comment)
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcconnect':
        reply_data = mkmsg.adcmsg()
        result = adc_action.connect()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        log(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcdisconnect':
        reply_data = mkmsg.adcmsg()
        result = adc_action.disconnect()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        log(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcpoweroff':
        reply_data = mkmsg.adcmsg()
        result = adc_action.power_off()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        log(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcstatus':
        reply_data = mkmsg.adcmsg()
        result = adc_action.status()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        log(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcactivate':
#        zdist = float(dict_data['zdist'])
        ra = float(dict_data['RA'])
        dec = float(dict_data['DEC'])
        result = await adc_action.move(0,4000)
        motor_1, motor_2 = result['motor_1'], result['motor_2']
        comment1=result['message']
        comment = f"{comment1} Lens rotated {motor_1}, {motor_2} counts successfully."
        reply_data = mkmsg.adcmsg()
        reply_data.update(message=comment, process='Done')
        rsp = json.dumps(reply_data)
        log(comment)
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcadjust':
        ra = float(dict_data['RA'])
        dec = float(dict_data['DEC'])

        # Cancel any running task before starting a new one
        if adcadjust_task and not adcadjust_task.done():
            log("Cancelling the running adcadjust task...")
            adcadjust_task.cancel()
            try:
                await adcadjust_task
            except asyncio.CancelledError:
                log("Previous adcadjust task cancelled.")

        # Start a new adcadjust task
        adcadjust_task = asyncio.create_task(handle_adcadjust2(ADC_server, adc_action, ra, dec))
        log("New adcadjust task started.")

    elif func == 'adcstop':
        reply_data = mkmsg.adcmsg()
        result = await adc_action.stop()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        log(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

        # Cancel the adcadjust task if it's running
        if adcadjust_task and not adcadjust_task.done():
            log("Stopping adcadjust task...")
            adcadjust_task.cancel()
            try:
                await adcadjust_task
            except asyncio.CancelledError:
                log("adcadjust task stopped.")
        else:
            log("No adcadjust task is currently running.")

    elif func in {'adcrotate1', 'adcrotate2'}:
        count = int(dict_data['pcount'])
        lens = dict_data['lens']
        result = await adc_action.move(lens, count)
        reply_data = mkmsg.adcmsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        log(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adchome':
        result = await adc_action.homing()
        reply_data = mkmsg.adcmsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        log(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adczero':
        result = await adc_action.zeroing()
        reply_data = mkmsg.adcmsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        log(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

    elif func == 'adcpark':
        result = await adc_action.parking()
        reply_data = mkmsg.adcmsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp = json.dumps(reply_data)
        log(reply_data['message'])
        await ADC_server.send_message('ICS', rsp)

async def handle_adcadjust(ADC_server, adc_action, ra, dec):
    try:
        ini_zdist = calculate_zenith_distance(ra, dec)
        calculator = ADCCalc()
        ini_count = calculator.degree_to_count(calculator.calc_from_za(ini_zdist))
        delcount = ini_count
        obsnum = 3

        for i in range(obsnum):
            comment=f"Rotation step {i+1}/{obsnum}. ADC is now rotating by {delcount} counts."
            log(comment)
            reply_data=mkmsg.adcmsg()
            reply_data.update(message=comment)
            rsp=json.dumps(reply_data)
            await ADC_server.send_message('ICS',rsp)

            result = await adc_action.move(0,delcount)
            motor_1, motor_2 = result['motor_1'], result['motor_2']
            comment1=result['message']  
            comment=f'{comment1} ADC lens rotated {motor_1}, {motor_2} counts successfully.'
            log(f"ADC lens rotated: {motor_1}, {motor_2} counts successfully.")
            reply_data=mkmsg.adcmsg()
            reply_data.update(result)
            if i == obsnum-1:
                reply_data.update(message=comment,process='Done')
            else:
                reply_data.update(message=comment,process='In process')

            rsp=json.dumps(reply_data)
            print('\033[32m'+'[ADC]', comment+'\033[0m')
            await ADC_server.send_message('ICS',rsp)

            await asyncio.sleep(30)                       # Wait for exposure time
            zdist = calculate_zenith_distance(ra, dec)
            next_count = calculator.degree_to_count(calculator.calc_from_za(zdist))
            delcount = next_count - ini_count

    except asyncio.CancelledError:
        log("handle_adcadjust task was cancelled.")
        raise
    except Exception as e:
        log(f"Error in handle_adcadjust: {e}")
    else:
        log("handle_adcadjust completed successfully.")


async def handle_adcadjust2(ADC_server, adc_action, ra, dec):
    try:
        ini_zdist = calculate_zenith_distance(ra, dec)
        calculator = ADCCalc()
        ini_count = calculator.degree_to_count(calculator.calc_from_za(ini_zdist))
        delcount = ini_count
        obsnum = 3

        while True:
            comment=f"ADC is now rotating by {delcount} counts."
            log(comment)
            reply_data=mkmsg.adcmsg()
            reply_data.update(message=comment)
            rsp=json.dumps(reply_data)
            await ADC_server.send_message('ICS',rsp)

            result = await adc_action.move(0,delcount)
            motor_1, motor_2 = result['motor_1'], result['motor_2']
            comment1=result['message']  
            comment=f'{comment1} ADC lens rotated {motor_1}, {motor_2} counts successfully.'
#            log(f"ADC lens rotated: {motor_1}, {motor_2} counts successfully.")
            reply_data=mkmsg.adcmsg()
            reply_data.update(result)
            reply_data.update(message=comment,process='In process')

            rsp=json.dumps(reply_data)
            print('\033[32m'+'[ADC]', comment+'\033[0m')
            await ADC_server.send_message('ICS',rsp)

            await asyncio.sleep(60)                       # Wait for exposure time
            zdist = calculate_zenith_distance(ra, dec)
            next_count = calculator.degree_to_count(calculator.calc_from_za(zdist))
            delcount = next_count - ini_count

    except asyncio.CancelledError:
        log("handle_adcadjust task was cancelled.")
        raise
    except Exception as e:
        log(f"Error in handle_adcadjust: {e}")
    else:
        log("handle_adcadjust completed successfully.")


def calculate_zenith_distance(ra_obj, dec_obj):
    location = EarthLocation(lat=-31.27118, lon=149.06256)  # AAO coordinates
    object_coord = SkyCoord(ra=ra_obj * u.deg, dec=dec_obj * u.deg)
    current_time = Time.now()
    times = current_time + np.arange(0, 6) * u.minute
    altaz_frame = AltAz(obstime=times, location=location)
    zenith_distance = 90. - object_coord.transform_to(altaz_frame).alt.degree
    return np.mean(zenith_distance)

