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

    async def on_lamp_message(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                dict_data = json.loads(message.body)
                message_text = dict_data['message']
                print('\033[94m' + '[LAMP] received: ' + message_text + '\033[0m')

                await identify_execute(LAMP_server, message.body)

            except Exception as e:
                print(f"Error in on_gfa_message: {e}", flush=True)

        print('Waiting for message from client......')


    await LAMP_server.define_consumer('LAMP',on_lamp_message)
    print('Waiting for message from client......')
    while True:
        await asyncio.sleep(1)
#        print('Waiting for message from client......')
#        msg=await LAMP_server.receive_message("LAMP")
#        dict_data=json.loads(msg)
#        message=dict_data['message']
#        print('\033[94m'+'[LAMP] received: ', message+'\033[0m')

#        await identify_execute(LAMP_server,msg)


if __name__ == "__main__":
    asyncio.run(main())
