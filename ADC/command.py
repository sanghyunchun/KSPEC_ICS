import os,sys
from Lib.AMQ import *
import json
import asyncio
import time
import Lib.mkmessage as mkmsg
from scipy import interpolate
import numpy as np

async def identify_excute(ADC_server,adc_action,cmd):    # For real observation
    dict_data=json.loads(cmd)
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

    if func == 'adcadjust':
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

