import sys
import os

from Lib.AMQ import AMQclass, UDPClientProtocol, TCPClient
from TCS.tcscli import handle_telcom
import asyncio

async def send_telcom_command(message):
    """Sends a command to the Telcom system via TCP."""
    telcom_client = TCPClient('127.0.0.1',8889)
    await telcom_client.connect()
    result = await handle_telcom(message,telcom_client)
    await telcom_client.close()
    return result


async def getra():
    msg='getra'
    result= await send_telcom_command(msg)
    print(result.decode())

async def stepra():
    msg = 'stepra 0067'
    result= await send_telcom_command(msg)
    print(result.decode())

async def stepdec():
    msg = 'stepdec -0089'
    result= await send_telcom_command(msg)
    print(result.decode())

if __name__ == "__main__":
    asyncio.run(stepdec())
