import os,sys
from Lib.AMQ import *
import json
import asyncio
import time
import Lib.mkmessage as mkmsg
from scipy import interpolate
import numpy as np
from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u
from .kspec_adc_controller.src.adc_calc_angle import ADCCalc


adcadjust_task=None
async def identify_excute(ADC_server,adc_action,cmd):    # For real observation
    dict_data=json.loads(cmd)
    global adcadjust_task
    func=dict_data['func']

    if func == 'adcinit':
        comment='ADC initialized.'
        reply_data=mkmsg.adcmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcconnect':
        reply_data=mkmsg.adcmsg()
        result=adc_action.connect()  # For real observation
        reply_data.update(result)      # For real observation
        comment=reply_data['message']  # For real observation

        reply_data.update(process='Done')   
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcdisconnect':
        reply_data=mkmsg.adcmsg()
        result=adc_action.disconnect()  # For real observation
        reply_data.update(result)      # For real observation
        comment=reply_data['message']  # For real observation

        reply_data.update(process='Done')   
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcpoweroff':
        reply_data=mkmsg.adcmsg()
        result=adc_action.power_off()  # For real observation
        reply_data.update(result)      # For real observation
        comment=reply_data['message']  # For real observation

        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcstatus':
        reply_data=mkmsg.adcmsg()
        result=adc_action.status()                  # For real observation
        reply_data.update(result)                   # For real observation
        comment=result['message']                   # For real observation

        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcactivate':
        reply_data=mkmsg.adcmsg()
        zdist=float(dict_data['zdist'])
        result=await adc_action.activate(zdist)  # For real observation. Rotate lens function by calculated values
        motor_1=result['motor_1']           # For real observation.
        motor_2=result['motor_2']           # For real observation.
        comment1=result['message']          # For real observation.
        comment=f'{comment1}. ADC lens rotate {motor_1}, {motor_2} counts successfully.'     # For real observation.

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcrotate1':
        reply_data=mkmsg.adcmsg()
        count=int(dict_data['pcount'])
        lens=dict_data['lens']                       #  For real observation.
        result=await adc_action.move(lens,count)           #  For real observation.
        reply_data.update(result)                    # For real observation
        comment=reply_data['message']                # For real observation

        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcrotate2':
        reply_data=mkmsg.adcmsg()
        count=int(dict_data['pcount'])
        lens=dict_data['lens']                       #  For real observation.
        result=await adc_action.move(lens,count)           #  For real observation.
        reply_data.update(result)                    # For real observation
        comment=reply_data['message']                # For real observation

        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adchome':
        reply_data=mkmsg.adcmsg()
        result=await adc_action.homing()           #  For real observation.
        reply_data.update(result)                    # For real observation
        comment=reply_data['message']                # For real observation

        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adczero':
        reply_data=mkmsg.adcmsg()
        result=await adc_action.zeroing()           #  For real observation.
        reply_data.update(result)                    # For real observation
        comment=reply_data['message']                # For real observation

        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)


    if func == 'adcadjust':
        ra=float(dict_data['RA'])
        dec=float(dict_data['DEC'])

        if adcadjust_task and not adcadjust_task.done():
            print("Cancelling the previous task...")
            adcadjust_task.cancel()
            try:
                await adcadjust_task
            except asyncio.CancelledError:
                print("Previous task cancelled")

        adcadjust_task=asyncio.create_task(handle_adcadjust(ADC_server,adc_action,ra,dec))


    if func == 'adcstop':
        reply_data=mkmsg.adcmsg()
        result=await adc_action.stop()           #  For real observation.
        reply_data.update(result)                    # For real observation
        comment=reply_data['message']                # For real observation

        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

        if adcadjust_task and not adcadjust_task.done():
            print("Stopping current task...")
            adcadjust_task.cancel()
            try:
                await adcadjust_task
            except asyncio.CancelledError:
                print("Current task stopped.")
        else:
            print("No task is currently running.")


async def handle_adcadjust(ADC_server,adc_action,ra,dec):
        ini_zdist=calculate_zenith_distance(ra,dec)
        calculator = ADCCalc()
        ang=calculator.calc_from_za(ini_zdist)
        ini_count=calculator.degree_to_count(ang)

        delcount=ini_count
        obsnum=3
        for i in range(obsnum):
            print(i)
            comment = f'ADC is now rotating. Rotaing count is {delcount}'
            print('\033[32m'+'[ADC]', comment+'\033[0m')
            reply_data=mkmsg.adcmsg()
            reply_data.update(message=comment)
            rsp=json.dumps(reply_data)
            await ADC_server.send_message('ICS',rsp)

            result = await adc_action.activate(delcount)
            motor_1=result['motor_1']           # For real observation.
            motor_2=result['motor_2']           # For real observation.
            comment1=result['message']          # For real observation.
            comment=f'{comment1} ADC lens rotated {motor_1}, {motor_2} counts successfully.'     # For real observation.
            reply_data=mkmsg.adcmsg()
            reply_data.update(result)
            if i == obsnum-1:
                reply_data.update(message=comment,process='Done')
            else:
                reply_data.update(message=comment,process='In process')

            rsp=json.dumps(reply_data)
            print('\033[32m'+'[ADC]', comment+'\033[0m')
            await ADC_server.send_message('ICS',rsp)
            await asyncio.sleep(30)

            zdist=calculate_zenith_distance(ra,dec)
            ang=calculator.calc_from_za(zdist)
            next_count=calculator.degree_to_count(ang)

            delcount = next_count - ini_count


def calculate_zenith_distance(ra_obj,dec_obj):

    longitude = 149.06256  # AAO longtitude degrees
    latitude = -31.27118   # AAO latitude degrees
    location = EarthLocation(lat=latitude, lon=longitude)

    object_coord = SkyCoord(ra=ra_obj * u.deg, dec=dec_obj * u.deg)

    current_time = Time.now()
    times = current_time + np.arange(0, 6) * u.minute

        # AltAz frame define
    altaz_frame = AltAz(obstime=times, location=location)

        # Calculate Alt. Az of stars
    object_altaz = object_coord.transform_to(altaz_frame)

        # Calculate Zenith distance 
    zenith_distance = 90. - object_altaz.alt.degree

    return np.mean(zenith_distance)




