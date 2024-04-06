import os,sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import json
import asyncio

def tcs_trafun(ra,dec):
    "Slew telescope to RA & DEC position"
    comments=f'Telescope slew to {ra} & {dec} position'

    dict_data={'inst':'TCS','func':'tra','ra':ra,'dec':dec,'comments':comments}
    TCSmsg=json.dumps(dict_data)
    return TCSmsg
