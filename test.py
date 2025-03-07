import asyncio
import json
from Lib.AMQ import AMQclass
from ADC.adccli import handle_adc
from GFA.gfacli import handle_gfa
from FBP.fbpcli import handle_fbp
from ENDO.ENDOcli import handle_endo
from MTL.mtlcli import handle_mtl
from LAMP.lampcli import handle_lamp
from SPECTRO.speccli import handle_spec

class KSPECRunner:
    def __init__(self, ICS_client):
        """
        Initializes the KSPEC runner with the ICS client.
        """
        self.ICS_client = ICS_client
        self.running = True
        self.response_queue = asyncio.Queue()  # 여러 개의 응답을 저장할 큐
        self.command_list = {
            "adc": ["adcstatus", "adcactivate", "adcadjust", "adcinit"],
            "gfa": ["gfastatus", "gfagrab", "gfastop", "gfaguide"],
            "fbp": ["fbpstatus", "fbpzero", "fbpmove", "fbpoffset"],
            "endo": ["endoguide", "endotest", "endofocus", "endostop"],
            "mtl": ["mtlstatus", "mtlexp", "mtlcal"],
            "lamp": ["lampstatus", "arcon", "arcoff", "flaton", "flatoff"],
            "spec": ["specstatus", "illuon", "illuoff", "getobj", "getbias"]
        }

    async def send_command(self, category, message):
        """
        Sends a command using the respective handler.
        """
        print(f"Sending command: {message}")
        handler_map = {
            "adc": handle_adc,
            "gfa": handle_gfa,
            "fbp": handle_fbp,
            "endo": handle_endo,
            "mtl": handle_mtl,
            "lamp": handle_lamp,
            "spec": handle_spec
        }

        if category in handler_map:
            await handler_map[category](message, self.ICS_client)
        else:
            print(f"Unknown command category: {category}")

    async def wait_for_response(self):
        """
        Continuously waits for responses from the ICS system.
        """
        while self.running:
            try:
                response = await self.ICS_client.receive_message("ICS")
                response_data = json.loads(response)
                print(f"Received response: {response_data}")
                await self.response_queue.put(response_data)  # 응답을 큐에 저장
            except Exception as e:
                print(f"Error in wait_for_response: {e}")

    async def process_responses(self):
        """
        Processes responses from the response queue.
        """
        while self.running:
            response_data = await self.response_queue.get()  # 응답 큐에서 꺼내서 처리
            print(f"Processed response: {response_data}")
            self.response_queue.task_done()

    async def user_input(self):
        """
        Handles user input asynchronously, allowing immediate command sending.
        """
        while self.running:
            try:
                message = await asyncio.get_event_loop().run_in_executor(None, input, "\nInput command: ")
                if message.lower() == "quit":
                    print("Exiting user input mode.")
                    self.running = False
                    break

                cmd_parts = message.split(" ", 1)
                if len(cmd_parts) == 2:
                    category, command = cmd_parts
                    if category in self.command_list and command in self.command_list[category]:
                        await self.send_command(category, command)
                    else:
                        print("Invalid command. Please enter a valid category and command.")
                else:
                    print("Invalid input format. Use: <category> <command>")
            except Exception as e:
                print(f"Error in user_input: {e}")

    async def run(self):
        """
        Main execution function.
        """
        try:
            await asyncio.gather(self.user_input(), self.wait_for_response(), self.process_responses())
        except asyncio.CancelledError:
            print("Task cancelled.")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            print("Runner finalized.")

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
        await runner.run()

    except Exception as e:
        print(f"Error in main: {e}")
    finally:
        await ICS_client.disconnect()
        print("Main finalized.")

if __name__ == "__main__":
    asyncio.run(main())

