import asyncio
import json
import math
import os
import time

import Lib.mkmessage as mkmsg
import kspec_metrology
from kspec_metrology.exposure.mtlexp import mtlexp as take_test_exposure
from kspec_metrology.mtlrun import MetrologyRun
from kspec_metrology.analysis.mtlcal import mtlcal as analyze_images, json_path
from kspec_metrology.analysis import utils as mtl_utils
from kspec_metrology.analysis.sky_correction import write_corrected_target


# 분석 설정. kspec_metrology 의 노트북(Calibration_Run, Metrology_Debug 등)과 run_trial.py 에서
# 실제 영상으로 검증한 값이다. MetrologyRun / mtlcal 의 자체 기본값(min_dist 40, finder_opts None,
# threshold 3000)은 PSF 가 큰 본 장비에서 spot 하나가 여러 검출로 쪼개져(deblending) fiducial
# 패턴 매칭이 안 될 수 있다. 메시지에 같은 이름의 키가 있으면 그 값을 쓴다 (mtlstart, mtlcal).
#   threshold      : peak 검출 시작 문턱 [ADU]; 검출 개수에 맞춰 자동으로 오르내린다
#   nwindow        : centroid 창 반폭 [px]
#   niter_recenter : centroid 를 무게중심으로 옮겨 다시 재는 횟수
#   min_dist       : 이보다 가까운 검출은 하나로 합친다 [px]
#   model          : camera -> focal 왜곡 모델
ANALYSIS_DEFAULTS = dict(threshold=1e3, nwindow=40, niter_recenter=1, min_dist=80, model='full+affine')
FINDER_OPTS = {'minarea': 9, 'deblend_cont': 1.0}      # sep: spot 하나를 쪼개지 않는다


def _analysis_options(message):
    """ANALYSIS_DEFAULTS 를 메시지 값으로 덮어 돌려준다 (타입은 기본값을 따른다)."""
    out = {}
    for key, default in ANALYSIS_DEFAULTS.items():
        out[key] = _value(message, key, default, type(default))
    if out['nwindow'] < 1 or out['niter_recenter'] < 0 or out['min_dist'] <= 0 or out['threshold'] <= 0:
        raise ValueError('nwindow >= 1, niter_recenter >= 0, min_dist > 0, threshold > 0 이어야 합니다.')
    out['finder_opts'] = dict(FINDER_OPTS)
    # camera -> focal 배율 초기값. None 이면 패키지 기본값 (2026-01 commissioning fit). 다른 광학계일 때만 준다.
    out['magnification'] = _value(message, 'magnification', None, float)
    # positioner 회전 중심 실측값 (arm scan, Measured_Geometry.txt) 을 쓸지. None 이면 패키지 기본값
    # (fiber_config.USE_MEASURED_POSITIONERS, 2026-10-27 부터 켜짐). fiducial 핀홀 실측과는 별개 스위치.
    out['use_measured_positioners'] = _flag(message, 'use_measured_positioners', None)
    return out


def _flag(message, key, default):
    """메시지의 참/거짓 값. 없으면 default. 문자열 'true'/'1'/'on' 등도 받는다."""
    value = message.get(key, None)
    if _is_missing(value):
        return default
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def _package_info():
    """어느 kspec_metrology 가 import 됐는지 (옛 설치본이 잡히는 사고를 로그와 응답으로 드러낸다)."""
    return dict(package=os.path.dirname(os.path.abspath(kspec_metrology.__file__)),
                magnification_default=float(mtl_utils.CAMERA2FOCAL_M))


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


def _expand_path(path):
    """설정이나 명령에 들어온 ~ 경로를 서버 실행 계정의 절대경로로 바꾼다."""
    return os.path.abspath(os.path.expanduser(path))


def _load_mtl_config():
    with open("./Lib/KSPEC.ini", "r", encoding="utf-8") as file:
        config = dict(json.load(file)["MTL"])

    for key in ("mtlfilepath", "mtlimagepath"):
        config[key] = _expand_path(config[key])

    return config


