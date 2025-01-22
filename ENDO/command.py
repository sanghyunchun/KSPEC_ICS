import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
#from ENDO.endo_controller.endo_actions import endo_actions

async def identify_execute(ENDO_server,endoaction,cmd):
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

# Below functions are for simulation. When connect the instruments, please annotate.




