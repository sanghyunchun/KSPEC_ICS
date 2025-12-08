import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time
import random
import shutil


guiding_task = None

def printing(message):
    """Utility function for consistent printingging.

    Args:
        message (str): The message to be printingged.
    """
    print(f"\033[32m[GFA] {message}\033[0m")

async def identify_execute(GFA_server,gfa_actions,finder_actions,cmd):
    global guiding_task 
    dict_data=json.loads(cmd)
    func=dict_data['func']

    with open('./Lib/KSPEC.ini','r') as f:
        kspecinfo=json.load(f)

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
        printing("New guiding task started.")
        reply_data=mkmsg.gfamsg()
        reply_data.update(process='START',message='Autoguide starts.',status='success')
        rsp=json.dumps(reply_data)
        await GFA_server.send_message('ICS',rsp)
        save = dict_data['save'] == 'True'
        guiding_task = asyncio.create_task(handle_guiding(GFA_server, gfa_actions, dict_data['ExpTime'],save))

    elif func == 'gfaguidestop':
        if guiding_task and not guiding_task.done():
            printing("Stopping guiding task...")
            guiding_task.cancel()
            reply_data=mkmsg.gfamsg()
            reply_data.update(process='Done',message='Autoguide Stop',status='success')
            rsp=json.dumps(reply_data)
            await GFA_server.send_message('ICS',rsp)

            path_astroimg=kspecinfo['GFA']['final_astrometry_images']
            shutil.rmtree(path_astroimg)                                        # Remove the guiding images after guiding stop.
            os.makedirs(path_astroimg, exist_ok=True)

            try:
                await guiding_task
            except asyncio.CancelledError:
                printing("Guiding task stopped.")
        else:
            printing("No Guiding task is currently running.")
            reply_data=mkmsg.gfamsg()
            reply_data.update(process='Done',message='No Guiding task is currently running.',status='normal')
            rsp=json.dumps(reply_data)
            await GFA_server.send_message('ICS',rsp)

    if func == 'loadguide':
        chipnum=dict_data['chipnum']
        ra=dict_data['ra']
        dec=dict_data['dec']
        mag=dict_data['mag']
        xp=dict_data['xp']
        yp=dict_data['yp']
        status, comment=savedata(ra,dec,xp,yp,mag)    # It would be removed, because guide stars are not necessary in current guiding system. 
        reply_data=mkmsg.gfamsg()
        reply_data.update(message=comment,process='Done',status=status)
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[GFA]', comment+'\033[0m')
        await GFA_server.send_message('ICS',rsp)


    if func == 'fdgrab':
        printing("Finder grab task started.")
        reply_data=mkmsg.gfamsg()
        reply_data.update(process='START',message='Finder grab starts.',status='success')
        rsp=json.dumps(reply_data)
        await GFA_server.send_message('ICS',rsp)
        result = await finder_actions.grab(dict_data['ExpTime'])
        reply_data=mkmsg.gfamsg()
        reply_data.update(result)
        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        printing(reply_data['message'])
        await GFA_server.send_message('ICS',rsp)

        
def savedata(ra,dec,xp,yp,mag):
    with open('./Lib/KSPEC.ini','r') as f:
        inidata=json.load(f)

    gfafilepath=inidata['GFA']['gfafilepath']        # guide stars info. is saved in GFA/etc directory. It would not be necessary.

    try:
        with open(gfafilepath+'position.radec','w') as savefile:
            for i in range(len(ra)):
                savefile.write("%12.6f %12.6f %12.6f %12.6f %9.4f\n" % (ra[i],dec[i],xp[i],yp[i],mag[i]))
    except TypeError:
        return 'fail', "Non-numeric values encountered while formatting output."
    except OSError as e:
        return 'fail', f"Failed to write file: {e}"

    msg="'Guide stars are loaded.'"
    return 'success', msg



async def handle_guiding(GFA_server, gfa_actions, expt, save):
    try:
        while True:
            result = await gfa_actions.guiding(expt,save)
            reply_data = mkmsg.gfamsg()
            reply_data.update(result)
            reply_data.update(process='ING')
            rsp=json.dumps(reply_data)
            await GFA_server.send_message('ICS',rsp)

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


