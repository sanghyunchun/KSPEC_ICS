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
    """Handle ADC commands with error checking."""
    cmd, *params = arg.split()

    # Basic command without parameters
    command_map = {
        'adcinit': adc_init, 'adcconnect': adc_connect, 'adcdisconnect': adc_disconnect,
        'adchome': adc_home, 'adczero': adc_zero, 'adcstatus': adc_status,
        'adcpoweroff': adc_poweroff, 'adcstop': adc_stop, 'adcpark': adc_park,
    }

    # Command rotating counts 
    if cmd in ['adcrotate1', 'adcrotate2', 'adcrotateop', 'adcrotatesame']:
        if len(params) != 1:
            print(f"Error: '{cmd}' command needs one integer parameter (count). ex) {cmd} 342")
            return
        try:
            count = int(params[0])
        except ValueError:
            print(f"Error: '{cmd}' command need one integer parameter. input value: {params[0]}")
            return
        lens_map = {'adcrotate1': 1, 'adcrotate2': 2, 'adcrotateop': 0, 'adcrotatesame': -1}
        command_map[cmd] = lambda: adc_rotate(lens_map[cmd], count, cmd)

    # adcadjust command
    elif cmd == 'adcadjust':
        if len(params) != 2:
            print("Error: 'adcadjust' command need RA an DEC parameters. ex) adcadjust 20:34:34.55 -31:13:45.67")
            return
        try:
            ra, dec = str(params[0]), str(params[1])
        except ValueError:
            print(f"Error: Parameters of 'adcadjust' should be string. input value: {params}")
            return
        command_map[cmd] = lambda: adc_adjust(ra, dec)

    # adcactivate command
    elif cmd == 'adcactivate':
        if len(params) != 1:
            print("Error: 'adcactivate' need one zenith distance value. ex) adcactivate 20.45 ")
            return
        try:
            zdist = float(params[0])
            if zdist >= 60.0:
                print("Error: Zenith distance should be less than 60 degree. input value: {zdist}")
                return
        except ValueError:
            print(f"Error: Input parameters of 'adcactivate' should be float. input value: {params[0]}")
            return
        command_map[cmd] = lambda: adc_activate(zdist)

    # Right command
    if cmd in command_map:
        adcmsg = command_map[cmd]()
        await ICS_client.send_message("ADC", adcmsg)
    else:
        print(f"Error: '{cmd}' is not right command for ADC")

