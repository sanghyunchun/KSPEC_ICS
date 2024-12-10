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

    print('MTL Server Started!!!')
    MTL_server=AMQclass(ip_addr,idname,pwd,'MTL','ics.ex')
    await MTL_server.connect()
    await MTL_server.define_consumer()
    while True:
        print('Waiting for message from client......')
        msg=await MTL_server.receive_message("MTL")
        dict_data=json.loads(msg)
        message=dict_data['message']
        print('\033[94m'+'[MTL] received: ', message+'\033[0m')

        await identify_excute(MTL_server,msg)


if __name__ == "__main__":
    asyncio.run(main())
