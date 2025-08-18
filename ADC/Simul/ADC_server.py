import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from ADC.Simul.command import *
from ADC.Simul.kspec_adc_controller.src.adc_actions import AdcActions

async def main():
    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']

    print('ADC Sever Started!!!')
    ADC_server=AMQclass(ip_addr,idname,pwd,'ADC','ics.ex')
    action=AdcActions()
    print('\033[32m'+'[ADC] ADC device is found and ready.'+'\033[0m')
    await ADC_server.connect()

    async def on_adc_message(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                dict_data = json.loads(message.body)
                message_text = dict_data['message']
                print('\033[94m' + '[ADC] received: ' + message_text + '\033[0m')

                await identify_execute(ADC_server, action, message.body)

            except Exception as e:
                print(f"Error in on_mtl_message: {e}", flush=True)

        print('Waiting for message from client......')

    await ADC_server.define_consumer('ADC',on_adc_message)
    print('Waiting for message from client......')
    while True:
        await asyncio.sleep(1)
#        msg=await ADC_server.receive_message("ADC")
#        dict_data=json.loads(msg)
#        message=dict_data['message']
#        print('\033[94m'+'[ADC] received: ', message+'\033[0m')

#        await identify_execute(ADC_server,action,msg)                     # For simulation. Annotate when real observation


if __name__ == "__main__":
    asyncio.run(main())
