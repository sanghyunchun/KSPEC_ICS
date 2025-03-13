import sys
import asyncio
import json
from Lib.AMQ import AMQclass, UDPClientProtocol, TCPClient
from ADC.adccli import handle_adc
from GFA.gfacli import handle_gfa
from FBP.fbpcli import handle_fbp
from ENDO.ENDOcli import handle_endo
from MTL.mtlcli import handle_mtl
from LAMP.lampcli import handle_lamp
from SPECTRO.speccli import handle_spec
from TCS.tcscli import handle_telcom
from script.scriptcli import handle_script

class KSPECRunner:
    def __init__(self, ICS_client):
        """
        Initializes the KSPEC runner with the ICS client.
        """
        self.ICS_client = ICS_client
        self.running = True
        self.response_queue = asyncio.Queue()
        self.GFA_response_queue = asyncio.Queue()
        self.ADC_response_queue = asyncio.Queue()

        self.command_list = self.load_command_list()
        self.tcsagentIP, self.tcsagentPort, self.telcomIP, self.telcomPort = self.load_config()
        
    def load_command_list(self):
        return {
            "adc": ["adcstatus", "adcactivate", "adcadjust", "adcinit", "adcconnect", "adcdisconnect", "adchome", "adczero",
            "adcpoweroff", "adcrotate1", "adcrotate2", "adcstop", "adcpark", "adcrotateop", "adcrotatesame"],
            "gfa": ["gfastatus", "gfagrab", "gfaguidestop", "gfaguide"],
            "fbp": ["fbpstatus", "fbpzero", "fbpmove", "fbpoffset"],
            "endo": ["endoguide", "endotest", "endofocus", "endostop","endoexpset","endoclear","endostatus"],
            "mtl": ["mtlstatus", "mtlexp", "mtlcal"],
            "lamp": ["lampstatus", "arcon", "arcoff", "flaton", "flatoff","fiducialon","fiducialoff"],
            "spec": ["specstatus", "illuon", "illuoff", "getobj", "getbias", "getflat","getar"],
            "tcs": ["tmradec", "start", "stop", "tcsint", "tcsreset", "tcsclose",
            "tcsarc", "tcsstatus", "tstat", "traw", "tsync", "tcmd",
            "treg", "tmradec", "tmr", "tmobject", "tmo", "tmelaz",
            "tme", "tmoffset", "toff", "tstop", "tstow", "tdi",
            "cc", "oo", "nstset", "nston", "nstoff", "auxinit",
            "auxreset", "auxclose", "auxarc", "auxstatus",
            "astat", "acmd", "fsastat", "fs", "fttstat",
            "ft", "dfocus", "dtilt", "fttgoto"],

            "telcom": ["getall", "getra", "getdec", "getha", "getel", "getaz", "getsecz", "mvstow", "mvelaz", "mvstop", "mvra", "mvdec", "track"],
            "script": ["runcalib", "obsinitial", "autoguide", "autoguidestop", "runobs"]
            }
    
    def load_config(self):
        """Loads configuration settings from KSPEC.ini."""
        with open('./Lib/KSPEC.ini', 'r') as f:
            kspecinfo = json.load(f)

        return (
            kspecinfo['TCS']['TCSagentIP'],
            kspecinfo['TCS']['TCSagentPort'],
            kspecinfo['TCS']['TelcomIP'],
            kspecinfo['TCS']['TelcomPort']
        )

    def find_category(self, cmd):
        """Finds the category of a given command."""
        return next((cat for cat, cmds in self.command_list.items() if cmd in cmds), None)

    async def wait_for_response(self):
        """
        Waits for responses from the K-SPEC sub-system and distributes then appropriately.
        """
        while self.running:
            try:
                response = await self.ICS_client.receive_message("ICS")
                response_data = json.loads(response)
                message=response_data.get('message','No message')
