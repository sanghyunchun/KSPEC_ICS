import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json

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

def adc_rotate1(count):
    "ADC lens 1 rotate"
    comment=f'ADC lens 1 rotate {count} counts.'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcrotate1',lens1=count,message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_rotate2(count):
    "ADC lens 1 rotate"
    comment=f'ADC lens 1 rotate {count} counts.'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcrotate2',lens2=count,message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_adjust(zdistance):
    "ADC lens adjusti with desired angle"
    comment='ADC is adjusting'
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcadjust',zdist=zdistance,message=comment)
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
