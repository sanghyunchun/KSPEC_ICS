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

    print('SPECTRO Sever Started!!!')
    SPEC_server=AMQclass(ip_addr,idname,pwd,'SPEC','ics.ex')
    await SPEC_server.connect()
    await SPEC_server.define_consumer()
    while True:
        print('Waiting for message from client......')
        msg=await SPEC_server.receive_message("SPEC")
        dict_data=json.loads(msg)
        message=dict_data['message']
        print('\033[94m'+'[SPEC] received: ', message+'\033[0m')

        await identify_excute(SPEC_server,msg)


if __name__ == "__main__":
    asyncio.run(main())