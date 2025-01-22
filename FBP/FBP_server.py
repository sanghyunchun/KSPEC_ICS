import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from FBP.command import *

async def main():
    with open('./Lib/KSPEC.ini','r') as f:
        jdata=json.load(f)

    ip_addr = jdata['RabbitMQ']['ip_addr']
    idname = jdata['RabbitMQ']['idname']
    pwd = jdata['RabbitMQ']['pwd']

    print('FBP Server Started!!!')
    FBP_server=AMQclass(ip_addr,idname,pwd,'FBP','ics.ex')  # Check queue name
    await FBP_server.connect()
    await FBP_server.define_consumer()
    while True:
        print('Waiting for message from client......')
        msg=await FBP_server.receive_message("FBP")   # Check queue name
        dict_data=json.loads(msg)
        message=dict_data['message']
        print('\033[94m'+'[FBP] received: ', message+'\033[0m')

        await identify_execute(FBP_server,msg)

if __name__ == "__main__":
    asyncio.run(main())
