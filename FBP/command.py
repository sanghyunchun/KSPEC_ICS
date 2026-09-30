import os,sys
from Lib.AMQ import *
import Lib.mkmessage as mkmsg
import json
import asyncio
import numpy as np
import time
from pathlib import Path
import FBP.kspec_positioner_controller.position_action as FBP_action

# The current tile is ready only after both loadmotion messages are saved.
_motion_tile = None
_motion_files = {}
_fbp_activate_lock = asyncio.Lock()


def loaded_motion_paths():
    if set(_motion_files) != {'alpha', 'beta'}:
        raise ValueError('Load both alpha and beta motion files for the tile first.')
    return {'alpha_file': _motion_files['alpha'], 'beta_file': _motion_files['beta']}


def load_config(config_path='./Lib/KSPEC.ini'):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"KSPEC.ini not found at {config_path}")

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Error parsing KSPEC.ini: {e}")
    except OSError as e:
        raise IOError(f"Error reading KSPEC.ini: {e}")

    return config

def printing(message):
    """Utility function for consistent printingging.

    Args:
        message (str): The message to be printingged.
    """
    print(f"\033[32m[FBP] {message}\033[0m")

async def send_fbp_response(FBP_server, result=None, *, log=True, **updates):
    reply_data = mkmsg.fbpmsg()

    if result is not None:
        reply_data.update(result)

    reply_data.update(updates)

    rsp = json.dumps(reply_data)
    if log and reply_data.get('message'):
        printing(reply_data['message'])

    await FBP_server.send_message('ICS', rsp)
    return reply_data

async def identify_execute(FBP_server,cmd):
    dict_data=json.loads(cmd)
    func=dict_data['func']

    if func in ('fbpmoveall', 'fbpinitial', 'fbpinitial_from_stop'):
        try:
            motion_paths = loaded_motion_paths()
        except ValueError as error:
            await send_fbp_response(FBP_server, func=func, process='Done',
                                    status='fail', message=str(error))
            return

    if func == 'loadobj':
        ra=dict_data['ra']
        dec=dict_data['dec']
        xp=dict_data['xp']
        yp=dict_data['yp']
        clss=dict_data['class']
        status, comment=savedata(ra,dec,xp,yp,clss)  # Save Target information

        reply_data=mkmsg.fbpmsg()
        reply_data.update(message=comment,process='Done',status=status)
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'loadmotion':
        status, comment = savemotion(dict_data)
        reply_data=mkmsg.fbpmsg()
        reply_data.update(func='loadmotion',arm=dict_data.get('arm'),message=comment,process='Done',status=status)
        rsp=json.dumps(reply_data)
        print('\033[32m'+'[FBP]', comment+'\033[0m')
        await FBP_server.send_message('ICS',rsp)

    if func == 'fbpstepstatus':
        result = await FBP_action.show_step_status()
        await send_fbp_response(
            FBP_server, result, func=func, process='Done', fbp_state='None'
        )
        return

    if func == 'fbpactivate':
        if _fbp_activate_lock.locked():
            await send_fbp_response(
                FBP_server,
                func=func,
                process='Done',
                status='error',
                message='TwinCAT Activate/Login/Play가 이미 진행 중입니다.',
                fbp_state='None',
            )
            return

        await send_fbp_response(
            FBP_server,
            func=func,
            process='START',
            status='success',
            message='PLC1, PLC2의 TwinCAT Activate 및 PLC Login/Play를 시작합니다.',
            fbp_state='None',
        )
        async with _fbp_activate_lock:
            result = await FBP_action.activate_and_play_all_plcs()

        await send_fbp_response(
            FBP_server, result, func=func, process='Done', fbp_state='None'
        )
        return

    if func == 'fbpstatus':
        positioner = dict_data['positioner']
        result = await FBP_action.show_status(axis=positioner)
        print(result['data'])

        await send_fbp_response(
                FBP_server, result, func = 'fbpstatus',
                 process='Done', fbp_state = 'None'
        )

    if func == 'fbplock':
        positioner_text = dict_data.get('positioners', '')

        if isinstance(positioner_text, list):
            positioner_list = [
                str(item).strip()
                for item in positioner_text
                if str(item).strip()
            ]
        else:
            positioner_text = str(positioner_text).strip()
            positioner_list = [
                item.strip()
                for item in positioner_text.split(',')
                if item.strip()
            ]

    #    print(positioner_list)
        result = await FBP_action.positioner_lock(positioner_list)

        await send_fbp_response(
            FBP_server, result, func='fbplock',process = 'Done', fbp_state = 'None')


    if func == 'fbpstop':
        await send_fbp_response(
                    FBP_server, message=f'Start stop current positioners moving',
                    process='START', status='success', fbp_state='assign')
        await asyncio.sleep(1)

        result = await FBP_action.stop_all_positioner()
        
        if result['status'] in ('success', 'stopped'):
            await send_fbp_response(
                    FBP_server, result, func = 'fbpstop', process = 'Done', fbp_state = 'stop')
        else:
            await send_fbp_response(
                    FBP_server, result, func = 'fbpstop', process = 'Done', fbp_state = 'None')

    if func == 'fbpmoveone':
        positioner = dict_data['positioner']
        motor = dict_data['motor']
        angle = dict_data['angle']
        await send_fbp_response(
                    FBP_server, message=f'Positioner {positioner} {motor} starts to move to {angle}.',
                    process='START', status='success', fbp_state='manual')

        result = await FBP_action.rotate_one(positioner=positioner, motor=motor, angle=angle)

        fbp_state = 'manual'
        if result.get('status') == 'stopped':
            fbp_state = 'stop'
        elif result.get('status') in ('error', 'fail'):
            fbp_state = 'assign'
        elif result.get('status') == 'success':
            # 초기각은 alpha/beta 모두 0도이다. 전체 비잠금 축을 확인한다.
            check_zero = await FBP_action.check_all_zero_positions()
            if check_zero.get('status') == 'success':
                fbp_state = 'initial'

        await send_fbp_response(
            FBP_server, result, func='fbpmoveone',
            process='Done', fbp_state=fbp_state
        )


    if func == 'fbpmoveall':
