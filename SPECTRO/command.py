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

    if func == 'specinitial':
        with open('./Lib/KSPEC.ini','r') as fs:
            kspecinfo = json.load(fs)

        specinfopath = kspecinfo['SPEC']['specinfopath']

        with open(specinfopath+'specinfo.json','w') as f:
            json.dump(dict_data,f)

        comment = 'Initializing of Spectrograph is finished.'
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done',status='success')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'getbias':
        numframe=dict_data['numframe']
        comment=get_bias(numframe) ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done',status='success')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'getflat':
        reply_data=mkmsg.specmsg()
        comment = 'Flat exposure starts.'
        reply_data.update(message=comment,process='ING',status='success')
        rsp=json.dumps(reply_data)
        await SPEC_server.send_message('ICS',rsp)
        exptime=dict_data['time']
        numframe=dict_data['numframe']
        comment=get_flat(exptime,numframe) ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done',status='success')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'getarc':
        reply_data=mkmsg.specmsg()
        comment = 'Arc exposure starts.'
        reply_data.update(message = comment, process='ING',status='success')
        rsp=json.dumps(reply_data)
        await SPEC_server.send_message('ICS',rsp)
        exptime=dict_data['time']
        numframe=dict_data['numframe']
        comment=get_arc(exptime,numframe) ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done',status='success')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'illuon':
        comment=illu_on() ### Position of back illumination light on function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done',status='success')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'illuoff':
        comment=illu_off()                      ### Position of back illumination light off function
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done',status='success')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[SPEC]', comment+'\033[0m')
        await SPEC_server.send_message('ICS',rsp)

    if func == 'getobj':
        exptime=dict_data['time']
        numframe=dict_data['numframe']
        await get_obj(SPEC_server,float(exptime),int(numframe))

    if func == 'specstatus':
        comment=spec_status()
        reply_data=mkmsg.specmsg()
        reply_data.update(message=comment,process='Done',status='success')
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
    reply_data.update(message=msg,process='ING',status='success')
    rsp=json.dumps(reply_data)
    print('\033[32m'+'[SPEC]', msg+'\033[0m')
    await SPEC_server.send_message('ICS', rsp)

    result= await asyncio.gather(create_fits_image(exptime),remaining(SPEC_server,exptime))
    msg=f'Exposure finished. Creating the image now.'
    reply_data=mkmsg.specmsg()
    reply_data.update(message=msg,process='ING',status='success')
    rsp=json.dumps(reply_data)
    print('\033[32m'+'[SPEC]', msg+'\033[0m')
    await SPEC_server.send_message('ICS', rsp)

    reply_data=mkmsg.specmsg()
    reply_data.update(result[0])
    rsp=json.dumps(reply_data)
    print('\033[32m'+'[SPEC]', reply_data["message"]+'\033[0m')
    await SPEC_server.send_message('ICS', rsp)

def get_next_filename(extension: str = "fits"):
    index = 1

#    with open('./Lib/KSPEC.ini','r') as fs:
#        kspecinfo = json.load(fs)

#    specinfopath = kspecinfo['SPEC']['specinfopath']
#    specimagepath = kspecinfo['SPEC']['specimagepath']

    with open('./SPECTRO/specinfo.json','r') as f:
        specinfo = json.load(f)

    dir_name = specinfo['dirname']

    while True:
        filepath=f'../DATA/RAWDATA/{dir_name}/'
        filename = f"{dir_name}{index:04d}.{extension}"
        if not os.path.exists(filepath+filename):
            return filepath,filename
        index += 1

async def create_fits_image(exptime, shape: tuple = (100, 100), data_type=np.float32):
    data = np.random.random(shape).astype(data_type)
    hdu = fits.PrimaryHDU(data)
    filepath,filename = get_next_filename()
#    print(filepath+filename)
    hdul = fits.HDUList([hdu])
    hdul.writeto(filepath+filename, overwrite=True)
    await asyncio.sleep(exptime)
    msg=f'FITS file {filename} is created.'
    response = {"status": "success", "message": msg, "filename": filepath+filename, "process": 'Done'}
    return response

async def remaining(SPEC_server, exptime):
    remaining_time = exptime
    while remaining_time > 0:
        await asyncio.sleep(min(10, remaining_time))  
        remaining_time -= 10
        msg = f'Remaining exposure time: {remaining_time} seconds.'
        print('\033[32m' + '[SPEC]', msg + '\033[0m')
        reply_data=mkmsg.specmsg()
        reply_data.update(message=msg,process='ING',status='success')
        rsp=json.dumps(reply_data)
        await SPEC_server.send_message('ICS', rsp)

def spec_status():
    msg='Spectrograph Status is below. Spectrograph is ready.'
    return msg

def get_bias(nframe):
    time.sleep(5)
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
