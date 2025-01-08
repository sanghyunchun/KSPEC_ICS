import os,sys
from Lib.AMQ import *
import json
import asyncio
import time
import Lib.mkmessage as mkmsg
from scipy import interpolate
import numpy as np

#async def identify_excute(ADC_server,adc_action,cmd):    # For real observation
async def identify_excute(ADC_server,cmd):               # For Simulation. Annotate when real observation
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
#        result=adc_action.power_off()  # For real observation
#        reply_data.update(result)      # For real observation
#        comment=reply_data['message']  # For real observation

        comment = 'ADC connected'                         # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')   
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcpoweroff':
        reply_data=mkmsg.adcmsg()
#        result=adc_action.power_off()  # For real observation
#        reply_data.update(result)      # For real observation
#        comment=reply_data['message']  # For real observation

        comment = 'ADC power off'                         # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcstatus':
        reply_data=mkmsg.adcmsg()
#        result=adc_action.status()                  # For real observation
#        reply_data.update(result)                   # For real observation
#        comment=result['message']                   # For real observation

        comment  = 'ADC connection is OK. ADC is ready'   # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcadjust':
        reply_data=mkmsg.adcmsg()
        zdist=float(dict_data['zdist'])
#        result=adc_action.activate(zdist)  # For real observation. Rotate lens function by calculated values
#        motor_1=result['motor_1']           # For real observation.
#        motor_2=result['motor_2']           # For real observation.
#        comment1=result['message']          # For real observation.
#        comment=f'{comment1}. ADC lens rotate {motor_1}, {motor_2} counts successfully.'     # For real observation.

        angle1,angle2=calangle(zdist)                                   # For Simulation. Annotate when real observation
        comment =f'ADC lens roate {angle1}, {angle2} successfully.'     # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcrotate1':
        reply_data=mkmsg.adcmsg()
        count=float(dict_data['pcount'])
#        lens=dict_data['lens']                       #  For real observation.
#        result=adc_action.move(lens,count)           #  For real observation.
#        reply_data.update(result)                    # For real observation
#        comment=reply_data['message']                # For real observation

        comment=rotate1(count)                                 # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcrotate2':
        reply_data=mkmsg.adcmsg()
        count=float(dict_data['pcount'])
#        lens=dict_data['lens']                       #  For real observation.
#        result=adc_action.move(lens,count)           #  For real observation.
#        reply_data.update(result)                    # For real observation
#        comment=reply_data['message']                # For real observation

        comment=rotate2(count)                                 # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)


# Below functions are for simulation. When connect the instruments, please annoate.
def calangle(inputvalue):
    zdist,angle1,angle2=np.loadtxt('./ADC/LUT.txt',dtype=float,unpack=True,usecols=(0,1,2),skiprows=1)
    f_spline1=interpolate.interp1d(zdist,angle1,kind='quadratic')
    f_spline2=interpolate.interp1d(zdist,angle2,kind='quadratic')
    ang1=f_spline1(inputvalue)
    ang2=f_spline2(inputvalue)
    return ang1,ang2

def rotate1(inputvalue):
    comment=f'Lens 1 rotates {inputvalue}' 
    return comment

def rotate2(inputvalue):
    comment=f'Lens 2 rotates {inputvalue}' 
    return comment

