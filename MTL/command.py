import asyncio
import json
import os
import time

import Lib.mkmessage as mkmsg
from kspec_metrology.exposure.mtlexp import mtlexp as take_test_exposure
from kspec_metrology.mtlrun import MetrologyRun
from kspec_metrology.analysis.mtlcal import mtlcal as analyze_images, json_path


class MTLContext:
    """MTL 서버가 실행되는 동안 현재 metrology run 상태를 보관한다."""

    def __init__(self):
        self.run = None
        self.target_file = None
        self.lock = asyncio.Lock()

    def reset(self):
        self.run = None


def _is_missing(value):
    return value is None or (isinstance(value, str) and value.strip() in ("", "None"))


def _value(message, key, default, cast=None):
    value = message.get(key, default)
    if _is_missing(value):
        value = default
    return cast(value) if cast is not None and value is not None else value


def _load_mtl_config():
    with open("./Lib/KSPEC.ini", "r", encoding="utf-8") as file:
        return json.load(file)["MTL"]


def _target_filename(data):
    project = data["project"]
    if not isinstance(project, str) or not project or os.path.basename(project) != project:
        raise ValueError("Invalid target project name")
    return f'{project}_2627_{int(data["tile_id"]):04d}.assign.json'
#    return f'object.info'


async def _send_response(server, func, message, process="Done", status="success", **data):
    reply_data = mkmsg.mtlmsg()
    reply_data.update(
        func=func,
        message=message,
        process=process,
        status=status,
        **data,
    )
    await server.send_message("ICS", json.dumps(reply_data))
    return reply_data


def _require_run(context):
    if context.run is None:
        raise RuntimeError("MTL run이 초기화되지 않았습니다. mtlstart를 먼저 실행하십시오.")
    return context.run


