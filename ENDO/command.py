import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
#from ENDO.endo_controller.endo_actions import endo_actions

async def identify_excute(ENDO_server,endoaction,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']
#    endoaction=endo_actions()
#    endoaction.endo_connect()

    if func == 'endoclear':
        comment=endoaction.endo_clear()
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[ENDO]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await ENDO_server.send_message('ICS',rsp)

    if func == 'endoguide':
        msg='start'
    #    exptime=float(dict_data['time'])
        itmax=3
        comment='Endoscope starts to expose'
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[ENDO]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await ENDO_server.send_message('ICS',rsp)
        await ENDO_server.guiding_start_stop('ICS',msg,itmax,endoaction.endo_guide,ENDO_server)
        
    if func == 'endostop':
        msg='stop'
        await ENDO_server.guiding_start_stop('ICS',msg,0,'None','None')
        comment='Endoscope Exposure Stop. Endoscope cameras exposure finished.'
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ENDO]', comment+'\033[0m')
        await ENDO_server.send_message('ICS',rsp)

    if func == 'endotest':
    #    exptime=float(dict_data['time'])
        comment=endoaction.endo_test()
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[ENDO]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await ENDO_server.send_message('ICS',rsp)

    if func == 'endofocus':
        fc=float(dict_data['focus'])
        comment=endoaction.endo_focus(fc)
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[ENDO]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await ENDO_server.send_message('ICS',rsp)

    if func == 'endoexpset':
        expt=float(dict_data['time'])
        comment=endoaction.endo_expset(expt)
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[ENDO]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await ENDO_server.send_message('ICS',rsp)

    if func == 'loadguide':
        chipnum=dict_data['chipnum']
        ra=dict_data['ra']
        dec=dict_data['dec']
        mag=dict_data['mag']
        xp=dict_data['xp']
        yp=dict_data['yp']
        comment=savedata(ra,dec,xp,yp,mag)
#        dict_data={'inst': 'ENDO', 'savedata': 'False','filename': 'None','message': message}
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[ENDO]', comment+'\033[0m')
        await ENDO_server.send_message('ICS',rsp)
        

def savedata(ra,dec,xp,yp,mag):
    with open('./Lib/KSPEC.ini','r') as f:
        inidata=json.load(f)

    gfafilepath=inidata['ENDO']['gfafilepath']

    savefile=open(gfafilepath+'position.radec','w')
    for i in range(len(ra)):
        savefile.write("%12.6f %12.6f %12.6f %12.6f %9.4f\n" % (ra[i],dec[i],xp[i],yp[i],mag[i]))
    savefile.close

    msg="'Guide stars are loaded.'"
    return msg

# Below functions are for simulation. When connect the instruments, please annotate.

async def autoguide(exptime,subserver):
    msg=random.randrange(1,11)
    if msg < 7:
        reply=mkmsg.gfamsg()
        comment='Autoguiding continue.......'
        dict_data={'inst': 'ENDO', 'savedata': 'False','filename': 'None','message': comment, 'thred': msg}
        reply.update(dict_data)
#        rsp=json.dumps(reply)
        rsp=reply
    else:
        reply=mkmsg.gfamsg()
        comment=f'Telescope offset {msg}'
        print('\033[32m'+'[ENDO]', comment+'\033[0m')
        dict_data={'inst': 'ENDO', 'savedata': 'False','filename': 'None','message': comment, 'thred': msg}
        reply.update(dict_data)
#        rsp=json.dumps(reply)
        rsp=reply
    return rsp

def gfastatus():
    msg = 'ENDO is ready'
    return msg

def gfacexp(exptime):
    time.sleep(exptime)
    msg='ENDO exposure finished'
    return msg

def gfaallexp():
    time.sleep(10)
    msg='All ENDO cameras exposure finished'
    return msg

   
def gfastop():
    msg='stop'
    return msg


