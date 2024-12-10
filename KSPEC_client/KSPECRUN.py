import os, sys

sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import asyncio
from Lib.AMQ import *
from command import *
import aio_pika
import configparser as cp
import Lib.process as processes



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


    async def response_act(self,ICS_client):
        while True:
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
                file_path = (
                    "../inputdata/etc/"
                    + dict_data["filename"]
                )
                with open(file_path, "w") as f:
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

    async def user_input(self,ICSclient):
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
                self.transport.close()  # Close the connection
                await on_con_lost  # Wait until the connection is closed
                break

            else:
                await identify(message,ICSclient,self.transport)
#    finally:
#        transport.close()  # Ensure transport is closed

async def main():
    cfg = cp.ConfigParser()
    cfg.read("../Lib/KSPEC.ini")
    ip_addr = cfg.get("MAIN", "ip_addr")
    idname = cfg.get("MAIN", "idname")
    pwd = cfg.get("MAIN", "pwd")

    ICS_client = AMQclass(ip_addr, idname, pwd, 'ICS', 'ics.ex')
    await ICS_client.connect()
    await ICS_client.define_producer()
    await ICS_client.define_consumer()
    kspecics=kspecicsclass()
    await asyncio.gather(kspecics.user_input(ICS_client),kspecics.response_act(ICS_client))
#    await asyncio.gather(temp.user_input(ICS_client))



if __name__ == "__main__":
    asyncio.run(main())  # Run the main coroutine
