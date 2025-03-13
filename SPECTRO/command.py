import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random

async def identify_execute(SPEC_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'getbias':
        numframe=dict_data['numframe']
        comment=get_bias(numframe) ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'getflat':
        exptime=dict_data['time']
        numframe=dict_data['numframe']
        comment=get_flat(exptime,numframe) ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'getarc':
        exptime=dict_data['time']
        numframe=dict_data['numframe']
        comment=get_arc(exptime,numframe) ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'illuon':
        comment=illu_on() ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'illuoff':
        comment=illu_off()                      ### Position of back illumination light off function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'getobj':
        exptime=dict_data['time']
        numframe=dict_data['numframe']
        comment = await get_obj(SPEC_server,float(exptime),int(numframe)) ### Position of all gfa camera exposure function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'specstatus':
        comment=spec_status()
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

# Below functions are for simulation. When connect the instruments, please annoate.

def illu_on():
    time.sleep(3)
    msg='Back illumination light on.'
    return msg

def illu_off():
    time.sleep(3)
    msg='Back illumination light off.'
    return msg


async def get_obj(SPEC_server, exptime, nframe):
    msg = f'KSPEC starts {nframe} exposures with {exptime} seconds'
    print('\033[32m' + '[SPEC]', msg + '\033[0m')
    reply_data=mkmsg.specmsg()
    reply_data.update(message=msg,process='ING')
    rsp=json.dumps(reply_data)
    await SPEC_server.send_message('ICS', rsp)

    for i in range(nframe):
        remaining_time = exptime
        msg = f'KSPEC runs {i+1}/{nframe} exposure with {exptime} seconds'
        print('\033[32m' + '[SPEC]', msg + '\033[0m')
        reply_data=mkmsg.specmsg()
        reply_data.update(message=msg,process='ING')
        rsp=json.dumps(reply_data)
        await SPEC_server.send_message('ICS', rsp)
        while remaining_time > 0:
            await asyncio.sleep(min(60, remaining_time))  # 1분 단위로 대기
            remaining_time -= 60
            msg = f'{i+1}/{nframe} exposure - Remaining exposure time: {remaining_time} seconds.'
            print('\033[32m' + '[SPEC]', msg + '\033[0m')
            reply_data=mkmsg.specmsg()
            reply_data.update(message=msg,process='ING')
            rsp=json.dumps(reply_data)
            await SPEC_server.send_message('ICS', rsp)
        msg=f'{i+1}/{nframe} exposure finished'
        reply_data=mkmsg.specmsg()
        reply_data.update(message=msg,process='ING')
        rsp=json.dumps(reply_data)
        await SPEC_server.send_message('ICS', rsp)

    msg = 'All Exposures finished'
    return msg


def spec_status():
    msg='Spectrograph Status is below. Spectrograph is ready.'
    return msg

def get_bias(nframe):
    msg=f'Bias exposure finished. {nframe} Bias Frames are obtained.'
    return msg

def get_flat(exptime,nframe):
    msg=f'Flat exposure {exptime} seconds finished. {nframe} Flat Frames are obtained.' 
    time.sleep(exptime)
    return msg

def get_arc(exptime,nframe):
    msg=f'Arc exposure {exptime} finished. {nframe} Arc Frames are obtained.'
    time.sleep(exptime)
    return msg