#        reply_data = mkmsg.fbpmsg()
#        comment = 'Positioners start to move to target positions.'
#        reply_data.update(message=comment,process='START',status='success',fbp_state = 'ING')
#        rsp=json.dumps(reply_data)
#        print('\033[32m'+'[FBP]', comment+'\033[0m')
#        await FBP_server.send_message('ICS',rsp)

        await send_fbp_response(
                    FBP_server, message=f'Positioners start to move to target positions.',
                    process='START', status='success', fbp_state='ING')

        # await asyncio.sleep(5)

        result = await FBP_action.rotate_all(**motion_paths)

        if result.get('status') == 'success':
            fbp_state = 'assign'
        elif result.get('status') == 'stopped':
            fbp_state = 'stop'
        elif result.get('status') in ('error', 'fail'):
            fbp_state = 'assign'
        else:
            fbp_state = 'None'

        await send_fbp_response(
                FBP_server, result, func = 'fbpmoveall',
                process='Done', fbp_state = fbp_state
        )

        
        #reply_data = mkmsg.fbpmsg()
        #comment = 'Positioners successfully moved to their target positions.'
        #reply_data.update(result)
        #reply_data.update(process='Done',fbp_state = 'assign')
        ##rsp=json.dumps(reply_data)
        #print('\033[32m'+'[FBP]', comment+'\033[0m')
        #await FBP_server.send_message('ICS',rsp)

        # reply_data=mkmsg.fbpmsg()
        # comment = 'Fiber positioners start to targets.'
        # reply_data.update(message=comment,process='START',status='success')
        # rsp=json.dumps(reply_data)
        # await FBP_server.send_message('ICS',rsp)

        # status, comment=fbp_move()     ### Position of fiber postioner movement function
        # reply_data=mkmsg.fbpmsg()
        # reply_data.update(message=comment,process='Done',status=status, pos_state='assign')
        # rsp=json.dumps(reply_data)
        # print('\033[32m'+'[FBP]', comment+'\033[0m')
        # await FBP_server.send_message('ICS',rsp)

    if func == 'fbpoffset':
        status, comment, alpha_file, beta_file = saveoffset(dict_data)
        if status != 'success':
            await send_fbp_response(
                FBP_server, func='fbpoffset', process='Done', status=status,
                message=comment, fbp_state='assign'
            )
            return

        await send_fbp_response(
            FBP_server,
            func='fbpoffset',
            message='Positioners start to move to metrology offset angles.',
            process='START',
            status='success',
            fbp_state='ING',
            alpha_file=alpha_file,
            beta_file=beta_file,
        )

        result = await FBP_action.rotate_offset_all(alpha_file, beta_file)

        if result.get('status') == 'success':
            fbp_state = 'assign'
        elif result.get('status') == 'stopped':
            fbp_state = 'stop'
        elif result.get('status') in ('error', 'fail'):
            fbp_state = 'assign'
        else:
            fbp_state = 'None'

        await send_fbp_response(
            FBP_server,
            result,
            func='fbpoffset',
            process='Done',
            fbp_state=fbp_state,
            alpha_file=alpha_file,
            beta_file=beta_file,
        )

