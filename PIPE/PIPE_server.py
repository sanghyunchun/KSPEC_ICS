import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from PIPE.command import *

async def main():
    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']

    print('PIPE Sever Started!!!')
    PIPE_server=AMQclass(ip_addr,idname,pwd,'PIPE','ics.ex')
    await PIPE_server.connect()
    await PIPE_server.define_consumer()
    while True:
        print('Waiting for message from client......')
        msg=await PIPE_server.receive_message("PIPE")
        dict_data=json.loads(msg)
        message=dict_data['message']
        print('\033[94m'+'[PIPE] received: ', message+'\033[0m')

        await identify_execute(PIPE_server,action,msg)               # For real observation


if __name__ == "__main__":
    asyncio.run(main())
