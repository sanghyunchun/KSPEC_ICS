import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import threading
import numpy as np
import pandas as pd
import json

"""
Provide Sky position (RA, DEC) of Tile and target position to TCS computer,
    GFA computer, Metrology computer and Fiber positioner computer.
"""

class sciobscli:

    def __init__(self):
        self.filename=None
        self.project=None
        self.obsdate=None
        self.tile_id = None
        self.ra = None
        self.dec = None
        with open('./Lib/KSPEC.ini','r') as fs:
            kspecinfo=json.load(fs)

        self.obsplanpath=kspecinfo['SCIOBS']['obsplanpath']
        self.targetpath=kspecinfo['SCIOBS']['targetpath']
        self.motionpath=kspecinfo['SCIOBS']['motionpath']
        self.obsinfofile=kspecinfo['SCIOBS']['obsinfofile']

# Read file information 
    def loadfile(self,filename):
        self.filename=filename
        data=pd.read_csv(self.obsplanpath+self.filename)

        wild=self.filename.split('_')
        self.project=wild[0]
        self.obsdate=wild[-1].split('.')[0]
        return data

    def obsstatus(self):
#        file_path='./SCIOBS/observation/obs_info.json'
        with open(self.obsinfofile,'r') as f:
            obs_info=json.load(f)

        print('##### Current loaded observation information #####')
        print('File name = ',obs_info['filename']) 
        print('OBS date = ',obs_info['OBS-date']) 
        print('Tile ID = ',obs_info['Tile-ID']) 
        print('Tile RA = ',obs_info['Tile-RA']) 
        print('Tile DEC = ',obs_info['Tile-DEC']) 


# Load tile position of RA/DEC
    def load_tilepos(self):
        dtype=[('tid','i'),('RA','f'),('DEC','f')]
        d=np.loadtxt(self.targetpath+self.project+'_tile_pos.txt',dtype=dtype,skiprows=1)
        tilepos_list=[]
        for row in d:
            ttid=row["tid"]
            ra=row["RA"]
            dec=row["DEC"]
            tilepos_list.append((ttid,ra,dec))

        tilepos_list=np.array(tilepos_list)
        ttid=tilepos_list[:,0]
        idx = (ttid == int(self.tile_id))
        stile_id=int(ttid[idx])
        self.ra=tilepos_list[stile_id-1,1]
        self.dec=tilepos_list[stile_id-1,2]

        message='Position of Tile is loaded'

        dict_data={"inst" : 'TCS', "func" : 'loadtile', 'tid' : stile_id, 
                'ra' : self.ra, 'dec' : self.dec, 'message' : message}
        tiledata=json.dumps(dict_data)
        return tiledata


# Load RA/DEC and X/Y of science objects assigned in ???? tile_ID
    def load_target(self):
#        dirs='../inputdata/obsplan/target_assign/'
        dtype=[('tid','i'),('fiber_id','i'),('xp','f'),('yp','f'),('ra','f'),('dec','f'),('class','U8')]
        tid,fiberid,xp,yp,ra,dec,clss=np.loadtxt(self.targetpath+self.project+'_assign.txt',dtype=dtype,skiprows=1,unpack=True,usecols=(0,1,2,3,4,5,6))
        idx = (tid == int(self.tile_id))
        obj_tid=tid[idx]
        obj_fiberid=fiberid[idx]
        obj_xp=xp[idx]
        obj_yp=yp[idx]
        obj_ra=ra[idx]
        obj_dec=dec[idx]
        obj_class=clss[idx]

        message='Objects file is loaded'

        dict_data = { "tile_id":obj_tid[0].tolist(), "inst" : 'SCIOBS', "func" : 'loadobj', "ra":obj_ra.tolist(), "dec":obj_dec.tolist(),"xp":obj_xp.tolist(),
                "yp":obj_yp.tolist(),"class":obj_class.tolist(),'message':message}

        objdata=json.dumps(dict_data)
        return objdata


# Load RA/DEC and X/Y of guide star in specific tile
    def load_guide(self):
#        dirs='../inputdata/obsplan/target_assign/'
        dtype=[('tid','i'),('chipid','i'),('ra','f'),('dec','f'),('mag','f'),('xp','f'),('yp','f')]
        tid,chipid,ra,dec,mag,xp,yp=np.loadtxt(self.targetpath+self.project+'_GFA.txt',dtype=dtype,skiprows=1,unpack=True)
        idx = (tid == int(self.tile_id))
        guide_tid=tid[idx]
        guide_chipid=chipid[idx]
        guide_ra=ra[idx]
        guide_dec=dec[idx]
        guide_mag=mag[idx]
        guide_xp=xp[idx]
        guide_yp=yp[idx]

        message='Guide star of tile is loaded'

        dict_data = {"inst" : 'GFA', "func" : 'loadguide', "chipnum" : guide_chipid.tolist(),'ra': guide_ra.tolist(),'dec' : guide_dec.tolist(),'mag':
                guide_mag.tolist(),'xp':guide_xp.tolist(),'yp':guide_yp.tolist(),'message':message}
        guidedata=json.dumps(dict_data)
        return guidedata


# Load motion plan of 150 fiber positioner
    def load_motion(self):
#        dirs='../inputdata/motion/'
        alpha=np.loadtxt(self.motionpath+self.project+'_assign_tilen'+self.tile_id+'_Pathdata_Alpha_motor.csv',delimiter=',')
        beta=np.loadtxt(self.motionpath+self.project+'_assign_tilen'+self.tile_id+'_Pathdata_Beta_motor.csv',delimiter=',')
        Fibnum=np.loadtxt('./Lib/Fibnum.def',dtype=str)

        motion_alpha={}
        motion_beta={}
        for i  in range(150):
            motion_alpha[Fibnum[i]]=alpha[:,i].tolist()
            motion_beta[Fibnum[i]]=beta[:,i].tolist()

        a_motion=mkmsg.fbpmsg()
        comment=f'Motion plan of alpha arm for Tile ID {self.tile_id} load.'
        a_motion.update(func='loadmotion',message=comment,arm='alpha',tileid=self.tile_id)
        a_motion.update(motion_alpha)

        b_motion=mkmsg.fbpmsg()
        comment=f'Motion plan of beta arm for Tile ID {self.tile_id} load.'
        b_motion.update(func='loadmotion',message=comment,arm='beta',tileid=self.tile_id)
        b_motion.update(motion_beta)

        motionmsg1=json.dumps(a_motion)
        motionmsg2=json.dumps(b_motion)
        return motionmsg1,motionmsg2


    def loadtile(self,tile_id):
#        file_path='./SCIOBS/observation/obs_info.json'

        self.tile_id=tile_id
        tileinfo = self.load_tilepos()
        TCSmsg = tileinfo

        guideinfo=self.load_guide()
        GFAmsg=guideinfo

        objinfo=self.load_target()
        OBJmsg=objinfo

        motionmsg1,motionmsg2=self.load_motion()

        obs_info={'filename': self.filename, 'OBS-date': self.obsdate, 'Tile-ID': self.tile_id, 'Tile-RA': self.ra, 'Tile-DEC': self.dec}
        with open(self.obsinfofile, 'w') as f:
            json.dump(obs_info,f)

        return TCSmsg,GFAmsg,OBJmsg,motionmsg1,motionmsg2
       



