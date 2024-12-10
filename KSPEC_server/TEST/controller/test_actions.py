import asyncio
import random
import Lib.mkmessage as mkmsg
from Lib.AMQ import *
import json
import configparser as cp


async def test_temp(subserver):
#    cfg=cp.ConfigParser()
#    cfg.read('../../Lib/KSPEC.ini')
#    ip_addr=cfg.get("MAIN","ip_addr")
#    idname=cfg.get("MAIN","idname")
#    pwd=cfg.get("MAIN",'pwd')

#    sub_server=AMQclass(ip_addr,idname,pwd,'TEST','ics.ex')

#    await sub_server.connect()
#    await sub_server.define_producer()

    index=random.randrange(1,10)
    print(index)
    if index in [6]:
        reply=mkmsg.gfamsg()
        comment='Telescope needs to slew.'
        offra=0.4
        offdec=0.03
        command=f'toff {offra} {offdec}'
        reply.update(comments=comment,_continue='True',nextstep=command)
        rsp=json.dumps(reply)
        await subserver.send_message('ICS',rsp)
        await asyncio.sleep(10)
#        return rsp
    else:
        reply=mkmsg.gfamsg()
        comment='Test process ok'
        reply.update(comments=comment)
        rsp=json.dumps(reply)
        return rsp
#        await TEST_server.send_message('ICS',rsp)