def _sky_corrected_target(target_file, config, message):
    """mtlstart 시점의 하늘 보정 파일 (<이름>_skycorr.json) 과 요약. 꺼져 있으면 (target_file, None).

    KSPEC.ini MTL.sky_correction: enabled, precession (TETE 세차 회전), instrument_offset
    (+ instrument_offset_deg: GFA 로 잰 기기 회전 - planner 회전; 재설치 후 다시 잰다).
    mtlstart 메시지의 sky_correction / precession / instrument_offset / instrument_offset_deg /
    obs_time 이 있으면 그 값이 우선한다. calibration target (이름이나 project 에 'calib',
    또는 하늘 좌표 없음) 은 보정하지 않고 원래 파일을 쓴다 (요약의 skipped).
    """
    sc = dict(config.get("sky_correction") or {})
    if not _flag(message, "sky_correction", bool(sc.get("enabled", False))):
        return target_file, None
    precession = _flag(message, "precession", bool(sc.get("precession", True)))
    use_offset = _flag(message, "instrument_offset", bool(sc.get("instrument_offset", True)))
    offset = _value(message, "instrument_offset_deg", sc.get("instrument_offset_deg", 0.0), float)
    out, summary = write_corrected_target(
        target_file,
        time=_value(message, "obs_time", None, str),
        precession=precession,
        instrument_offset_deg=offset if use_offset else 0.0,
    )
    if summary.get("skipped"):
        print(f"MTL sky correction skipped for {os.path.basename(target_file)}: {summary['skipped']}")
        return target_file, summary
    print(f"MTL sky correction: {os.path.basename(target_file)} -> {os.path.basename(out)}, "
          f"rotation {summary['rotation_deg']:+.4f} deg (precession {summary['precession_deg']:+.4f}"
          f", instrument {summary['instrument_offset_deg']:+.4f}), max shift "
          f"{summary['shift_max_um']:.0f} um, clipped {[c['fiber'] for c in summary['clipped']]}")
    return out, summary


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


