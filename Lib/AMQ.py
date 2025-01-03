import asyncio
import aio_pika
import threading
import json
import uuid


class AMQclass():
    def __init__(self,ipaddr,idname,password,whoami,exchange):
        self.ipaddr=ipaddr
        self.id=idname
        self.pw=password

        self.im=whoami
        self.exchange = exchange
        self.queue = None
        self.channel = None
        self.connection = None
        self.futures = {}
        self.stop_event = asyncio.Event()
        self.mission = False

    async def connect(self):
        self.connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw)
        self.channel = await self.connection.channel()
        print('RabbitMQ server connected')

    async def define_producer(self):
        self.cmd_exchange = await self.channel.declare_exchange(self.exchange, aio_pika.ExchangeType.DIRECT)
        print(f'{self.exchange} exchange was defined')

    async def send_message(self, _routing_key, message):
        await self.cmd_exchange.publish(
                aio_pika.Message(body=message.encode()),
                routing_key=_routing_key,
            )
        print(f"{self.im} sent message to device '{_routing_key}'")

    async def define_consumer(self):
        if self.queue is None:
            self.cmd_exchange = await self.channel.declare_exchange(self.exchange, aio_pika.ExchangeType.DIRECT)
            self.queue = await self.channel.declare_queue(f'{self.im}_queue',durable=True)

    async def receive_message(self,_routing_key):
        await self.queue.bind(self.cmd_exchange,routing_key=_routing_key)
        async with self.queue.iterator() as qiterator:
            async for message in qiterator:
                async with message.process():
                    print(f'{_routing_key} Server received message') #, message.body.decode())
                    return message.body

    async def start_guidingloop(self, _routing_key,itmax,function,subserver):    ### For autoguiding
        itn=0
        while not self.stop_event.is_set():
            response=await function(subserver)
            if response != None:
                if itn==itmax or response['thred'] > 7:
                    response=json.dumps(response)
                    await self.cmd_exchange.publish(
                    aio_pika.Message(body=response.encode()),
                    routing_key=_routing_key,
                    )
                    print(f"{self.im} Sever sent message to '{_routing_key}'")
                    itn=0
                itn=itn+1
            await asyncio.sleep(2)  # Wait for ??? seconds : Interval Time to send response

    async def guiding_start_stop(self,_routing_key,msg,itmax,function,subserver):
        if msg != 'stop':
            asyncio.create_task(self.start_guidingloop(_routing_key,itmax,function,subserver))
        elif msg == 'stop':
            self.stop_event.set()
            await asyncio.sleep(2)  # Wait for ??? second to ensure all tasks are completed.
                                    # This time should be longer than interval time to send response in send_looprespons function.
            self.stop_event.clear()  # Reset stop_event for future messages


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


"""
class TCSclient():
    def __init__(self,host,port):
        self.host=host
        self.port=port
        self.reader=None
        self.writer=None

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        print('Connected to the server')
        await self.send_message("START")

    async def send_message(self, message):
        print(f'Sending: {message}')
        self.writer.write((message + "\n").encode())
        await self.writer.drain()

    async def receive_message(self):
        try:
            while True:
                data = await self.reader.readline()
                print(f"Received: {data.decode().strip()}")
        except asyncio.CancelledError:
            print("Connection closed by server")
        finally:
            self.close_connection()

#    async def user_input(self):
#        loop = asyncio.get_event_loop()
#        while True:
#            message = await loop.run_in_executor(None, input, "")
#            await self.send_message(message)

    def close_connection(self):
        if self.writer:
            self.writer.close()
            print("Connection closed")

#    async def run(self):
#        await self.connect()
#        await asyncio.gather(self.receive_message(), self.user_input())
"""
