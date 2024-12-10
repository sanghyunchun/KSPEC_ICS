import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from command import *
import configparser as cp
from kspec_adc_controller.src.adc_actions import AdcActions

async def main():
    cfg=cp.ConfigParser()
    cfg.read('../../Lib/KSPEC.ini')
    ip_addr=cfg.get("MAIN","ip_addr")
    idname=cfg.get("MAIN","idname")
    pwd=cfg.get("MAIN",'pwd')

    print('ADC Sever Started!!!')
    ADC_server=AMQclass(ip_addr,idname,pwd,'ADC','ics.ex')
    action=AdcActions()
    await ADC_server.connect()
    await ADC_server.define_consumer()
    while True:
        print('ADC device is found and ready.')
        print('Waiting for message from client......')
        msg=await ADC_server.receive_message("ADC")
        dict_data=json.loads(msg)
        message=dict_data['message']
        print('\033[94m'+'[ADC] received: ', message+'\033[0m')

        await identify_excute(ADC_server,msg)


if __name__ == "__main__":
    asyncio.run(main())
