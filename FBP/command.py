import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import numpy as np
import time


with open('./Lib/KSPEC.ini','r') as fs:
    kspecinfo=json.load(fs)

    fbpfilepath=kspecinfo['FBP']['fbpfilepath']

async def identify_excute(FBP_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'loadobj':
        ra=dict_data['ra']
        dec=dict_data['dec']
        xp=dict_data['xp']
        yp=dict_data['yp']
        clss=dict_data['class']
        comment=savedata(ra,dec,xp,yp,clss)  # Save Target information

        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'loadmotion':
        arm=dict_data['arm']
        if dict_data['arm'] == 'alpha':
            file_path=(fbpfilepath+'motion_alpha.info')
            with open(file_path,"w") as f:
                json.dump(dict_data,f)

        if dict_data['arm'] == 'beta':
            file_path=(fbpfilepath+'motion_beta.info')
            with open(file_path,"w") as f:
                json.dump(dict_data,f)

        comment=f'Motion plan of {arm} is saved.'
        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'fbpmove':
        reply_data=mkmsg.fbpmsg()
        comment = 'Fiber positioners start to move'
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await FBP_server.send_message('ICS',rsp)

        comment=fbpmove()     ### Position of fiber postioner movement function
        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'fbpoffset':
        comment = fbpoffset()   ### Position of fiber offset movement function
        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'fbpstatus':
        comment = fbpstatus()
        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'fbpinit':
        reply_data=mkmsg.fbpmsg()
        comment = 'Fiber positioners start to move'
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

        comment=fbpinit()     ### Position of fiber postioner movement function
        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

# Below functions are for simulation. When connect the Fiber positioner, please annotate
def fbpinit():
    ra,dec,xp,yp=np.loadtxt(fbpfilepath+'object.radec',dtype=float,unpack=True,usecols=(0,1,2,3))
    time.sleep(5)
    rspmsg=f'Fiber positioners moved to initial position.'
    return rspmsg

def fbpmove():
    ra,dec,xp,yp=np.loadtxt(fbpfilepath+'object.radec',dtype=float,unpack=True,usecols=(0,1,2,3))
    time.sleep(5)
    rspmsg=f'Fiber positioners movement finished.'
    return rspmsg

def fbpoffset():
    ra,dec,xp,yp=np.loadtxt(fbpfilepath+'object.radec',dtype=float,unpack=True,usecols=(0,1,2,3))
    time.sleep(5)
    rspmsg='Fiber positioners offset finished.'
    return rspmsg

def fbpstatus():
    time.sleep(2)
    rspmsg='Fiber positioners status below. FBP is ready.'
    return rspmsg

def savedata(ra,dec,xp,yp,clss):
    f=open(fbpfilepath+'object.radec','w')
    for i in range(len(ra)):
        f.write("%12.6f %12.6f %12.6f %12.6f %8s\n" % (ra[i],dec[i],xp[i],yp[i],clss[i]))
    f.close
    rspmsg="'Objects are loaded in FBP server.'"
    return rspmsg