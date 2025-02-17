import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from GFA.Simul.command import *
from GFA.Simul.kspec_gfa_controller.src.gfa_actions import GFAActions
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
    gfa_action=GFAActions()
    await GFA_server.connect()
    await GFA_server.define_consumer()
    while True:
        print('Waiting for message from client......')
#        msgtot,msg=await GFA_server.receive_message('GFA.q')
        msg=await GFA_server.receive_message('GFA')
        dict_data=json.loads(msg)
        message=dict_data['message']
        print('\033[94m'+'[GFA] received: ', message+'\033[0m')

        await identify_execute(GFA_server,gfa_action,msg)


if __name__ == "__main__":
    asyncio.run(main())
