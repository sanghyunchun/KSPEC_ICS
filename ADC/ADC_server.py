import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from ADC.command import *
#import configparser as cp
#from ADC.kspec_adc_controller.src.adc_actions import AdcActions

async def main():
    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']

    print('ADC Sever Started!!!')
    ADC_server=AMQclass(ip_addr,idname,pwd,'ADC','ics.ex')
#    action=AdcActions()
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
