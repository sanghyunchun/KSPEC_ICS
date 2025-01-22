import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from LAMP.command import *


async def main():
    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']

    print('LAMP Sever Started!!!')
    LAMP_server=AMQclass(ip_addr,idname,pwd,'LAMP','ics.ex')
    await LAMP_server.connect()
    await LAMP_server.define_consumer()
    while True:
        print('Waiting for message from client......')
        msg=await LAMP_server.receive_message("LAMP")
        dict_data=json.loads(msg)
        message=dict_data['message']
        print('\033[94m'+'[LAMP] received: ', message+'\033[0m')

        await identify_execute(LAMP_server,msg)


if __name__ == "__main__":
    asyncio.run(main())
