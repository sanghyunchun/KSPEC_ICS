import os,sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import json
import asyncio


def mtl_expfun():
    comments='Metrology camera exposure start'

    dict_data={'inst': 'MTL', 'func' : 'mtlexp','comments': comments}
    MTLmsg=json.dumps(dict_data)
    return MTLmsg
