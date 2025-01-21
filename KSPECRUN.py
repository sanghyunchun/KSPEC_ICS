import os, sys

sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import asyncio
from Lib.AMQ import *
from icscommand import *
import aio_pika
import Lib.process as processes
import json

class kspecicsclass():
    def __init__(self):
        self.transport = 'None'
        self.tcslist = ["start","stop","tcsint","tcsreset","tcsclose",
            "tcsarc","tcsstatus","tstat","traw","tsync","tcmd",
            "treg","tmradec","tmr","tmobject","tmo","tmelaz",
            "tme","tmoffset","toff","tstop","tstow","tdi",
            "cc","oo","nstset","nston","nstoff","auxinit",
            "auxreset","auxclose","auxarc","auxstatus",
            "astat","acmd","fsastat","fs","fttstat",
            "ft","dfocus","dtilt","fttgoto",]
        self.running = True

    async def response_act(self,ICS_client):
        try:
            while self.running:
                rsp_msg = await ICS_client.receive_message('ICS')
                dict_data = json.loads(rsp_msg)
                inst = dict_data['inst']
                process_status = dict_data['process']
                print('process status :', process_status)
                processes.update_process(inst,process_status)

                saveflag = dict_data["savedata"]
                if saveflag == "False":
                    print('\033[94m'+'[ICS] received: ',dict_data["message"]+'\n\033[0m')
                else:
                    with open('./Lib/KSPEC.ini','r') as fs:
                        kspecinfo=json.load(f)

                    savefilepath=kspecinfo['savepath']

                    with open(savefilepath + dict_data["filename"], "w") as f:
                        json.dump(dict_data, f)
                    outfile=dict_data["filename"]
                    print('\033[94m'+'\n[ICS] received: ',dict_data["message"]+'\033[0m')
                    print('\033[94m'+f'[ICS] "{outfile}" File saved'+'\033[0m')

                nextstep = dict_data['nextstep']
                if nextstep == 'True':
                    message=dict_data['nextstep']
                    cmd=message.split(" ")

                    if cmd[0] in self.tcslist:
                        self.transport.sendto(message.encode())  # Send message to server

                    else:
                        await identify(message,ICS_client,self.transport)

                if nextstep == 'None':
                    pass
        except asyncio.CancelledError:
            print("response_act cancelled.")
        except Exception as e:
            print(f"An error occurred in response_act: {e}")
        finally:
            print("response_act finalized.")


    async def user_input(self,ICSclient):
        try:
            loop = asyncio.get_event_loop()
            on_con_lost = loop.create_future()  # Future to wait for connection loss

    # Define a factory function that returns a new protocol instance
            def protocol_factory():
                return UDPClientProtocol(on_con_lost)

    # Create UDP connection
            self.transport, self.protocol = await loop.create_datagram_endpoint(
                protocol_factory, remote_addr=("127.0.0.1", 12345)
            )


    #    try:
            while True:
        # Run input() in the default executor (blocking call to non-blocking)
                message = await loop.run_in_executor(None, input, "\n Input command: ")
                cmd = message.split(" ")

                if cmd[0] in self.tcslist:
                    self.transport.sendto(message.encode())  # Send message to server

                elif message.lower() == "quit":  # Exit condition
                    print("Closing connection...")
                    self.transport.close()  # Close the connection
                    print(type(ICSclient))
#                    await ICSclient.disconnect()
                    self.running = False
#                on_con_lost.set_result(None)  # Wait until the connection is closed
#                asyncio.get_running_loop().stop()
                    break

                else:
                    await identify(message,ICSclient,self.transport)
        except asyncio.CancelledError:
            print("user_input cancelled.")
        except Exception as e:
            print(f"An error occurred in user_input: {e}")
        finally:
            print("user_input finalized.")

async def main():

    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']

    ICS_client = AMQclass(ip_addr, idname, pwd, 'ICS', 'ics.ex')
    await ICS_client.connect()
    await ICS_client.define_producer()
    await ICS_client.define_consumer()
    kspecics=kspecicsclass()
    
    try:
        await asyncio.gather(kspecics.user_input(ICS_client),kspecics.response_act(ICS_client))
    except asyncio.CancelledError:
        print("Main coroutine cancelled.")
    except Exception as e:
        print(f"An error occurred in main: {e}")
    finally:
        # Ensure RabbitMQ connection is properly closed
        if ICS_client:
            await ICS_client.disconnect()
            print("Main finalized")


if __name__ == "__main__":
    if sys.argv[1] == 'ics':
        try:
            asyncio.run(main())  # Run the main coroutine
        except KeyboardInterrupt:
            print("Program terminated by User.")
        except SystemExit:
            print("System exit called.")

    if sys.argv[1] == 'GFA':
        from GFA import GFA_server
        asyncio.run(GFA_server.main())

    if sys.argv[1] == 'ADC':
        from ADC import ADC_server
        asyncio.run(ADC_server.main())

    if sys.argv[1] == 'FBP':
        from FBP import FBP_server
        asyncio.run(FBP_server.main())

    if sys.argv[1] == 'MTL':
        from MTL import MTL_server
        asyncio.run(MTL_server.main())

    if sys.argv[1] == 'SPECTRO':
        from SPECTRO import SPEC_server
        asyncio.run(SPEC_server.main())

    if sys.argv[1] == 'LAMP':
        from LAMP import LAMP_server
        asyncio.run(LAMP_server.main())

    if sys.argv[1] == 'ENDO':
        from ENDO import ENDO_server
        asyncio.run(ENDO_server.main())

    if sys.argv[1] == 'ADCsimul':
        from ADC.Simul import ADC_server
        asyncio.run(ADC_server.main())



