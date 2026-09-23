from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

import pyads


CONTROLLER_DIR = Path(__file__).resolve().parent

if str(CONTROLLER_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_DIR))

import kspec_0_function as _core  # noqa: E402
import kspec_main as _kspec_main  # noqa: E402
import kspec_reverse as _kspec_reverse  # noqa: E402
import kspec_reverse_from_stop_step as _kspec_reverse_from_stop_step  # noqa: E402
import kspec_stop as _kspec_stop  # noqa: E402
import kspec_zero_position as _kspec_zero_position  # noqa: E402


def _sync_controller_globals() -> None:
    """
    코어의 파일 경로와 JSON 축 매핑을 구동 모듈에 동기화한다.

    kspec_0_function.py가 controller 아래 data/Log 경로를 설정하고
    프로젝트 공용 Lib/positioner_axis_map.json을 로드한다. 래퍼는 이 설정을 그대로 사용한다.
    구동 모듈들은 from kspec_0_function import *를 사용하므로 코어에서
    설정이 교체된 경우에도 같은 경로와 매핑을 참조하도록 갱신한다.
    """
    for module in (
        _kspec_main,
        _kspec_reverse,
        _kspec_reverse_from_stop_step,
        _kspec_stop,
        _kspec_zero_position,
    ):
        for name in (
            "FBP_DIR",
            "DATA_DIR",
            "LOG_DIR",
            "LIB_DIR",
            "POSITIONER_AXIS_MAP_FILE",
            "POSITIONER_AXIS_MAP",
        ):
            setattr(module, name, getattr(_core, name))


_sync_controller_globals()


def _error_result(message: str, **data: Any) -> dict[str, Any]:
    """
    예외 상황을 command.py가 처리할 수 있는 result dictionary로 변환한다.

    Returns:
        {
            "status": "error",
            "message": str,
            "data": dict,
        }
    """
    return {
        "status": "error",
        "message": message,
        "data": data,
    }


async def _close_plcs(plc_connections: dict[str, Any]) -> dict[str, str]:
    """
    열려 있는 PLC 연결들을 닫고, 닫기 실패 정보를 반환한다.

    Args:
        plc_connections: {"PLC1": plc, "PLC2": plc} 형태의 PLC 연결 dictionary.

    Returns:
        닫기에 실패한 PLC 정보. 실패가 없으면 빈 dictionary를 반환한다.
        예: {"PLC1": "error message"}
    """
    close_results = await asyncio.gather(
        *[
            asyncio.to_thread(plc.close)
            for plc in plc_connections.values()
        ],
        return_exceptions=True,
    )

    failed_close_plcs = {}
    for plc_name, close_result in zip(plc_connections.keys(), close_results):
        if isinstance(close_result, Exception):
            failed_close_plcs[plc_name] = str(close_result)

    return failed_close_plcs


async def _open_command_plcs() -> dict[str, Any]:
    """
    command 실행에 사용할 PLC1/PLC2 연결을 연다.

    PLC1과 PLC2를 동시에 open한다. 한쪽 PLC 연결이 실패하면 이미 열린
    다른 PLC 연결을 닫고 RuntimeError를 발생시킨다.

    Returns:
        {
            "PLC1": plc_connection,
            "PLC2": plc_connection,
        }
    """
    plc_connections = {
        "PLC1": _core.create_plc_connection("PLC1"),
        "PLC2": _core.create_plc_connection("PLC2"),
    }

    open_results = await asyncio.gather(
        _core.open_one_plc("PLC1", plc_connections["PLC1"]),
        _core.open_one_plc("PLC2", plc_connections["PLC2"]),
        return_exceptions=True,
    )

    failed_open_plcs = {}
    opened_plcs = {}

    for plc_name, open_result in zip(plc_connections.keys(), open_results):
        if isinstance(open_result, Exception):
            failed_open_plcs[plc_name] = str(open_result)
        else:
            opened_plcs[plc_name] = plc_connections[plc_name]

    if failed_open_plcs:
        if opened_plcs:
            await _close_plcs(opened_plcs)
        raise RuntimeError(f"PLC 연결 실패: {failed_open_plcs}")

    print("PLC1, PLC2 연결 완료")
    return plc_connections


