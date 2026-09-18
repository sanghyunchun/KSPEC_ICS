# stop 당시 lock상태와 현재 lock 상태가 동일해야함. 즉 lock 된 축 변경이 일어나면 안됨
# stop당시 각도와 현재 각도가 같은지에 대한 검사는 없음. stop 이후에 rotate_one등으로 각도가 달라졌더라도 복귀가능함. 이 부분은 주의 해야함


import time
import asyncio
import pyads

from kspec_0_function import *


async def reverse_from_stop_step( # pyright: ignore[reportGeneralTypeIssues]
    plc_connections,
    position_tolerance: float = 0.2,
    step_timeout: float = 300.0,
):

    print("reverse_from_stop_step() 시작")

    # ========================================================
    # 원본 JSON 읽기
    # ========================================================
    try:
        axis_points, total_steps = read_json( ALPHA_FILE, BETA_FILE )

    except FileNotFoundError as e:
        result = {
            "status": "fail",
            "message": f"JSON 파일을 찾을 수 없습니다: {e.filename}",
            "data": {
                "missing_file": e.filename,
                "direction": "stop_reverse"
            }
        }
        print(result["message"])
        save_result_json(result)
        return result

    except KeyError as e:
        result = {
            "status": "fail",
            "message": (
                "JSON 파일 내부 구조가 예상과 다릅니다. "
                f"Key: {e}"
            ),
            "data": {
                "missing_key": str(e),
                "direction": "stop_reverse"
            }
        }
        print(result["message"])
        save_result_json(result)
        return result

    except ValueError as e:
        result = {
            "status": "fail",
            "message": (
                "JSON 데이터 값 또는 길이에 문제가 있습니다: "
                f"{e}"
            ),
            "data": {
                "error": str(e),
                "direction": "stop_reverse"
            }
        }
        print(result["message"])
        save_result_json(result)
        return result



    opened_plcs = ["PLC1", "PLC2"]

    plc_motion_routes = {
        "PLC1": [],
        "PLC2": [],
    }

    recovery_started = False

    try:


        # ====================================================
        # PLC1 / PLC2 Stop 기록 동시 읽기
        # ====================================================
        stop_record_results = await asyncio.gather(
            *[
                read_stop_record_one_plc(
                    plc_name,
                    plc_connections[plc_name]
                )
                for plc_name in opened_plcs
            ]
        )

        stop_records = {
            record["plc_name"]: record
            for record in stop_record_results
        }

        #print(f"Stop 기록: {stop_records}")


        # ====================================================
        # 복귀 전 필수 Stop 기록 검사
        # ====================================================
        # 실제 Stop 기록이 있는 PLC만 복귀 대상으로 선택
        recovery_plcs = sorted(
            plc_name
            for plc_name, record in stop_records.items()
            if record["stopped_valid"]
        )

        if not recovery_plcs:
            raise ValueError(
                "사용 가능한 Stop 기록이 있는 PLC가 없습니다."
            )

        #print(f"Stop 복귀 참여 PLC: {recovery_plcs}")

        incomplete_stop_plcs = [
            plc_name
            for plc_name in recovery_plcs
            if (
                stop_records[plc_name]["stop_busy"]
                or not stop_records[plc_name]["stop_occurred"]
                or not stop_records[plc_name]["stop_done"]
            )
        ]

        if incomplete_stop_plcs:
            raise ValueError(
                "Stop 처리가 완전히 끝나지 않은 PLC가 있습니다: "
                f"{incomplete_stop_plcs}"
            )


        # ===============================================
        # ===============================================
        stopped_modes = {
            stop_records[plc_name]["stopped_mode"]
            for plc_name in recovery_plcs
        }

        if len(stopped_modes) != 1:
            raise ValueError(
                "PLC들의 Stop 당시 Motion Mode가 서로 다릅니다: "
                f"{sorted(stopped_modes)}"
            )

        source_stop_mode = next(iter(stopped_modes))

        if source_stop_mode not in (MOTION_MODE_FORWARD, MOTION_MODE_REVERSE, MOTION_MODE_STOP_REVERSE):
            raise ValueError(
                "main(), reverse_main(), reverse_from_stop_step() 중 발생한 Stop만 복귀할 수 있습니다. "
                f"stopped_mode={source_stop_mode}"
            )

        # ==================================
        # Stop 당시 모션에 따라 원본 JSON 기준 복귀 시작 step 결정
        # ==================================
        if source_stop_mode == MOTION_MODE_FORWARD:

           
            # main() 중 Stop
            # PLC step 번호 = 원본 JSON step 번호
            invalid_total_points_plcs = [
                {
                    "plc_name": plc_name,
                    "stopped_total_points":
                        stop_records[plc_name]["stopped_total_points"],
                    "current_json_total_steps":
                        total_steps,
                }
                for plc_name in recovery_plcs
                if (
                    stop_records[plc_name]["stopped_total_points"]
                    != total_steps
                )
            ]

            if invalid_total_points_plcs:
                raise ValueError(
                    "main() Stop 당시 경로 길이와 현재 JSON의 "
                    "경로 길이가 일치하지 않습니다: "
                    f"{invalid_total_points_plcs}"
                )
                           
            invalid_last_step_plcs = [
                {
                    "plc_name": plc_name,
                    "last_completed_step": stop_records[plc_name]["last_completed_step"],
                    "target_step": stop_records[plc_name]["target_step"],
                }
                for plc_name in recovery_plcs
                if not(
                    1 <= stop_records[plc_name]["last_completed_step"] <= total_steps 
                    or ( stop_records[plc_name]["last_completed_step"] == 0 and stop_records[plc_name]["target_step"] == 1 )
                )
            ]

            if invalid_last_step_plcs:
                raise ValueError(
                    "main() Stop의 step 정보가 올바르지 않습니다: "
                    f"{invalid_last_step_plcs}"
                )

            common_return_step = min(
                stop_records[plc_name]["last_completed_step"]
                for plc_name in recovery_plcs
            )

        elif source_stop_mode == MOTION_MODE_REVERSE:

            # reverse_main()중 Stop
            invalid_total_points_plcs = [
                {
                    "plc_name": plc_name,
                    "stopped_total_points":
                        stop_records[plc_name]["stopped_total_points"],
                    "current_json_total_steps":
                        total_steps,
                }
                for plc_name in recovery_plcs
                if (
                    stop_records[plc_name]["stopped_total_points"]
                    != total_steps
                )
            ]

            if invalid_total_points_plcs:
                raise ValueError(
                    "reverse_main() Stop 당시 경로 길이와 현재 JSON의 "
                    "경로 길이가 일치하지 않습니다: "
                    f"{invalid_total_points_plcs}"
                )            
            invalid_reverse_stop_plcs = [
                {
                    "plc_name": plc_name,
                    "last_completed_step": stop_records[plc_name]["last_completed_step"],
                    "target_step": stop_records[plc_name]["target_step"]
                }

                for plc_name in recovery_plcs
                if not ( 0 <= stop_records[plc_name]["last_completed_step"] <= total_steps
                        and 1<= stop_records[plc_name]["target_step"] <= total_steps
                        )       
            ]

            if invalid_reverse_stop_plcs:
                raise ValueError(
                    "reverse_main() Stop의 step 정보가 올바르지 않습니다: "
                    f"{invalid_reverse_stop_plcs}"
                )

            common_reverse_target_step = max(stop_records[plc_name]["target_step"] for plc_name in recovery_plcs )

            common_return_step = (total_steps - common_reverse_target_step + 1)

        else:
            #==================================
            # reverse_from_stop_step() 중 다시 stop
            # stopped_mode = 3
            # ====================================

            stopped_total_points_values = {
                stop_records[plc_name]["stopped_total_points"]
                for plc_name in recovery_plcs
            }

            # 두 PLC가 같은 복귀 경로를 수행하다 Stop 된 것인지 확인
            if len(stopped_total_points_values) != 1:
                raise ValueError(
                    "PLC들의 이전 Stop 복귀 경로 길이가 서로 다릅니다." 
                    f"{sorted(stopped_total_points_values)}"
                )

            previous_recovery_total_steps = next(iter(stopped_total_points_values))

            if not ( 1 <= previous_recovery_total_steps <= total_steps ):
                raise ValueError(
                    "이전 Stop 복귀의 TotalPoints 정보가 올바르지 않습니다: "
                    f"{previous_recovery_total_steps}"
                )

            invalid_stop_reverse_plcs = [
                {
                    "plc_name": plc_name,
                    "last_completed_step": stop_records[plc_name]["last_completed_step"],
                    "target_step": stop_records[plc_name]["target_step"],
                    "stopped_total_points": stop_records[plc_name]["stopped_total_points"],
                }
                for plc_name in recovery_plcs
                if not ( 0 <= stop_records[plc_name]["last_completed_step"] <= previous_recovery_total_steps
                        and 1 <= stop_records[plc_name]["target_step"] <= previous_recovery_total_steps
                        )
            ]

            if invalid_stop_reverse_plcs:
                raise ValueError(
                    "reverse_from_stop_step() Stop의 Step 정보가 올바르지 않습니다: "
                    f"{invalid_stop_reverse_plcs}"
                )

            # 복귀 경로 내부에서 더 Step 1 방향으로 진행한 
            # target step을 공통 기준으로 사용
            common_stop_reverse_target_step = max(
                stop_records[plc_name]["target_step"]
                for plc_name in recovery_plcs
            )

            # 이전 복귀 경로와 내부 step 번호를 원본 JSON step 번호로 변환
            common_return_step = (
                previous_recovery_total_steps - common_stop_reverse_target_step + 1
            )

        display_return_step = (
            1
            if common_return_step == 0
            else common_return_step
        )

        print(
            "공통 복귀 기준 원본 step: "
            f"{display_return_step}"
        )


        lock_results = await asyncio.gather(
            *[
                read_one_plc_lock_state(
                    plc_name,
                    plc_connections[plc_name]
                )
                for plc_name in recovery_plcs
            ]
        )

        # Stop 당시 모션 참여축
        stopped_selected_axes = sorted({
            global_axis
            for plc_name in recovery_plcs
            for global_axis in stop_records[plc_name]["stopped_selected_axes"]
        })

        # Stop 당시 Lock 축
        stopped_locked_axes = sorted({
            global_axis
            for plc_name in recovery_plcs
            for global_axis
            in stop_records[plc_name]["stopped_locked_axes"]
        })

        # 현재 Lock 축
        current_locked_axes = sorted({
            global_axis
            for lock_result in lock_results
            for global_axis in lock_result["locked_axes"]
        })


        # 보기 좋은 축 이름 출력을 위한 route
        global_axis_routes = build_global_axis_routes()

        def axis_names(global_axes):
            return [
                (
                    f"{global_axis_routes[axis]['positioner']}-"
                    f"{'α'if global_axis_routes[axis]['motor'] == 'alpha' else 'β'}"
                )
                for axis in global_axes
            ]

        print(
            "Stop 당시 모션 참여 축: "
            f"{axis_names(stopped_selected_axes)}"
        )

        print(
            "Stop 당시 Lock 축: "
            f"{axis_names(stopped_locked_axes)}"
        )

        print(
            "현재 Lock 축: "
            f"{axis_names(current_locked_axes)}"
        )
        # ==============================
        # Stop 이후 Lock / Unlock 변경 검사
        # ==============================
        newly_locked_axes = sorted(set(current_locked_axes) - set(stopped_locked_axes))

        newly_unlocked_axes = sorted(set(stopped_locked_axes) - set(current_locked_axes))

        if newly_locked_axes or newly_unlocked_axes:
            print( "Stop 이후 Lock/Unlock 상태 변경이 감지되었습니다.")

            if newly_locked_axes:
                print(
                    "Stop 이후 새로 Lock된 축: "
                    f"{axis_names(newly_locked_axes)}"
                )

            if newly_unlocked_axes:
                print(
                    "Stop 이후 Unlock된 축: "
                    f" {axis_names(newly_unlocked_axes)}"
                )
            print(
                "Stop 당시와 포지셔너 Lock 구성이 달라졌습니다. "
                "reverse_from_stop_step의 경로 이동에 있어 충돌 위험이 있습니다."
            )

            print(
                "Lock 상태를 Stop 당시 상태로 복원한 후 "
                "reverse_from_stop_step()을 다시 실행 하십시오"
            )

            raise ValueError(
                "Stop 이후 Lock/Unlock 상태가 변경되어" \
                "충돌 방지를 위해 Stop 복귀를 실행하지 않겠습니다."
            )
        print("Stop 당시 현재 Lock 상태가 동일한 것을 확인했습니다.")

        # =========================
        # 복귀 대상은 반드시 Stop 당시 모션 참여 축만 사용
        # =========================

        motion_axes = stopped_selected_axes
        locked_axes = stopped_locked_axes

        if not motion_axes:
            raise ValueError(
                "Stop 당시 모션에 참여한 축이 없어 복귀할 수 없습니다."
            )

        # Stop 당시 참여 축이 현재 Lock 인지 최종 안전 확인
        recovery_locked_axes = sorted(set(motion_axes) & set(current_locked_axes))

        if recovery_locked_axes:

            print(
                "Stop 당시 모션 참여 축 중 현재 Lock된 축이 있습니다: "
                f"{axis_names(recovery_locked_axes)}"
            )

            print(
                "일부 축만 제외하고 복귀하면 충돌 회피용 Step 경로가 변경되므로 전체 복귀를 시작하지 않습니다.")

            raise ValueError(
                "Stop 당시 모션 참여 축이 현재 Lock 상태입니다. "
                "따라서 Stop 복귀를 실행 할 수 없습니다."
            )

        print(
            "Stop 당시 모션 참여 축만 복귀 대상으로 사용합니다: "
            f"{axis_names(motion_axes)}"
        )


        
        # ====================================================
        # 아직 움직이는 축이 있으면 복귀 시작 금지
        # ====================================================
        global_axis_routes = build_global_axis_routes()

        plc_motion_routes = {
            "PLC1": [],
            "PLC2": [],
        }

        for global_axis in motion_axes:
            if global_axis not in global_axis_routes:
                raise KeyError(
                    f"{global_axis}번 전역축의 매핑 정보가 없습니다."
                )

            route = global_axis_routes[global_axis]
            plc_motion_routes[route["plc_name"]].append(route)

        before_recovery_snapshots = await asyncio.gather(
            *[
                read_one_plc_motion_snapshot(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name]
                )
                for plc_name in recovery_plcs
            ]
        )

        busy_axes_before_recovery = [
            axis_state
            for snapshot in before_recovery_snapshots
            for axis_state in snapshot["axis_states"]
            if axis_state["busy"]
        ]

        if busy_axes_before_recovery:
            raise ValueError(
                "아직 움직이는 축이 있어 Stop 복귀를 시작할 수 없습니다: "
                f"{busy_axes_before_recovery}"
            )


        # ====================================================
        # 복귀 경로 생성
        #
        # common_return_step = 9 이면
        # 원본 JSON: 1,2,3,...,9
        # 복귀 path: 9,8,7,...,1
        #
        # PLC 내부 새 모션 step 번호는 다시
        # 1,2,3,...,9 로 증가한다.
        # ====================================================
        if common_return_step == 0:
            # 0 -> 1단계 이동 중  Stop 된 경우
            # 현재 Stop 위치 -> 원본 Step 1 위치
            recovery_axis_points = {
                global_axis: [
                    float(axis_points[global_axis][0])
                ]
                for global_axis in motion_axes
            }

            recovery_total_steps = 1

        else:
            recovery_axis_points = {
                global_axis: list(
                    reversed(
                        axis_points[global_axis][:common_return_step]
                    )
                )
                for global_axis in motion_axes
            }
            recovery_total_steps = common_return_step


        if common_return_step == 0:
            print(
                "복귀 경로 생성 완료: "
                "정지 위치 -> 원본 1단계"
            )
        else:
            print(
                "복귀 경로 생성 완료: "
                f"정지 위치 -> 원본 {common_return_step}단계 "
                "-> .... -> 원본 1단계"
            )
     


        # ====================================================
        # Stop 기록이 있는 PLC는 모두 실제 복귀 대상 축이 있어야 한다.
        # ====================================================
        prepared_plcs = [
            plc_name
            for plc_name in recovery_plcs
            if plc_motion_routes[plc_name]
        ]

        if sorted(prepared_plcs) != sorted(recovery_plcs):
            raise ValueError(
                "Stop 기록은 있지만 현재 복귀 가능한 축이 없는 "
                "PLC가 있습니다. "
                f"Stop 기록 PLC: {recovery_plcs}, "
                f"복귀 가능 PLC: {prepared_plcs}"
            )
        prepared_plcs_text = ", ".join(prepared_plcs)
        # ====================================================
        # mode 3 설정
        # ====================================================
        await asyncio.gather(
            *[
                set_stop_reverse_mode(
                    plc_name,
                    plc_connections[plc_name]
                )
                for plc_name in prepared_plcs
            ]
        )
        print(f"{prepared_plcs_text} Stop 복귀 모드(mode 3) 설정 완료")


        # ====================================================
        # StartSpline / Active 초기화
        # ====================================================
        await asyncio.gather(
            *[
                clear_one_plc_motion_flags(
                    plc_name,
                    plc_connections[plc_name]
                )
                for plc_name in prepared_plcs
            ]
        )
        await asyncio.sleep(0.1)

        print(f"{prepared_plcs_text} 모션 플래그 초기화 완료")


        # ====================================================
        # Power ON
        # ====================================================
        await asyncio.gather(
            *[
                power_on_one_plc(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name]
                )
                for plc_name in prepared_plcs
            ]
        )
        print(f"{prepared_plcs_text} 복귀 대상 축 Power ON 완료")

        await asyncio.sleep(1.0)


        # ====================================================
        # 실제 Powered 확인
        # ====================================================
        power_targets = [
            (plc_name, route)
            for plc_name, routes in plc_motion_routes.items()
            for route in routes
        ]

        powered_results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    plc_connections[plc_name].read_by_name,
                    f"GVL.gAxisState[{route['local_axis']}].Powered",
                    pyads.PLCTYPE_BOOL
                )
                for plc_name, route in power_targets
            ]
        )

        not_powered_axes = [
            {
                "plc_name": plc_name,
                "global_axis": route["global_axis"],
                "local_axis": route["local_axis"],
                "positioner": route["positioner"],
                "motor": route["motor"],
            }
            for (plc_name, route), powered
            in zip(power_targets, powered_results)
            if not powered
        ]

        if not_powered_axes:
            raise RuntimeError(
                "Power ON에 실패한 복귀 대상 축이 있습니다: "
                f"{not_powered_axes}"
            )

        print("전체 복귀 대상 축 Powered = True 확인 완료")


        # ====================================================
        # 복귀 path 전송
        # ====================================================
        await asyncio.gather(
            *[
                send_path_to_one_plc(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name],
                    recovery_axis_points,
                    recovery_total_steps
                )
                for plc_name in prepared_plcs
            ]
        )
        print(f"{prepared_plcs_text} Stop 복귀 경로 데이터 전송 완료")

        await asyncio.sleep(0.5)


        # ====================================================
        # Active 설정
        # ====================================================
        await asyncio.gather(
            *[
                activate_one_plc(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name]
                )
                for plc_name in prepared_plcs
            ]
        )

        print(f"{prepared_plcs_text} 복귀 대상 축 Active 설정 완료")


        # ====================================================
        # 첫 번째 복귀 step만 허가
        # recovery step 1 = 원본 common_return_step
        # ====================================================
        await set_allowed_step_all_plcs(
            plc_connections,
            prepared_plcs,
            1
        )

        last_allowed_step = 1

        print(
            "Stop 복귀 Step 동기화 초기화 완료: "
            f"복귀 Step 1 = 원본 {display_return_step}단계"
        )


        # ====================================================
        # StartSpline 전 MotionSequence 저장
        # ====================================================
        sequence_values = await asyncio.gather(
            *[
                asyncio.to_thread(
                    plc_connections[plc_name].read_by_name,
                    "GVL.gMotionSequence",
                    pyads.PLCTYPE_UDINT
                )
                for plc_name in prepared_plcs
            ]
        )

        motion_sequence_before = {
            plc_name: int(sequence_value)
            for plc_name, sequence_value in zip(
                prepared_plcs,
                sequence_values
            )
        }

        print(
            "복귀 전 MotionSequence: "
            f"{motion_sequence_before}"
        )


        # ====================================================
        # StartSpline 동시 전송
        # StartSpline 전송을 시도하는 순간부터
        # 일부 PLC가 이미 움직일 수 있으므로 True
        # ====================================================
        recovery_started = True

        started_command_plcs = list(
            await asyncio.gather(
                *[
                    start_one_plc(
                        plc_name,
                        plc_connections[plc_name],
                        plc_motion_routes[plc_name]
                    )
                    for plc_name in prepared_plcs
                ]
            )
        )

        print(
            f"{prepared_plcs_text} Stop 복귀 "
            f"StartSpline 전송 완료: {started_command_plcs}"
        )


        # ====================================================
        # MotionSequence 변화 확인
        # ====================================================
        start_results = await asyncio.gather(
            *[
                wait_one_plc_started(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name],
                    motion_sequence_before[plc_name],
                    2.0
                )
                for plc_name in prepared_plcs
            ]
        )

        started_plcs = sorted(
            start_result["plc_name"]
            for start_result in start_results
            if start_result["started"]
        )

        not_started_plcs = sorted(
            start_result["plc_name"]
            for start_result in start_results
            if not start_result["started"]
        )

        start_failure_details = [
            start_result
            for start_result in start_results
            if not start_result["started"]
        ]

        start_failure_has_axis_error = any(
            start_result["reason"] == "axis_error"
            for start_result in start_failure_details
        )

        if not_started_plcs:
            stop_result = await request_all_plcs_stop(
                plc_connections,
                prepared_plcs
            )

            if not stop_result["success"]:
                print(
                    "Stop 명령 전송 실패 PLC: "
                    f"{stop_result['failed_plcs']}"
                )

            successful_stop_plcs = [
                plc_name
                for plc_name in stop_result["requested_plcs"]
                if plc_name not in stop_result["failed_plcs"]
            ]

            if successful_stop_plcs:
                await wait_all_motion_axes_stopped(
                    plc_connections,
                    plc_motion_routes,
                    successful_stop_plcs,
                    timeout=5.0,
                    known_axis_error=start_failure_has_axis_error
                )

            result = {
                "status": "fail",
                "message": (
                    "일부 PLC가 Stop 복귀 모션을 정상 접수하지 않아 "
                    "전체 PLC에 정지를 요청했습니다."
                ),
                "data": {
                    "direction": "stop_reverse",
                    "common_return_step": common_return_step,
                    "started_plcs": started_plcs,
                    "not_started_plcs": not_started_plcs,
                    "start_failure_details": start_failure_details,
                }
            }
            print(result["message"])
            save_result_json(result)
            return result

        print(
            f"{prepared_plcs_text} Stop 복귀 "
            f"모션 접수 확인 완료: {started_plcs}"
        )


        # ====================================================
        # step timeout 시작
        # ====================================================
        step_wait_start_time = time.time()


        # ====================================================
        # 복귀 중 상태 감시 + 2-PLC step 동기화
        # ====================================================
        print()
        while True:

            snapshot_results = await asyncio.gather(
                *[
                    read_one_plc_motion_snapshot(
                        plc_name,
                        plc_connections[plc_name],
                        plc_motion_routes[plc_name]
                    )
                    for plc_name in prepared_plcs
                ]
            )

            all_axis_states = [
                axis_state
                for snapshot in snapshot_results
                for axis_state in snapshot["axis_states"]
            ]

            completed_steps = {
                snapshot["plc_name"]: snapshot["completed_step"]
                for snapshot in snapshot_results
            }

            allowed_steps = {
                snapshot["plc_name"]: snapshot["allowed_step"]
                for snapshot in snapshot_results
            }

            if common_return_step == 0:
                current_original_target_step = 1
            else:
                current_original_target_step = (
                    common_return_step - last_allowed_step + 1
                )

            status_parts = [
                (
                    f"{axis_state['positioner']}-"
                    f"{'α' if axis_state['motor'] == 'alpha' else 'β'}:"
                    f"{axis_state['actual_position']:7.2f}"
                )
                for axis_state in all_axis_states
            ]

            step_status_parts = []

            for snapshot in snapshot_results:

                internal_completed_step = snapshot["completed_step"]
                internal_allowed_step = snapshot["allowed_step"]

                # main()의 0 -> Step 1 이동 중 Stop된 특수 상황
                if common_return_step == 0:
                    original_completed_step = 1
                    original_target_step = 1

                else:
                    # 아직 첫 복귀 Step을 완료하기 전이면
                    # 공통 복귀 시작 Step을 현재 기준으로 표시
                    if internal_completed_step == 0:
                        original_completed_step = common_return_step

                    else:
                        original_completed_step = (
                            common_return_step
                            - internal_completed_step
                            + 1
                        )

                    # PLC 내부 허가 Step을 원본 JSON Step으로 변환
                    original_target_step = (
                        common_return_step
                        - internal_allowed_step
                        + 1
                    )

                step_status_parts.append(
                    (
                        f"{snapshot['plc_name']}:"
                        f"{original_completed_step}/"
                        f"{recovery_total_steps}"
                        f"(Target Step {original_target_step})"
                    )
                )


            print(
                "\033[1A\r\033[2K"
                + "복귀 Step | "
                + "  ".join(step_status_parts)
                + "\n\033[2K"
                + "상태 | "
                + "  ".join(status_parts),
                end="\r",
                flush=True
            )


            # =================================================
            # 축 Error -> 전체 Stop
            # =================================================
            error_axes = [
                axis_state
                for axis_state in all_axis_states
                if axis_state["error"]
            ]

            if error_axes:
                stop_result = await request_all_plcs_stop(
                    plc_connections,
                    prepared_plcs
                )

                if not stop_result["success"]:
                    print(
                        "Stop 명령 전송 실패 PLC: "
                        f"{stop_result['failed_plcs']}"
                    )

                successful_stop_plcs = [
                    plc_name
                    for plc_name in stop_result["requested_plcs"]
                    if plc_name not in stop_result["failed_plcs"]
                ]

                if successful_stop_plcs:
                    await wait_all_motion_axes_stopped(
                        plc_connections,
                        plc_motion_routes,
                        successful_stop_plcs,
                        timeout=5.0,
                        known_axis_error=True
                    )

                result = {
                    "status": "error",
                    "message": (
                        "Stop 지점 복귀 중 축 에러가 발생하여 "
                        "전체 PLC에 정지를 요청했습니다."
                    ),
                    "data": {
                        "direction": "stop_reverse",
                        "error_axes": error_axes,
                        "common_return_step": common_return_step,
                        "completed_steps": completed_steps,
                        "allowed_steps": allowed_steps,
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result


            # =================================================
            # 복귀 중 외부 Stop 감지
            # =================================================
            stop_detected_plcs = sorted(
                snapshot["plc_name"]
                for snapshot in snapshot_results
                if (
                    snapshot["stop_busy"]
                    or snapshot["stop_occurred"]
                )
            )

            if stop_detected_plcs:
                stop_result = await request_all_plcs_stop(
                    plc_connections,
                    prepared_plcs
                )

                if not stop_result["success"]:
                    print(
                        "Stop 명령 전송 실패 PLC: "
                        f"{stop_result['failed_plcs']}"
                    )

                successful_stop_plcs = [
                    plc_name
                    for plc_name in stop_result["requested_plcs"]
                    if plc_name not in stop_result["failed_plcs"]
                ]

                if successful_stop_plcs:
                    await wait_all_motion_axes_stopped(
                        plc_connections,
                        plc_motion_routes,
                        successful_stop_plcs,
                        timeout=5.0
                    )

                if stop_result["failed_plcs"]:
                    stop_status = "error"
                    stop_message = (
                        "사용자의 Stop 요청은 감지되었지만 "
                        "일부 PLC에 Stop 명령 재전송이 실패하여 "
                        "Stop 복귀 모션의 전체 정지를 보장할 수 없습니다."
                    )
                else:
                    stop_status = "stopped"
                    stop_message = (
                        "사용자의 Stop 요청으로 Stop 지점 복귀가 "
                        "중간에 중단되었습니다."
                    )

                result = {
                    "status": stop_status,
                    "message": stop_message,
                    "data": {
                        "direction": "stop_reverse",
                        "stop_detected_plcs": stop_detected_plcs,
                        "stop_success_plcs": successful_stop_plcs,
                        "stop_failed_plcs": stop_result["failed_plcs"],
                        "common_return_step": common_return_step,
                        "completed_steps": completed_steps,
                        "allowed_steps": allowed_steps,
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result


            # =================================================
            # Python 허가 step보다 PLC가 앞서갔는지 확인
            # =================================================
            sync_overrun_plcs = [
                snapshot["plc_name"]
                for snapshot in snapshot_results
                if snapshot["completed_step"] > last_allowed_step
            ]

            if sync_overrun_plcs:
                stop_result = await request_all_plcs_stop(
                    plc_connections,
                    prepared_plcs
                )

                if not stop_result["success"]:
                    print(
                        "Stop 명령 전송 실패 PLC: "
                        f"{stop_result['failed_plcs']}"
                    )

                successful_stop_plcs = [
                    plc_name
                    for plc_name in stop_result["requested_plcs"]
                    if plc_name not in stop_result["failed_plcs"]
                ]

                if successful_stop_plcs:
                    await wait_all_motion_axes_stopped(
                        plc_connections,
                        plc_motion_routes,
                        successful_stop_plcs,
                        timeout=5.0
                    )

                result = {
                    "status": "error",
                    "message": (
                        "Stop 복귀 중 PLC가 Python에서 허가한 step보다 "
                        "먼저 진행했습니다."
                    ),
                    "data": {
                        "direction": "stop_reverse",
                        "sync_overrun_plcs": sorted(sync_overrun_plcs),
                        "last_allowed_step": last_allowed_step,
                        "completed_steps": completed_steps,
                        "allowed_steps": allowed_steps,
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result


            # =================================================
            # 현재 복귀 step timeout
            # =================================================
            if (
                last_allowed_step <= recovery_total_steps
                and time.time() - step_wait_start_time > step_timeout
            ):
                timeout_plcs = [
                    snapshot["plc_name"]
                    for snapshot in snapshot_results
                    if snapshot["completed_step"] < last_allowed_step
                ]

                stop_result = await request_all_plcs_stop(
                    plc_connections,
                    prepared_plcs
                )

                if not stop_result["success"]:
                    print(
                        "Stop 명령 전송 실패 PLC: "
                        f"{stop_result['failed_plcs']}"
                    )
                successful_stop_plcs = [
                    plc_name
                    for plc_name in stop_result["requested_plcs"]
                    if plc_name not in stop_result["failed_plcs"]
                ]               
                if successful_stop_plcs:
                    await wait_all_motion_axes_stopped(
                        plc_connections,
                        plc_motion_routes,
                        successful_stop_plcs,
                        timeout=5.0
                    )
                result = {
                    "status": "fail",
                    "message": (
                        f"원본 Step {current_original_target_step} 복귀가 "
                        f"{step_timeout}초 동안 완료되지 않아 "
                        "전체 PLC를 정지했습니다."
                    ),
                    "data": {
                        "direction": "stop_reverse",
                        "reason": "step_timeout",
                        "timeout_plcs": timeout_plcs,
                        "recovery_step": last_allowed_step,
                        "original_target_step": (
                            current_original_target_step
                        ),
                        "completed_steps": completed_steps,
                        "allowed_steps": allowed_steps,
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result


            # =================================================
            # 현재 허가된 복귀 step을 두 PLC 모두 완료하면
            # 다음 복귀 step 허가
            #
            # 예:
            # 복귀 step 1 = 원본 9
            # 두 PLC 모두 원본 9 도착 -> 복귀 step 2 = 원본 8 허가
            # =================================================
            if last_allowed_step < recovery_total_steps:
                all_plcs_completed_allowed_step = all(
                    snapshot["completed_step"] == last_allowed_step
                    for snapshot in snapshot_results
                )

                if all_plcs_completed_allowed_step:
                    next_allowed_step = last_allowed_step + 1

                    await set_allowed_step_all_plcs(
                        plc_connections,
                        prepared_plcs,
                        next_allowed_step
                    )

                    last_allowed_step = next_allowed_step
                    step_wait_start_time = time.time()


            # =================================================
            # 최종 복귀 step = 원본 1단계 완료 확인
            # =================================================
            all_plcs_completed_final_step = all(
                snapshot["completed_step"] >= recovery_total_steps
                for snapshot in snapshot_results
            )

            all_motion_axes_not_busy = not any(
                axis_state["busy"]
                for axis_state in all_axis_states
            )

            if (
                all_plcs_completed_final_step
                and all_motion_axes_not_busy
            ):
                print()
                break

            await asyncio.sleep(0.05)


        # ====================================================
        # 원본 JSON 1단계 실제 위치 최종 확인
        # ====================================================
        final_snapshot_results = await asyncio.gather(
            *[
                read_one_plc_motion_snapshot(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name]
                )
                for plc_name in prepared_plcs
            ]
        )

        final_axis_states = [
            axis_state
            for snapshot in final_snapshot_results
            for axis_state in snapshot["axis_states"]
        ]

        final_positions = {}
        invalid_axes = []

        for axis_state in final_axis_states:
            global_axis = axis_state["global_axis"]

            expected = float(
                axis_points[global_axis][0]
            )

            actual = float(
                axis_state["actual_position"]
            )

            position_error = abs(actual - expected)

            final_positions[str(global_axis)] = {
                "plc_name": axis_state["plc_name"],
                "local_axis": axis_state["local_axis"],
                "positioner": axis_state["positioner"],
                "motor": axis_state["motor"],
                "expected_step_1_position": expected,
                "actual_position": actual,
                "position_error": position_error,
                "busy": axis_state["busy"],
                "error": axis_state["error"],
            }

            if (
                position_error > position_tolerance
                or axis_state["busy"]
                or axis_state["error"]
            ):
                invalid_axes.append({
                    "global_axis": global_axis,
                    "plc_name": axis_state["plc_name"],
                    "expected": expected,
                    "actual": actual,
                    "position_error": position_error,
                    "busy": axis_state["busy"],
                    "error": axis_state["error"],
                })

        if invalid_axes:
            result = {
                "status": "fail",
                "message": (
                    "Stop 복귀 모션은 종료되었지만 일부 축이 "
                    "원본 JSON 1단계 위치 허용오차를 벗어났습니다. "
                    "Stop 기록은 삭제하지 않습니다."
                ),
                "data": {
                    "direction": "stop_reverse",
                    "common_return_step": common_return_step,
                    "position_tolerance": position_tolerance,
                    "invalid_axes": invalid_axes,
                    "final_positions": final_positions,
                }
            }
            print(result["message"])
            save_result_json(result)
            return result

        # ====================================================
        # 실제 모션 복귀는 이미 완전히 끝났음
        # 이후 오류는 모션 Stop 대상이 아님
        # ====================================================
        recovery_started = False

        try:
            await clear_stopped_info_all_plcs(
                plc_connections,
                prepared_plcs,
                timeout=2.0
            )

        except Exception as clear_exc:

            # 어떤 PLC에 Stop 기록이 아직 남아 있는지 다시 확인
            stopped_valid_results = await asyncio.gather(
                *[
                    asyncio.to_thread(
                        plc_connections[plc_name].read_by_name,
                        "GVL.gStoppedValid",
                        pyads.PLCTYPE_BOOL
                    )
                    for plc_name in prepared_plcs
                ],
                return_exceptions=True
            )

            remaining_stopped_plcs = []

            for plc_name, stopped_valid_result in zip(
                prepared_plcs,
                stopped_valid_results
            ):
                if isinstance(stopped_valid_result, Exception):
                    remaining_stopped_plcs.append(plc_name)

                elif stopped_valid_result:
                    remaining_stopped_plcs.append(plc_name)

            # 아직 기록이 남은 PLC만 한 번 더 삭제 시도
            if remaining_stopped_plcs:
                try:
                    await clear_stopped_info_all_plcs(
                        plc_connections,
                        remaining_stopped_plcs,
                        timeout=2.0
                    )

                    remaining_stopped_plcs = []

                except Exception:
                    pass

            # 재시도 후에도 남았다면 모션은 성공했지만
            # Stop 기록 정리는 실패했다고 별도로 반환
            if remaining_stopped_plcs:
                result = {
                    "status": "fail",
                    "message": (
                        "Stop 복귀 모션과 1단계 위치 확인은 완료되었지만 "
                        "일부 PLC의 Stop 기록 삭제에 실패했습니다."
                    ),
                    "data": {
                        "direction": "stop_reverse",
                        "reason": "stopped_info_clear_failed",
                        "remaining_stopped_plcs": remaining_stopped_plcs,
                        "clear_error": str(clear_exc),
                        "final_positions": final_positions,
                    }
                }   
                print(result["message"])
                save_result_json(result)
                return result

        print("Stop 기록 삭제 완료")

        # ====================================================
        # 정상 완료 결과
        # ====================================================
        if common_return_step == 0:
            success_message = (
                f"{prepared_plcs_text}의 Stop 위치에서 "
                "원본 1단계까지 복귀가 완료되었습니다."
            )
        else:
            success_message = (
                f"{prepared_plcs_text}의 Stop 복귀가 "
                f"공통 원본 {common_return_step}단계에서 "
                "원본 1단계까지 완료되었습니다."
            )

        result = {
            "status": "success",
            "message": success_message,
            "data": {
                "direction": "stop_reverse",
                "stop_records_before_recovery": stop_records,
                "common_return_step": common_return_step,
                "recovery_total_steps": recovery_total_steps,
                "motion_axes": motion_axes,
                "locked_axes": locked_axes,
                "position_tolerance": position_tolerance,
                "final_positions": final_positions,
                "stopped_info_cleared_plcs": prepared_plcs,
            }
        }

        print(result["message"])
        save_result_json(result)
        return result


    except StopAxisError as e:
        result = {
            "status": "error",
            "message": str(e),
            "data": {
                "direction": "stop_reverse",
                "reason": "stop_axis_error"
            }
        }
        print(result["message"])
        save_result_json(result)
        return result


    except (ValueError, KeyError, TimeoutError, ConnectionError) as e:
        result = {
            "status": "fail",
            "message": str(e),
            "data": {
                "direction": "stop_reverse"
            }
        }
        print(result["message"])
        save_result_json(result)
        return result


    except pyads.ADSError as e:
        successful_stop_plcs = []
        stop_failed_plcs = {}
        stop_wait_error = None

        if opened_plcs and recovery_started:
            stop_result = await request_all_plcs_stop(
                plc_connections,
                prepared_plcs
            )

            stop_failed_plcs = stop_result["failed_plcs"]

            successful_stop_plcs = [
                plc_name
                for plc_name in stop_result["requested_plcs"]
                if plc_name not in stop_failed_plcs
            ]

            if stop_failed_plcs:
                print(
                    "Stop 명령 전송 실패 PLC: "
                    f"{stop_failed_plcs}"
                )

            if successful_stop_plcs:
                try:
                    await wait_all_motion_axes_stopped(
                        plc_connections,
                        plc_motion_routes,
                        successful_stop_plcs,
                        timeout=5.0
                    )
                except Exception as stop_wait_exc:
                    stop_wait_error = str(stop_wait_exc)

        result = {
            "status": "error",
            "message": (
                "PLC 통신 또는 ADS 에러가 발생했습니다: "
                f"{e}"
            ),
            "data": {
                "direction": "stop_reverse",
                "stop_success_plcs": successful_stop_plcs,
                "stop_failed_plcs": stop_failed_plcs,
                "stop_wait_error": stop_wait_error,
            }
        }
        print(result["message"])
        save_result_json(result)
        return result


    except Exception as e:
        successful_stop_plcs = []
        stop_failed_plcs = {}
        stop_wait_error = None

        if opened_plcs and recovery_started:
            stop_result = await request_all_plcs_stop(
                plc_connections,
                prepared_plcs
            )

            stop_failed_plcs = stop_result["failed_plcs"]

            successful_stop_plcs = [
                plc_name
                for plc_name in stop_result["requested_plcs"]
                if plc_name not in stop_failed_plcs
            ]

            if stop_failed_plcs:
                print(
                    "Stop 명령 전송 실패 PLC: "
                    f"{stop_failed_plcs}"
                )

            if successful_stop_plcs:
                try:
                    await wait_all_motion_axes_stopped(
                        plc_connections,
                        plc_motion_routes,
                        successful_stop_plcs,
                        timeout=5.0
                    )
                except Exception as stop_wait_exc:
                    stop_wait_error = str(stop_wait_exc)

        result = {
            "status": "error",
            "message": (
                "Stop 지점 복귀 중 예상하지 못한 에러가 발생했습니다: "
                f"{e}"
            ),
            "data": {
                "direction": "stop_reverse",
                "stop_success_plcs": successful_stop_plcs,
                "stop_failed_plcs": stop_failed_plcs,
                "stop_wait_error": stop_wait_error,
            }
        }
        print(result["message"])
        save_result_json(result)
        return result


    finally:

        if opened_plcs:
            await asyncio.gather(
                *[
                    clear_one_plc_motion_flags(
                        plc_name,
                        plc_connections[plc_name]
                    )
                    for plc_name in opened_plcs
                ],
                return_exceptions=True
            )



