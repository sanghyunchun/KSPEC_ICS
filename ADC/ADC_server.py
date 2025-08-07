import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__)))))
from Lib.AMQ import *
import asyncio
import aio_pika
import json
from ADC.command import *
from ADC.kspec_adc_controller.src.adc_actions import AdcActions     # For real observation

"""
Main module for the ADC server. This script initializes the ADC server, connects to RabbitMQ, and processes incoming messages by executing specified actions.
"""

async def main():
    """Main entry point for the ADC server.

    This function performs the following steps:
    - Loads RabbitMQ connection information from a configuration file.
    - Initializes and connects the server to RabbitMQ.
    - Waits for incoming messages from clients and processes them.

    Raises:
        FileNotFoundError: If the configuration file 'KSPEC.ini' is not found.
        KeyError: If required keys are missing in the configuration file.
    """
    try:
        with open('./Lib/KSPEC.ini','r') as f:
            kspecinfo=json.load(f)

        ip_addr = kspecinfo['RabbitMQ']['ip_addr']
        idname = kspecinfo['RabbitMQ']['idname']
        pwd = kspecinfo['RabbitMQ']['pwd']

        print('ADC Sever Started!!!')
        ADC_server=AMQclass(ip_addr,idname,pwd,'ADC','ics.ex')
        action=AdcActions()                                             # For real observation.
        print('\033[32m'+'[ADC] ADC device is found and ready.'+'\033[0m')

        await ADC_server.connect()

        sync def on_adc_message(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                dict_data = json.loads(message.body)
                message_text = dict_data['message']
                print('\033[94m'+'[ADC] received: ' + message_text + '\033[0m')

                await identify_execute(ADC_server, message.body)

            except Exception as e:
                print(f"Error in on_gfa_message: {e}", flush=True)

            print('Waiting for message from client......')


        await ADC_server.define_consumer('ADC',on_adc_message)
        print('Waiting for message from client......')

        while True:
            await asyncio.sleep(1)
#            msg = await ADC_server.receive_message("ADC")
#            dict_data=json.loads(msg)
#            message=dict_data['message']
#            print('\033[94m'+'[ADC] received: ', message+'\033[0m')

#            await identify_execute(ADC_server,action,msg)               # For real observation

    except FileNotFoundError as e:
        print(f"Configuration file not found: {e}")
    except KeyError as e:
        print(f"Missing configuration key: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    """Execute the main function in an asynchronous event loop."""
    asyncio.run(main())
