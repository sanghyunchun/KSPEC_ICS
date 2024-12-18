import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random

async def identify_excute(SPEC_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'biasexp':
        numframe=dict_data['numframe']
        comment=bias_exp(numframe) ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'flatexp':
        exptime=dict_data['time']
        numframe=dict_data['numframe']
        comment=flat_exp(exptime,numframe) ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'arcexp':
        exptime=dict_data['time']
        numframe=dict_data['numframe']
        comment=arc_exp(exptime,numframe) ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'specilluon':
        comment=specilluon() ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'specilluoff':
        comment=specilluoff()                      ### Position of back illumination light off function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'specexp':
        exptime=dict_data['time']
        comment=specexp(float(exptime)) ### Position of all gfa camera exposure function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'specstatus':
        comment=specstatus()
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

# Below functions are for simulation. When connect the instruments, please annoate.

def specilluon():
    time.sleep(3)
    msg='Back illumination light on.'
    return msg

def specilluoff():
    time.sleep(3)
    msg='Back illumination light off.'
    return msg

def specexp(exptime):
    time.sleep(exptime)
    msg='Exposure finished'
    return msg

def specstatus():
    msg='Spectrograph Status is below. Spectrograph is ready.'
    return msg

def bias_exp(nframe):
    msg=f'Bias exposure finished. {nframe} Bias Frames are obtained.'
    return msg

def flat_exp(time,nframe):
    msg=f'Flat exposure {time} seconds finished. {nframe} Flat Frames are obtained.' 
    return msg

def arc_exp(time,nframe):
    msg=f'Arc exposure {time} finished. {nframe} Arc Frames are obtained.'
    return msg
