import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from command import *
import configparser as cp


#async def send_response(channel, msg):
#    while not stop_event.is_set():
#        await asyncio.sleep(5)  # Wait for 5 seconds
#        await channel.default_exchange.publish(
#                aio_pika.Message(body=msg.encode()),
#                routing_key='client_queue',
#        )
#        print(f" [x] Sent {msg}")

#async def receive_message():
#    connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
#    async with connection:
#        channel = await connection.channel()
#        queue = await channel.declare_queue('tcs_queue')

#        stop_event = asyncio.Event()
#        async with queue.iterator() as queue_iter:
#            async for message in queue_iter:
#                async with message.process():
#                    if message.body == b'start':
#                    print(message.body)
#                    await asyncio.sleep(3)
#                    response_msg='Tile load finished'
#                    asyncio.create_task(send_response(channel, response_msg))
#                    elif message.body == b'stop':
#                        stop_event.set()
#                        await asyncio.sleep(1)  # Wait for 1 second to ensure all tasks are completed
#                        stop_event.clear()  # Reset stop_event for future messages


async def main():
    cfg=cp.ConfigParser()
    cfg.read('/media/shyunc/DATA/KSpec/KSPECICS_P4/Lib/KSPEC.ini')
    ip_addr=cfg.get("MAIN","ip_addr")
    idname=cfg.get("MAIN","idname")
    pwd=cfg.get("MAIN",'pwd')

    print('TCS Sever Started!!!')
    TCS_server=Server(ip_addr,idname,pwd,'TCS')
    while True:
        print('Waiting for message from client......')
        msg=await TCS_server.receive_message("TCS")
        dict_data=json.loads(msg)
        message=dict_data['comments']
        print('[TCS]', message)
        await identify_excute(TCS_server,msg)
        

if __name__ == "__main__":
    asyncio.run(main())

