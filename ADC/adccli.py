import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json



def adc_init():
    "ADC initializing"
    comment="Start ADC initializing"
#    dict_data={'inst': 'ADC', 'func': 'adcinit','comments':comment}
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcinit',message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_adjust(zdistance):
    "ADC lens adjusti with desired angle"
    comment='ADC is adjusting'
#    dict_data={'inst': 'ADC', 'func': 'adcadjust','zdist': zdistance,'comments':comments}
    cmd_data=mkmsg.adcmsg()
    cmd_data.update(func='adcadjust',zdist=zdistance,message=comment)
    adcmsg=json.dumps(cmd_data)
    return adcmsg

def adc_status():
    "Show ADC current status"
    comment='ADC status'
#    dict_data={'inst': 'ADC', 'func': 'adcstatus','comments':comments}
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
