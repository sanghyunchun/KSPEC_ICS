import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from SCIOBS.sciobscli import sciobscli
from GFA.gfacli import *
from MTL.mtlcli import *
from TCS.tcscli import *
from FBP.fbpcli import *
from ADC.adccli import *
from LAMP.lampcli import *
from SPECTRO.speccli import *
from ENDO.ENDOcli import *
from Lib.AMQ import *
#from script.test import *
import Lib.process as processes

cmdlist = [
    '', 'loadfile', 'obsstatus',
    'getra',
    'gfastatus', 'gfacexp', 'gfaallexp', 'gfastop', 'autoguide', 'autoguidestop',
    'endoguide', 'endotest', 'endofocus', 'endostop', 'endoexpset', 'endoclear',
    'mtlstatus', 'mtlexp', 'mtlcal',
    'adcstatus', 'adcactivate', 'adcadjust', 'adcinit', 'adcconnect', 'adcdisconnect', 'adchome', 'adczero', 
    'adcpoweroff', 'adcrotate1', 'adcrotate2', 'adcstop', 'adcpark','adcrotateop','adcrotatesame',
    'fbpstatus', 'fbpmove', 'fbpoffset', 'fbpinit',
    'lampstatus', 'arcon', 'arcoff', 'flaton', 'flatoff', 'fidon', 'fiducialoff',
    'specstatus', 'specilluon', 'specilluoff', 'getobj', 'getbias', 'getflat', 'getarc',
    'runscript',
    'testfunc', 'teststop'
]

