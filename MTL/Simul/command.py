import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
from MTL.Simul.kspec_metrology.exposure import mtlexp
from MTL.Simul.kspec_metrology.analysis import mtlcal

with open('./Lib/KSPEC.ini','r') as fs:
    kspecinfo=json.load(fs)

mtlfilepath=kspecinfo['MTL']['mtlfilepath']

async def identify_execute(MTL_server,cmd):
    receive_msg=json.loads(cmd)
    func=receive_msg['func']

    if func == 'mtlstatus':
        comment=mtl_status()
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message=comment,process='Done')
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

        file_path=(mtlfilepath+'object.info')
        with open(file_path,"w") as f:
            json.dump(receive_msg,f)

        comment="'Objects are loaded in MTL server.'"
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)

    if func == 'mtlexp':
        exptime=float(receive_msg['time'])
        comment=mtlexp.mtlexp(exptime)
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)

    if func == 'mtlcal':
        offx,offy,comment = mtlcal.mtlcal()
        reply_data=mkmsg.mtlmsg()
        reply_data.update(savedata='True',filename='MTLresult.json',offsetx=offx.tolist(),offsety=offy.tolist(),message=comment)
        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)


# Below functions are for simulation. When connect the instruments, pleas annotate.
def mtl_status():
    mtl_rsp = 'Metrology Status is below. MTL is ready.'
    return mtl_rsp
