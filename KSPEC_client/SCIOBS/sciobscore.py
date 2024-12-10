import numpy as np
import os,sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
#from Lib.MsgMiddleware import *
#import argh
#import uuid
from .obj_def import *
import json
import asyncio

#def readplan():
#    dtype=[('tid','i'),('obs_time','S100'),('obs_num','i')]
#    d=np.loadtxt(ppwd+filename,dtype=dtype,skiprows=1)
#    sequence_list=[]
#    for row in d:
#        ttid=row["tid"]
#        obsnum=row["obs_num"]
#        sequence_list.append((ttid,obsnum))
#    return sequence_list

# Load tile position of RA/DEC
def load_tilepos(tile_id):
    dtype=[('tid','i'),('RA','f'),('DEC','f')]
    dirs='../../inputdata/plan/default/'
    d=np.loadtxt(dirs+'ASPECS_tile_pos.txt',dtype=dtype,skiprows=1)
    tilepos_list=[]
    for row in d:
        ttid=row["tid"]
        ra=row["RA"]
        dec=row["DEC"]
        tilepos_list.append((ttid,ra,dec))

    tilepos_list=np.array(tilepos_list)
    ttid=tilepos_list[:,0]
    idx = (ttid == int(tile_id))
    stile_id=int(ttid[idx])
#    print(stile_id)
    ra=tilepos_list[stile_id-1,1]
    dec=tilepos_list[stile_id-1,2]

    comments='Position of Tile is loaded'

    dict_data={"inst" : 'TCS', "func" : 'loadtile', 'tid' : stile_id, 'ra' : ra, 'dec' : dec, 'comments' : comments}
    tiledata=json.dumps(dict_data)
    return tiledata

# Load RA/DEC and X/Y of guide star in specific tile
def load_guide(tile_id):
    dirs='../../inputdata/plan/default/'
    dtype=[('tid','i'),('chipid','i'),('ra','f'),('dec','f'),('mag','f'),('xp','f'),('yp','f')]
    tid,chipid,ra,dec,mag,xp,yp=np.loadtxt(dirs+'ASPECS_GFA.txt',dtype=dtype,skiprows=1,unpack=True)
    idx = (tid == int(tile_id))
    guide_tid=tid[idx]
    guide_chipid=chipid[idx]
    guide_ra=ra[idx]
    guide_dec=dec[idx]
    guide_mag=mag[idx]
    guide_xp=xp[idx]
    guide_yp=yp[idx]

    comments='Guide star of tile is loaded'

    dict_data = {"inst" : 'GFA', "func" : 'loadguide', "chipnum" : guide_chipid.tolist(),'ra': guide_ra.tolist(),'dec' : guide_dec.tolist(),'mag':
            guide_mag.tolist(),'xp':guide_xp.tolist(),'yp':guide_yp.tolist(),'comments':comments}
    guiddata=json.dumps(dict_data)
    return guiddata

# Slew telescope to RA & DEC position
def tradec(ra,dec):
    dict_data={"inst": 'TCS', "func" : 'tra', 'pra' : ra, 'pdec' : dec}
    skyposition=json.dumps(dict_data)
    return skyposition



#if __name__ == "__main__":
#    ttt=readplan()
#    lll=load_tilepos()
