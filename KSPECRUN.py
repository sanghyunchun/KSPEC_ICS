#!/usr/bin/env python
# -*- coding: utf-8 -*- 
#
# @Author: Sang-Hyun Chun (shyunc@kasi.re.kr)
# @Date: 2025-02-22
# @Filename: KSPECRUN.py

import os
import sys
import asyncio
from Lib.AMQ import *
#from icscommand import *
from ADC.adccli import handle_adc
from GFA.gfacli import handle_gfa
from FBP.fbpcli import handle_fbp
from ENDO.ENDOcli import handle_endo
from MTL.mtlcli import handle_mtl
from LAMP.lampcli import handle_lamp
from SPECTRO.speccli import handle_spec
from script.scriptcli import handle_script
from TCS.telcomcli import handle_telcom 
import aio_pika
import Lib.process as processes
import json

class kspecicsclass:
    """
    Class to handle inter-process communication and command handling for KSPEC.

    Attributes:
        transport (str): The transport layer for communication using UDP.
        tcslist (list): List of TCS commands for TCS communication.
        running (bool): Flag to control the running state of the process.
    """

    def __init__(self):
        """
        Initializes kspecicsclass with default attributes.
        """
        self.transport = 'None'
        self.tcslist = [
            "start", "stop", "tcsint", "tcsreset", "tcsclose",
            "tcsarc", "tcsstatus", "tstat", "traw", "tsync", "tcmd",
            "treg", "tmradec", "tmr", "tmobject", "tmo", "tmelaz",
            "tme", "tmoffset", "toff", "tstop", "tstow", "tdi",
            "cc", "oo", "nstset", "nston", "nstoff", "auxinit",
            "auxreset", "auxclose", "auxarc", "auxstatus",
            "astat", "acmd", "fsastat", "fs", "fttstat",
            "ft", "dfocus", "dtilt", "fttgoto"
        ]

        self.telcomlist = [
                'getall', 'getra','getdec', 'getha', 'getel', 'getaz', 'getsecz',
                'telra', 'teldec', 'telstow', 'telelaz', 'telstop', 'teltrack'
        ]

        self.adclist = [
                'adcstatus', 'adcactivate', 'adcadjust', 'adcinit', 'adcconnect', 'adcdisconnect', 'adchome', 'adczero',
                'adcpoweroff', 'adcrotate1', 'adcrotate2', 'adcstop', 'adcpark','adcrotateop','adcrotatesame'
        ]

        self.gfalist = [
                'gfastatus', 'gfagrab', 'gfastop', 'gfaguide', 'gfaguidestop'
        ]

        self.fbplist = [
                'fbpstatus', 'fbpzero', 'fbpmove', 'fbpoffset'
        ]

        self.endolist = [
                'endoguide', 'endotest', 'endofocus', 'endostop', 'endoexpset', 'endoclear', 'endostatus'
        ]

        self.mtllist = [
                'mtlstatus','mtlexp','mtlcal'
        ]

        self.lamplist = [
                'lampstatus', 'arcon', 'arcoff', 'flaton', 'flatoff', 'fiducialon',  'fiducialoff'
        ]

        self.speclist = [
                'specstatus', 'illuon', 'illuoff', 'getobj', 'getbias', 'getflat', 'getarc'
        ]

        self.scriptlist = [
                'obsinitial','runscript','runcalib'
        ]

        self.running = True

    async def user_input(self, ICSclient):
        """
        Handles user input asynchronously and sends commands to the server.

        Args:
            ICSclient (AMQclass): The AMQ client instance for communication.
        """
        with open('./Lib/KSPEC.ini', 'r') as f:
            kspecinfo = json.load(f)

        tcsagentIP = kspecinfo['TCS']['TCSagentIP']
        tcsagentPort = kspecinfo['TCS']['TCSagentPort']
        telcomIP = kspecinfo['TCS']['TelcomIP']
        telcomPort = kspecinfo['TCS']['TelcomPort']

#        telcom_client = TCPClient(telcomIP, telcomPort)

        try:
            loop = asyncio.get_event_loop()
            on_con_lost = loop.create_future()  # Future to wait for connection loss

            # Define a factory function that returns a new protocol instance
            def protocol_factory():
                return UDPClientProtocol(on_con_lost)

            # Create UDP connection
            self.transport, self.protocol = await loop.create_datagram_endpoint(
                protocol_factory, remote_addr=(tcsagentIP, tcsagentPort)
            )

            # Create TCP/IP connection
            telcom_client = TCPClient(telcomIP, telcomPort)
            await telcom_client.connect()

            while True:
                # Run input() in the default executor (blocking call to non-blocking)
                message = await loop.run_in_executor(None, input, "\n Input command: ")
                if not message:
                    continue

                cmd = message.split(" ")
                messagetcs='KSPEC>TC '+message

                if cmd[0] in self.tcslist:
                    self.transport.sendto(messagetcs.encode())  # Send TCS message to TCS UDP server

                elif cmd[0] in self.telcomlist:
                    await handle_telcom(message,telcom_client)

                elif cmd[0] in self.adclist:
                    await handle_adc(message,ICSclient)

                elif cmd[0] in self.gfalist:
                    await handle_gfa(message,ICSclient)

                elif cmd[0] in self.fbplist:
                    await handle_fbp(message,ICSclient)

                elif cmd[0] in self.endolist:
                    await handle_endo(message,ICSclient)

                elif cmd[0] in self.mtllist:
                    await handle_mtl(message,ICSclient)

                elif cmd[0] in self.lamplist:
                    await handle_lamp(message,ICSclient)

                elif cmd[0] in self.speclist:
                    await handle_spec(message,ICSclient)

                elif cmd[0] in self.scriptlist:
                    await handle_script(message,ICSclient,self.transport)

                elif message.lower() == "quit":  # Exit condition
                    print("Closing connection...")
                    self.transport.close()  # Close the connection
                    await telcom_client.close()
                    self.running = False
                    break

