import sys
import os
import asyncio

from Lib.AMQ import AMQclass, UDPClientProtocol, TCPClient
from SPECTRO.speccli import handle_spec



class KSPECRunner:
    def __init__(self, ICS_client):
        """
        Initializes the KSPEC runner with the ICS client.
        """
        self.ICS_client = ICS_client
        self.observer = None
        self.running = True
        self.response_queue = asyncio.Queue()
        self.SPEC_response_queue = asyncio.Queue()

        self.command_list = self.load_command_list()
        self.tcsagentIP, self.tcsagentPort, self.telcomIP, self.telcomPort = self.load_config()
        self.scriptrun = script()


#    @asyncSlot()
    async def send_command(self, category, message):
        """
        Sends a command using the respective handler.
        """
        category = category.lower()

        general_handlers = {
            "adc": handle_adc, "gfa": handle_gfa, "fbp": handle_fbp,
            "mtl": handle_mtl, "lamp": handle_lamp,
            "spec": handle_spec,
        }

        if category == "utils":
            self.handle_utils(message)
            return

        if category == "script":
            await handle_script(message, scriptrun=self.scriptrun, logging=self.logging)
            return

        handler = general_handlers.get(category)
        if handler is None:
            print(f"Unknown command category: {category}", flush=True)
            return

        await handler(message, self.ICS_client)




     ### User input command like CLI ###
    @asyncSlot()
    async def user_input(self):
        """
        Handles user input asynchronously, allowing immediate command sending.
        """
        try:
            sys.stdout.flush()

            message = self.ui.lineEdit_cmd.text().strip() or self.ui.lineEdit_cmd_2.text().strip()
                
            cmd = message.split(" ")[0]
            category = self.find_category(cmd)
            print(f'Command Category is {category}', flush=True)

            if category:
                if category.lower() == 'tcs':
                    messagetcs = 'KSPEC>TC ' + message
                    await self.send_udp_message(messagetcs)
                    self.ui.lineEdit_cmd.clear()
                    self.ui.lineEdit_cmd_2.clear()
                elif category.lower() == 'telcom':
                    telcom_result = await self.send_telcom_command(message)
                    print('\033[94m' + '[ICS] received: ', telcom_result.decode() + '\033[0m', flush=True)
                    self.logging(telcom_result.decode(), level='receive')
                else:
                    await self.send_command(category, message)

                self.ui.lineEdit_cmd.clear()
                self.ui.lineEdit_cmd_2.clear()
            else:
                print("Invalid command. Please enter a valid command.\n", flush=True)
        except Exception as e:
            print(f"Error in user_input: {e}", flush=True)       



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

        runner = KSPECRunner(ICS_client)
        await ICS_client.define_consumer('ICS',runner.on_ics_message)
        await asyncio.gather(runner.user_input())

    except Exception as e:
        print(f"Error in main: {e}", flush=True)
    finally:
        runner.running = False
        if hasattr(runner,"autoguide_task") and runner.autoguide_task  and not runner.autoguide_task.done():
            runner.autoguide_task.cancel()
            try:
                await runner.autoguide_task
            except asyncio.CancelledError:
                print("Autoguide task was cancelled on shutdown", flush=True)

        await ICS_client.disconnect()
        print("Main finalized.", flush=True)



if __name__ == "__main__":
    if sys.argv[1] == 'ics':
        try:
            asyncio.run(main())  # Run the main coroutine
        except KeyboardInterrupt:
            print("Program terminated by User.")
        except SystemExit:
            print("System exit called.")