async def identify(arg, ICS_client, telcom_client, transport):
    """
    Identify and execute commands based on user input.

    Args:
        arg (str): Command string entered by the user.
        ICS_client (AMQclass): Instance of AMQclass for inter-process communication.
        transport (object): Transport object for sending data of TCS

    Returns:
        None
    """
    cmd = arg.split(' ')
    obs = sciobscli()
    processes.initial()

    if cmd[0] not in cmdlist:
        print('Please insert right command')
        return

    # Commands for testing
    if cmd[0] == 'testfunc':
        testmsg = test_func()
        await ICS_client.send_message("TEST", testmsg)

    if cmd[0] == 'teststop':
        testmsg = test_stop()
        await ICS_client.send_message("TEST", testmsg)

    # Observation status command
    if cmd[0] == 'obsstatus':
        obs.obsstatus()

    # Load observation file to ICS main server
    if cmd[0] == 'loadfile':
        data = obs.loadfile(cmd[1])
        print(data)
        select_tile = input('Please select Tile ID above you want to observe: ')

        obs.loadtile(select_tile)
        if int(select_tile) <= 6000:
            tilemsg, guidemsg, objmsg, motionmsg1, motionmsg2 = obs.loadtile(select_tile)
            await ICS_client.send_message("GFA", guidemsg)
            await ICS_client.send_message("MTL", objmsg)
            await ICS_client.send_message("FBP", objmsg)
            await ICS_client.send_message("FBP", motionmsg1)
            await ICS_client.send_message("FBP", motionmsg2)
        else:
            print('Tile number should be less than 6000')
    
    # TCS Telcom commands. These commands are just backup.
    if cmd[0] == 'getra':
        tcsmsg = await RequestRA(telcom_client)
        print(tcsmsg)


    # Guide camera commands
    if cmd[0] == 'gfastatus':
        gfamsg = gfa_status()
        await ICS_client.send_message("GFA", gfamsg)

    if cmd[0] == 'gfacexp':
        gfamsg = gfa_cexp(cmd[1], cmd[2])
        await ICS_client.send_message("GFA", gfamsg)

    if cmd[0] == 'gfaallexp':
        gfamsg = gfa_allexp(cmd[1])
        respond = await ICS_client.send_message('GFA', gfamsg)

    if cmd[0] == 'autoguide':
        gfamsg = gfa_autoguide()
        await ICS_client.send_message("GFA", gfamsg)

    if cmd[0] == 'autoguidestop':
        gfamsg = autoguide_stop()
        await ICS_client.send_message("GFA", gfamsg)

    # Endoscope commands
    if cmd[0] == 'endoguide':
        endomsg = endo_guide()
        await ICS_client.send_message("ENDO", endomsg)

    if cmd[0] == 'endostop':
        endomsg = endo_stop()
        await ICS_client.send_message("ENDO", endomsg)

    if cmd[0] == 'endotest':
        endomsg = endo_test()
        await ICS_client.send_message("ENDO", endomsg)

    if cmd[0] == 'endofocus':
        endomsg = endo_focus(cmd[1])
        await ICS_client.send_message("ENDO", endomsg)

    if cmd[0] == 'endoexpset':
        endomsg = endo_expset(cmd[1])
        await ICS_client.send_message("ENDO", endomsg)

    if cmd[0] == 'endoclear':
        endomsg = endo_clear()
        await ICS_client.send_message("ENDO", endomsg)

    # Metrology commands
    if cmd[0] == 'mtlexp':
        mtlmsg = mtl_exp(cmd[1])
        await ICS_client.send_message("MTL", mtlmsg)

    if cmd[0] == 'mtlcal':
        mtlmsg = mtl_cal()
        await ICS_client.send_message("MTL", mtlmsg)

    if cmd[0] == 'mtlstatus':
        mtlmsg = mtl_status()
        await ICS_client.send_message('MTL', mtlmsg)
        return

    # Fiber positioner commands
    if cmd[0] == 'fbpmove':
        fbpmsg = fbp_move()
        await ICS_client.send_message("FBP", fbpmsg)

    if cmd[0] == 'fbpoffset':
        fbpmsg = fbp_offset()
        await ICS_client.send_message("FBP", fbpmsg)

    if cmd[0] == 'fbpstatus':
        fbpmsg = fbp_status()
        await ICS_client.send_message("FBP", fbpmsg)

    if cmd[0] == 'fbpinit':
        fbpmsg = fbp_init()
        await ICS_client.send_message("FBP", fbpmsg)

    # ADC commands
    if cmd[0] == 'adcactivate':
        adcmsg = adc_activate(cmd[1])
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcadjust':
        adcmsg = adc_adjust(cmd[1], cmd[2])
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcinit':
        adcmsg = adc_init()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcstatus':
        adcmsg = adc_status()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcpoweroff':
        adcmsg = adc_poweroff()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcconnect':
        adcmsg = adc_connect()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcdisconnect':
        adcmsg = adc_disconnect()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adchome':
        adcmsg = adc_home()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adczero':
        adcmsg = adc_zero()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcpark':
        adcmsg = adc_park()
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcrotate1':                   # ADC2 rotate @ L4
        adcmsg = adc_rotate1(cmd[1])
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcrotate2':                   # ADC1 rotate @ L3
        adcmsg = adc_rotate2(cmd[1])
        await ICS_client.send_message("ADC", adcmsg)

    if cmd[0] == 'adcrotateop':             
        adcmsg=adc_rotateop(cmd[1])
        await ICS_client.send_message("ADC",adcmsg)

    if cmd[0] == 'adcrotatesame':               
        adcmsg=adc_rotatesame(cmd[1])
        await ICS_client.send_message("ADC",adcmsg)

    if cmd[0] == 'adcstop':
        adcmsg = adc_stop()
        await ICS_client.send_message("ADC", adcmsg)

    # Spectrograph commands
    if cmd[0] == 'specilluon':
        specmsg = spec_illu_on()
        await ICS_client.send_message("SPEC", specmsg)

    if cmd[0] == 'specilluoff':
        specmsg = spec_illu_off()
        await ICS_client.send_message("SPEC", specmsg)

    if cmd[0] == 'objexp':
        specmsg = obj_exp(cmd[1])
        await ICS_client.send_message("SPEC", specmsg)

    if cmd[0] == 'specstatus':
        specmsg = spec_status()
        await ICS_client.send_message("SPEC", specmsg)

    if cmd[0] == 'biasexp':
        specmsg = bias_exp(cmd[1])
        await ICS_client.send_message("SPEC", specmsg)

    if cmd[0] == 'flatexp':
        specmsg = flat_exp(cmd[1], cmd[2])
        await ICS_client.send_message("SPEC", specmsg)

    if cmd[0] == 'arcexp':
        specmsg = arc_exp(cmd[1], cmd[2])
        await ICS_client.send_message("SPEC", specmsg)

    # Lamp commands
    if cmd[0] == 'lampstatus':
        lampmsg = lamp_status()
        await ICS_client.send_message("LAMP", lampmsg)

    if cmd[0] == 'arcon':
        lampmsg = arcon()
        await ICS_client.send_message("LAMP", lampmsg)

    if cmd[0] == 'arcoff':
        lampmsg = arcoff()
        await ICS_client.send_message("LAMP", lampmsg)

    if cmd[0] == 'flaton':
        lampmsg = flaton()
        await ICS_client.send_message("LAMP", lampmsg)

    if cmd[0] == 'flatoff':
        lampmsg = flatoff()
        await ICS_client.send_message("LAMP", lampmsg)

    if cmd[0] == 'fiducialon':
        lampmsg = fiducialon()
        await ICS_client.send_message("LAMP", lampmsg)

    if cmd[0] == 'fiducialoff':
        lampmsg = fiducialoff()
        await ICS_client.send_message("LAMP", lampmsg)

    # Script commands
    if cmd[0] == 'runscript':
        await scriptrun(ICS_client, telcom_client, transport, cmd[1])

