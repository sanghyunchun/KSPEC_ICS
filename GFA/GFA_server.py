import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import aio_pika
import json
from GFA.command import *
from GFA.kspec_gfa_controller.src.kspec_gfa_controller.gfa_actions import GFAActions
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
    await GFA_server.connect()

    async def on_gfa_message(message: aio_pika.IncomingMessage):
        async with message.process():
            func = 'None'
            try:
                dict_data = json.loads(message.body)
                func = dict_data.get('func', 'None')
                message_text = dict_data['message']
                print('\033[94m' + '[GFA] received: ' + message_text + '\033[0m')

                await identify_execute(GFA_server, gfa_actions, message.body)

            except Exception as e:
                comment = f"GFA command failed: {e}"
                print(f"Error in on_gfa_message: {comment}", flush=True)
                reply_data = mkmsg.gfamsg()
                reply_data.update(
                    func=func,
                    process='Done',
                    status='fail',
                    message=comment,
                )
                try:
                    await GFA_server.send_message('ICS', json.dumps(reply_data))
                except Exception as send_error:
                    print(f"Error sending GFA failure response: {send_error}", flush=True)

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
