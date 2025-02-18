import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import asyncio
import socket

tele_num = 150
TELID = 'KMTNET'
SYSID = 'TCS'
PID = '123'

def RequestALL(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} REQUEST ALL'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

def RequestHA(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} REQUEST HA'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

def RequestRA(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} REQUEST RA'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

def RequestDEC(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} REQUEST DEC'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data(1024)
    return recv

def RequestEL(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} REQUEST EL'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data(1024)
    return recv

def RequestAZ(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} REQUEST AZ'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data(1024)
    return recv

def RequestSECZ(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} REQUEST SECZ'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data(1024)
    return recv

def CommandNEXTRA(self,ra):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} COMMAND NEXTRA {ra}\r\n'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

def CommandNEXTDEC(self,dec):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} COMMAND NEXTDEC {dec}'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

def CommandMVNEXT(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} COMMAND MOVNEXT\r\n'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

def CommandMVSTOW(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} COMMAND MOVSTOW\r\n'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

def CommandMVELAZ(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} COMMAND ELAZ\r\n'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

def CommandMVSTOP(self):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} COMMAND CANCEL\r\n'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

def CommandTRACK(self,bools):
    cmd = f'{self.TELID} {self.SYSID} {self.PID} COMMAND TRACK {bools}\r\n'
    print('Telescope request cmd :', cmd)
    self.clientsocket.send(cmd.encode())
    recv=self.recv_data()
    return recv

