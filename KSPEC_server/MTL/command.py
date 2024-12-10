import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
from kspec_metrology.exposure import mtlexp
from kspec_metrology.analysis import mtlcal

async def identify_excute(MTL_server,cmd):
    receive_msg=json.loads(cmd)
    func=receive_msg['func']

    if func == 'loadobj':
        tid=receive_msg['tile_id']
        ra=receive_msg['ra']
        dec=receive_msg['dec']
        xp=receive_msg['xp']
        yp=receive_msg['yp']
        clss=receive_msg['class']

        file_path=('./target/object.info')
        with open(file_path,"w") as f:
            json.dump(receive_msg,f)

        comment="'Objects are loaded in MTL server.'"
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)

    if func == 'mtlexp':
        exptime=receive_msg['time']
        comment=mtlexp.mtlexp(exptime)
        reply_data=mkmsg.mtlmsg()
        reply_data.update(message=comment,process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)

    if func == 'mtlcal':
        offx,offy,comment = mtlcal.mtlcal()
        reply_data=mkmsg.mtlmsg()
        reply_data.update(savedata='True',filename='MTLresult.json',offsetx=offx.tolist(),offsety=offy.tolist(),message=comment)
        reply_data.update(process='Done')
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[MTL]', comment+'\033[0m')
        await MTL_server.send_message('ICS',rsp)


#def savedata(ra,dec,xp,yp,clss):
#    f=open('./etc/object.radec','w')
#    for i in range(len(ra)):
#        f.write("%12.6f %12.6f %12.6f %12.6f %8s\n" % (ra[i],dec[i],xp[i],yp[i],clss[i]))
#    f.close

#    response="'Objects are loaded in MTL server.'"
#    return response

