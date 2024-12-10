import asyncio
import aio_pika
import threading
import json
import uuid


class Client():
    def __init__(self,ipaddr,idname,password):
        self.ipaddr=ipaddr
        self.id=idname
        self.pw=password
        self.futures = {}

    async def connect(self):
        self.connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
        self.channel = await self.connection.channel()

        self.callback_queue = await self.channel.declare_queue(exclusive=True)
        await self.callback_queue.consume(self.on_response, no_ack=True)
  
    async def on_response(self,message):
        if self.futures.get(message.correlation_id):
            future = self.futures.pop(message.correlation_id)
            future.set_result(message.body)
#            return await future
 
    async def send_message(self, device, message):
        corr_id=str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        self.futures[corr_id] = future

        await self.channel.default_exchange.publish(
#                aio_pika.Message(body=message.encode()),
                aio_pika.Message(body=message.encode(),correlation_id=corr_id),
                routing_key=f'{device}_queue',
            )
        print(f" [ICS] Sent command to device '{device}'")
        return await future

    async def receive_response(self):
        self.queue = await self.channel.declare_queue('client_queue')
        async with self.queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    return message.body

class UDPClientProtocol:
    def __init__(self, on_con_lost):
        self.on_con_lost = on_con_lost  # Future to signal connection lost

    def connection_made(self, transport):
        self.transport = transport  # Save the transport for sending data

    def datagram_received(self, data, addr):
        print(f"From server: {data.decode()}")  # Print received message

    def error_received(self, exc):
        print(f"Error received: {exc}")
        if not self.on_con_lost.done():
            self.on_con_lost.set_result(True)  # Signal the connection is lost on error

    def connection_lost(self, exc):
        print("Connection closed.")
        if not self.on_con_lost.done():
            self.on_con_lost.set_result(True)  # Signal the connection is lost on close



#class TCSclient():
#    def __init__(self,host,port):
#        self.host=host
#        self.port=port
#        self.reader=None
#        self.writer=None

#    async def connect(self):
#        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
#        print('Connected to the server')
#        await self.send_message("START")

#    async def send_message(self, message):
#        print(f'Sending: {message}')
#        self.writer.write((message + "\n").encode())
#        await self.writer.drain()

#    async def receive_message(self):
#        try:
#            while True:
#                data = await self.reader.readline()
#                print(f"Received: {data.decode().strip()}")
#        except asyncio.CancelledError:
#            print("Connection closed by server")
#        finally:
#            self.close_connection()

#    async def user_input(self):
#        loop = asyncio.get_event_loop()
#        while True:
#            message = await loop.run_in_executor(None, input, "")
#            await self.send_message(message)

#    def close_connection(self):
#        if self.writer:
#            self.writer.close()
#            print("Connection closed")

#    async def run(self):
#        await self.connect()
#        await asyncio.gather(self.receive_message(), self.user_input())



class Server():
    def __init__(self,ipaddr,idname,password,device_name):
        self.queue_name=device_name
        self.ipaddr=ipaddr
        self.id=idname
        self.pw=password
        self.stop_event = asyncio.Event()

    async def connect(self):
        self.connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
        self.channel = await self.connection.channel()
        self.exchange = self.channel.default_exchange
        self.queue = None 


#    async def send_loopresponse(self, device,response):
#        connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
#        async with connection:
#            channel = await connection.channel()
#            while not self.stop_event.is_set():
#                await channel.default_exchange.publish(
#                    aio_pika.Message(body=response.encode()),
#                    routing_key='client_queue',
#                )
#                await asyncio.sleep(3)  # Wait for ??? seconds : Interval Time to send response
#                print(f" [{device}] Sent response to Client")

    async def send_loopresponse(self, device,itmax,function):
        connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
        async with connection:
            channel = await connection.channel()
            itn=0
            while not self.stop_event.is_set():
                response=await function()
                if itn==itmax:
                    await channel.default_exchange.publish(
                    aio_pika.Message(body=response.encode()),
                    routing_key='client_queue',
                    )
                    print(f" [{device}] Sent response to Client")
                    itn=0
                itn=itn+1
                await asyncio.sleep(2)  # Wait for ??? seconds : Interval Time to send response

    async def loop_start_stop(self,device,msg,itmax,function):
        if msg != 'stop':
#            print(function)
            asyncio.create_task(self.send_loopresponse(device,itmax,function))
        elif msg == 'stop':
            self.stop_event.set()
            await asyncio.sleep(5)  # Wait for ??? second to ensure all tasks are completed. 
                                    # This time should be longer than interval time to send response in send_looprespons function.
            self.stop_event.clear()  # Reset stop_event for future messages

    async def receive_message(self,device):
        self.queue = await self.channel.declare_queue(f'{device}_queue')
        async with self.queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    print(f"[{device}] {device} Server received command")#, message.body.decode())
                    return message,message.body

    async def send_response(self, device, msgtot, response):
#        async with self.queue.iterator() as queue_iter:
#            async for message in queue_iter:
        await self.exchange.publish(
            aio_pika.Message(body=response.encode(),correlation_id=msgtot.correlation_id),
            routing_key=msgtot.reply_to,
            )
        print(f" [{device}] Sent response to Client")
#        await connection.close()

    async def run(self):
        await self.receive_start_stop_message()


if __name__ == "__main__":
    client = Client()
    server = Server()
    asyncio.run(server.run())
    asyncio.run(client.run())

