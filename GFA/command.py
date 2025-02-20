import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
#from .kspec_gfa_controller.src.gfa_actions import GFAActions
#from KSPEC_Server.GFA.kspec_gfa_controller.src.gfa_actions import gfa_actions


guiding_task = None

def printing(message):
    """Utility function for consistent printingging.

    Args:
        message (str): The message to be printingged.
    """
    print(f"\033[32m[GFA] {message}\033[0m")

async def identify_execute(GFA_server,gfa_actions,cmd):
    global guiding_task 
    dict_data=json.loads(cmd)
    func=dict_data['func']
#    endoaction=endo_actions()
#    endoaction.endo_connect()

    if func == 'gfastatus':
        result=gfa_actions.status()
        reply_data=mkmsg.gfamsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        printing(reply_data['message'])
        await GFA_server.send_message('ICS',rsp)

    elif func == 'gfagrab':
        result = await gfa_actions.grab(dict_data['CamNum'],dict_data['ExpTime'])
        reply_data=mkmsg.gfamsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        printing(reply_data['message'])
        await GFA_server.send_message('ICS',rsp)

    elif func == 'gfaguide':

        # Cancel any running task before starting a new one
        if guiding_task and not guiding_task.done():
            printing("Cancelling the running autoguiding task...")
            guiding_task.cancel()
            try:
                await guiding_task
            except asyncio.CancelledError:
                printing("Previous guiding task cancelled.")

        # Start a new adcadjust task
        guiding_task = asyncio.create_task(handle_guiding(GFA_server, gfa_actions))
        printing("New guiding task started.")

    elif func == 'gfaguidestop':
        if guiding_task and not guiding_task.done():
            printing("Stopping guiding task...")
            guiding_task.cancel()
            try:
                await guiding_task
            except asyncio.CancelledError:
                printing("Guiding task stopped.")
        else:
            printing("No Guiding task is currently running.")


    if func == 'loadguide':
        chipnum=dict_data['chipnum']
        ra=dict_data['ra']
        dec=dict_data['dec']
        mag=dict_data['mag']
        xp=dict_data['xp']
        yp=dict_data['yp']
        comment=savedata(ra,dec,xp,yp,mag)
#        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': message}
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        await GFA_server.send_message('ICS',rsp)
        

def savedata(ra,dec,xp,yp,mag):
    with open('./Lib/KSPEC.ini','r') as f:
        inidata=json.load(f)

    gfafilepath=inidata['GFA']['gfafilepath']

    savefile=open(gfafilepath+'position.radec','w')
    for i in range(len(ra)):
        savefile.write("%12.6f %12.6f %12.6f %12.6f %9.4f\n" % (ra[i],dec[i],xp[i],yp[i],mag[i]))
    savefile.close

    msg="'Guide stars are loaded.'"
    return msg

# Below functions are for simulation. When connect the instruments, please annotate.

async def autoguide(exptime,subserver):
    msg=random.randrange(1,11)
    if msg < 7:
        reply=mkmsg.gfamsg()
        comment='Autoguiding continue.......'
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': comment, 'thred': msg}
        reply.update(dict_data)
#        rsp=json.dumps(reply)
        rsp=reply
    else:
        reply=mkmsg.gfamsg()
        comment=f'Telescope offset {msg}'
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','message': comment, 'thred': msg}
        reply.update(dict_data)
#        rsp=json.dumps(reply)
        rsp=reply
    return rsp


async def handle_guiding(GFA_server, gfa_actions):
    try:
        while True:
            result = await gfa_actions.guiding()
            reply_data = mkmsg.gfamsg()
            reply_data.update(result)
            reply_data.update(process='In process')
            rsp=json.dumps(reply_data)
            await GFA_server.send_message('ICS',rsp)

            await asyncio.sleep(30)

    except asyncio.CancelledError:
        printing("handle_guiding task was cancelled.")
        raise
    except Exception as e:
        comment=f"Error in handle_guiding: {e}"
        printing(comment)
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        await GFA_server.send_message('ICS',rsp)
    else:
        printing("handle_guiding completed successfully.")


