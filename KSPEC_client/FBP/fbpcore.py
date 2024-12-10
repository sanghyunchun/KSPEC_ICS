import os,sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import json
import asyncio


def fbp_move():
    comments='Fiber positioner start to move.'

    dict_data={'inst': 'FBP', 'func': 'fbp_move','refunc': 'None','comments': comments}
    FBPmsg=json.dumps(dict_data)
    return FBPmsg

def fbp_offset():
    comments='Fiber positioner start to move.'

    dict_data={'inst': 'FBP', 'func' : 'fbp_offset','refunc': 'None','comments': comments}
    FBPmsg=json.dumps(dict_data)
    return FBPmsg