async def _run_with_plcs(
    action: Callable[..., Awaitable[dict[str, Any]]],
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    PLC 연결이 필요한 FBP 동작을 실행하는 공통 wrapper 함수.

    command.py에서 호출되는 대부분의 public 함수는 이 함수를 통해 실행된다.
    이 함수는 코어의 파일 경로와 축 매핑을 동기화하고, PLC1/PLC2 연결을 연 뒤,
    실제 구동 함수(action)를 실행하고, 마지막에 PLC 연결을 닫는다.

    Args:
        action: plc_connections를 첫 번째 인자로 받는 실제 구동 coroutine.
        *args: action에 전달할 위치 인자.
        **kwargs: action에 전달할 키워드 인자.

    Returns:
        실행 결과 dictionary를 반환한다.

        기본 구조:
            {
                "status": "success" | "fail" | "error" | "stopped" | "idle",
                "message": str,
                "data": dict,
            }

    Notes:
        action 실행 중 예외가 발생하면 서버가 죽지 않도록 "error" 상태의
        result dictionary로 변환한다. PLC 연결 종료 실패도 data 안에
        failed_close_plcs로 추가한다.
    """
    plc_connections = None
    result: dict[str, Any] | None = None

    try:
        _sync_controller_globals()
        plc_connections = await _open_command_plcs()
        result = await action(plc_connections, *args, **kwargs)

        if not isinstance(result, dict):
            result = _error_result(
                f"{action.__name__} returned a non-dictionary result.",
                returned_type=type(result).__name__,
            )

    except Exception as exc:
        result = _error_result(
            f"{action.__name__} 실행 중 예상하지 못한 에러가 발생했습니다: {exc}",
            reason=action.__name__,
        )

    finally:
        if plc_connections:
            failed_close_plcs = await _close_plcs(plc_connections)
            if failed_close_plcs:
                result = result or _error_result("PLC 연결 종료에 실패했습니다.")
                result.setdefault("data", {})
                result["data"]["failed_close_plcs"] = failed_close_plcs
                if result.get("status") == "success":
                    result["status"] = "error"
                    result["message"] = (
                        f"{result.get('message', '')} "
                        "단, 일부 PLC 연결 종료에 실패했습니다."
                    ).strip()

    return result or _error_result(f"{action.__name__} 실행 결과가 없습니다.")


async def rotate_all(alpha_file: str, beta_file: str) -> dict[str, Any]:
    """
    Lock되지 않은 모든 포지셔너 축을 target position까지 정방향으로 이동한다.

    command.py에서 fbpmoveall 명령을 처리하기 위한 wrapper 함수이다.
    실제 구동은 kspec_main.main()에서 수행하며, PLC 연결은
    _run_with_plcs()에서 열고 닫는다.

    Returns:
        실행 결과 dictionary를 반환한다.

        성공 시 data 주요 항목:
            {
                "direction": "forward",
                "total_steps": int,
                "active_plcs": list[str],
                "motion_axes": list[int],
                "locked_axes": list[int],
                "completed_steps": dict,
                "allowed_steps": dict,
                "final_positions": dict,
            }

    Notes:
        result_*.json 파일은 코어의 LOG_DIR(controller/Log)에 저장된다.
    """
    return await _run_with_plcs(_kspec_main.main, alpha_file=alpha_file, beta_file=beta_file)


async def reverse_all(alpha_file: str, beta_file: str) -> dict[str, Any]:
    """
    전체 포지셔너를 target position에서 initial position 쪽으로 역방향 이동한다.

    command.py에서 fbpinitial 명령을 처리하기 위한 wrapper 함수이다.
    실제 구동은 kspec_reverse.reverse_main()에서 수행하며, PLC 연결은
    _run_with_plcs()에서 열고 닫는다.

    Returns:
        실행 결과 dictionary를 반환한다.

        성공 시 data 주요 항목:
            {
                "direction": "reverse",
                "total_steps": int,
                "active_plcs": list[str],
                "motion_axes": list[int],
                "locked_axes": list[int],
                "completed_steps": dict,
                "allowed_steps": dict,
                "final_positions": dict,
            }

    Notes:
        result_*.json 파일은 코어의 LOG_DIR(controller/Log)에 저장된다.
    """
    return await _run_with_plcs(_kspec_reverse.reverse_main, alpha_file=alpha_file, beta_file=beta_file)


async def reverse_from_stop_step(
    position_tolerance: float = 0.2,
    step_timeout: float = 300.0,
    *,
    alpha_file: str,
    beta_file: str,
) -> dict[str, Any]:
    """
    Stop으로 중단된 구동을 Stop 기록 기준으로 initial 방향으로 복귀시킨다.

    command.py에서 fbpinitial_from_stop 명령을 처리하기 위한 wrapper 함수이다.
    실제 복귀 로직은 kspec_reverse_from_stop_step.reverse_from_stop_step()에서
    수행한다.

    Args:
        position_tolerance: 복귀 시작 위치 확인에 사용할 허용오차. 단위는 degree.
        step_timeout: 각 step 완료를 기다리는 최대 시간. 단위는 second.

    Returns:
        실행 결과 dictionary를 반환한다.

        기본 구조:
            {
                "status": "success" | "fail" | "error" | "stopped",
                "message": str,
                "data": dict,
            }

    Notes:
        PLC에 저장된 Stop 기록이 없거나, Stop 기록의 motion mode가 복귀 가능한
        mode가 아니면 실패 result를 반환한다.
    """
    return await _run_with_plcs(
        _kspec_reverse_from_stop_step.reverse_from_stop_step,
        alpha_file=alpha_file,
        beta_file=beta_file,
        position_tolerance=position_tolerance,
        step_timeout=step_timeout,
    )


# async def zero_main(
#     start_tolerance: float = 0.1,
#     zero_tolerance: float = 0.1,
#     timeout: float = 60.0,
# ) -> dict[str, Any]:
#     """
#     포지셔너 축들을 0도 위치로 이동한다.

#     command.py에서 fbpzero 명령을 처리하기 위한 wrapper 함수이다.
#     실제 0도 이동 로직은 kspec_zero_position.zero_main()에서 수행한다.

#     Args:
#         start_tolerance: 0도 이동 시작 위치 확인에 사용할 허용오차. 단위는 degree.
#         zero_tolerance: 최종 0도 도착 확인에 사용할 허용오차. 단위는 degree.
#         timeout: 0도 이동 완료를 기다리는 최대 시간. 단위는 second.

#     Returns:
#         실행 결과 dictionary를 반환한다.

#         성공 시 data 주요 항목:
#             {
#                 "direction": "zero",
#                 "motion_axes": list[int],
#                 "locked_axes": list[int],
#                 "start_positions": dict,
#                 "final_positions": dict,
#                 "zero_total_steps": int,
#                 "json_total_steps": int,
#             }
#     """
#     return await _run_with_plcs(
#         _kspec_zero_position.zero_main,
#         start_tolerance=start_tolerance,
#         zero_tolerance=zero_tolerance,
#         timeout=timeout,
#     )


async def stop_all_positioner(
    dec: float = _core.DEC,
    start_timeout: float = 2.0,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    현재 구동 중인 포지셔너 축들을 감속 정지한다.

    command.py에서 fbpstop 명령을 처리하기 위한 wrapper 함수이다.
    실제 Stop 명령 전송과 Stop 기록 확인은 kspec_stop.stop_all_positioner()에서
    수행한다.

    Args:
        dec: Stop에 사용할 감속도.
        start_timeout: PLC가 Stop 요청을 접수했는지 확인하는 최대 시간.
        timeout: Stop 완료를 기다리는 최대 시간.

    Returns:
        실행 결과 dictionary를 반환한다.

        정상 정지 시 status는 일반적으로 "stopped"이다.
        data에는 moving_axes, stop_records, final_positions 등의 정보가 들어간다.
    """
    return await _run_with_plcs(
        _kspec_stop.stop_all_positioner,
        dec=dec,
        start_timeout=start_timeout,
        timeout=timeout,
    )


async def rotate_one(
    positioner: str,
    motor: str,
    angle: float,
    velocity: float = _core.VELOCITY,
    acc: float = _core.ACC,
    dec: float = _core.DEC,
    start_timeout: float = 2.0,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    지정한 포지셔너의 alpha 또는 beta 모터 하나를 절대각도로 이동한다.

    command.py에서 fbpmoveone 명령을 처리하기 위한 wrapper 함수이다.
    실제 단일 축 구동은 kspec_0_function.rotate_one()에서 수행한다.
    PLC 연결은 _run_with_plcs()에서 열고 닫는다.

    Args:
        positioner: positioner_axis_map.json에 등록된 포지셔너 이름. 예: "A1".
        motor: 모터 이름. "alpha" 또는 "beta".
        angle: 이동할 목표 절대각도. 단위는 degree.
        velocity: 모터 구동 속도.
        acc: 모터 가속도.
        dec: 모터 감속도.
        start_timeout: PLC가 모션 시작을 확인할 때까지 기다리는 최대 시간.
        timeout: 모터 이동 완료를 기다리는 최대 시간.

    Returns:
        실행 결과 dictionary를 반환한다.

        성공 시 data 예:
            {
                "positioner": str,
                "motor": str,
                "plc_name": str,
                "global_axis": int,
                "local_axis": int,
                "current_position_before_move": float,
                "target_angle": float,
                "actual_position": float,
                "locked": bool,
            }

    Notes:
        이 함수 자체는 result JSON 파일을 저장하지 않는다.
        반환된 결과는 command.py에서 ICS/GUI로 전송된다.
    """
    return await _run_with_plcs(
        _core.rotate_one,
        positioner=positioner,
        motor=motor,
        angle=angle,
        velocity=velocity,
        acc=acc,
        dec=dec,
        start_timeout=start_timeout,
        timeout=timeout,
    )


async def positioner_lock(positioners: list[str] | str) -> dict[str, Any]:
    """
    입력한 포지셔너들을 Lock 상태로 설정하고 나머지는 Unlock한다.

    command.py에서 fbplock 명령을 처리하기 위한 wrapper 함수이다.
    실제 Lock 변경과 검증은 kspec_0_function.positioner_lock()에서 수행한다.

    Args:
        positioners: Lock할 포지셔너 목록. 예: ["A1", "A3"].
            빈 list 또는 빈 문자열이면 전체 Unlock으로 처리된다.

    Returns:
        실행 결과 dictionary를 반환한다.

        성공 시 data 주요 항목:
            {
                "locked_positioners": list[str],
                "locked_axes": list[int],
                "unlocked_positioners": list[str],
                "unlocked_axes": list[int],
            }
    """
    return await _run_with_plcs(_core.positioner_lock, positioners)


async def show_status(axis: str) -> dict[str, Any]:
    """
    포지셔너 하나의 alpha/beta 현재 상태를 읽는다.

    command.py에서 fbpstatus 명령을 처리하기 위한 wrapper 함수이다.
    실제 상태 읽기는 kspec_0_function.show_status()에서 수행한다.

    Args:
        axis: 상태를 확인할 포지셔너 이름. 예: "A1".

    Returns:
        실행 결과 dictionary를 반환한다.

        성공 시 data에는 alpha와 beta의 현재 각도, Busy, Error, Locked 상태가
        들어간다.
    """
    return await _run_with_plcs(_core.show_status, axis)


async def show_status_all() -> dict[str, Any]:
    """
    positioner_axis_map.json에 등록된 모든 포지셔너의 현재 상태를 읽는다.

    실제 상태 읽기는 kspec_0_function.show_status_all()에서 수행한다.

    Returns:
        실행 결과 dictionary를 반환한다.

    Notes:
        kspec_0_function.show_status_all() 내부에서 result_*.json 파일이
        코어의 LOG_DIR(controller/Log)에 저장된다.
    """
    return await _run_with_plcs(_core.show_status_all)


async def _check_all_zero_positions(
    plc_connections: dict[str, Any],
    zero_tolerance: float = 0.1,
    include_locked_axes: bool = False,
) -> dict[str, Any]:
    """
    PLC 연결을 이용해 검사 대상 축들이 모두 0도 위치에 있는지 확인한다.

    Args:
        plc_connections: {"PLC1": plc, "PLC2": plc} 형태의 열린 PLC 연결.
        zero_tolerance: 0도 판정에 사용할 허용오차. 단위는 degree.
        include_locked_axes: True이면 Lock된 축도 검사하고,
            False이면 Lock된 축은 검사 대상에서 제외한다.

    Returns:
        0도 검사 결과 dictionary를 반환한다.

        data 주요 항목:
            {
                "zero_tolerance": float,
                "include_locked_axes": bool,
                "locked_axes": list[int],
                "unlocked_axes": list[int],
                "invalid_axes": list[dict],
                "final_positions": dict,
            }
    """
    lock_results = await asyncio.gather(
        _core.read_one_plc_lock_state("PLC1", plc_connections["PLC1"]),
        _core.read_one_plc_lock_state("PLC2", plc_connections["PLC2"]),
    )

    locked_axes: list[int] = []
    unlocked_axes: list[int] = []

    for lock_result in lock_results:
        locked_axes.extend(lock_result["locked_axes"])
        unlocked_axes.extend(lock_result["motion_axes"])

    locked_axes = sorted(locked_axes)
    unlocked_axes = sorted(unlocked_axes)
    locked_axis_set = set(locked_axes)

    final_positions = {}
    zero_check_errors = []

    for global_axis, route in sorted(_core.build_global_axis_routes().items()):
        if not include_locked_axes and global_axis in locked_axis_set:
            continue

        plc = plc_connections[route["plc_name"]]
        local_axis = route["local_axis"]

        actual_position, busy, error = await asyncio.gather(
            asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisState[{local_axis}].ActPos",
                pyads.PLCTYPE_LREAL,
            ),
            asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisState[{local_axis}].Busy",
                pyads.PLCTYPE_BOOL,
            ),
            asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisState[{local_axis}].Error",
                pyads.PLCTYPE_BOOL,
            ),
        )

        actual_position = float(actual_position)
        position_error = abs(actual_position)
        is_locked = global_axis in locked_axis_set

        final_positions[str(global_axis)] = {
            "plc_name": route["plc_name"],
            "local_axis": local_axis,
            "global_axis": global_axis,
            "axis": global_axis,
            "positioner": route["positioner"],
            "motor": route["motor"],
            "target_position": 0.0,
            "actual_position": actual_position,
            "position_error": position_error,
            "busy": bool(busy),
            "error": bool(error),
            "locked": is_locked,
        }

        if not math.isfinite(actual_position) or position_error > zero_tolerance or busy or error:
            zero_check_errors.append({
                "plc_name": route["plc_name"],
                "local_axis": local_axis,
                "global_axis": global_axis,
                "axis": global_axis,
                "positioner": route["positioner"],
                "motor": route["motor"],
                "target_position": 0.0,
                "actual_position": actual_position,
                "position_error": position_error,
                "locked": is_locked,
            })

    status = "fail" if zero_check_errors else "success"
    message = (
        "일부 축이 0도 허용오차를 벗어났거나 이동 중 또는 오류 상태입니다."
        if zero_check_errors
        else "검사 대상 모든 축이 0도 위치에 있습니다."
    )

    return {
        "status": status,
        "message": message,
        "data": {
            "zero_tolerance": zero_tolerance,
            "include_locked_axes": include_locked_axes,
            "locked_axes": locked_axes,
            "unlocked_axes": unlocked_axes,
            "invalid_axes": zero_check_errors,
            "final_positions": final_positions,
        },
    }


