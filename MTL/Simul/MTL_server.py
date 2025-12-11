import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from MTL.Simul.command import *


def ensure_directory(dir_path):
    if not os.path.exists(dir_path):
        print(f"There is no directroy. Now making directory: {dir_path}")
        os.makedirs(dir_path)
    else:
        print(f"There is alireay the directory. Skip making directory : {dir_path}")

async def main():
    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']

    data_path=kspecinfo['MTL']['mtlimagepath']
    ensure_directory(data_path)
    file_path=kspecinfo['MTL']['mtlfilepath']
    ensure_directory(file_path)

    print('MTL Server Started!!!')
    MTL_server=AMQclass(ip_addr,idname,pwd,'MTL','ics.ex')
    await MTL_server.connect()

    async def on_mtl_message(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                dict_data = json.loads(message.body)
                print(dict_data)
                message_text = dict_data['message']
                print('\033[94m' + '[MTL] received: ' + message_text + '\033[0m')

                await identify_execute(MTL_server, message.body)

            except Exception as e:
                print(f"Error in on_mtl_message: {e}", flush=True)

        print('Waiting for message from client......')
        
    await MTL_server.define_consumer('MTL',on_mtl_message)
    print('Waiting for message from client......')
    while True:
        await asyncio.sleep(1)
#        msg=await MTL_server.receive_message("MTL")
#        dict_data=json.loads(msg)
#        message=dict_data['message']
#        print('\033[94m'+'[MTL] received: ', message+'\033[0m')

#        await identify_execute(MTL_server,msg)


if __name__ == "__main__":
    asyncio.run(main())
