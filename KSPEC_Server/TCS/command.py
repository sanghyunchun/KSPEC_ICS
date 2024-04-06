import numpy as np
import os,sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import json
import asyncio
from TCScore import *


#TCS_server=Server('kspecadmin','kasikspec','TCS')
async def identify_excute(TCS_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']
    
    if func == 'loadtile':
        tile_id=dict_data['tid']
        t_ra=dict_data['ra']
        t_dec=dict_data['dec']

        rsp=savedata(tile_id,t_ra,t_dec)
#        print(rsp)
#        savedata(tile_id,t_ra,t_dec)
#        loop=asyncio.get_event_loop()
#        task=loop.create_task(TCS_server.send_response("TCS",rsp))
#        loop.run_until_complete(task)
#        asyncio.create_task(TCS_server.send_response("TCS",rsp))
        await TCS_server.send_response("TCS",rsp)

    if func == 'tra':
        rsp='Telescope slewing.....'
        await TCS_server.send_response("TCS",rsp)
        tra()
        rsp='Telescope slew finished'
        await TCS_server.send_response("TCS",rsp)


def savedata(tid,tra,tdec):
    f=open('./data/position.radec','w')
    for i in range(10):
        f.write("%4i %12.6f %12.6f \n" % (tid,tra, tdec))
    f.close

    response="'TCS loaded the tile information'"
    return response
