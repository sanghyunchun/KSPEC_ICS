import asyncio
import aio_pika
import threading

class Client:
    def __init__(self):
        self.input_thread = threading.Thread(target=self.user_input_thread)
   
#    async def connection(self):
#        self.connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")

    async def send_message(self, device, message):
        connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
        async with connection:
            channel = await connection.channel()
            await channel.default_exchange.publish(
                aio_pika.Message(body=message.encode()),
                routing_key=f'{device}_queue',
            )
            print(f" [x] Sent '{message}' to device '{device}'")
            await connection.close()

#    async def close(self):
#        await self.connection.close()

    async def receive_message(self):
        connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue('client_queue')
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        print(" [x] Received ", message.body.decode())

    def user_input_thread(self):
        while True:
            user_input = input("Type 'start' to start receiving messages or 'stop' to stop: ")
            if user_input.strip().lower() in ('start', 'stop'):
                device = input("Enter the device ID (device1 or device2): ")
                message = user_input.strip().lower()
                asyncio.run(self.send_message(device, message))

    async def run(self):
        self.input_thread.start()
        await self.receive_message()

class Server:
    def __init__(self,queue_name):
        self.queue_name=queue_name

    async def send_response(self, channel, device, msg):
#        while not self.stop_event.is_set():
        await channel.default_exchange.publish(
            aio_pika.Message(body=msg),
            routing_key='client_queue',
        )
#            await asyncio.sleep(3)  # Wait for 5 seconds
        print(f" [x] Sent '{msg}' to device '{device}'")

    async def send_loopresponse(self, channel, device, msg):
        while True:
            await channel.default_exchange.publish(
                aio_pika.Message(body=msg),
                routing_key='client_queue',
            )
            await asyncio.sleep(3)  # Wait for 3 seconds
            print(f" [x] Sent '{msg}' to device '{device}'")


    async def receive_message(self,device):
        connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(f'{device}_queue')
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
#                        if message.body == b'start':
#                            for device in ('device1', 'device2'):
                        print("[x] Server receuved ", message.body.decode())
                        asyncio.create_task(self.send_hello(channel, device))
#                        elif message.body == b'stop':
#                            self.stop_event.set()
#                            print(" [x] Received 'stop'. Stopping current task...")
#                            await asyncio.sleep(1)  # Wait for 1 second to ensure all tasks are completed
#                            self.stop_event.clear()  # Reset stop_event for future messages

    async def run(self):
        await self.receive_start_stop_message()

if __name__ == "__main__":
    client = Client()
    server = Server()
    asyncio.run(server.run())
    asyncio.run(client.run())

