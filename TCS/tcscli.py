import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
from .tcscore import *
import asyncio
import socket


with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

TelcomIP = kspecinfo['TCS']['TelcomIP']
TelcomPort = kspecinfo['TCS']['TelcomPort']

class Telcomclass():
    def __init__(self):
        self.tele_num = 150
        self.TELID = 'KMTNET'
        self.SYSID = ' TCS'
        self.PID = '123'
        self.host = TelcomIP
        self.port = int(TelcomPort)

    def TelcomConnect(self):
        self.clientsocket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        
        try:
            self.clientsocket.connect((self.host,self.port))
            return True
        except OSError:
            print('Connection to Telcom fail')
            return False

    def TelcomDisconnect(self):
        print('Telcom socket close')
        try:
            self.clientsocket.close()
            print('Telcom disconnected OK')
            return True
        except:
            print('Telcom disconnected fail')
            return False

    def recv_data(self):
        data=self.clientsocket.recv(1024)
        return data

    def RequestRA(self):
        cmd = f'REQUEST RA'
        print('Telescope request cmd :', cmd)
        self.clientsocket.send(cmd.encode())
        RA=self.recv_data()
        return RA

    def RequestDEC(self):
        cmd = f'REQUEST DEC'
        print('Telescope request cmd :', cmd)
        self.clientsocket.send(cmd.encode())
        DEC=self.recv_data()
        return DEC

"""
async def tcp_client(message):
    host='127.0.0.1'
    port='8888'
    reader, writer = await asyncio.open_connection(host, port)

    print(f'Connected to server at {host}:{port}')

    try:
        writer.write(message.encode())
        await writer.drain()
            
        print('Message sent, waiting for response...')
        response = await reader.read(1024)
        print(f'Received from server: {response.decode()}')

    except KeyboardInterrupt:
        print("Client stopped.")
    finally:
        print('Closing the connection')
        writer.close()
        await writer.wait_closed()

#    TCS_client=TCSclient('127.0.0.1','8888')
#    await TCS_client.connect()

def tcs_tra(ra,dec):
#    TCS_client=Client('kspecadmin','kasikspec','TCS')
    TCSmsg=tcs_trafun(ra,dec)
    return TCSmsg
#    asyncio.run(TCS_client.send_message('TCS',TCSmsg))


async def trafun(cmd):
    tcsclient=TCSclient('127.0.0.1', '8888')
    await tcsclient.connect()
    await tcsclient.send_message(cmd)
#    asyncio.run(tcp_client(cmd))
#    TCS_client=TCSclient(
#    TCS_client.connect()
#    asyncio.run(TCS_client.send_message(cmd))

#    asyncio.run(TCS_client.receive_message())

async def tcsstart(cmd):
    tcsclient=TCSclient('127.0.0.1', '8888')
    await tcsclient.connect()
    await tcsclient.send_message(cmd)
"""
