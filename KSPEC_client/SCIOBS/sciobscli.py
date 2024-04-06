import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
#import argh
#import uuid
from .sciobscore import *
import asyncio
import threading

"""
Provide Sky position (RA, DEC) of Tile and target position to TCS computer,
    GFA computer, Metrology computer and Fiber positioner computer.
"""

#TCS_client = Client('TCS')
#GFA_client=Client('GFA')
def load_tile(tile_id):
#    print(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
    tileinfo = load_tilepos(tile_id)
    TCSmsg = tileinfo
    return TCSmsg
#    asyncio.run(TCS_client.send_message("TCS", TCSmsg))

#    guideinfo=load_guide(tile_id)
#    GFAmsg=guideinfo
#    asyncio.run(GFA_client.send_message("GFA",GFAmsg))


def tra(ra,dec):
    TCSmsg=tradec(ra,dec)
    asyncio.run(TCS_client.send_message("TCS",TCSmsg))
