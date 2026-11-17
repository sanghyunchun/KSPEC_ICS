import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from SPECTRO_ISOPLANE.command import Isoplane


async def main():
    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']
    cfgpath = kspecinfo.get('ISOPLANE', {}).get('config', './SPECTRO_ISOPLANE/isoplane_local.json')
    if not os.path.exists(cfgpath):
        sys.exit(f'{cfgpath} not found: copy SPECTRO_ISOPLANE/isoplane_local.example.json and edit it.')
    with open(cfgpath, 'r') as f:
        cfg = json.load(f)

    isoplane = Isoplane(cfg)
    try:
        await isoplane.start()
        print('ISOPLANE Server Started!!!')
        ISOPLANE_server=AMQclass(ip_addr,idname,pwd,'ISOPLANE','ics.ex')
        await ISOPLANE_server.connect()
        await serve(isoplane, ISOPLANE_server)
    finally:
        # back-illumination light off, and LightField disposed: a LightField left running in
        # its AddInProcess.exe blocks every later start
        await isoplane.close()


async def serve(isoplane, ISOPLANE_server):

    async def on_isoplane_message(message: aio_pika.IncomingMessage):
        # Ack on receipt, not after the command: an exposure command can run longer than the
        # broker's consumer_timeout (30 min by default). A delivery unacked that long is
        # requeued, which killed the command before its header cards and started the same
        # exposure again (20261029 darks 0037-0050, 20261030_0020/0021). A command is thus
        # never redelivered, also not after a server crash mid-exposure.
        await message.ack()
        try:
            dict_data = json.loads(message.body)
            print('\033[94m' + '[ISOPLANE] received: ' + str(dict_data.get('message', dict_data.get('func'))) + '\033[0m')
            await isoplane.handle(ISOPLANE_server, message.body)
        except Exception as e:
            print(f"Error in on_isoplane_message: {e}", flush=True)

        print('Waiting for message from client......')

    await ISOPLANE_server.define_consumer('ISOPLANE',on_isoplane_message)
    print('Waiting for message from client......')
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
