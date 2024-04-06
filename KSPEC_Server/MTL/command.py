import os,sys
from Lib.AMQ import *
import json
import asyncio
import MTL_Exposure as mtl

#MTL_server=Server('MTL')

async def identify_excute(MTL_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'mtlexp':
        rsp=mtl.MTLexposure()

        await MTL_server.send_response('MTL',rsp)