#                else:
#                    await identify(message, ICSclient, telcom_client, self.transport)

        except asyncio.CancelledError:
            print("user_input cancelled.")
        except Exception as e:
            print(f"An error occurred in user_input: {e}")
        finally:
            print("user_input finalized.")

    async def response_act(self, ICS_client):
        """
        Handles responses from the ICS client asynchronously.

        Args:
            ICS_client (AMQclass): The AMQ client instance for communication.
        """
        try:
            while self.running:
                rsp_msg = await ICS_client.receive_message('ICS')
                dict_data = json.loads(rsp_msg)
                inst = dict_data['inst']
                print(f'{inst} process status :', dict_data['process'])
                processes.update_process(inst, dict_data['process'])
                if dict_data['process'] == 'Done':
                    ICS_client.stop_event.set()

                saveflag = dict_data["savedata"]
                if saveflag == "False":
                    print('\033[94m' + '[ICS] received: ', dict_data["message"] + '\n\033[0m')
                else:
                    with open('./Lib/KSPEC.ini', 'r') as fs:
                        kspecinfo = json.load(fs)
                    fs.close()

                    savefilepath = kspecinfo['savepath']

                    with open(savefilepath + dict_data["filename"], "w") as f:
                        json.dump(dict_data, f)
                    f.close()

                    outfile = dict_data["filename"]
                    print('\033[94m' + '\n[ICS] received: ', dict_data["message"] + '\033[0m')
                    print('\033[94m' + f'[ICS] "{outfile}" File saved' + '\033[0m')

#                nextstep = dict_data['nextstep']
#                if nextstep == 'True':
#                    message = dict_data['nextstep']
#                    cmd = message.split(" ")

#                    if cmd[0] in self.tcslist:
#                        self.transport.sendto(message.encode())  # Send message to server

#                    else:
#                        await identify(message, ICS_client, self.transport)

#                if nextstep == 'None':
#                    pass
        except asyncio.CancelledError:
            print("response_act cancelled.")
        except Exception as e:
            print(f"An error occurred in response_act: {e}")
        finally:
            print("response_act finalized.")

async def main():
    """
    Main function to initialize and run the asynchronous tasks.
    """
    with open('./Lib/KSPEC.ini', 'r') as f:
        kspecinfo = json.load(f)

    ip_addr = kspecinfo['RabbitMQ']['ip_addr']
    idname = kspecinfo['RabbitMQ']['idname']
    pwd = kspecinfo['RabbitMQ']['pwd']

    ICS_client = AMQclass(ip_addr, idname, pwd, 'ICS', 'ics.ex')
    await ICS_client.connect()
    await ICS_client.define_producer()
    await ICS_client.define_consumer()

    kspecics = kspecicsclass()

    try:
        processes.initial()
        await asyncio.gather(kspecics.user_input(ICS_client), kspecics.response_act(ICS_client))
    except asyncio.CancelledError:
        print("Main coroutine cancelled.")
    except Exception as e:
        print(f"An error occurred in main: {e}")
    finally:
        # Ensure RabbitMQ connection is properly closed
        if ICS_client:
            await ICS_client.disconnect()
            print("Main finalized")

if __name__ == "__main__":
    """
    Entry point for the script. Runs different modules based on the input argument.
    """
    if sys.argv[1] == 'ics':
        try:
            asyncio.run(main())  # Run the main coroutine
        except KeyboardInterrupt:
            print("Program terminated by User.")
        except SystemExit:
            print("System exit called.")

    if sys.argv[1] == 'GFA':
        from GFA import GFA_server
        asyncio.run(GFA_server.main())

    if sys.argv[1] == 'ADC':
        from ADC import ADC_server
        asyncio.run(ADC_server.main())

    if sys.argv[1] == 'FBP':
        from FBP import FBP_server
        asyncio.run(FBP_server.main())

    if sys.argv[1] == 'MTL':
        from MTL import MTL_server
        asyncio.run(MTL_server.main())

    if sys.argv[1] == 'SPEC':
        from SPECTRO import SPEC_server
        asyncio.run(SPEC_server.main())

    if sys.argv[1] == 'LAMP':
        from LAMP import LAMP_server
        asyncio.run(LAMP_server.main())

    if sys.argv[1] == 'ENDO':
        from ENDO import ENDO_server
        asyncio.run(ENDO_server.main())

    if sys.argv[1] == 'ADCsimul':
        from ADC.Simul import ADC_server
        asyncio.run(ADC_server.main())

    if sys.argv[1] == 'GFAsimul':
        from GFA.Simul import GFA_server
        asyncio.run(GFA_server.main())

    if sys.argv[1] == 'ENDOsimul':
        from ENDO.Simul import ENDO_server
        asyncio.run(ENDO_server.main())

    if sys.argv[1] == 'MTLsimul':
        from MTL.Simul import MTL_server
        asyncio.run(MTL_server.main())
