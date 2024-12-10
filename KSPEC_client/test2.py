import os, sys

sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import asyncio
from Lib.AMQ import *
import aio_pika
import configparser as cp

cfg = cp.ConfigParser()
cfg.read("../Lib/KSPEC.ini")
ip_addr = cfg.get("MAIN", "ip_addr")
idname = cfg.get("MAIN", "idname")
pwd = cfg.get("MAIN", "pwd")

ICS_client = AMQclass(ip_addr, idname, pwd, 'ICS', 'ics.ex')
asyncio.run(ICS_client.connect())