async def identify_execute(MTL_server, cmd, context):
    """MTL 명령을 실행하고 MetrologyRun의 상태를 다음 명령까지 유지한다."""

    receive_msg = json.loads(cmd)
    func = receive_msg["func"]

    async with context.lock:
        try:
            if func == "mtlstatus":
                comment = await asyncio.to_thread(mtl_status)
                run = context.run
                await _send_response(
                    MTL_server,
                    func,
                    comment,
                    initialized=run is not None,
                    itrial=run.itrial if run is not None else 0,
                    converged=run.converged if run is not None else False,
                    should_continue=run.should_continue if run is not None else False,
                )
                return

            if func == "loadobj":
                status, comment = await asyncio.to_thread(savedata, receive_msg)
                if status == "success":
                    # target이 바뀌었으므로 기존 run을 다시 사용하지 않는다.
                    context.reset()
                    context.target_file = os.path.join(
                        _load_mtl_config()["mtlfilepath"], _target_filename(receive_msg)
                    )
                await _send_response(MTL_server, func, comment, status=status)
                return

            if func == "mtlstart":
                config = _load_mtl_config()
                target_file = _value(
                    receive_msg,
                    "target_file",
                    context.target_file or os.path.join(config["mtlfilepath"], "object.info"),
                )
                data_dir = _value(receive_msg, "data_dir", config["mtlimagepath"])
                json_dir = _value(receive_msg, "json_dir", config["mtlfilepath"])
                tile = _value(receive_msg, "tile", None)

                run = MetrologyRun(
                    target_file=target_file,
                    data_dir=data_dir,
                    json_dir=json_dir,
                    tolerance=_value(receive_msg, "tolerance", 10.0, float),
                    metric=_value(receive_msg, "metric", "max", str),
                    max_trial=_value(receive_msg, "max_trial", 5, int),
                    nexposure=_value(receive_msg, "nexposure", 1, int),
                    mode=_value(receive_msg, "mode", "Predict", str),
                    threshold=_value(receive_msg, "threshold", 3000.0, float),
                    exptime=_value(receive_msg, "time", 0.1, float),
                    gain=_value(receive_msg, "gain", 10, float),
                    offset=_value(receive_msg, "offset", 30, float),
                    readmode=_value(receive_msg, "readmode", 1, int),
                    usb_traffic=_value(receive_msg, "usb_traffic", 40, int),
                    tile=tile,
                )
                trial0_json = await asyncio.to_thread(run.start)

                # 생성과 start가 모두 성공한 경우에만 현재 run을 교체한다.
                context.run = run

                await _send_response(
                    MTL_server,
                    func,
                    "MTL run이 초기화되었고 Trial 0 기준 JSON이 생성되었습니다.",
                    savedata="True",
                    filename=trial0_json,
                    tile=run.tile,
                    itrial=run.itrial,
                    max_trial=run.max_trial,
                    nexposure=run.nexposure,
                    tolerance=run.tolerance,
                    metric=run.metric,
                )
                return

            if func == "mtltest":
                config = _load_mtl_config()
                exptime = _value(receive_msg, "time", 0.1, float)
                nexposure = _value(receive_msg, "nexposure", 1, int)
                data_dir = _value(
                    receive_msg,
                    "data_dir",
                    config["mtlimagepath"],
                    str,
                )
                requested_file = _value(receive_msg, "file", "test.fits", str)

                if exptime <= 0:
                    raise ValueError("exptime은 0보다 커야 합니다.")
                if nexposure < 1:
                    raise ValueError("nexposure는 1 이상이어야 합니다.")

                # mtlexp()는 최종 파일명이 아닌 파일명 접두어(head)를 받는다.
                # 경로 성분은 제거하여 테스트 이미지가 data_dir 밖에 저장되지 않게 한다.
                filename = os.path.basename(requested_file)
                stem = os.path.splitext(filename)[0] or "test"
                head = f"{stem}_"

                await _send_response(
                    MTL_server,
                    func,
                    "MTL camera test exposure starts.",
                    process="ING",
                    exptime=exptime,
                    nexposure=nexposure,
                )

                images = await asyncio.to_thread(
                    take_test_exposure,
                    exptime=exptime,
                    nexposure=nexposure,
                    data_dir=data_dir,
                    head=head,
                    gain=_value(receive_msg, "gain", 10, float),
                    offset=_value(receive_msg, "offset", 30, float),
                    readmode=_value(receive_msg, "readmode", 1, int),
                    usb_traffic=_value(receive_msg, "usb_traffic", 40, int),
                    extra_header={"IMAGETYP": "MTL CAMERA TEST"},
                )

                await _send_response(
                    MTL_server,
                    func,
                    "MTL camera test exposure finished successfully.",
                    exptime=exptime,
                    nexposure=len(images),
                    images=list(images),
                )
                return

            if func == "mtlcal":
                options = {
                    'data_dir': _value(receive_msg, 'data_dir', './MTL/data/', str),
                    'head': _value(receive_msg, 'head', 'test', str),
                    'mode': _value(receive_msg, 'mode', 'Raw', str),
                    'threshold': _value(receive_msg, 'threshold', 3e3, float),
                    'nwindow': _value(receive_msg, 'nwindow', 40, int),
                    'nexposure': _value(receive_msg, 'nexposure', 1, int),
                    'target_file': _value(receive_msg, 'target_file', None, str),
                    'json_dir': _value(receive_msg, 'json_dir', None, str),
                    'target_name': _value(receive_msg, 'target_name', None, str),
                    'itrial': _value(receive_msg, 'itrial', 1, int),
                }
                if options['mode'] not in ('Raw', 'Predict'):
                    raise ValueError('mode must be Raw or Predict')
                if options['nwindow'] < 1 or options['nexposure'] < 1 or options['itrial'] < 1:
                    raise ValueError('nwindow, nexposure and itrial must be at least 1')
                if (options['json_dir'] is None) != (options['target_name'] is None):
                    raise ValueError('Specify both json_dir and target_name to save JSON')

                await _send_response(MTL_server, func, 'MTL image analysis starts.', process='ING')
                dx, dy, angle_rot, angle_cum = await asyncio.to_thread(analyze_images, **options)
                filename = None
                if options['json_dir'] is not None:
                    filename = json_path(options['json_dir'], options['target_name'], options['itrial'])
                await _send_response(
                    MTL_server, func, 'MTL image analysis finished successfully.',
                    savedata='True' if filename is not None else 'False',
                    filename=filename, itrial=options['itrial'],
                    offsetx=dx.tolist(), offsety=dy.tolist(),
                    angle_rot=angle_rot.tolist(), angle_cum=angle_cum.tolist(),
                )
                return

            if func == "mtltrial":
                run = _require_run(context)
                if not run.should_continue:
                    raise RuntimeError("이미 수렴했거나 max_trial 횟수에 도달했습니다.")
                expected_trial = run.itrial + 1

                await _send_response(
                    MTL_server,
                    func,
                    f"MTL Trial {expected_trial} exposure and analysis start.",
                    process="ING",
                    itrial=expected_trial,
                )

                result = await asyncio.to_thread(run.trial, expose=True)

                await _send_response(
                    MTL_server,
                    func,
                    f"MTL Trial {result.itrial} exposure, analysis and JSON saving finished successfully.",
                    savedata="True",
                    filename=result.json,
                    itrial=result.itrial,
                    err_max=result.err_max,
                    err_median=result.err_median,
                    converged=result.converged,
                    should_continue=run.should_continue,
                    offsetx=result.dx.tolist(),
                    offsety=result.dy.tolist(),
                    images=result.images,
                )
                return

            if func == "mtlresult":
                run = _require_run(context)
                result = run.result()
                await _send_response(
                    MTL_server,
                    func,
                    "MTL run result.",
                    filename=result.json,
                    tile=result.tile,
                    itrial=result.ntrial,
                    converged=result.converged,
                    err_max=result.err_max if result.history else None,
                    err_median=result.err_median if result.history else None,
                    should_continue=run.should_continue,
                )
                return

            if func == "mtlreset":
                context.reset()
                await _send_response(MTL_server, func, "MTL run 상태를 초기화했습니다.")
                return

            await _send_response(
                MTL_server,
                func,
                f"지원하지 않는 MTL 명령입니다: {func}",
                status="fail",
            )

        except Exception as error:
            await _send_response(
                MTL_server,
                func,
                f"MTL {func} failed: {error}",
                status="fail",
            )


def savedata(data):
    try:
        config = _load_mtl_config()
        mtlfilepath = config["mtlfilepath"]
        target_file = os.path.join(mtlfilepath, _target_filename(data))
        os.makedirs(mtlfilepath, exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as savefile:
            json.dump(data, savefile)
    except (KeyError, TypeError, ValueError) as error:
        return "fail", f"Invalid target data or configuration: {error}"
    except OSError as error:
        return "fail", f"Failed to write file: {error}"

    return "success", f"Objects are saved to {target_file} in MTL server."


def mtl_status():
    time.sleep(3)
    return "Metrology Status is below. MTL is ready."
