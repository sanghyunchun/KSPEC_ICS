import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import time

async def identify_excute(server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'arcon':
        comment=arc_on()
        reply_data=mkmsg.lampmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[LAMP]', comment+'\033[0m')
        await server.send_message('ICS',rsp)

    if func == 'arcoff':
        comment=arc_off()
        reply_data=mkmsg.lampmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[LAMP]', comment+'\033[0m')
        await server.send_message('ICS',rsp)

    if func == 'flaton':
        comment=flat_on()
        reply_data=mkmsg.lampmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[LAMP]', comment+'\033[0m')
        await server.send_message('ICS',rsp)

    if func == 'flatoff':
        comment=flat_off()
        reply_data=mkmsg.lampmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[LAMP]', comment+'\033[0m')
        await server.send_message('ICS',rsp)

    if func == 'fiducialon':
        comment=fiducial_on()
        reply_data=mkmsg.lampmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[LAMP]', comment+'\033[0m')
        await server.send_message('ICS',rsp)

    if func == 'fiducialoff':
        comment=fiducial_off()
        reply_data=mkmsg.lampmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[LAMP]', comment+'\033[0m')
        await server.send_message('ICS',rsp)

def arc_on():
    time.sleep(3)    # function to turn on the arc lamp'
    rsp_msg='Arc lamp turns on.'
    return rsp_msg

def arc_off():
    time.sleep(3)    # function to turn off the arc lamp'
    rsp_msg='Arc lamp turns off.'
    return rsp_msg

def flat_on():
    time.sleep(3)    # function to turn on the flat lamp'
    rsp_msg='Flat lamp turns on.'
    return rsp_msg

def flat_off():
    time.sleep(3)    # function to turn on the flat lamp'
    rsp_msg='Flat lamp turns off.'
    return rsp_msg

def fiducial_on():
    time.sleep(3)    # function to turn on the flat lamp'
    rsp_msg='Fiducial lamp turns on.'
    return rsp_msg

def fiducial_off():
    time.sleep(3)    # function to turn on the flat lamp'
    rsp_msg='Fiducial lamp turns off.'
    return rsp_msg