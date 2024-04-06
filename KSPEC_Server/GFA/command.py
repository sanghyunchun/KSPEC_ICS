import os,sys
from Lib.AMQ import *
import json
import asyncio


async def identify_excute(GFA_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func == 'gfaallexp':
        time=dict_data['time']
        rsp=gfacexp(time)
#        print(rsp)
        await GFA_server.loop_start_stop('GFA',rsp)

    if func == 'gfastop':
        rsp=gfastop()
        await GFA_server.loop_start_stop('GFA',rsp)
        rsp = 'GFA exposure finished'
        await GFA_server.send_response('GFA',rsp)

    if func == 'loadguide':
        chipnum=dict_data['chipnum']
        ra=dict_data['ra']
        dec=dict_data['dec']
        mag=dict_data['mag']
        xp=dict_data['xp']
        yp=dict_data['yp']
        rsp=savedata(ra,dec,xp,yp,mag)
        await GFA_server.send_response('GFA',rsp)


def gfacexp(time):
    response='GFA exposure running'
    return response

   
def gfastop():
    response='stop'
    return response


def savedata(ra,dec,xp,yp,mag):
    f=open('./data/position.radec','w')
    for i in range(len(ra)):
        f.write("%12.6f %12.6f %12.6f %12.6f %9.4f\n" % (ra[i],dec[i],xp[i],yp[i],mag[i]))
    f.close

    response="'Guide stars are loaded.'"
    return response
