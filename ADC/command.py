import os,sys
from Lib.AMQ import *
import json
import asyncio
import time
import Lib.mkmessage as mkmsg
from scipy import interpolate
import numpy as np
#from ADC.kspec_adc_controller.src.adc_actions import adc_actions

async def identify_excute(ADC_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

#    action=adc_action()

    if func == 'adcinit':
        comment='ADC initialized.'
#        reply_data={'inst': 'ADC', 'savedata': 'False','filename': 'None','message': message}
        reply_data=mkmsg.adcmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcpoweroff':
#        result=action.power_off()
        comment = 'ADC power off'   # For Simulation. Annotate when real observation
        reply_data=mkmsg.adcmsg()
#        reply_data.update(result)
        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcstatus':
#        result=action.status()
        reply_data=mkmsg.adcmsg()
#        reply_data.update(result)
        reply_data.update(process='Done')
        msg  = 'ADC connection is OK. ADC is ready'  # For Simulation. Annotate when real observation
        reply_data.update(message=msg)                # For Simulation. Annotate when real observation
#        comment=result['message']
        comment = 'ADC status was sent to ICS'  # For Simulation. Annotate when real observation
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcadjust':
        zdist=dict_data['zdist']       # For Simulation. Annotate when real observation
        angle1,angle2=calangle(zdist)   # For Simulation. Annotate when real observation
#        result=action.activate(angle1)  # Rotate lens function by calculated values
#        motor_1=result['motor_1']
#        motor_2=result['motor_2']
#        comment1=result['message']
        reply_data=mkmsg.adcmsg()
#        comment=f'{comment1} ADC lens rotate {motor_1}, {motor_2} counts successfully.'
        comment =f'ADC lens roate {angle1}, {angle2} successfully.'     # For Simulation. Annotate when real observation
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



