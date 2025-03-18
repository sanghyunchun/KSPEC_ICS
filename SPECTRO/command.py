import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
from astropy.io import fits
import numpy as  np 

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
        await get_obj(SPEC_server,float(exptime),int(numframe)) ### Position of all gfa camera exposure function

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
    msg=f'Exposure Start!!!'
    reply_data=mkmsg.specmsg()
    reply_data.update(message=msg,process='ING')
    rsp=json.dumps(reply_data)
    print('\033[32m'+'[SPEC]', msg+'\033[0m')
    await SPEC_server.send_message('ICS', rsp)

    result= await asyncio.gather(create_fits_image(exptime),remaining(SPEC_server,exptime))
    msg=f'Exposure finished'
    reply_data=mkmsg.specmsg()
    reply_data.update(message=msg,process='ING')
    rsp=json.dumps(reply_data)
    print('\033[32m'+'[SPEC]', msg+'\033[0m')
    await SPEC_server.send_message('ICS', rsp)

    print(result[0])
    reply_data=mkmsg.specmsg()
    reply_data.update(result[0])
    rsp=json.dumps(reply_data)
    print('\033[32m'+'[SPEC]', reply_data["message"]+'\033[0m')
    await SPEC_server.send_message('ICS', rsp)

def get_next_filename(prefix: str = "250314", extension: str = "fits"):
    index = 1
    while True:
        filename = f"./RAWDATA/{prefix}{index:04d}.{extension}"
        if not os.path.exists(filename):
            return filename
        index += 1

async def create_fits_image(exptime,shape: tuple = (100, 100), data_type=np.float32):
    data = np.random.random(shape).astype(data_type)
    hdu = fits.PrimaryHDU(data)
    filename = get_next_filename()
    hdul = fits.HDUList([hdu])
    hdul.writeto(filename, overwrite=True)
    await asyncio.sleep(exptime)
    msg=f'FITS file {filename} is created.'
    response = {"status": "success", "message": msg, "file": filename, "process": 'Done'}
    return response

async def remaining(SPEC_server, exptime):
    remaining_time = exptime
    while remaining_time > 0:
        await asyncio.sleep(min(10, remaining_time))  # 1분 단위로 대기
        remaining_time -= 10
        msg = f'Remaining exposure time: {remaining_time} seconds.'
        print('\033[32m' + '[SPEC]', msg + '\033[0m')
        reply_data=mkmsg.specmsg()
        reply_data.update(message=msg,process='ING')
        rsp=json.dumps(reply_data)
        await SPEC_server.send_message('ICS', rsp)

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
