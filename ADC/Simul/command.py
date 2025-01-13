import os,sys
from Lib.AMQ import *
import json
import asyncio
import time
import Lib.mkmessage as mkmsg
from scipy import interpolate
import numpy as np

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
        comment = 'ADC connected'                         # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcdisconnect':
        reply_data=mkmsg.adcmsg()
        comment = 'ADC disconnected'                         # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcpoweroff':
        reply_data=mkmsg.adcmsg()
        comment = 'ADC power off'                         # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcstatus':
        reply_data=mkmsg.adcmsg()
        comment  = 'ADC connection is OK. ADC is ready'   # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcadjust':
        reply_data=mkmsg.adcmsg()
        zdist=float(dict_data['zdist'])
        angle1,angle2=calangle(zdist)                                   # For Simulation. Annotate when real observation
        comment =f'ADC lens roate {angle1}, {angle2} successfully.'     # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcrotate1':
        reply_data=mkmsg.adcmsg()
        count=int(dict_data['pcount'])
        comment=rotate1(count)                                 # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adcrotate2':
        reply_data=mkmsg.adcmsg()
        count=int(dict_data['pcount'])
        comment=rotate2(count)                                 # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adchome':
        reply_data=mkmsg.adcmsg()
        comment=homing()                                 # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)

    if func == 'adczero':
        reply_data=mkmsg.adcmsg()
        comment=zeroing()                                 # For Simulation. Annotate when real observation

        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ADC]', comment+'\033[0m')
        await ADC_server.send_message('ICS',rsp)


# Below functions are for simulation. When connect the instruments, please annoate.
def calangle(inputvalue):
    zdist,angle1,angle2=np.loadtxt('./ADC/Simul/Lookup_test.txt',dtype=float,unpack=True,usecols=(0,1,2),skiprows=1)
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

def homing():
    comment=f'Homing finished' 
    return comment

def zeroing():
    comment=f'Zeroing finished' 
    return comment