#                print(response_data)

                if isinstance(message,dict):
                    message = json.dumps(message, indent=2)
                    print(f'\033[94m[ICS] received: {message}\033[0m', flush=True)
                else:
                    print('\033[94m' + '[ICS] received: ', response_data['message'] + '\033[0m', flush=True)

                queue_map = {"GFA": self.GFA_response_queue, "ADC": self.ADC_response_queue}
                if response_data['inst'] in queue_map and response_data['process'] == 'ING':
                    await queue_map[response_data['inst']].put(response_data)
                else:
                    await self.response_queue.put(response_data)
            except Exception as e:
                print(f"Error in wait_for_response: {e}", flush=True)

    async def send_udp_message(self, message):
        """
        Sends a message to the TCS Agent via UDP using UDPClientProtocol 
        """
        loop = asyncio.get_running_loop()
        on_con_lost = loop.create_future()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: UDPClientProtocol(on_con_lost),
            remote_addr=(self.tcsagentIP, self.tcsagentPort)
        )

        print(f"\033[32m[ICS] sent TCS message to TCS Agent: {message}\033[0m", flush=True)
        transport.sendto(message.encode())
        transport.close()        

    async def send_telcom_command(self,message):
        """Sends a command to the Telcom system via TCP."""
        telcom_client = TCPClient(self.telcomIP,self.telcomPort)
        await telcom_client.connect()
        result = await handle_telcom(message,telcom_client)
        await telcom_client.close()
        return result

    async def send_command(self, category, message):
        """
        Sends a command using the respective handler.
        """
 #       print(f"Sending command: {message}")
        handler_map = {
            "adc": handle_adc, "gfa": handle_gfa, "fbp": handle_fbp,
            "endo": handle_endo, "mtl": handle_mtl, "lamp": handle_lamp,
            "spec": handle_spec, "script": handle_script
        }
        if category in handler_map:
            await handler_map[category](message, self.ICS_client)
        else:
            print(f"Unknown command category: {category}",flush=True)

    async def user_input(self):
        """
        Handles user input asynchronously, allowing immediate command sending.
        """
        while self.running:
            try:
                message = await asyncio.get_event_loop().run_in_executor(None, input, "Input command: ")
                if message.lower() == "quit":
                    print("Exiting user input mode.")
                    self.running = False
                    break

                cmd = message.split(" ")[0]
                category = self.find_category(cmd)
                print(f'Command Category is {category}')

                if category:
                    if category.lower() == 'tcs':
                        messagetcs = 'KSPEC>TC ' + message
                        await self.send_udp_message(messagetcs)
                    elif category.lower() == 'telcom':
                        telcom_result = await self.send_telcom_command(message)
                        print('\033[94m' + '[ICS] received: ', telcom_result.decode() + '\033[0m', flush=True)
                    elif category.lower() == "script":
                        await handle_script(message, self.ICS_client, self.send_udp_message, self.send_telcom_command, self.response_queue, self.GFA_response_queue, self.ADC_response_queue)
                    else:
                        await self.send_command(category, message)
                else:
                    print("Invalid command. Please enter a valid command.\n")
            except Exception as e:
                print(f"Error in user_input: {e}")

async def main():
    """
    Main function to initialize and run KSPECRunner.
    """
    try:
        with open('./Lib/KSPEC.ini', 'r') as f:
            kspecinfo = json.load(f)

        ICS_client = AMQclass(
            kspecinfo['RabbitMQ']['ip_addr'],
            kspecinfo['RabbitMQ']['idname'],
            kspecinfo['RabbitMQ']['pwd'],
            'ICS', 'ics.ex'
        )
        await ICS_client.connect()
        await ICS_client.define_producer()
        await ICS_client.define_consumer()

        runner = KSPECRunner(ICS_client)
        await asyncio.gather(runner.user_input(), runner.wait_for_response())
    except Exception as e:
        print(f"Error in main: {e}")
    finally:
        await ICS_client.disconnect()
        print("Main finalized.")

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

    if sys.argv[1] == 'SPEC':
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

    if sys.argv[1] == 'GFAsimul':
        from GFA.Simul import GFA_server
        asyncio.run(GFA_server.main())

    if sys.argv[1] == 'ENDOsimul':
        from ENDO.Simul import ENDO_server
        asyncio.run(ENDO_server.main())

    if sys.argv[1] == 'MTLsimul':
        from MTL.Simul import MTL_server
        asyncio.run(MTL_server.main())
