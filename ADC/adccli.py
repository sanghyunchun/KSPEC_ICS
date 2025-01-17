import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json
from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u
import numpy as np
#from .kspec_adc_controller.src.adc_calc_angle import ADCCalc

def adc_init():
    "ADC initializing"
    comment="Start ADC initializing"
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcinit',message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_connect():
    "ADC connection"
    comment="Connect ADC instrument"
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcconnect',message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_disconnect():
    "ADC disconnection"
    comment="Disconnect ADC instrument"
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcdisconnect',message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_home():
    "ADC Homing"
    comment="Homing ADC lens"
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adchome',message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_zero():
    "ADC zeroing"
    comment="Rotate ADC lens to zero position"
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adczero',message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_rotate1(count):
    "ADC lens 1 rotate"
    comment=f'ADC lens 1 rotate {count} counts.'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcrotate1',lens=1,pcount=count,message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_rotate2(count):
    "ADC lens 1 rotate"
    comment=f'ADC lens 2 rotate {count} counts.'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcrotate2',lens=2,pcount=count,message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_adjust(ra,dec):
    "ADC lens adjust with desired angle"
    comment='ADC is adjusting'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcadjust',RA=ra,DEC=dec,message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_activate(count):
    "ADC lens adjusti with desired angle"
    comment='ADC is adjusting'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcactivate',pcount=count,message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_status():
    "Show ADC current status"
    comment='ADC status'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcstatus',message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_poweroff():
    "Show ADC current status"
    comment='ADC disconnect and power off'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcpoweroff',message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_stop():
    "Stop ADC rotating"
    comment='ADC rotating stop'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcstop',message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

