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
    cfg.read('/media/shyunc/DATA/KSpec/KSPECICS_P4/Lib/KSPEC.ini')
    ip_addr=cfg.get("MAIN","ip_addr")
    idname=cfg.get("MAIN","idname")
    pwd=cfg.get("MAIN",'pwd')

    print('GFA Sever Started!!!')
    GFA_server=Server(ip_addr,idname,pwd,'GFA')
    while True:
        print('Waiting for message from client......')
        msg=await GFA_server.receive_message("GFA")
        dict_data=json.loads(msg)
        message=dict_data['comments']
        print('[GFA]', message)

        await identify_excute(GFA_server,msg)


if __name__ == "__main__":
    asyncio.run(main())
