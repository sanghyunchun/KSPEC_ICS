import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import numpy as np
import time
import FBP.kspec_positioner_controller.position_action as FBP_action


def load_config(config_path='./Lib/KSPEC.ini'):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"KSPEC.ini not found at {config_path}")

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Error parsing KSPEC.ini: {e}")
    except OSError as e:
        raise IOError(f"Error reading KSPEC.ini: {e}")

    return config

def printing(message):
    """Utility function for consistent printingging.

    Args:
        message (str): The message to be printingged.
    """
    print(f"\033[32m[FBP] {message}\033[0m")

async def send_fbp_response(FBP_server, result=None, *, log=True, **updates):
    reply_data = mkmsg.fbpmsg()

    if result is not None:
        reply_data.update(result)

    reply_data.update(updates)

    rsp = json.dumps(reply_data)
    if log and reply_data.get('message'):
        printing(reply_data['message'])

    await FBP_server.send_message('ICS', rsp)
    return reply_data

async def identify_execute(FBP_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'loadobj':
        ra=dict_data['ra']
        dec=dict_data['dec']
        xp=dict_data['xp']
        yp=dict_data['yp']
        clss=dict_data['class']
        status, comment=savedata(ra,dec,xp,yp,clss)  # Save Target information

        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done',status=status)
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'loadmotion':
        status, comment = savemotion(dict_data)
        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done',status=status)
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'fbpstatus':
        positioner = dict_data['positioner']
        result = FBP_action.show_status(axis=positioner)

        await send_fbp_response(
                 FBP_server, result,
                 process='Done',
        )

    if func == 'fbpmoveone':
        positioner = dict_data['positioner']
        motor = dict_data['motor']
        angle = dict_data['angle']
        result = FBP_action.rotate_one(positioner=positioner, motor=motor, angle=angle)

        await send_fbp_response(
                 FBP_server, result,
                 process='Done',
        )


    if func == 'fbpmoveall':
        print('Hahahah')

        result = FBP_action.rotate_all()

        # reply_data=mkmsg.fbpmsg()
        # comment = 'Fiber positioners start to targets.'
        # reply_data.update(message=comment,process='START',status='success')
        # rsp=json.dumps(reply_data)
        # await FBP_server.send_message('ICS',rsp)

        # status, comment=fbp_move()     ### Position of fiber postioner movement function
        # reply_data=mkmsg.fbpmsg()
        # reply_data.update(message=comment,process='Done',status=status, pos_state='assign')
        # rsp=json.dumps(reply_data)
        # print('\033[32m'+'[FBP]', comment+'\033[0m')
        # await FBP_server.send_message('ICS',rsp)

    if func == 'fbpoffset':
        reply_data=mkmsg.fbpmsg()
        comment = 'Fiber positioners start to offset.'
        reply_data.update(message=comment,process='START',status='success',pos_state='assign')
        rsp=json.dumps(reply_data)
        await FBP_server.send_message('ICS',rsp)

        status, comment = fbp_offset()   ### Position of fiber offset movement function
        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done', status=status, pos_state='assign')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'fbpzero':
        reply_data=mkmsg.fbpmsg()
        comment = 'Fiber positioners start to move to zero positions'
        reply_data.update(message=comment,process='START',status='success')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

        status, comment=fbp_zero()     ### Position of fiber postioner movement function
        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done',status=status,pos_state='zero')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'fbpinitial':
        print('ggggg')

# Below functions are for simulation. When connect the Fiber positioner, please annotate
def fbp_zero():
    try:
        kspecinfo=load_config()
        fbpfilepath = kspecinfo['FBP']['fbpfilepath']
    except Exception as e:
        return 'fail', str(e)

#    ra,dec,xp,yp=np.loadtxt(fbpfilepath+'object.radec',dtype=float,unpack=True,usecols=(0,1,2,3))
    time.sleep(5)
    rspmsg=f'Fiber positioners successfully moved to zero position.'
    return 'success', rspmsg

def fbp_move():
    try:
        kspecinfo=load_config()
        fbpfilepath = kspecinfo['FBP']['fbpfilepath']
    except Exception as e:
        return 'fail', str(e)

    with open(fbpfilepath+'motion_alpha.info','r') as fs:
        alpha=json.load(fs)
    with open(fbpfilepath+'motion_alpha.info','r') as fs:
        alpha=json.load(fs)

    time.sleep(20)
    rspmsg=f'Fiber positioners movement finished.'
    return 'success', rspmsg

def fbp_offset():
#    ra,dec,xp,yp=np.loadtxt(fbpfilepath+'object.radec',dtype=float,unpack=True,usecols=(0,1,2,3))
    time.sleep(10)
    rspmsg='Fiber positioners offset movement finished.'
    return 'success', rspmsg

def fbp_status():
    time.sleep(2)
    rspmsg='Fiber positioners status below. FBP is ready.'
    return 'success', rspmsg

def savedata(ra,dec,xp,yp,clss):
    try:
        kspecinfo=load_config()
        fbpfilepath = kspecinfo['FBP']['fbpfilepath']
    except Exception as e:
        return 'fail', str(e)

    try:
        with open(fbpfilepath+'object.radec','w') as savefile:
            for i in range(len(ra)):
                savefile.write("%12.6f %12.6f %12.6f %12.6f %8s\n" % (ra[i],dec[i],xp[i],yp[i],clss[i]))
    except TypeError:
        return 'fail', "Non-numeric values encountered while formatting output."
    except OSError as e:
        return 'fail', f"Failed to write file: {e}"

    rspmsg="'Objects are loaded in FBP server.'"
    return 'success', rspmsg


def savemotion(dict_data):
    try:
        kspecinfo=load_config()
        fbpfilepath = kspecinfo['FBP']['fbpfilepath']
    except Exception as e:
        return 'fail', str(e)

    arm=dict_data['arm']
    try:
        if dict_data['arm'] == 'alpha':
            file_path=(fbpfilepath+'motion_alpha.info')
            with open(file_path,"w") as f:
                json.dump(dict_data,f)

        if dict_data['arm'] == 'beta':
            file_path=(fbpfilepath+'motion_beta.info')
            with open(file_path,"w") as f:
                json.dump(dict_data,f)
    
    except TypeError:
        return 'fail', "Non-numeric values encountered while formatting output."
    except OSError as e:
        return 'fail', f"Failed to write file: {e}"

    msg=f'Motion plan of {arm} is successfully loaded in FBP server.'
    return 'success', msg