async def check_all_zero_positions(
    zero_tolerance: float = 0.1,
    include_locked_axes: bool = False,
) -> dict[str, Any]:
    """
    현재 모든 검사 대상 축이 0도 위치에 있는지 확인한다.

    command.py에서 fbpmoveone 이후 fbp_state를 "manual" 또는 "initial"로
    결정할 때 사용하는 wrapper 함수이다. PLC 연결은 _run_with_plcs()에서
    열고 닫는다.

    Args:
        zero_tolerance: 0도 판정에 사용할 허용오차. 단위는 degree.
        include_locked_axes: True이면 Lock된 축도 검사하고,
            False이면 Lock된 축은 검사 대상에서 제외한다.

    Returns:
        검사 결과 dictionary를 반환한다.
        모든 검사 대상 축이 오류 없이 정지해 있고 0도이면 status는 "success"이다.
        비정상 위치 값, 허용오차 초과, 이동 중 또는 축 오류이면 "fail"이다.
    """
    return await _run_with_plcs(
        _check_all_zero_positions,
        zero_tolerance=zero_tolerance,
        include_locked_axes=include_locked_axes,
    )


__all__ = [
    "check_all_zero_positions",
    "positioner_lock",
    "reverse_all",
    "reverse_from_stop_step",
    "rotate_all",
    "rotate_one",
    "show_status",
    "show_status_all",
    "stop_all_positioner",
    "zero_main",
]
