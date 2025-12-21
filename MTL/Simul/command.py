import os,sys
import time
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
from MTL.Simul.kspec_metrology.exposure import mtlexp
from MTL.Simul.kspec_metrology.analysis import mtlcal


async def identify_execute(MTL_server,cmd):
    receive_msg=json.loads(cmd)
    func=receive_msg['func']

    if func == 'mtlstatus':
        comment=mtl_status()
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message=comment,process='Done',status='success')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)

    if func == 'loadobj':
        tid=receive_msg['tile_id']
        ra=receive_msg['ra']
        dec=receive_msg['dec']
        xp=receive_msg['xp']
        yp=receive_msg['yp']
        clss=receive_msg['class']

        status, comment=savedata(receive_msg)     # save the loaded objects
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message=comment,process='Done',status=status)
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)

    if func == 'mtlexp':
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message='MTL exposure starts.',process='ING',status='success')
        rsp=json.dumps(reply_data)
        await MTL_server.send_message('ICS',rsp)

        exptime=float(receive_msg['time'])
        filename = str(receive_msg['file'])
        nexposure = int(receive_msg['nexposure'])
        status, comment=mtlexp.mtlexp(exptime,filename,nexposure=nexposure)
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message=comment,process='Done',status=status)
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)

    if func == 'mtlcal':
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message='MTL calculation starts.',process='ING',status='success')
        rsp=json.dumps(reply_data)
        await MTL_server.send_message('ICS',rsp)

        status, comment, offx,offy = mtlcal.mtlcal()
#        comment='Metrology analysis finished successfully. Offsets were calculated.'
        reply_data=mkmsg.mtlmsg()
        reply_data.update(savedata='True',filename='MTLresult.json',offsetx=offx.tolist(),offsety=offy.tolist(),message=comment)
        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)

        with open('./Lib/KSPEC.ini','r') as fs:
            kspecinfo=json.load(fs)
    
        mtlfilepath=kspecinfo['MTL']['mtlfilepath']

        with open(mtlfilepath+'MTLresult.json',"w") as f:
            json.dump(reply_data, f)

        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)


def savedata(data):
    with open('./Lib/KSPEC.ini','r') as fs:
        kspecinfo=json.load(fs)

    mtlfilepath=kspecinfo['MTL']['mtlfilepath']

    try:
        with open(mtlfilepath+'object.info','w') as savefile:
            json.dump(data,savefile)
    except TypeError:
        return 'fail', "Non-numeric values encountered while formatting output."
    except OSError as e:
        return 'fail', f"Failed to write file: {e}"

    msg="'Objects are loaded in MTL server.'"
    return 'success', msg

# Below functions are for simulation. When connect the instruments, pleas annotate.
def mtl_status():
    time.sleep(3)
    mtl_rsp = 'Metrology Status is below. MTL is ready.'
    return mtl_rsp
