import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
# from Lib.MsgMiddleware import *
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
from TCS.tcscli import handle_telcom
import asyncio
import json



def bytes_to_sexagesimal(value: bytes, encoding="ascii") -> str:
        """
        b"453467.8"  -> "45:34:67.8"
        b"-453456.7" -> "-45:34:56.7"
        """
        # bytes → str
        s = value.decode(encoding).strip()

        # 부호 처리
        sign = "-" if s.startswith("-") else ""
        s = s.lstrip("+-")

        # 정수부 / 소수부 분리
        if "." in s:
            integer, frac = s.split(".", 1)
            frac = "." + frac
        else:
            integer = s
            frac = ""

        if len(integer) < 6:
            raise ValueError(f"sexagesimal 변환에 필요한 자릿수 부족: {s}")

        h = integer[0:2]
        m = integer[2:4]
        sec = integer[4:] + frac

        return f"{sign}{h}:{m}:{sec}"

def load_config():
    """Loads configuration settings from KSPEC.ini."""
    with open('./Lib/KSPEC.ini', 'r') as f:
        kspecinfo = json.load(f)

    return kspecinfo['TCS']['TCSagentIP'], kspecinfo['TCS']['TCSagentPort'], kspecinfo['TCS']['TelcomIP'],kspecinfo['TCS']['TelcomPort']



def create_gfa_command(func, **kwargs):
    """Helper function to create ADC commands."""
    cmd_data = mkmsg.gfamsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)

def gfa_status() : return create_gfa_command('gfastatus', message ='Show GFA status')

def gfa_guiding(expt: float = 1.0, save: bool = False, *, ra: str=None, dec: str=None) : 
    return create_gfa_command('gfaguide', ExpTime=expt,save=save,message ='Autoguiding Start!', ra=ra, dec=dec)

def gfa_guidestop() : return create_gfa_command('gfaguidestop',message='Stop autoguiding')

def gfa_grab(cam,expt, *,ra: str=None, dec: str=None):
    return create_gfa_command('gfagrab',CamNum=cam,ExpTime=expt,message=f'Expose camera {cam} for {expt} seconds.',ra=ra,dec=dec)

def fd_grab(expt):
    return create_gfa_command('fdgrab',ExpTime=expt,message=f'Expose finder camera for {expt} seconds.')

def gfa_pointing(expt: float=1.0, ra: str=None, dec: str=None):
    return create_gfa_command('pointing', ExpTime=expt, ra=ra, dec=dec, message=f'Pointing to RA={ra}, DEC={dec}')      # Using six GFA cameras 

async def send_telcom_command(message):
    tcsagentIP, tcsagentPort, telcomIP, telcomPort = load_config()
    telcom_client = TCPClient(telcomIP,telcomPort)
    await telcom_client.connect()
    result = await handle_telcom(message,telcom_client)
    await telcom_client.close()
    return result

async def getradec():
    ra_bytes=await send_telcom_command('getra')
    dec_bytes=await send_telcom_command('getdec')
#    print(ra_bytes,dec_bytes)

    ra=bytes_to_sexagesimal(ra_bytes)
    dec=bytes_to_sexagesimal(dec_bytes)
    return ra, dec


async def handle_gfa(arg, ICS_client):
    cmd, *params = arg.split()
    command_map = {
        'gfastatus': gfa_status,
        'gfaguidestop' : gfa_guidestop
    }

#    ra_bytes=await send_telcom_command('getra')
#    dec_bytes=await send_telcom_command('getdec')
#    print(ra_bytes,dec_bytes)

#    ra=bytes_to_sexagesimal(ra_bytes)
#    dec=bytes_to_sexagesimal(dec_bytes)

    if cmd == 'gfagrab':
        if len(params) != 2:
            print("Error: 'gfagrab' needs two parameters: camera number and exposure time value. ex) gfagrab 1 10 ")
            return
        try:
            camNum, ExpT = int(params[0]), float(params[1])
        except ValueError:
            print(f"Error: Input parameters of 'gfagrab' should be int and float. input value: {params[0]} {params[1]}")
            return
        ra,dec= await getradec()
        command_map[cmd] = lambda: gfa_grab(camNum, ExpT, ra=ra, dec=dec)

    elif cmd == 'gfaguide':
        ra,dec=await getradec()
        if not params:
            command_map[cmd] = lambda: gfa_guiding(ra=ra, dec=dec)
        else:
            ExpT = float(params[0])
            save = params[1]
            command_map[cmd] = lambda: gfa_guiding(ExpT, save, ra=ra, dec=dec)

    elif cmd == 'fdgrab':
        if len(params) != 1:
            print("Error: 'fdgrab' needs one parameter: Exposure time value. ex) fdgrab 10 ")
            return
        try:
            ExpT = float(params[0])
        except ValueError:
            print(f"Error: Input parameters of 'fdgrab' should be float. input value: {params[0]}")
            return
        command_map[cmd] = lambda: fd_grab(ExpT)

    elif cmd == 'pointing':
        ExpT = float(params[0])
        ra = params[1]
        dec = params[2]
        command_map[cmd] = lambda: gfa_pointing(ExpT,ra,dec)


    if cmd in command_map:
        gfamsg = command_map[cmd]()
        await ICS_client.send_message("GFA", gfamsg)
    else:
        print(f"Error: '{cmd}' is not right command for GFA.")

