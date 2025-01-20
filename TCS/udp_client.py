import asyncio

class UDPClientProtocol:
    def __init__(self, on_con_lost):
        self.on_con_lost = on_con_lost

    def connection_made(self, transport):
        self.transport = transport
        asyncio.create_task(self.send_messages())

    async def send_messages(self):
        while True:
            message = await asyncio.get_event_loop().run_in_executor(None, input, 
							"Input command: ")
            self.transport.sendto(message.encode())
            if message.lower() == "quit":
                self.transport.close()
                self.on_con_lost.set_result(True)
                break

    def datagram_received(self, data, addr):
        print(f"From server: {data.decode()}")

    def error_received(self, exc):
        print(f'error : {exc}')
        if not self.on_con_lost.done():
            self.on_con_lost.set_result(True)

    def connection_lost(self, exc):
        print("Connection closed.")
        if not self.on_con_lost.done():
            self.on_con_lost.set_result(True)

async def main():
    loop = asyncio.get_running_loop()
    on_con_lost = loop.create_future()

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UDPClientProtocol(on_con_lost),
        remote_addr=('192.168.13.108', 6606)
    )

    try:
        await on_con_lost
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())

