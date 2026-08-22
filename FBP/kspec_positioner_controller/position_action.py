from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

import pyads


TEMP_DIR = Path(__file__).resolve().parent
FBP_DIR = TEMP_DIR.parent

if str(TEMP_DIR) not in sys.path:
    sys.path.insert(0, str(TEMP_DIR))

import kspec_0_function as _core  # noqa: E402


def _resolve_motion_file(filename: str) -> str:
    path = Path(filename)
    if path.is_absolute():
        return str(path)

    for base_dir in (Path.cwd(), TEMP_DIR, FBP_DIR / "data"):
        candidate = base_dir / path
        if candidate.exists():
            return str(candidate)

    return str(TEMP_DIR / path)


_core.ALPHA_FILE = _resolve_motion_file(_core.ALPHA_FILE)
_core.BETA_FILE = _resolve_motion_file(_core.BETA_FILE)

import kspec_main as _kspec_main  # noqa: E402
import kspec_reverse as _kspec_reverse  # noqa: E402
import kspec_reverse_from_stop_step as _kspec_reverse_from_stop_step  # noqa: E402
import kspec_stop as _kspec_stop  # noqa: E402
import kspec_zero_position as _kspec_zero_position  # noqa: E402


def _sync_motion_file_globals() -> None:
    for module in (
        _kspec_main,
        _kspec_reverse,
        _kspec_reverse_from_stop_step,
        _kspec_zero_position,
    ):
        module.ALPHA_FILE = _core.ALPHA_FILE
        module.BETA_FILE = _core.BETA_FILE


_sync_motion_file_globals()


def _error_result(message: str, **data: Any) -> dict[str, Any]:
    return {
        "status": "error",
        "message": message,
        "data": data,
    }


async def _close_plcs(plc_connections: dict[str, Any]) -> dict[str, str]:
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
    plc_connections = None
    result: dict[str, Any] | None = None

    try:
        _sync_motion_file_globals()
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


async def rotate_all() -> dict[str, Any]:
    return await _run_with_plcs(_kspec_main.main)


async def reverse_all() -> dict[str, Any]:
    return await _run_with_plcs(_kspec_reverse.reverse_main)


async def reverse_from_stop_step(
    position_tolerance: float = 0.2,
    step_timeout: float = 300.0,
) -> dict[str, Any]:
    return await _run_with_plcs(
        _kspec_reverse_from_stop_step.reverse_from_stop_step,
        position_tolerance=position_tolerance,
        step_timeout=step_timeout,
    )


async def zero_main(
    start_tolerance: float = 0.1,
    zero_tolerance: float = 0.1,
    timeout: float = 60.0,
) -> dict[str, Any]:
    return await _run_with_plcs(
        _kspec_zero_position.zero_main,
        start_tolerance=start_tolerance,
        zero_tolerance=zero_tolerance,
        timeout=timeout,
    )


async def stop_all_positioner(
    dec: float = _core.DEC,
    start_timeout: float = 2.0,
    timeout: float = 30.0,
) -> dict[str, Any]:
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
    return await _run_with_plcs(_core.positioner_lock, positioners)


async def show_status(axis: str) -> dict[str, Any]:
    return await _run_with_plcs(_core.show_status, axis)


async def show_status_all() -> dict[str, Any]:
    return await _run_with_plcs(_core.show_status_all)


async def _check_all_zero_positions(
    plc_connections: dict[str, Any],
    zero_tolerance: float = 0.1,
    include_locked_axes: bool = False,
) -> dict[str, Any]:
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

        if position_error > zero_tolerance:
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
        "일부 축이 0도 허용오차를 벗어났습니다."
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
