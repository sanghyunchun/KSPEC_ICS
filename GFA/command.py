import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
from GFA.endo_controller.endo_actions import endo_actions
#from GFA.kspec_gfa_controller.python.gfa_controller import gfa_actions
#from KSPEC_Server.GFA.kspec_gfa_controller.src.gfa_actions import gfa_actions


async def identify_excute(GFA_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']
    endoaction=endo_actions()
    endoaction.endo_connect()

    if func == 'gfastatus':
        comment=gfastatus()
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        await GFA_server.send_message('ICS',rsp)

    if func == 'gfaallexp':
        comment=gfaallexp()
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
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

    if func == 'autoguide':
        msg='start'
#        action=gfa_actions()
        exptime=float(dict_data['time'])
        itmax=3
        comment = 'Autoguide start'
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await GFA_server.send_message('ICS',rsp)
#        await GFA_server.loop_start_stop('ICS',msg,itmax,action.guiding,exptime,GFA_server)
        await GFA_server.guiding_start_stop('ICS',msg,itmax,autoguide,exptime,GFA_server)  # For Simulation. Annotate when real observation
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
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        await GFA_server.send_message('ICS',rsp)

    if func == 'endoguide':
        msg='start'
        exptime=float(dict_data['time'])
        itmax=3
        comment='Endoscope starts to expose'
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await GFA_server.send_message('ICS',rsp)
        await GFA_server.guiding_start_stop('ICS',msg,itmax,endoaction.endo_guide,exptime,GFA_server)
        
    if func == 'endostop':
        msg='stop'
        await GFA_server.loop_start_stop('ICS',msg,0,'None','None','None')
        comment='Endoscope Exposure Stop. Endoscope cameras exposure finished.'
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        await GFA_server.send_message('ICS',rsp)

    if func == 'endotest':
        exptime=float(dict_data['time'])
        comment=endoaction.endo_test(exptime)
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await GFA_server.send_message('ICS',rsp)

    if func == 'endofocus':
        fc=float(dict_data['focus'])
        comment=endoaction.endo_focus(fc)
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await GFA_server.send_message('ICS',rsp)

    if func == 'endoexpset':
        expt=float(dict_data['time'])
        comment=endoaction.endo_expset(expt)
        reply_data=mkmsg.gfamsg()
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
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
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        await GFA_server.send_message('ICS',rsp)
        

def savedata(ra,dec,xp,yp,mag):
    with open('./Lib/KSPEC.ini','r') as f:
        inidata=json.load(f)

    gfafilepath=inidata['GFA']['gfafilepath']

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
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': comment, 'thred': msg}
        reply.update(dict_data)
#        rsp=json.dumps(reply)
        rsp=reply
    else:
        reply=mkmsg.gfamsg()
        comment=f'Telescope offset {msg}'
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': comment, 'thred': msg}
        reply.update(dict_data)
#        rsp=json.dumps(reply)
        rsp=reply
    return rsp

def gfastatus():
    msg = 'GFA is ready'
    return msg

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


