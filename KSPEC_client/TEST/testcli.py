import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio


def test_func():
    "Exposure specific GFA camera with desired exposure time"
    comment='Test function stars.'

    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='testfunc',message=comment)
    testmsg=json.dumps(cmd_data)

    return testmsg

def test_stop():
    "Exposure specific GFA camera with desired exposure time"
    comment='Test function stars.'

    cmd_data=mkmsg.gfamsg()
    cmd_data.update(func='teststop',message=comment)
    GFAmsg=json.dumps(cmd_data)

    return GFAmsg

