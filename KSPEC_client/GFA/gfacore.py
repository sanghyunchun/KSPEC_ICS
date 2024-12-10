import os,sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import json
import asyncio


def gfa_cexpfun(time,chip):
    "Exposure specific GFA camera with desired exposure time"
    comments='GFA camera exposure start'

    dict_data={'inst': 'GFA', 'func' : 'gfacexp', 'time': time, 'chip' : chip,
            'comments': comments}
    GFAmsg=json.dumps(dict_data)
    return GFAmsg


def gfa_allexpfun(time):
    "Exposure all GFA camera with desired exposure time"
    comments='All GFA camera exposure start'

    dict_data={'inst': 'GFA', 'func' : 'gfaallexp', 'time': time,
            'comments': comments}
    GFAmsg=json.dumps(dict_data)
    return GFAmsg

def gfa_autoguidefuc(time):
    "GFA camera autoguiding start"
    comments='GFA autoguiding start'

    dict_data={'inst': 'GFA', 'func' : 'autoguide', 'time': time,
            'comments': comments}
    GFAmsg=json.dumps(dict_data)
    return GFAmsg

def gfa_stopfun():
    comments='All GFA camera exposure stop'

    dict_data={'inst': 'GFA', 'func' : 'gfastop',
            'comments': comments}
    GFAmsg=json.dumps(dict_data)
    return GFAmsg

