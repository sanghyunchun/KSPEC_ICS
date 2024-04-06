import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import click
#from SCIOBS.sciobscli import load_tile,tra
import asyncio
import threading
import aio_pika
from command import *
from Lib.AMQ import *
import configparser as cp

#async def receive_message():
#    connection = await aio_pika.connect_robust(host='localhost',login=self.id,password=self.pw)
#    async with connection:
#        channel = await connection.channel()
#        queue = await channel.declare_queue('client_queue')
#        async with queue.iterator() as queue_iter:
#            async for message in queue_iter:
#                async with message.process():
#                    print(" [ICS] Received: ", message.body.decode())


#async def send_message(message):
#    connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
#    async with connection:
#        channel = await connection.channel()
#        await channel.default_exchange.publish(
#            aio_pika.Message(body=message.encode()),
#            routing_key='server_queue',
#        )
#        print(f" [x] Sent '{message}'")
#        await connection.close()


#def loadtile(tileid):
#    load_tile(tileid)


#def identify(cmd):
#    if command[0] == 'loadtile':
#        print('Command is loadtile')
#        loadtile(command[1])



def user_input_loop():
    while True:
        user_input = input("KSPECRUN:> ")
        args=user_input.split(' ')
        identify(args)

#        cmd='python KSPECRUN.py '+user_input.strip().lower()
#        print(cmd)
#        if user_input.strip().lower() in ('start', 'stop'):
#            device = await asyncio.to_thread(input, "Enter the device ID (device1 or device2): ")
#            message = user_input.strip().lower()
#            await self.send_message(device, message)

async def main():
    input_thread = threading.Thread(target=user_input_loop)
    input_thread.start()

    cfg=cp.ConfigParser()
    cfg.read('/media/shyunc/DATA/KSpec/KSPECICS_P4/Lib/KSPEC.ini')
    ip_addr=cfg.get("MAIN","ip_addr")
    idname=cfg.get("MAIN","idname")
    pwd=cfg.get("MAIN",'pwd')
    ICS_client=Client(ip_addr,idname,pwd)
    await ICS_client.receive_response()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Bye!')
