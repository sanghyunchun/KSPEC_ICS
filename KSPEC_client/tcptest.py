import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
#from SCIOBS.sciobscli import load_tile,tra
import asyncio
import aio_pika
from command import *
from Lib.AMQ import *



async def user_input(TCSclient):

    loop = asyncio.get_event_loop()

    tcslist=['start','stop','tcsint','tcsreset','tcsclose','tcsarc','tcsstatus','tstat','traw','tsync',
            'tcmd','treg','tmradec','tmr','tmobject','tmo','tmelaz','tme','tmoffset','toff','tstop','tstow',
            'tdi','cc','oo','nstset','nston','nstoff','auxinit','auxreset','auxclose','auxarc','auxstatus',
            'astat','acmd','fsastat','fs','fttstat','ft','dfocus','dtilt','fttgoto']

    while True:
        user_input=await loop.run_in_executor(None, input,"KSPECRUN >")
        cmd=user_input.split(' ')

        if cmd[0] not in tcslist:
            print('Please insert right command!!!')
        else :
            await TCSclient.send_message(user_input)


async def main():
    TCS_client=TCSclient('127.0.0.1','8888')
    await TCS_client.connect()
    await asyncio.gather(TCS_client.receive_message(),user_input(TCS_client))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Bye!')