#     if func == 'fbpzero':
# #        reply_data=mkmsg.fbpmsg()
# #        comment = 'Positioners start to move to zero positions.'
# #        reply_data.update(message=comment,process='START',status='success', fbp_state = 'ING')
# #        rsp=json.dumps(reply_data)
# #        print('\033[32m'+'[FBP]', comment+'\033[0m')
# #        await FBP_server.send_message('ICS',rsp)

#         await send_fbp_response(
#                     FBP_server, message=f'Positioners starts to move to zero positions.',
#                     process='START', status='success', fbp_state='ING')

#         await asyncio.sleep(5)

#         result = await FBP_action.zero_main()

#         if result.get('status') == 'success':
#             fbp_state = 'zero'
#         elif result.get('status') == 'stopped':
#             fbp_state = 'stop'
#         else:
#             fbp_state = 'None'

#         await send_fbp_response(
#                 FBP_server, result, func = 'fbpzero',
#                 process='Done', fbp_state = fbp_state
#         )

    if func == 'fbpinitial':
        comment = 'Positioners start to move to initial positions from assigned positions.'
        await send_fbp_response(FBP_server,message=comment,process='START',status='success',fbp_state='ING')

        result = await FBP_action.reverse_all(**motion_paths)

#        await asyncio.sleep(5)

        if result.get('status') == 'success':
            fbp_state = 'initial'
        elif result.get('status') == 'stopped':
            fbp_state = 'stop'
        elif result.get('status') in ('error', 'fail'):
            fbp_state = 'assign'
        else:
            fbp_state = 'None'

        await send_fbp_response(
                FBP_server, result, func = 'fbpinitial',
                process='Done', fbp_state = fbp_state
        )

    if func == 'fbpinitial_from_stop':
        comment = 'Positioners start to move to initial positions from stop positions.'
        await send_fbp_response(FBP_server,message=comment,process='START',status='success',fbp_state='ING')

        result = await FBP_action.reverse_from_stop_step(**motion_paths)

        if result.get('status') == 'success':
            fbp_state = 'initial'
        elif result.get('status') == 'stopped':
            fbp_state = 'stop'
        elif result.get('status') in ('error', 'fail'):
            fbp_state = 'assign'
        else:
            fbp_state = 'None'

        await send_fbp_response(
                FBP_server, result, func = 'fbpintial_from_stop',
                process='Done', fbp_state = fbp_state
        )

# Below functions are for simulation. When connect the Fiber positioner, please annotate
def fbp_zero():
    try:
        kspecinfo=load_config()
        fbpfilepath = kspecinfo['FBP']['fbpfilepath']
    except Exception as e:
        return 'fail', str(e)

#    ra,dec,xp,yp=np.loadtxt(fbpfilepath+'object.radec',dtype=float,unpack=True,usecols=(0,1,2,3))
    time.sleep(5)
    rspmsg=f'Fiber positioners successfully moved to zero position.'
    return 'success', rspmsg

def fbp_move():
    try:
        kspecinfo=load_config()
        fbpfilepath = kspecinfo['FBP']['fbpfilepath']
    except Exception as e:
        return 'fail', str(e)

    with open(fbpfilepath+'motion_alpha.info','r') as fs:
        alpha=json.load(fs)
    with open(fbpfilepath+'motion_alpha.info','r') as fs:
        alpha=json.load(fs)

    time.sleep(20)
    rspmsg=f'Fiber positioners movement finished.'
    return 'success', rspmsg

def fbp_status():
    time.sleep(2)
    rspmsg='Fiber positioners status below. FBP is ready.'
    return 'success', rspmsg

def savedata(ra,dec,xp,yp,clss):
    try:
        kspecinfo=load_config()
        fbpfilepath = kspecinfo['FBP']['fbpfilepath']
    except Exception as e:
        return 'fail', str(e)

    try:
        with open(fbpfilepath+'object.radec','w') as savefile:
            for i in range(len(ra)):
                savefile.write("%12.6f %12.6f %12.6f %12.6f %8s\n" % (ra[i],dec[i],xp[i],yp[i],clss[i]))
    except TypeError:
        return 'fail', "Non-numeric values encountered while formatting output."
    except OSError as e:
        return 'fail', f"Failed to write file: {e}"

    rspmsg="'Objects are loaded in FBP server.'"
    return 'success', rspmsg


