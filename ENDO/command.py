import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
#from ENDO.endo_controller.endo_actions import endo_actions


guiding_task = None

def printing(message):
    """Utility function for consistent printingging.

    Args:
        message (str): The message to be printingged.
    """
    print(f"\033[32m[ENDO] {message}\033[0m")

async def identify_execute(ENDO_server,endoactions,cmd):
    global guiding_task
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'endoclear':
        result=endoactions.endo_clear()
        reply_data=mkmsg.endomsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        printing(reply_data['message'])
        await ENDO_server.send_message('ICS',rsp)

    elif func == 'endoguide':
        # Cancel any running task before starting a new one
        if guiding_task and not guiding_task.done():
            printing("Cancelling the running Endoscope autoguiding task...")
            guiding_task.cancel()
            try:
                await guiding_task
            except asyncio.CancelledError:
                printing("Previous endoscope guiding task cancelled.")

        # Start a new adcadjust task
        guiding_task = asyncio.create_task(handle_guiding(ENDO_server, endoactions))
        printing("New endoscope guiding task started.")

    elif func == 'endostop':
        if guiding_task and not guiding_task.done():
            printing("Stopping Endoscope guiding task...")
            guiding_task.cancel()
            try:
                await guiding_task
            except asyncio.CancelledError:
                printing("Endoscope Guiding task stopped.")
        else:
            printing("No Endoscope Guiding task is currently running.")

    if func == 'endotest':
        result=endoactions.endo_test()
        reply_data=mkmsg.endomsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        printing(reply_data['message'])
        rsp=json.dumps(reply_data)
        await ENDO_server.send_message('ICS',rsp)

    if func == 'endofocus':
        fc=float(dict_data['focus'])
        result=endoactions.endo_focus(fc)
        reply_data=mkmsg.endomsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        printing(reply_data['message'])
        rsp=json.dumps(reply_data)
        await ENDO_server.send_message('ICS',rsp)

    if func == 'endoexpset':
        expt=float(dict_data['time'])
        result=endoactions.endo_expset(expt)
        reply_data=mkmsg.endomsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        printing(reply_data['message'])
        rsp=json.dumps(reply_data)
        await ENDO_server.send_message('ICS',rsp)

async def handle_guiding(ENDO_server, endoactions):
    try:
        while True:
            result = await endoactions.endo_guide()
            reply_data = mkmsg.endomsg()
            reply_data.update(result)
            reply_data.update(process='In process')
            rsp=json.dumps(reply_data)
            await ENDO_server.send_message('ICS',rsp)

            await asyncio.sleep(30)

    except asyncio.CancelledError:
        printing("handle_guiding task was cancelled.")
        raise
    except Exception as e:
        comment=f"Error in handle_guiding: {e}"
        printing(comment)
        reply_data=mkmsg.endomsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await ENDO_server.send_message('ICS',rsp)
    else:
        printing("handle_guiding completed successfully.")

