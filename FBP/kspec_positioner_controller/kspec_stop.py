import time
import asyncio
import pyads

from kspec_0_function import *

async def stop_all_positioner(
    plc_connections,
    dec: float = DEC,
    start_timeout: float = 2.0,
    timeout: float = 30.0,
):
    """
    PLC1 / PLC2에서 현재 구동 중인 포지셔너를 동시에 감속 정지한다.

    사용:
        1) main(), reverse_main(), reverse_from_stop_step(), zero_main() 중 모션 함수를 실행
        2) 이 Stop 함수를 별도 실행
        3) PLC1 / PLC2에 gStopALL = True 전송
        4) Stop 완료 확인
        5) Stop 기록(gStopped...)은 삭제하지 않고 유지
    """

    print("전체 포지셔너 정지 요청")

    opened_plcs = ["PLC1", "PLC2"]
    connection_failed_plcs = {}

    # Stop 완료 확인에 사용할 route.
    # 처음에는 각 PLC의 모든 담당 축을 넣고,
    # 실제 Stop 전에는 Busy였던 축만 남긴다.
    all_routes = {
        "PLC1": [],
        "PLC2": [],
    }

    moving_routes = {
        "PLC1": [],
        "PLC2": [],
    }

    try:
        # ==========================================
        # PLC별 담당 route 구성
        # ==========================================
        global_axis_routes = build_global_axis_routes()

        for route in global_axis_routes.values():
            all_routes[route["plc_name"]].append(route)

        for plc_name in all_routes:
            all_routes[plc_name].sort(
                key=lambda route: route["global_axis"]
            )

        # ==========================================
        # Stop 직전 상태 읽기
        # ==========================================
        before_snapshots = await asyncio.gather(
            *[
                read_one_plc_motion_snapshot(
                    plc_name,
                    plc_connections[plc_name],
                    all_routes[plc_name],
                )
                for plc_name in opened_plcs
            ]
        )

        moving_axes = []
        positions_before_stop = {}

        for snapshot in before_snapshots:
            plc_name = snapshot["plc_name"]

            busy_global_axes = {
                axis_state["global_axis"]
                for axis_state in snapshot["axis_states"]
                if axis_state["busy"]
            }

            moving_routes[plc_name] = [
                route
                for route in all_routes[plc_name]
                if route["global_axis"] in busy_global_axes
            ]

            for axis_state in snapshot["axis_states"]:
                global_axis = axis_state["global_axis"]

                positions_before_stop[str(global_axis)] = {
                    "plc_name": plc_name,
                    "local_axis": axis_state["local_axis"],
                    "positioner": axis_state["positioner"],
                    "motor": axis_state["motor"],
                    "actual_position": axis_state["actual_position"],
                    "busy": axis_state["busy"],
                    "error": axis_state["error"],
                }

                if axis_state["busy"]:
                    moving_axes.append(global_axis)

        moving_axes = sorted(moving_axes)

        # 현재 이미 Stop 처리 중인지도 확인
        already_stopping = any(
            snapshot["stop_busy"]
            for snapshot in before_snapshots
        )

        if not moving_axes and not already_stopping:
            if connection_failed_plcs:
                result = {
                    "status": "error",
                    "message": (
                        "연결된 PLC에서는 구동 중인 축이 없지만, "
                        "연결 실패한 PLC의 상태를 확인하거나 정지시킬 수 없습니다."
                    ),
                    "data": {
                        "moving_axes": [],
                        "positions": positions_before_stop,
                        "connection_failed_plcs": connection_failed_plcs,
                    },
                }
            else:
                result = {
                    "status": "idle",
                    "message": "현재 구동 중인 포지셔너가 없습니다.",
                    "data": {
                        "moving_axes": [],
                        "positions": positions_before_stop,
                        "connection_failed_plcs": {},
                    },
                }
            print(result["message"])
            save_result_json(result)
            return result

        print(f"정지 대상 전역축: {moving_axes}")

        # ==========================================
        # PLC1 / PLC2에 Stop 동시 전송
        # ==========================================
        def request_stop_one_plc(plc_name: str):
            plc = plc_connections[plc_name]

            plc.write_by_name(
                "GVL.gStopDec",
                float(dec),
                pyads.PLCTYPE_LREAL,
            )

            plc.write_by_name(
                "GVL.gStopAll",
                True,
                pyads.PLCTYPE_BOOL,
            )

            return plc_name

        stop_results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    request_stop_one_plc,
                    plc_name,
                )
                for plc_name in opened_plcs
            ],
            return_exceptions=True,
        )

        stop_failed_plcs = {}

        for plc_name, stop_result in zip(
            opened_plcs,
            stop_results,
        ):
            if isinstance(stop_result, Exception):
                stop_failed_plcs[plc_name] = str(stop_result)

        successful_stop_plcs = [
            plc_name
            for plc_name in opened_plcs
            if plc_name not in stop_failed_plcs
        ]

        if stop_failed_plcs:
            print(
                "Stop 명령 전송 실패 PLC: "
                f"{stop_failed_plcs}"
            )

        if not successful_stop_plcs:
            result = {
                "status": "error",
                "message": "연결된 PLC 모두에 Stop 명령 전송이 실패했습니다.",
                "data": {
                    "connection_failed_plcs": connection_failed_plcs,
                    "stop_failed_plcs": stop_failed_plcs,
                    "moving_axes": moving_axes,
                },
            }
            print(result["message"])
            save_result_json(result)
            return result

        # ==========================================
        # PLC가 Stop 요청을 접수했는지 확인
        # ==========================================
        accepted_plcs = []
        not_accepted_plcs = []

        async def wait_one_plc_stop_accepted(plc_name: str):
            start_time = time.time()

            while time.time() - start_time <= start_timeout:
                stop_busy = await asyncio.to_thread(
                    plc_connections[plc_name].read_by_name,
                    "GVL.gStopBusy",
                    pyads.PLCTYPE_BOOL,
                )

                stop_occurred = await asyncio.to_thread(
                    plc_connections[plc_name].read_by_name,
                    "GVL.gStopOccurred",
                    pyads.PLCTYPE_BOOL,
                )

                if stop_busy or stop_occurred:
                    return True

                await asyncio.sleep(0.02)

            return False

        accepted_results = await asyncio.gather(
            *[
                wait_one_plc_stop_accepted(plc_name)
                for plc_name in successful_stop_plcs
            ]
        )

        for plc_name, accepted in zip(
            successful_stop_plcs,
            accepted_results,
        ):
            if accepted:
                accepted_plcs.append(plc_name)
            else:
                not_accepted_plcs.append(plc_name)

        if not_accepted_plcs:
            print(
                "Stop 요청 접수 확인 실패 PLC: "
                f"{not_accepted_plcs}"
            )

        # ==========================================
        # Stop을 접수한 PLC들의 실제 정지 완료 확인
        # ==========================================
        stopped_snapshots = []

        if accepted_plcs:
            stopped_snapshots = await wait_all_motion_axes_stopped(
                plc_connections,
                moving_routes,
                accepted_plcs,
                timeout=timeout,
            )

        # ==========================================
        # Stop 기록 및 최종 위치 읽기
        # ==========================================
        stop_records = {}

        for plc_name in accepted_plcs:
            plc = plc_connections[plc_name]

            stopped_valid = await asyncio.to_thread(
                plc.read_by_name,
                "GVL.gStoppedValid",
                pyads.PLCTYPE_BOOL,
            )
            last_completed_step = await asyncio.to_thread(
                plc.read_by_name,
                "GVL.gStoppedLastCompletedStep",
                pyads.PLCTYPE_INT,
            )
            target_step = await asyncio.to_thread(
                plc.read_by_name,
                "GVL.gStoppedTargetStep",
                pyads.PLCTYPE_INT,
            )
            total_points = await asyncio.to_thread(
                plc.read_by_name,
                "GVL.gStoppedTotalPoints",
                pyads.PLCTYPE_INT,
            )
            stopped_state = await asyncio.to_thread(
                plc.read_by_name,
                "GVL.gStoppedState",
                pyads.PLCTYPE_INT,
            )
            motion_mode = await asyncio.to_thread(
                plc.read_by_name,
                "GVL.gStoppedMotionMode",
                pyads.PLCTYPE_INT,
            )
            motion_sequence = await asyncio.to_thread(
                plc.read_by_name,
                "GVL.gStoppedMotionSequence",
                pyads.PLCTYPE_UDINT,
            )

            stop_records[plc_name] = {
                "stopped_valid": bool(stopped_valid),
                "last_completed_step": int(last_completed_step),
                "target_step": int(target_step),
                "total_points": int(total_points),
                "stopped_state": int(stopped_state),
                "motion_mode": int(motion_mode),
                "motion_sequence": int(motion_sequence),
            }

        final_positions = {}

        for snapshot in stopped_snapshots:
            for axis_state in snapshot["axis_states"]:
                final_positions[str(axis_state["global_axis"])] = {
                    "plc_name": axis_state["plc_name"],
                    "local_axis": axis_state["local_axis"],
                    "positioner": axis_state["positioner"],
                    "motor": axis_state["motor"],
                    "actual_position": axis_state["actual_position"],
                    "busy": axis_state["busy"],
                    "error": axis_state["error"],
                }

        # ==========================================
        # 실제 Stop 직전에 움직이던 PLC의
        # Stop 복귀 기록(gStoppedValid) 정상 저장 여부 확인
        # ==========================================
        moving_plcs = [
            plc_name
            for plc_name in opened_plcs
            if moving_routes[plc_name]
        ]

        invalid_stop_record_plcs = [
            plc_name
            for plc_name in moving_plcs
            if (
                plc_name not in stop_records
                or not stop_records[plc_name]["stopped_valid"]
            )
        ]


        moving_stop_failed_plcs = [
            plc_name
            for plc_name in moving_plcs
            if plc_name in stop_failed_plcs
        ]

        moving_not_accepted_plcs = [
            plc_name
            for plc_name in moving_plcs
            if plc_name not in accepted_plcs
        ]        

        fully_stopped = (
            not connection_failed_plcs
            and not moving_stop_failed_plcs
            and not moving_not_accepted_plcs
            and not invalid_stop_record_plcs
        )

        if fully_stopped:
            status = "stopped"
            message = (
                "PLC1과 PLC2의 구동 중인 모든 포지셔너가 "
                "감속 정지했고 Stop 복귀 기록도 정상 저장되었습니다."
            )
        else:
            status = "error"


            if (
                connection_failed_plcs
                or stop_failed_plcs
                or not_accepted_plcs
            ):
                message = (
                    "Stop은 가능한  PLC에 전송했지만 일부 PLC의 "
                    "연결 또는 Stop 완료를 정상 확인하지 못했습니다."
                )

            elif invalid_stop_record_plcs:
                message = (
                    "포지셔너의 물리적인 Stop은 완료되었지만 "
                    "일부 구동 PLC의 Stop 복귀 기록이 정상 저장되지 않았습니다. "
                )

            else:
                message = (
                    "전체 Stop 결과를 정상적으로 확인하지 못했습니다. "
                )


        result = {
            "status": status,
            "message": message,
            "data": {
                "stop_deceleration": dec,
                "moving_axes": moving_axes,
                "moving_plcs": moving_plcs,
                "positions_before_stop": positions_before_stop,
                "stop_records": stop_records,
                "invalid_stop_record_plcs": invalid_stop_record_plcs,
                "moving_stop_failed_plcs": moving_stop_failed_plcs,
                "moving_not_accepted_plcs": moving_not_accepted_plcs,
                "final_positions": final_positions,
                "opened_plcs": opened_plcs,
                "connection_failed_plcs": connection_failed_plcs,
                "stop_failed_plcs": stop_failed_plcs,
                "not_accepted_plcs": not_accepted_plcs,
            },
        }
        print(result["message"])
        save_result_json(result)
        return result

    except StopAxisError as e:
        result = {
            "status": "error",
            "message": str(e),
            "data": {
                "reason": "stop_axis_error",
            },
        }
        print(result["message"])
        save_result_json(result)
        return result

    except TimeoutError as e:
        result = {
            "status": "fail",
            "message": str(e),
            "data": {
                "reason": "stop_timeout",
            },
        }
        print(result["message"])
        save_result_json(result)
        return result

    except pyads.ADSError as e:
        result = {
            "status": "error",
            "message": (
                "PLC 통신 또는 ADS 에러가 발생했습니다: "
                f"{e}"
            ),
            "data": {},
        }

        print(result["message"])
        save_result_json(result)
        return result

    except Exception as e:
        result = {
            "status": "error",
            "message": (
                "전체 Stop 중 예상하지 못한 에러가 발생했습니다: "
                f"{e}"
            ),
            "data": {},
        }
        print(result["message"])
        save_result_json(result)
        return result


