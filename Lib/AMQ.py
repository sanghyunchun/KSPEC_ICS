import asyncio
import aio_pika
import threading

class Client():
    def __init__(self,ipaddr,idname,password):
#        self.queue_name=device_name
        self.ipaddr=ipaddr
        self.id=idname
        self.pw=password
#        self.receive_tread=threading.Thread(target=self.receive_response)
#        self.input_thread = threading.Thread(target=self.user_input_thread)
   
    async def send_message(self, device, message):
        connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
        async with connection:
            channel = await connection.channel()
            await channel.default_exchange.publish(
                aio_pika.Message(body=message.encode()),
                routing_key=f'{device}_queue',
            )
            print(f" [ICS] Sent command to device '{device}'")
            await connection.close()

    async def receive_response(self):
        connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue('client_queue')
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        print(" [ICS] Received ", message.body.decode())

#    def receive_response(self):
#        print('tttt')
#        connection = asyncio.run(aio_pika.connect_robust("amqp://guest:guest@localhost/"))
#        channel = connection.channel()
#        queue = asyncio.run(channel.declare_queue('client_queue'))

#        async def _receive():
#            async for message in queue:
#                async with message.process():
#                    print("Received response from server:", message.body.decode())

#        asyncio.run(_receive())


#async with queue.iterator() as queue_iter:
#            async for message in queue_iter:
#                async with message.process():
#                    print(" [x] Received ", message.body.decode())

#    def start_thread(self):
#        self.receive_tread.start()

#    def user_input_thread(self):
#        while True:
#            user_input = input("Type 'start' to start receiving messages or 'stop' to stop: ")
#            if user_input.strip().lower() in ('start', 'stop'):
#                device = input("Enter the device ID (device1 or device2): ")
#                message = user_input.strip().lower()
#                asyncio.run(self.send_message(device, message))

#    async def run(self):
#        self.input_thread.start()
#        await self.receive_message()

class Server():
    def __init__(self,ipaddr,idname,password,device_name):
        self.queue_name=device_name
        self.ipaddr=ipaddr
        self.id=idname
        self.pw=password
        self.stop_event = asyncio.Event()
        print(self.id)


    async def send_response(self, device, response):
        connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
        async with connection:
            channel = await connection.channel()
            await channel.default_exchange.publish(
                aio_pika.Message(body=response.encode()),
                routing_key='client_queue',
            )
            print(f" [{device}] Sent response to Client")
            await connection.close()


    async def send_loopresponse(self, device,response):
#        print('ok good')
        connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
        async with connection:
            channel = await connection.channel()
            while not self.stop_event.is_set():
                await channel.default_exchange.publish(
                    aio_pika.Message(body=response.encode()),
                    routing_key='client_queue',
                )
                await asyncio.sleep(3)  # Wait for ??? seconds : Interval Time to send response
                print(f" [{device}] Sent response to Client")

    async def loop_start_stop(self,device,response):
        if response != 'stop':
            asyncio.create_task(self.send_loopresponse(device,response))
        elif response == 'stop':
            self.stop_event.set()
            await asyncio.sleep(5)  # Wait for ??? second to ensure all tasks are completed. 
                                    # This time should be longer than interval time to send response in send_looprespons function.
            self.stop_event.clear()  # Reset stop_event for future messages


    async def receive_message(self,device):
        connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(f'{device}_queue')
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        print(f"[{device}] {device} Server received command")#, message.body.decode())
                        return message.body

    async def run(self):
        await self.receive_start_stop_message()

if __name__ == "__main__":
    client = Client()
    server = Server()
    asyncio.run(server.run())
    asyncio.run(client.run())

