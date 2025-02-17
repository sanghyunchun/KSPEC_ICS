import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json
from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u
import numpy as np

def adc_init():
    """
    Initialize the ADC.

    Returns:
        str: JSON string containing the ADC initialization command.
    """
    comment = "Start ADC initializing"
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcinit', message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_connect():
    """
    Connect the ADC instrument.

    Returns:
        str: JSON string containing the ADC connection command.
    """
    comment = "Connect ADC instrument"
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcconnect', message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_disconnect():
    """
    Disconnect the ADC instrument.

    Returns:
        str: JSON string containing the ADC disconnection command.
    """
    comment = "Disconnect ADC instrument"
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcdisconnect', message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_home():
    """
    Move the ADC lens to the home position.

    Returns:
        str: JSON string containing the ADC homing command.
    """
    comment = "Homing ADC lens"
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adchome', message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_zero():
    """
    Rotate the ADC lens to the zero position.

    Returns:
        str: JSON string containing the ADC zeroing command.
    """
    comment = "Rotate ADC lens to zero position"
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adczero', message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_rotate1(count):
    """
    Rotate the ADC lens 2 by a specified count.

    Args:
        count (int): Number of steps to rotate lens 2.

    Returns:
        str: JSON string containing the ADC lens 2 rotation command.
    """
    comment = f'Rotate ADC lens 2 by {count} counts.'
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcrotate1', lens=1, pcount=count, message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_rotate2(count):
    """
    Rotate the ADC lens 1 by a specified count.

    Args:
        count (int): Number of steps to rotate lens 1.

    Returns:
        str: JSON string containing the ADC lens 1 rotation command.
    """
    comment = f'Rotate ADC lens 1 by {count} counts.'
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcrotate2', lens=2, pcount=count, message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_rotateop(count):
    """
    Rotate both ADC lens 1 and 2 by a specified count in opposite direction.
    (-) count : ADC 1 counter-clockwise. ADC 2 clockwise.
    (+) count : ADC 1clockwise. ADC 2 counter-clockwise.

    Args:
        count (int) : Number of counts to rotate the ADC lens

    Returns:
        str: JSON string containing the ADC lens 1 and 2 rotation command.
    """
    comment=f'Rotate ADC lens 1 and 2 by {count} counts.'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcrotateop',lens=0,pcount=count,message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_rotatesame(count):
    """
    Rotate both ADC lens 1 and 2 by a specified count in the same direction.
    (-) count : ADC 1 counter-clockwise. ADC 2 counter-clockwise.
    (+) count : ADC 1 clockwise. ADC 2 clockwise.

    Args:
        count (int) : Number of counts to rotate the ADC lens

    Returns:
        str: JSON string containing the ADC lens 1 and 2 rotation command.
    """
    comment=f'Rotate ADC lens 1 and 2 by {count} counts.'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcrotatesame',lens=-1,pcount=count,message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg


def adc_adjust(ra, dec):
    """
    Adjust the ADC lens based on the desired RA and DEC angles.

    Args:
        ra (float): Right Ascension angle.
        dec (float): Declination angle.

    Returns:
        str: JSON string containing the ADC adjustment command.
    """
    comment = 'ADC adjusting'
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcadjust', RA=ra, DEC=dec, message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_activate(zdist):
    """
    Activate the ADC with a specified zenith distance.

    Args:
        zdist (float): Zenith distance.

    Returns:
        str: JSON string containing the ADC activation command.
    """
    comment = 'ADC activate'
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcactivate', zdist=zdist, message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_status():
    """
    Retrieve the current status of the ADC.

    Returns:
        str: JSON string containing the ADC status command.
    """
    comment = 'ADC status'
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcstatus', message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_poweroff():
    """
    Power off the ADC.

    Returns:
        str: JSON string containing the ADC power-off command.
    """
    comment = 'ADC power off'
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcpoweroff', message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_stop():
    """
    Stop the ADC rotation.

    Returns:
        str: JSON string containing the ADC stop command.
    """
    comment = 'ADC rotating stop'
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcstop', message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

def adc_park():
    """
    Move the ADC to the parking position.

    Returns:
        str: JSON string containing the ADC parking command.
    """
    comment = 'Rotate ADC to parking position'
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func='adcpark', message=comment)
    adcmsg = json.dumps(cmd_data)
    return adcmsg

async def handle_adc(arg, ICS_client):
    cmd = arg.split(' ')

    # ADC commands
    if cmd[0] == 'adcactivate':
        adcmsg = adc_activate(cmd[1])
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcadjust':
        adcmsg = adc_adjust(cmd[1], cmd[2])
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcinit':
        adcmsg = adc_init()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcstatus':
        adcmsg = adc_status()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcpoweroff':
        adcmsg = adc_poweroff()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcconnect':
        adcmsg = adc_connect()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcdisconnect':
        adcmsg = adc_disconnect()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adchome':
        adcmsg = adc_home()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adczero':
        adcmsg = adc_zero()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcpark':
        adcmsg = adc_park()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcrotate1':                   # ADC2 rotate @ L4
        adcmsg = adc_rotate1(cmd[1])
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcrotate2':                   # ADC1 rotate @ L3
        adcmsg = adc_rotate2(cmd[1])
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcrotateop':
        adcmsg=adc_rotateop(cmd[1])
        await ICS_client.send_message("ADC",adcmsg)

    if cmd[0] == 'adcrotatesame':
        adcmsg=adc_rotatesame(cmd[1])
        await ICS_client.send_message("ADC",adcmsg)

    if cmd[0] == 'adcstop':
        adcmsg = adc_stop()
        await ICS_client.send_message("ADC", adcmsg)





