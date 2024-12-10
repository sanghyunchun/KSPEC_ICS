import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
#from KSPEC_server.GFA.kspec_gfa_controller.src.gfa_loop_test import autoguide
#from KSPEC_Server.GFA.kspec_gfa_controller.src.gfa_actions import gfa_actions


async def identify_excute(GFA_server,cmd):
#    ttt=GfaLoopTest()
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'gfaallexp':
        comment=gfaallexp()
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
#        print(GFA_server._continue)
        await GFA_server.send_message('ICS',rsp)

    if func == 'gfacexp':
        exptime=float(dict_data['time'])
        cam=dict_data['chip']
        comment=gfacexp(exptime)                      ### Position of all gfa camera exposure function
#        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': message}
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        await GFA_server.send_message('ICS',rsp)

#    if func == 'autoguide':
#        time=dict_data['time']
#        message='Autoguide offset'
#        dict_data={'inst': 'GFA', 'savedata': 'True','filename': 'Auideoffset.txt','offset': value,'message': message}
#        rsp=json.dumps(dict_data)
#        await GFA_server.loop_start_stop('GFA',rsp)

    if func == 'autoguide':
        msg='start'
#        action=gfa_actions()
        itmax=2
#        await GFA_server.loop_start_stop('GFA',msg,itmax,action.grab)
        await GFA_server.loop_start_stop('ICS',msg,itmax,autoguide,GFA_server)
#        reply_data=mkmsg.gfamsg()
#        reply_data.update(message=comment)
#        message='Autoguide offset'
#        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': message}
#        rsp=json.dumps(reply_data)
#        print('\033[32m'+'[GFA]', comment+'\033[0m')
#        await GFA_server.send_message('GFA',rsp)

    if func == 'autoguidestop':
        msg='stop'
        await GFA_server.loop_start_stop('ICS',msg,0,'None','None')
        comment='Autoguide Stop. All GFA cameras exposure finished.'
#        rsp=gfastop()
#        await GFA_server.loop_start_stop('GFA',rsp)
#        message = 'GFA exposure finished'
#        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': message}
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment)
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        await GFA_server.send_message('ICS',rsp)

    if func == 'loadguide':
        chipnum=dict_data['chipnum']
        ra=dict_data['ra']
        dec=dict_data['dec']
        mag=dict_data['mag']
        xp=dict_data['xp']
        yp=dict_data['yp']
        comment=savedata(ra,dec,xp,yp,mag)

#        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': message}
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment)
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        await GFA_server.send_message('ICS',rsp)
        


async def autoguide(subserver):
    msg=random.randrange(1,11)
    if msg < 5:
        reply=mkmsg.gfamsg()
        comment='Autoguiding running'
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': comment}
        reply.update(dict_data)
        rsp=json.dumps(reply)
    else:
        reply=mkmsg.gfamsg()
        comment=f'Telescope offset {msg}'
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': comment}
        reply.update(dict_data)
        rsp=json.dumps(reply)
    return rsp

def gfacexp(exptime):
    time.sleep(exptime)
    msg='GFA exposure finished'
    return msg

def gfaallexp():
    time.sleep(10)
    msg='All GFA cameras exposure finished'
    return msg

   
def gfastop():
    msg='stop'
    return msg


def savedata(ra,dec,xp,yp,mag):
    f=open('./etc/position.radec','w')
    for i in range(len(ra)):
        f.write("%12.6f %12.6f %12.6f %12.6f %9.4f\n" % (ra[i],dec[i],xp[i],yp[i],mag[i]))
    f.close

    msg="'Guide stars are loaded.'"
    return msg
