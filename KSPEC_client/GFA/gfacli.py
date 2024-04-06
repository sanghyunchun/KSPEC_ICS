import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
#import argh
#import uuid
from .gfacore import *
import asyncio
import threading


def gfa_cexp(time,chip):
 #   GFA_client=Client('GFA')
    GFAmsg=gfa_cexpfun(time,chip)
    return GFAmsg
#    asyncio.run(GFA_client.send_message("GFA", GFAmsg))


def gfa_allexp(time):
#    GFA_client=Client('GFA')
    GFAmsg=gfa_allexpfun(time)
    return GFAmsg
#    asyncio.run(GFA_client.send_message("GFA", GFAmsg))

def gfa_stop():
#    GFA_client=Client('GFA')
    GFAmsg=gfa_stopfun()
    return GFAmsg
#    print(GFAmsg)
#    asyncio.run(GFA_client.send_message("GFA", GFAmsg))

