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
from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
from astropy.utils import iers

iers.conf.auto_download = False

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
        tile_id = int(self.tile_id)
        info_path = os.path.join(self.targetpath, f'{self.project}_2627.info.txt')
        matches = []
        with open(info_path) as file:
            for line_number, line in enumerate(file, start=1):
                columns = line.partition('#')[0].split()
                if not columns:
                    continue
                if len(columns) != 3:
                    raise ValueError(f'Invalid tile position at {info_path}:{line_number}')
                try:
                    row_tile_id = int(columns[0])
                except ValueError as error:
                    raise ValueError(f'Invalid Tile ID at {info_path}:{line_number}') from error
                if row_tile_id == tile_id:
                    matches.append((float(columns[1]), float(columns[2])))

        if len(matches) != 1:
            raise ValueError(f'Expected one position for Tile ID {tile_id} in {info_path}; found {len(matches)}')
        self.ra, self.dec = matches[0]

        message='Load Position of Tile'

        dict_data={"inst" : 'TCS', "func" : 'loadtile', 'tid' : tile_id,
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

        zenith_angle = self.calculate_zenith_distance(self.ra, self.dec)
        message='Load Target Objects of Tile'

        dict_data = { "tile_id":tile_id, "project":self.project, "inst" : 'SCIOBS', "func" : 'loadobj', "ra":obj_ra.tolist(), "dec":obj_dec.tolist(),"xp":obj_xp.tolist(),
                "yp":obj_yp.tolist(),"class":obj_class.tolist(),'message':message, 'process': 'Done', 'zenith_angle': zenith_angle}

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
    def load_motion(self, invert_angles=False):
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
            # GUI Deploy reverses the path angle before applying the arm offset.
            path_angles=-angles[:,i] if invert_angles else angles[:,i]
            motion[fiberid]=(path_angles+offsets[arm]).tolist()

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


    def loadtile(self,tile_id, invert_motion_angles=False):
        self.tile_id=tile_id
#        print(self.tile_id)
        tileinfo = self.load_tilepos()
        TCSmsg = tileinfo

    #    guideinfo=self.load_guide()
    #    GFAmsg=guideinfo

        objinfo=self.load_target()
        OBJmsg=objinfo

        #print(OBJmsg)

        motionmsg1,motionmsg2=self.load_motion(invert_angles=invert_motion_angles)

        obs_info={'filename': self.filename, 'OBS-date': self.obsdate, 'Tile-ID': self.tile_id, 'Tile-RA': self.ra, 'Tile-DEC': self.dec}
        with open(self.obsinfofile, 'w') as f:
            json.dump(obs_info,f)

#        return OBJmsg
        return TCSmsg,OBJmsg,motionmsg1,motionmsg2


    def calculate_zenith_distance(self, ra, dec):
        """Calculate the zenith distance for a given RA and DEC.

        Args:
            ra_obj (float): Right Ascension in degrees.
            dec_obj (float): Declination in degrees.

        Returns:
            float: The zenith distance in degrees.
        """

        AAO_LOCATION = EarthLocation(lat=-31.27118, lon=149.06256, height=1165*u.m)
        
        #ra_obj = Angle(ra, unit=u.deg).degree
        #dec_obj = Angle(dec, unit=u.deg).degree
        object_coord = SkyCoord(ra=ra*u.deg, dec=dec*u.deg)
        current_time = Time.now()
        times = current_time + np.arange(0, 16) * u.minute
        altaz_frame = AltAz(obstime=times, location=AAO_LOCATION)
        altaz_coord = object_coord.transform_to(altaz_frame)
        zenith_distance = 90. - altaz_coord.alt.degree
    #    print(f'Current UT time: {current_time}')
    #    print(f'Mean Zenith distance for 16 min. : {zenith_distance} degree')
        return np.mean(zenith_distance)
       
