import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import threading
import numpy as np
import pandas as pd
import json
from astropy.coordinates import Angle
import astropy.units as u

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

    def obsstatus(self):
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

        message='Load Position of Tile'

        dict_data={"inst" : 'TCS', "func" : 'loadtile', 'tid' : stile_id, 
                'ra' : self.ra, 'dec' : self.dec, 'message' : message, 'process': 'Done'}
        tiledata=json.dumps(dict_data)
        return tiledata


# Load science objects from the assignment file for the selected tile.
    def load_target(self):
        tile_id=int(self.tile_id)
        assignfile=os.path.join(self.targetpath, f'{self.project}_2627_{tile_id:04d}.assign.txt')
        # File columns: fiberid, xp, yp, mag, class, flag, ra, dec (no header).
        dtype=[('fiber_id','U16'),('xp','f'),('yp','f'),('ra','f'),('dec','f'),('class','U8')]
        obj_fiberid,obj_xp,obj_yp,obj_ra,obj_dec,obj_class=np.loadtxt(
            assignfile,dtype=dtype,unpack=True,usecols=(0,1,2,6,7,4),ndmin=1)

        message='Load Target Objects of Tile'

        dict_data = { "tile_id":tile_id, "project":self.project, "inst" : 'SCIOBS', "func" : 'loadobj', "ra":obj_ra.tolist(), "dec":obj_dec.tolist(),"xp":obj_xp.tolist(),
                "yp":obj_yp.tolist(),"class":obj_class.tolist(),'message':message, 'process': 'Done'}

        objdata=json.dumps(dict_data)
        return objdata


# Load RA/DEC and X/Y of guide star in specific tile
    def load_guide(self):
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

        message='Load Guide star of Tile'

        dict_data = {"inst" : 'GFA', "func" : 'loadguide', "chipnum" : guide_chipid.tolist(),'ra': guide_ra.tolist(),'dec' : guide_dec.tolist(),'mag':
                guide_mag.tolist(),'xp':guide_xp.tolist(),'yp':guide_yp.tolist(),'message':message, 'process': 'Done'}
        guidedata=json.dumps(dict_data)
        return guidedata


# Load alpha/beta motion plans from the selected tile's path file.
    def load_motion(self):
        # Reload offsets so configuration changes apply to the next tile load.
        with open('./Lib/KSPEC.ini','r') as fs:
            motion_config=json.load(fs)['SCIOBS']
        offsets={'a': float(motion_config['alpha_offset_deg']),
                 'b': float(motion_config['beta_offset_deg'])}

        pathfile=os.path.join(self.motionpath, f'{self.project}_2627_{int(self.tile_id):04d}.path.txt')
        with open(pathfile, 'r') as fs:
            columns=[column.strip() for column in fs.readline().strip().split(',')]
            angles=np.loadtxt(fs,delimiter=',',ndmin=2)

        if angles.size == 0 or angles.shape[1] != len(columns):
            raise ValueError(f'Invalid motion data or header column count in {pathfile}')

        # Each data row is one step, numbered from 1.
        steps=list(range(1,angles.shape[0]+1))
        motion_alpha={'step': steps}
        motion_beta={'step': steps}
        for i, column in enumerate(columns):
            fiberid, separator, arm=column.rpartition('_')
            if not separator or not fiberid or arm not in ('a','b'):
                raise ValueError(f'Invalid motion column: {column}')
            motion=motion_alpha if arm == 'a' else motion_beta
            if fiberid in motion:
                raise ValueError(f'Duplicate motion column: {column}')
            motion[fiberid]=(angles[:,i]+offsets[arm]).tolist()

        if motion_alpha.keys() != motion_beta.keys():
            raise ValueError(f'Alpha/beta fiber IDs do not match in {pathfile}')

        a_motion=mkmsg.fbpmsg()
        comment=f'Load Motion plan of alpha arm for Tile ID {self.tile_id}.'
        a_motion.update(func='loadmotion',message=comment,arm='alpha',tileid=self.tile_id,project=self.project,process='Done')
        a_motion.update(motion_alpha)

        b_motion=mkmsg.fbpmsg()
        comment=f'Load Motion plan of beta arm for Tile ID {self.tile_id}.'
        b_motion.update(func='loadmotion',message=comment,arm='beta',tileid=self.tile_id,project=self.project,process='Done')
        b_motion.update(motion_beta)

        motionmsg1=json.dumps(a_motion)
        motionmsg2=json.dumps(b_motion)

        return motionmsg1,motionmsg2


    def loadtile(self,tile_id):
        self.tile_id=tile_id
#        print(self.tile_id)
        tileinfo = self.load_tilepos()
        TCSmsg = tileinfo

    #    guideinfo=self.load_guide()
    #    GFAmsg=guideinfo

        objinfo=self.load_target()
        OBJmsg=objinfo

        print(OBJmsg)

        motionmsg1,motionmsg2=self.load_motion()

        obs_info={'filename': self.filename, 'OBS-date': self.obsdate, 'Tile-ID': self.tile_id, 'Tile-RA': self.ra, 'Tile-DEC': self.dec}
        with open(self.obsinfofile, 'w') as f:
            json.dump(obs_info,f)

#        return OBJmsg
        return TCSmsg,OBJmsg,motionmsg1,motionmsg2
       
