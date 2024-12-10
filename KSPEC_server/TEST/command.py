import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
from controller.test_actions import test_temp


async def identify_excute(TEST_server,cmd):
#    ttt=GfaLoopTest()
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'testfunc':
        msg='start'
        itmax=10
 #       reply_data=mkmsg.gfamsg()
 #       comment='Good!! Test function executed'
 #       print(comment)
#        reply_data.update(message=comment)
#        rsp=json.dumps(reply_data)
        await TEST_server.loop_start_stop('ICS',msg,itmax,test_temp,TEST_server)
#        await TEST_server.send_message('ICS',rsp)

    if func == 'teststop':
        msg='stop'
        await TEST_server.loop_start_stop('ICS',msg,0,'None','None')
