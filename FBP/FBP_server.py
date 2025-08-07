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

    async def on_fbp_message(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                dict_data = json.loads(message.body)
                message_text = dict_data['message']
                print('\033[94m' + '[FBP] received: ' + message_text + '\033[0m')

                await identify_execute(FBP_server, message.body)

            except Exception as e:
                print(f"Error in on_gfa_message: {e}", flush=True)

        print('Waiting for message from client......')


    await FBP_server.define_consumer('FBP',on_fbp_message)
    print('Waiting for message from client......')
    while True:
        await asyncio.sleep(1)
#        msg=await FBP_server.receive_message("FBP")   # Check queue name
#        dict_data=json.loads(msg)
#        message=dict_data['message']
#        print('\033[94m'+'[FBP] received: ', message+'\033[0m')

#        await identify_execute(FBP_server,msg)

if __name__ == "__main__":
    asyncio.run(main())
