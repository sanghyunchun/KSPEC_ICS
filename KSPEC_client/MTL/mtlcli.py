import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
#import argh
#import uuid
from .mtlcore import *
import asyncio
import threading


def mtl_exp():
#    MTL_client=Client('MTL')
    MTLmsg=mtl_expfun()
    return MTLmsg
#    asyncio.run(MTL_client.send_message('MTL',MTLmsg))
