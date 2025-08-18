import asyncio

# Async TCP Server
class AsyncTCPServer:
    def __init__(self, host='127.0.0.1', port=8889):
        self.host = host
        self.port = port

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"Connected by {addr}")
        
        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                message = data.decode()
                print(f"Received from {addr}: {message}")
                cmd=message.split(" ")

                if cmd[4] == 'RA':
                    answer='310.4567'
                elif cmd[4] == 'DEC':
                    answer='-31.4455'

                writer.write(answer.encode())
                await writer.drain()
        except Exception as e:
            print(f"Error with client {addr}: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            print(f"Connection closed for {addr}")

    async def start_server(self):
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addr = server.sockets[0].getsockname()
        print(f"Server listening on {addr}")
        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    server = AsyncTCPServer()
    asyncio.run(server.start_server())