def savemotion(dict_data):
    global _motion_tile
    try:
        kspecinfo=load_config()
        fbpfilepath = kspecinfo['FBP']['fbpfilepath']
    except Exception as e:
        _motion_files.clear()
        return 'fail', str(e)

    try:
        arm=dict_data['arm']
        if arm not in ('alpha', 'beta'):
            raise ValueError(f'Invalid motion arm: {arm}')
        project=dict_data['project']
        if not isinstance(project, str) or not project or os.path.basename(project) != project:
            raise ValueError('Invalid motion project name')
        tile_id=int(dict_data['tileid'])
        file_path=os.path.abspath(os.path.join(fbpfilepath, f'{project}_2627_{tile_id:04d}_{arm}.path.json'))
        os.makedirs(fbpfilepath, exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(dict_data, f)

    except (KeyError, TypeError, ValueError) as e:
        _motion_files.clear()
        return 'fail', f'Invalid motion data: {e}'
    except OSError as e:
        _motion_files.clear()
        return 'fail', f"Failed to write file: {e}"

    tile = (project, tile_id)
    if tile != _motion_tile or arm in _motion_files:
        _motion_files.clear()
    _motion_tile = tile
    _motion_files[arm] = file_path
    msg=f'Motion plan of {arm} is successfully saved to {file_path}.'
    return 'success', msg


def saveoffset(dict_data):
    """MTL 누적각 JSON 메시지를 alpha/beta offset JSON으로 분리해 저장한다."""
    try:
        kspecinfo = load_config()
        fbpfilepath = os.path.abspath(os.path.expanduser(kspecinfo['FBP']['fbpfilepath']))
        offsets = dict_data['offsets']
        source_name = Path(str(dict_data.get('source_name', 'metrology.json'))).name

        if not isinstance(offsets, dict) or not offsets:
            raise ValueError('offsets는 비어 있지 않은 object 형식이어야 합니다.')

        map_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'Lib',
            'positioner_axis_map.json',
        )
        with open(map_path, 'r', encoding='utf-8') as file:
            expected_positioners = set(json.load(file))

        alpha_data = {}
        beta_data = {}
        for key, value in offsets.items():
            if not isinstance(key, str) or not key.endswith(('_a', '_b')):
                raise ValueError(f'잘못된 offset key입니다: {key}')

            positioner, suffix = key.rsplit('_', 1)
            if isinstance(value, bool):
                raise ValueError(f'{key} offset 각도는 숫자여야 합니다.')
            angle = float(value)
            if not np.isfinite(angle):
                raise ValueError(f'{key} offset 각도는 유한한 값이어야 합니다.')

            destination = alpha_data if suffix == 'a' else beta_data
            if positioner in destination:
                raise ValueError(f'중복된 offset key입니다: {key}')
            destination[positioner] = angle

        if set(alpha_data) != expected_positioners:
            raise ValueError(
                'alpha offset positioner 구성이 축 매핑과 다릅니다. '
                f'missing={sorted(expected_positioners - set(alpha_data))}, '
                f'extra={sorted(set(alpha_data) - expected_positioners)}'
            )
        if set(beta_data) != expected_positioners:
            raise ValueError(
                'beta offset positioner 구성이 축 매핑과 다릅니다. '
                f'missing={sorted(expected_positioners - set(beta_data))}, '
                f'extra={sorted(set(beta_data) - expected_positioners)}'
            )

        source_stem = source_name[:-5] if source_name.lower().endswith('.json') else source_name
        if not source_stem:
            source_stem = 'metrology'
        os.makedirs(fbpfilepath, exist_ok=True)
        alpha_file = os.path.join(fbpfilepath, f'{source_stem}_alpha.offset.json')
        beta_file = os.path.join(fbpfilepath, f'{source_stem}_beta.offset.json')

        for output_file, data in ((alpha_file, alpha_data), (beta_file, beta_data)):
            with open(output_file, 'w', encoding='utf-8') as file:
                json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
                file.write('\n')

    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return 'fail', f'Invalid offset data: {error}', None, None
    except OSError as error:
        return 'fail', f'Failed to write offset file: {error}', None, None

    message = f'Offset files are saved to {alpha_file} and {beta_file}.'
    return 'success', message, alpha_file, beta_file
