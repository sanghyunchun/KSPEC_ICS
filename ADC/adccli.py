import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import asyncio
import json


def create_adc_command(func, **kwargs):
    """Helper function to create ADC commands."""
    cmd_data = mkmsg.adcmsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)

def adc_init(): return create_adc_command('adcinit', message='Start ADC initializing')
def adc_connect(): return create_adc_command('adcconnect', message='Connect ADC instrument')
def adc_disconnect(): return create_adc_command('adcdisconnect', message='Disconnect ADC instrument')
def adc_home(): return create_adc_command('adchome', message='Homing ADC lens')
def adc_zero(): return create_adc_command('adczero', message='Rotate ADC lens to zero position')
def adc_status(): return create_adc_command('adcstatus', message='ADC status')
def adc_poweroff(): return create_adc_command('adcpoweroff', message='ADC power off')
def adc_stop(): return create_adc_command('adcstop', message='ADC rotating stop')
def adc_park(): return create_adc_command('adcpark', message='Rotate ADC to parking position')

def adc_rotate(lens, count, direction):
    """Rotate ADC lens."""
    return create_adc_command(direction, lens=lens, pcount=count, message=f'Rotate ADC lens {lens} by {count} counts.')

def adc_adjust(ra, dec):
    return create_adc_command('adcadjust', RA=ra, DEC=dec, message='ADC adjusting')

def adc_activate(zdist):
    return create_adc_command('adcactivate', zdist=zdist, message='ADC activate')

async def handle_adc(arg, ICS_client):
    """Handle ADC commands."""
    cmd, *params = arg.split()
    command_map = {
        'adcinit': adc_init, 'adcconnect': adc_connect, 'adcdisconnect': adc_disconnect,
        'adchome': adc_home, 'adczero': adc_zero, 'adcstatus': adc_status,
        'adcpoweroff': adc_poweroff, 'adcstop': adc_stop, 'adcpark': adc_park,
        'adcrotate1': lambda: adc_rotate(1, int(params[0]), 'adcrotate1'),
        'adcrotate2': lambda: adc_rotate(2, int(params[0]), 'adcrotate2'),
        'adcrotateop': lambda: adc_rotate(0, int(params[0]), 'adcrotateop'),
        'adcrotatesame': lambda: adc_rotate(-1, int(params[0]), 'adcrotatesame'),
        'adcadjust': lambda: adc_adjust(float(params[0]), float(params[1])),
        'adcactivate': lambda: adc_activate(float(params[0]))
    }
    if cmd in command_map:
        adcmsg = command_map[cmd]()
        await ICS_client.send_message("ADC", adcmsg)
