import asyncio

class UDPServerProtocol:
    def __init__(self):
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        print("UDP server up and listening")

    def datagram_received(self, data, addr):
        message = data.decode()
        print(message)
        print(f"Received {message} from {addr}")
        response = f"Echo: {message}"
        self.transport.sendto(response.encode(), addr)

async def main():
    loop = asyncio.get_running_loop()
    listen = loop.create_datagram_endpoint(
        UDPServerProtocol, local_addr=('127.0.0.1', 12345))
    transport, protocol = await listen

    try:
        await asyncio.sleep(3600)  # 서버를 1시간 동안 실행
    finally:
        transport.close()

if __name__ == '__main__':
    asyncio.run(main())