def _exposure_settings(message):
    # Wire exposure time is in microseconds; default fiber exposure is 30 ms.
    # kspec_metrology (MetrologyRun / mtlexp) takes milliseconds since 2026-10-24,
    # so the value is converted here, at the boundary.
    exptime_us = _value(message, 'time', 10_000.0, float)     # 2026-10-29: fiber 10 ms (30 ms 는 포화)
    count = _value(message, 'nexposure', 1, float)
    if not math.isfinite(exptime_us) or exptime_us <= 0:
        raise ValueError('Exposure time must be finite and greater than zero')
    if not math.isfinite(count) or count < 1 or not count.is_integer():
        raise ValueError('Exposure count must be a positive integer')
    return exptime_us / 1e3, int(count)          # -> milliseconds


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
                exptime, nexposure = _exposure_settings(receive_msg)
                config = _load_mtl_config()
                target_file = _expand_path(
                    _value(
                        receive_msg,
                        "target_file",
                        context.target_file or os.path.join(config["mtlfilepath"], "object.info"),
                    )
                )
                data_dir = _expand_path(
                    _value(receive_msg, "data_dir", config["mtlimagepath"])
                )
                json_dir = _expand_path(
                    _value(receive_msg, "json_dir", config["mtlfilepath"])
                )
                tile = _value(receive_msg, "tile", None)
                # 하늘 보정 (세차 + 기기 회전 오프셋): Trial 0 각도와 이후 trial 의 목표가 같은 파일을 쓴다
                target_file, sky = _sky_corrected_target(target_file, config, receive_msg)

                analysis = _analysis_options(receive_msg)
                info = _package_info()
                print(f"MTL mtlstart: kspec_metrology at {info['package']}, "
                      f"default magnification {info['magnification_default']:.3f}, "
                      f"analysis {analysis}")

                run = MetrologyRun(
                    target_file=target_file,
                    data_dir=data_dir,
                    json_dir=json_dir,
                    tolerance=_value(receive_msg, "tolerance", 10.0, float),
                    metric=_value(receive_msg, "metric", "max", str),
                    max_trial=_value(receive_msg, "max_trial", 10, int),   # 2026-10-27: 5 -> 10
                    nexposure=nexposure,
                    mode=_value(receive_msg, "mode", "Raw", str),      # Raw: detect + match (robust); Predict only once the errors are < ~1 mm
                    **analysis,                                        # threshold, nwindow, niter_recenter, min_dist, model, finder_opts, magnification
                    n_extra=_value(receive_msg, "n_extra", 0, int),
                    exptime=exptime,
                    fid_exptime=[1.0, 10.0],  # separate fiducial frames [ms] each trial
                    gain=_value(receive_msg, "gain", 10, float),
                    offset=_value(receive_msg, "offset", 30, float),
                    readmode=_value(receive_msg, "readmode", 1, int),
                    usb_traffic=_value(receive_msg, "usb_traffic", 40, int),
                    tile=tile,
                )
                trial0_json = await asyncio.to_thread(run.start)

                # 생성과 start가 모두 성공한 경우에만 현재 run을 교체한다.
                context.run = run
                context.target_file = target_file  # mtlcal 도 보정된 목표를 쓴다

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
                    target_file=target_file,
                    sky_correction=sky,
                    **info,
                )
                return

            if func == "mtlset":
                run = _require_run(context)
                exptime, nexposure = _exposure_settings(receive_msg)
                run.camera['exptime'] = exptime                  # [ms]
                run.nexposure = nexposure
                await _send_response(
                    MTL_server, func,
                    f'MTL exposure settings updated: {exptime / 1e3:g} s, {nexposure} images (next trial).',
                    exptime=exptime, nexposure=nexposure,
                )
                return

            if func == "mtltest":
                config = _load_mtl_config()
                exptime = _value(receive_msg, "time", 1_000_000.0, float) / 1e3   # wire: microseconds -> ms
                nexposure = _value(receive_msg, "nexposure", 1, int)
                data_dir = _expand_path(
                    _value(
                        receive_msg,
                        "data_dir",
                        config["mtlimagepath"],
                        str,
                    )
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
                    exptime_ms=exptime,
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
                config = _load_mtl_config()
                default_target = context.target_file or os.path.join(
                    config['mtlfilepath'], 'object.info'
                )
                json_dir = _value(receive_msg, 'json_dir', None, str)
                fid_head = receive_msg.get('fid_head', None)      # fiducial 전용 노출의 head (0-2 개)
                if isinstance(fid_head, str):
                    fid_head = [t.strip() for t in fid_head.replace(';', ',').split(',') if t.strip()]
                options = {
                    'data_dir': _expand_path(
                        _value(receive_msg, 'data_dir', config['mtlimagepath'], str)
                    ),
                    'head': _value(receive_msg, 'head', 'test', str),
                    'fid_head': list(fid_head) if fid_head else None,
                    'mode': _value(receive_msg, 'mode', 'Raw', str),
                    'n_extra': _value(receive_msg, 'n_extra', 0, int),
                    'nexposure': _value(receive_msg, 'nexposure', 1, int),
                    **_analysis_options(receive_msg),
                    'target_file': _expand_path(
                        _value(receive_msg, 'target_file', default_target, str)
                    ),
                    'json_dir': _expand_path(json_dir) if json_dir is not None else None,
                    'target_name': _value(receive_msg, 'target_name', None, str),
                    'itrial': _value(receive_msg, 'itrial', 1, int),
                }
                if options['mode'] not in ('Raw', 'Predict'):
                    raise ValueError('mode must be Raw or Predict')
                if options['nexposure'] < 1 or options['itrial'] < 1:
                    raise ValueError('nexposure and itrial must be at least 1')
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
