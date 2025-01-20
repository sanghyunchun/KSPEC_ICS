import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from ENDO.command import *
from ENDO.endo_controller.endo_actions import endo_actions



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

    data_path=kspecinfo['ENDO']['endoimagepath']
    ensure_directory(data_path)

    print('Endoscope Sever Started!!!')
    ENDO_server=AMQclass(ip_addr,idname,pwd,'ENDO','ics.ex')
    await ENDO_server.connect()
    await ENDO_server.define_consumer()
    endoaction=endo_actions()
    endoaction.endo_connect()
    while True:
        print('Waiting for message from client......')
        msg=await ENDO_server.receive_message('ENDO')
        dict_data=json.loads(msg)
        message=dict_data['message']
        print('\033[94m'+'[ENDO] received: ', message+'\033[0m')

        await identify_execute(ENDO_server,endoaction,msg)


if __name__ == "__main__":
    asyncio.run(main())
