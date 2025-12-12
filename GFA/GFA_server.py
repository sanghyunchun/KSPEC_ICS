import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from GFA.command import *
from GFA.kspec_gfa_controller.src.gfa_actions import GFAActions
from GFA.kspec_gfa_controller.src.finder_actions import FinderGFAActions
#from GFA.endo_controller.endo_actions import endo_actions
#import configparser as cp


async def main():

    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']

    print('GFA Sever Started!!!')
    GFA_server=AMQclass(ip_addr,idname,pwd,'GFA','ics.ex')
    gfa_actions=GFAActions()
    finder_actions=FinderGFAActions()
    await GFA_server.connect()

    async def on_gfa_message(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                dict_data = json.loads(message.body)
                message_text = dict_data['message']
                print('\033[94m' + '[GFA] received: ' + message_text + '\033[0m')

                await identify_execute(GFA_server, gfa_actions, finder_actions, message.body)

            except Exception as e:
                print(f"Error in on_gfa_message: {e}", flush=True)

        print('Waiting for message from client......')

    await GFA_server.define_consumer('GFA',on_gfa_message)
    print('Waiting for message from client......')
    while True:
        await asyncio.sleep(1)
#        msg=await GFA_server.receive_message('GFA')
#        dict_data=json.loads(msg)
#        message=dict_data['message']
#        print('\033[94m'+'[GFA] received: ', message+'\033[0m')

#        await identify_execute(GFA_server,gfa_actions,msg)


if __name__ == "__main__":
    asyncio.run(main())
