import os,sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from SCIOBS.sciobscli import sciobscli
from GFA.gfacli import *
from MTL.mtlcli import *
#from TCS.tcscli import *
from FBP.fbpcli import *
from ADC.adccli import *
from LAMP.lampcli import *
from SPECTRO.speccli import *
#import configparser as cp
from Lib.AMQ import *
#from script.test import scriptrun
import Lib.process as processes
#from TEST.testcli import *


cmdlist=['','loadfile','obsstatus',
        'gfastatus','gfacexp','gfaallexp','gfastop','autoguide','autoguidestop',
        'mtlstatus','mtlexp','mtlcal',
        'adcstatus','adcadjust','adcinit',
        'fbpstatus','fbpmove','fbpoffset','fbpinit',
        'lampstatus','arcon','arcoff','flaton','flatoff','fidon','fiducialoff',
        'specstatus','specilluon','specilluoff','objexp','biasexp','flatexp','arcexp',
        'runscript',
        'testfunc','teststop']


async def identify(arg,ICS_client,transport):
    cmd=arg.split(' ')
    obs = sciobscli()
    processes.initial()

    if cmd[0] not in cmdlist:
        print('Please insert right command')

#### Command for TEST ######
    if cmd[0] == 'testfunc':
        testmsg=test_func()
        await ICS_client.send_message("TEST", testmsg)

    if cmd[0] == 'teststop':
        testmsg=test_stop()
        await ICS_client.send_message("TEST", testmsg)

### Command for current observation information
    if cmd[0] == 'obsstatus':
        obs.obsstatus()

### Load observation file to ICS main server 
    if cmd[0] == 'loadfile':
        data=obs.loadfile(cmd[1])
        print(data)
        select_tile=input('Please select Tile ID above you want to observe: ')

        obs.loadtile(select_tile)
        if int(select_tile) <= 6000:
            tilemsg,guidemsg,objmsg,motionmsg1,motionmsg2=obs.loadtile(select_tile)
            await ICS_client.send_message("GFA", guidemsg)
            await ICS_client.send_message("MTL", objmsg)
            await ICS_client.send_message("FBP", objmsg)
            await ICS_client.send_message("FBP", motionmsg1)
            await ICS_client.send_message("FBP", motionmsg2)
        else:
            print('Tile number should be less than 6000')
#            return

##### Command for Guide Camera ###############
# Start exposure specific guide camera
    if cmd[0] == 'gfastatus':
        gfamsg=gfa_status()
        await ICS_client.send_message("GFA", gfamsg)

    if cmd[0] == 'gfacexp':
        gfamsg=gfa_cexp(cmd[1],cmd[2])
        await ICS_client.send_message("GFA", gfamsg)

    if cmd[0] == 'gfaallexp':
        gfamsg=gfa_allexp(cmd[1])
        respond=await ICS_client.send_message('GFA',gfamsg)

    # Start exposure all guide camera
    if cmd[0] == 'autoguide':
        gfamsg=gfa_autoguide()
        await ICS_client.send_message("GFA", gfamsg)

    # Stop GFA camera exposure
    if cmd[0] == 'autoguidestop':
        gfamsg=autoguide_stop()
        await ICS_client.send_message("GFA", gfamsg)


##### Command for Metrology #################
    # Start Metrology exposure
    if cmd[0] == 'mtlexp':
        mtlmsg=mtl_exp(cmd[1])
        await ICS_client.send_message("MTL", mtlmsg)

    if cmd[0] == 'mtlcal':
        mtlmsg=mtl_cal()
        await ICS_client.send_message("MTL", mtlmsg)

    if cmd[0] == 'mtlstatus':
        mtlmsg=mtl_status()
        await ICS_client.send_message('MTL',mtlmsg)
        return

##### Command for Fiber positioner ########################
    if cmd[0] == 'fbpmove':
        fbpmsg=fbp_move()
        await ICS_client.send_message("FBP", fbpmsg)

    if cmd[0] == 'fbpoffset':
        fbpmsg=fbp_offset()
        await ICS_client.send_message("FBP", fbpmsg)

    if cmd[0] == 'fbpstatus':
        fbpmsg=fbp_status()
        await ICS_client.send_message("FBP", fbpmsg)

    if cmd[0] == 'fbpinit':
        fbpmsg=fbp_init()
        await ICS_client.send_message("FBP", fbpmsg)

##### Command for ADC #####################################
    if cmd[0] == 'adcadjust':
        adcmsg=adc_adjust(cmd[1])
        await ICS_client.send_message("ADC",adcmsg)

    if cmd[0] == 'adcinit':
        adcmsg=adc_init()
        await ICS_client.send_message("ADC",adcmsg)

    if cmd[0] == 'adcstatus':
        adcmsg=adc_status()
        await ICS_client.send_message("ADC",adcmsg)

    if cmd[0] == 'adcpoweroff':
        adcmsg=adc_status()
        await ICS_client.send_message("ADC",adcmsg)

##### Command for Spectrograph #####################################
    if cmd[0] == 'specilluon':
        specmsg=spec_illu_on()
        await ICS_client.send_message("SPEC",specmsg)

    if cmd[0] == 'specilluoff':
        specmsg=spec_illu_off()
        await ICS_client.send_message("SPEC",specmsg)

    if cmd[0] == 'objexp':
        specmsg=obj_exp(cmd[1])
        await ICS_client.send_message("SPEC",specmsg)

    if cmd[0] == 'specstatus':
        specmsg=spec_status()
        await ICS_client.send_message("SPEC",specmsg)

    if cmd[0] == 'biasexp':
        specmsg=bias_exp(cmd[1])
        await ICS_client.send_message("SPEC",specmsg)

    if cmd[0] == 'flatexp':
        specmsg=flat_exp(cmd[1],cmd[2])
        await ICS_client.send_message("SPEC",specmsg)

    if cmd[0] == 'arcexp':
        specmsg=arc_exp(cmd[1],cmd[2])
        await ICS_client.send_message("SPEC",specmsg)


##### Command for Arc, Flat & Fiducial Lamp  ######################
    if cmd[0] == 'lampstatus':
        lampmsg=lamp_status()
        await ICS_client.send_message("LAMP",lampmsg)
  
    if cmd[0] == 'arcon':
        lampmsg=arcon()
        await ICS_client.send_message("LAMP",lampmsg)

    if cmd[0] == 'arcoff':
        lampmsg=arcoff()
        await ICS_client.send_message("LAMP",lampmsg)

    if cmd[0] == 'flaton':
        lampmsg=flaton()
        await ICS_client.send_message("LAMP",lampmsg)

    if cmd[0] == 'flatoff':
        lampmsg=flatoff()
        await ICS_client.send_message("LAMP",lampmsg)

    if cmd[0] == 'fiducialon':
        lampmsg = fiducialon()
        await ICS_client.send_message("LAMP",lampmsg)

    if cmd[0] == 'fiducialoff':
        lampmsg=fiducialoff()
        await ICS_client.send_message("LAMP",lampmsg)

##### Command for script ##################################
    if cmd[0] == 'runscript':
        await scriptrun(ICS_client,transport,cmd[1])
