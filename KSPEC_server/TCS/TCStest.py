import asyncio
from TCScore import *

class TCPServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.server = None

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"Connected to {addr}")

        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                message = data.decode()
                print(f"Received from {addr}: {message}")

                mmm=tra()

                writer.write(mmm.encode())
                await writer.drain()
        except asyncio.CancelledError:
            pass
        finally:
            print(f"Disconnected from {addr}")
            writer.close()
            await writer.wait_closed()

    async def start_server(self):
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addr = self.server.sockets[0].getsockname()
        print(f"Serving on {addr}")

        async with self.server:
            await self.server.serve_forever()

    def close(self):
        if self.server:
            self.server.close()





if __name__ == '__main__':
    host = '127.0.0.1'  # 서버 IP 주소
    port = 8888         # 서버 포트

    server = TCPServer(host, port)
    
    try:
        asyncio.run(server.start_server())
    except KeyboardInterrupt:
        print("Server stopped.")
        server.close()

