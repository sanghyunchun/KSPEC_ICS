import os,sys
from Lib.AMQ import *
import json
import asyncio
import time
import random

async def identify_excute(GFA_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'gfaallexp':
        time=dict_data['time']
        comments=gfaallexp()                      ### Position of all gfa camera exposure function
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','comments': comments}
        rsp=json.dumps(dict_data)
        await GFA_server.send_response('GFA',rsp)

    if func == 'gfacexp':
        time=dict_data['time']
        cam=dict_data['cam']
        comments=gfacexp()                      ### Position of all gfa camera exposure function
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','comments': comments}
        rsp=json.dumps(dict_data)
        await GFA_server.send_response('GFA',rsp)

    if func == 'autoguide':
        time=dict_data['time']
        value=autoguide() ### Position of all gfa camera exposure function
        print(value)
        if value < 4:		
        	comments='Autoguide running'
        	dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','comments': comments}
        	rsp=json.dumps(dict_data)
        	await GFA_server.loop_start_stop('GFA',rsp)
        else:
        	comments='Autoguide offset'
        	dict_data={'inst': 'GFA', 'savedata': 'True','filename': 'Auideoffset.txt','offset': value,'comments': comments}
        	rsp=json.dumps(dict_data)
        	await GFA_server.loop_start_stop('GFA',rsp)

    if func == 'gfastop':
        rsp=gfastop()
        await GFA_server.loop_start_stop('GFA',rsp)
        comments = 'GFA exposure finished'
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','comments': comments}
        rsp=json.dumps(dict_data)
        await GFA_server.send_response('GFA',rsp)

    if func == 'loadguide':
        chipnum=dict_data['chipnum']
        ra=dict_data['ra']
        dec=dict_data['dec']
        mag=dict_data['mag']
        xp=dict_data['xp']
        yp=dict_data['yp']
        comments=savedata(ra,dec,xp,yp,mag)

        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','comments': comments}
        rsp=json.dumps(dict_data)
        await GFA_server.send_response('GFA',rsp)


def autoguide():
    time.sleep(5)
    msg=random.randrange(1,11)
#    msg='Autoguiding running'
    return msg

def gfacexp(time):
    time.sleep(5)
    msg='GFA exposure finished'
    return msg

def gfaallexp():
    time.sleep(5)
    msg='All GFA cameras exposure finished'
    return msg

   
def gfastop():
    msg='stop'
    return msg


def savedata(ra,dec,xp,yp,mag):
    f=open('./etc/position.radec','w')
    for i in range(len(ra)):
        f.write("%12.6f %12.6f %12.6f %12.6f %9.4f\n" % (ra[i],dec[i],xp[i],yp[i],mag[i]))
    f.close

    msg="'Guide stars are loaded.'"
    return msg
