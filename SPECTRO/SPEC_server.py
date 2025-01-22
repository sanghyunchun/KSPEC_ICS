import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from SPECTRO.command import *
import configparser as cp


async def main():
    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']

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

        await identify_execute(SPEC_server,msg)


if __name__ == "__main__":
    asyncio.run(main())
