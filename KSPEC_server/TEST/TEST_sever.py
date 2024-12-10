import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from command import *
import configparser as cp



async def main():
    cfg=cp.ConfigParser()
    cfg.read('../../Lib/KSPEC.ini')
    ip_addr=cfg.get("MAIN","ip_addr")
    idname=cfg.get("MAIN","idname")
    pwd=cfg.get("MAIN",'pwd')

    print('TEST Sever Started!!!')
    TEST_server=AMQclass(ip_addr,idname,pwd,'TEST','ics.ex')
    await TEST_server.connect()
    await TEST_server.define_consumer()
    while True:
        print('Waiting for message from client......')
#        msgtot,msg=await GFA_server.receive_message('GFA.q')
        msg=await TEST_server.receive_message('TEST')
        dict_data=json.loads(msg)
        message=dict_data['message']
        print('\033[94m'+'[TEST] received: ', message+'\033[0m')
#        print(GFA_server.cmd_exchange)

        await identify_excute(TEST_server,msg)


if __name__ == "__main__":
    asyncio.run(main())
