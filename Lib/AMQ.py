import asyncio
import aio_pika
import threading
import json
import uuid
import socket

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
        self.stop_event = None
        self.mission = False
        self.heartbeat_interval = 60

    async def connect(self):
        self.connection = await aio_pika.connect_robust(host=self.ipaddr,login=self.id,password=self.pw,heartbeat=self.heartbeat_interval)
        self.channel = await self.connection.channel()
        print('RabbitMQ server connected', flush=True)

    async def disconnect(self):
        """Safely disconnect the RabbitMQ connection and close channels."""
        try:
            # Unbind and delete the queue if it exists
            if self.queue:
                await self.queue.unbind(self.cmd_exchange)
                await self.queue.delete()
                print("Queue unbound and deleted.", flush=True)

            # Close the channel if it exists
            if self.channel:
                await self.channel.close()
                print("Channel closed.", flush=True)

            # Close the connection if it exists
            if self.connection:
                await self.connection.close()
                print("RabbitMQ connection closed.", flush=True)
        except Exception as e:
            print(f"Error during RabbitMQ disconnect: {e}", flush=True)

    async def define_producer(self):
        self.cmd_exchange = await self.channel.declare_exchange(self.exchange, aio_pika.ExchangeType.DIRECT)
        print(f'{self.exchange} exchange was defined', flush=True)

    async def send_message(self, _routing_key, message):
        await self.cmd_exchange.publish(
                aio_pika.Message(body=message.encode()),
                routing_key=_routing_key,
            )
        dict_data=json.loads(message)
        print(f"\033[32m[{self.im}] sent message to device '{_routing_key}'. message: {dict_data['message']}\033[0m", flush=True)

    async def define_consumer(self):
        if self.queue is None:
            self.cmd_exchange = await self.channel.declare_exchange(self.exchange, aio_pika.ExchangeType.DIRECT)
            self.queue = await self.channel.declare_queue(f'{self.im}_queue',durable=True)

    async def receive_message(self,_routing_key):
        await self.queue.bind(self.cmd_exchange,routing_key=_routing_key)
        async with self.queue.iterator() as qiterator:
            async for message in qiterator:
                async with message.process():
                    print(f'\n{_routing_key} Server received message', flush=True) #, message.body.decode())
                    return message.body

#    async def start_guidingloop(self, _routing_key,itmax,function,subserver):    ### For autoguiding
#        itn=0
#        while not self.stop_event.is_set():
#            response=await function(subserver)
#            if response != None:
#                if itn==itmax or response['thred'] > 7:
#                    response=json.dumps(response)
#                    await self.cmd_exchange.publish(
#                    aio_pika.Message(body=response.encode()),
#                    routing_key=_routing_key,
#                    )
#                    print(f"{self.im} Sever sent message to '{_routing_key}'")
#                    itn=0
#                itn=itn+1
#            await asyncio.sleep(2)  # Wait for ??? seconds : Interval Time to send response

#    async def guiding_start_stop(self,_routing_key,msg,itmax,function,subserver):
#        if msg != 'stop':
#            asyncio.create_task(self.start_guidingloop(_routing_key,itmax,function,subserver))
#        elif msg == 'stop':
#            self.stop_event.set()
#            await asyncio.sleep(2)  # Wait for ??? second to ensure all tasks are completed.
                                    # This time should be longer than interval time to send response in send_looprespons function.
#            self.stop_event.clear()  # Reset stop_event for future messages


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



# Async TCP Client
class TCPClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            print(f"Connected to {self.host}:{self.port}")
        except Exception as e:
            print(f"Connection error: {e}")

    async def send_receive(self, message):
        try:
            self.writer.write(message.encode())
            await self.writer.drain()
            print(f"Sent: {message}")

            data = await self.reader.read(1024)
            print(f"Received: {data.decode()}")
            return data
        except Exception as e:
            print(f"Error: {e}")

    async def close(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            print("Connection closed.")

