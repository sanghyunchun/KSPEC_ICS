import json
import shlex

import Lib.mkmessage as mkmsg


def seconds_to_microseconds(exptime):
    """GUI/CLI의 초 단위 노출시간을 kspec_metrology용 마이크로초로 바꾼다."""
    return float(exptime) * 1_000_000.0


def create_mtl_command(func, **kwargs):
    """MTL 서버에 전달할 JSON 명령을 생성한다."""
    cmd_data = mkmsg.mtlmsg()
    cmd_data.update(func=func, **kwargs)
    return json.dumps(cmd_data)


def mtl_status():
    return create_mtl_command(
        "mtlstatus",
        message="Show metrology status",
    )


def mtl_start(
        target_file=None,
        tolerance=None,
        max_trial=None,
        nexposure=None,
        exptime=None,
        ):
    """MetrologyRun을 초기화하고 Trial 0 기준 JSON 생성을 요청한다."""
    data = {
        "message": "Initialize metrology run",
    }

    if target_file is not None:
        data["target_file"] = target_file
    if tolerance is not None:
        data["tolerance"] = tolerance
    if max_trial is not None:
        data["max_trial"] = max_trial
    if nexposure is not None:
        data["nexposure"] = nexposure
    if exptime is not None:
        data["time"] = seconds_to_microseconds(exptime)

    return create_mtl_command("mtlstart", **data)


def mtl_test(exptime=None, nexposure=None, filename=None):
    """MetrologyRun과 무관하게 metrology 카메라 시험 촬영을 요청한다."""
    data = {
        "message": "Test metrology camera",
    }

    if exptime is not None:
        data["time"] = seconds_to_microseconds(exptime)
    if nexposure is not None:
        data["nexposure"] = nexposure
    if filename is not None:
        data["file"] = filename

    return create_mtl_command("mtltest", **data)


def mtl_trial(filename=None):
    """초기화된 run으로 다음 trial의 촬영, 분석, JSON 저장을 요청한다."""
    data = {
        "message": "Expose and analyze metrology trial",
    }

    if filename is not None:
        # 서버는 tile/trial 기반 파일명을 사용하지만 기존 호출 형식을 허용한다.
        data["file"] = filename

    return create_mtl_command("mtltrial", **data)


def mtl_result():
    return create_mtl_command(
        "mtlresult",
        message="Get metrology run result",
    )


def mtl_reset():
    return create_mtl_command(
        "mtlreset",
        message="Reset metrology run",
    )


async def handle_mtl(arg, ICS_client):
    """MTL CLI 명령을 검사하고 JSON 메시지로 변환해 서버에 전달한다."""
    try:
        parts = shlex.split(arg)
    except ValueError as error:
        print(f"Error: Invalid MTL command: {error}")
        return

    if not parts:
        print("Error: Empty MTL command")
        return

    cmd, *params = parts

    try:
        if cmd == "mtlstatus":
            if params:
                raise ValueError("Usage: mtlstatus")
            message = mtl_status()

        elif cmd == "mtlstart":
            if len(params) > 5:
                raise ValueError(
                    "Usage: mtlstart "
                    "[target_file] [tolerance] [max_trial] [nexposure] [exptime]"
                )

            target_file = params[0] if len(params) >= 1 else None
            tolerance = float(params[1]) if len(params) >= 2 else None
            max_trial = int(params[2]) if len(params) >= 3 else None
            nexposure = int(params[3]) if len(params) >= 4 else None
            exptime = float(params[4]) if len(params) >= 5 else None


        #    print(f'dfdfdf {target_file} {exptime}')

            message = mtl_start(
                target_file=target_file,
                tolerance=tolerance,
                max_trial=max_trial,
                nexposure=nexposure,
                exptime=exptime,
            )

        elif cmd == "mtltest":
            if len(params) not in (0, 2, 3):
                raise ValueError(
                    "Usage: mtltest [exptime nexposure [filename]]"
                )

            if params:
                exptime = float(params[0])
                nexposure = int(params[1])
                filename = params[2] if len(params) == 3 else None
            else:
                exptime = None
                nexposure = None
                filename = None

            message = mtl_test(
                exptime=exptime,
                nexposure=nexposure,
                filename=filename,
            )

        elif cmd == "mtltrial":
            if len(params) > 1:
                raise ValueError("Usage: mtltrial [filename]")

            filename = params[0] if params else None
            message = mtl_trial(filename)

        elif cmd == "mtlresult":
            if params:
                raise ValueError("Usage: mtlresult")
            message = mtl_result()

        elif cmd == "mtlreset":
            if params:
                raise ValueError("Usage: mtlreset")
            message = mtl_reset()

        else:
            print(f"Error: '{cmd}' is not a valid MTL command")
            return

    except ValueError as error:
        print(f"Error: {error}")
        return

    await ICS_client.send_message("MTL", message)
