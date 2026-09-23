#  Stop 후 재실행에서는 “Stop 당시 zero에 참여했던 축”만 계속 0도로 보내고, 그 축을 새로 Lock하면 실행 금지, 원래 Lock이던 축을 Unlock해도 새로 참여시키지는 않는다.


import time
import asyncio
import pyads

from kspec_0_function import * 

async def zero_main( # pyright: ignore[reportGeneralTypeIssues]
    plc_connections,
    start_tolerance: float = 0.1,
    zero_tolerance: float = 0.1,
    timeout: float = 60.0,
    *,
    alpha_file: str,
    beta_file: str,
):

    print("전체 포지셔너 1단계 -> 0도 이동 시작")


    # ========================================================
    # 원본 JSON 읽기
    # 1단계 실제 목표 위치 확인용
    # ========================================================
    try:
        axis_points, total_steps = read_json(alpha_file, beta_file)

    except FileNotFoundError as e:
        result = {
            "status": "fail",
            "message": f"JSON 파일을 찾을 수 없습니다: {e.filename}",
            "data": {
                "missing_file": e.filename,
                "direction": "zero"
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
                "direction": "zero"
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
                "direction": "zero"
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

    zero_started = False

    # zero_main() 이동중 Stop 된 뒤 
    # 다시 zero_main()을 실행하는 경우인지 표시
    resume_zero_from_stop = False

    # mode 4 Stop 기록이 있는 PLC
    zero_stop_plcs = []

    # PLC Stop 기록
    stop_records = {}


    try:


        # ====================================================
        # 이전 Stop 기록 확인
        #
        # Stop 기록이 없으면: 정상적인 Step 1 -> 0 이동
        #
        # mode 4(zero_main) Stop 기록이면: Stop 위치 -> 0도 재이동 허용
        #
        # 다른 mode의 Stop 기록이면: zero_main() 실행 금지
        # =====================================================
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
            for  record in stop_record_results
        }

        zero_stop_plcs = sorted(
            plc_name
            for plc_name, record in stop_records.items()
            if record["stopped_valid"]
        )

        if zero_stop_plcs:
            stopped_modes = {
                stop_records[plc_name]["stopped_mode"]
                for plc_name in zero_stop_plcs
            }

            # Stop 기록이 여러 PLC에 존재하는데
            # Motion Mode가 서로 다르면 실행하지 않음
            if len(stopped_modes) != 1:
                raise ValueError(
                    "PLC들의 Stop 당시 Motion Mode가 서로 다릅니다: "
                    f"{sorted(stopped_modes)}"
                )

            source_stop_mode = next(iter(stopped_modes))

            # zero_main()중 발생한 Stop만
            # 다시 zero_main()으로 이어서 실행 가능
            if source_stop_mode != MOTION_MODE_ZERO:
                raise ValueError(
                    "zero_main() 이외의 모션에서 발생한 Stop 기록이 남아있어 "
                    "0도 이동을 재실행 할 수 없습니다. " 
                    f"stopped_mode={source_stop_mode}"
                )

            # 실제 Stop 처리가 완전히 끝났는지 검사
            incomplete_stop_plcs = [
                plc_name
                for plc_name in zero_stop_plcs
                if (
                    stop_records[plc_name]["stop_busy"]
                    or not stop_records[plc_name]["stop_occurred"]
                    or not stop_records[plc_name]["stop_done"]
                )
            ]

            if incomplete_stop_plcs:
                raise ValueError(
                    "이전 0도 이동의 Stop 처리가 아직 완전히 끝나지 않은 PLC가 있습니다: "
                    f"{incomplete_stop_plcs}"
                )
            resume_zero_from_stop = True

            print(
                "zero_main() 이동중 발생한 Stop 기록을 확인했습니다. " 
                "현재 Stop 위치에서 0도 이동을 다시 시작합니다."
            )

        # ====================================================
        # PLC1 / PLC2 잠금 상태 확인
        # ====================================================
        lock_results = await asyncio.gather(
            read_one_plc_lock_state("PLC1", plc_connections["PLC1"] ),
            read_one_plc_lock_state("PLC2", plc_connections["PLC2"] ),
        )

        current_locked_axes = []
        current_motion_axes = []

        for lock_result in lock_results:

            current_locked_axes.extend(
                lock_result["locked_axes"]
            )

            current_motion_axes.extend(
                lock_result["motion_axes"]
            )

        current_locked_axes = sorted(current_locked_axes)
        current_motion_axes = sorted(current_motion_axes)


        # ====================================================
        # 일반 zero 시작 / Stop 후 zero 재시작 구분
        # ====================================================
        if resume_zero_from_stop:

            # Stop 당시 실제 zero 이동에 참여했던 축만 사용
            stopped_selected_axes = sorted({
                global_axis
                for plc_name in zero_stop_plcs
                for global_axis
                in stop_records[plc_name]["stopped_selected_axes"]
            })

            if not stopped_selected_axes:
                raise ValueError(
                    "Stop 당시 0도 이동에 참여한 축 정보가 없습니다."
                )

            # Stop 당시 움직이던 축이
            # Stop 후 새로 Lock되었는지 검사
            newly_locked_motion_axes = sorted(
                set(stopped_selected_axes)
                & set(current_locked_axes)
            )

            if newly_locked_motion_axes:
                raise ValueError(
                    "Stop 당시 0도 이동 중이던 축이 현재 Lock되어 "
                    "zero_main()을 다시 시작할 수 없습니다: "
                    f"{newly_locked_motion_axes}"
                )

            # Stop 당시 실제 움직이던 축만 다시 0도로 이동
            motion_axes = stopped_selected_axes
            locked_axes = current_locked_axes

            print(
                "Stop 당시 0도 이동 참여 축만 "
                f"재이동 대상으로 사용합니다: {motion_axes}"
            )

        else:

            # 정상적인 Step 1 -> 0도 이동
            motion_axes = current_motion_axes
            locked_axes = current_locked_axes

        print(f"잠금 축: {locked_axes}")
        print(f"0도 이동 대상 축: {motion_axes}")

        if not motion_axes:

            result = {
                "status": "fail",
                "message": (
                    "모든 PLC의 모든 축이 잠겨 있어 "
                    "0도 이동을 시작할 수 없습니다."
                ),
                "data": {
                    "direction": "zero",
                    "locked_axes": locked_axes,
                    "motion_axes": []
                }
            }

            print(result["message"])
            save_result_json(result)
            return result


        # ====================================================
        # global_axis -> PLC / local_axis 매핑 생성
        # ====================================================
        global_axis_routes = build_global_axis_routes()


        # ====================================================
        # 실제 0도 이동 대상 축을 PLC별로 나눔
        # 잠긴 축은 제외됨
        # ====================================================
        for global_axis in motion_axes:

            if global_axis not in global_axis_routes:
                raise KeyError(
                    f"{global_axis}번 전역축의 "
                    "매핑 정보가 없습니다."
                )

            route = global_axis_routes[global_axis]

            plc_motion_routes[
                route["plc_name"]
            ].append(route)


        print(
            "PLC1 0도 이동 전역축:",
            [
                route["global_axis"]
                for route
                in plc_motion_routes["PLC1"]
            ]
        )

        print(
            "PLC2 0도 이동 전역축:",
            [
                route["global_axis"]
                for route
                in plc_motion_routes["PLC2"]
            ]
        )


        # ====================================================
        # 실제 움직일 축이 있는 PLC
        # ====================================================
        prepared_plcs = [
            plc_name
            for plc_name, routes
            in plc_motion_routes.items()
            if routes
        ]

        prepared_plcs_text = ", ".join(prepared_plcs)

        if not prepared_plcs:
            raise RuntimeError(
                "0도 이동 준비가 완료된 PLC가 없습니다."
            )


        # ====================================================
        # 이전 StartSpline / Active 초기화
        # ====================================================
        await asyncio.gather(
            clear_one_plc_motion_flags(
                "PLC1",
                plc_connections["PLC1"]
            ),
            clear_one_plc_motion_flags(
                "PLC2",
                plc_connections["PLC2"]
            )
        )

        await asyncio.sleep(0.1)

        print("PLC1, PLC2 모션 플래그 초기화 완료")


        # ====================================================
        # 현재 위치가 원본 JSON 1단계 위치인지 검사
        #
        # 잠긴 축은 검사 대상에서 제외된다.
        # ====================================================
        start_snapshot_results = await asyncio.gather(
            *[
                read_one_plc_motion_snapshot(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name]
                )
                for plc_name in prepared_plcs
            ]
        )

        start_positions = {}
        invalid_start_axes = []

        for snapshot in start_snapshot_results:

            for axis_state in snapshot["axis_states"]:

                global_axis = axis_state["global_axis"]

                expected = float(
                    axis_points[
                        global_axis
                    ][0]
                )

                actual = float(
                    axis_state["actual_position"]
                )

                position_error = abs(
                    actual - expected
                )

                start_positions[
                    str(global_axis)
                ] = {
                    "plc_name":
                        axis_state["plc_name"],

                    "local_axis":
                        axis_state["local_axis"],

                    "positioner":
                        axis_state["positioner"],

                    "motor":
                        axis_state["motor"],

                    "expected_step_1_position":
                        expected,

                    "actual_position":
                        actual,

                    "position_error":
                        position_error,

                    "busy":
                        axis_state["busy"],

                    "error":
                        axis_state["error"],
                }
                if (
                    axis_state["busy"]
                    or axis_state["error"]
                    or (
                        not resume_zero_from_stop
                        and position_error > start_tolerance
                    )
                ):
                    
                    invalid_start_axes.append({
                        "global_axis":
                            global_axis,

                        "plc_name":
                            axis_state["plc_name"],

                        "expected":
                            expected,

                        "actual":
                            actual,

                        "position_error":
                            position_error,

                        "busy":
                            axis_state["busy"],

                        "error":
                            axis_state["error"],
                    })


        # ====================================================
        # 하나라도 1단계 위치가 아니면
        # 아무 축도 움직이지 않는다.
        # ====================================================
        if invalid_start_axes:

            if resume_zero_from_stop:
                fail_message = (
                    "Stop 후 0도 재이동 대상 축 중 "
                    "Busy 또는 Error 상태인 축이 있어 "
                    "0도 이동을 다시 시작하지 않습니다."
                )
            else:
                fail_message = (
                    "일부 0도 이동 대상 축이 원본 JSON "
                    "1단계 위치를 만족하지 않아 "
                    "0도 이동을 시작하지 않습니다."
                )

            result = {
                "status": "fail",
                "message": fail_message,
                "data": {
                    "direction": "zero",
                    "start_tolerance":
                        start_tolerance,

                    "invalid_axes":
                        invalid_start_axes,

                    "start_positions":
                        start_positions,

                    "motion_axes":
                        motion_axes,

                    "locked_axes":
                        locked_axes,

                    "json_total_steps":
                        total_steps,
                }
            }

            print(result["message"])
            save_result_json(result)
            return result

        if resume_zero_from_stop:
            print("0도 이동 Stop 위치에서 재실행 조건 확인 완료")

        else:
            print("전체 0도 이동 대상 축의 원본 JSON 1단계 위치 확인 완료")


        # ====================================================
        # 각 축에 1-step짜리 0도 경로 생성
        #
        # global_axis -> [0.0]
        # TotalPoints = 1
        # ====================================================
        zero_axis_points, zero_total_steps = create_zero_axis_points(motion_axes, zero_position=0.0)


        # ====================================================
        # PLC1 / PLC2 zero mode = 4
        # ====================================================
        await asyncio.gather(
            set_zero_mode(
                "PLC1",
                plc_connections["PLC1"]
            ),
            set_zero_mode(
                "PLC2",
                plc_connections["PLC2"]
            )
        )

        print(
            "PLC1, PLC2 0도 이동 모드"
            "(mode 4) 설정 완료"
        )


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

        print(
            f"{prepared_plcs_text} 0도 이동 대상 축 "
            "Power ON 완료"
        )

        await asyncio.sleep(1.0)


        # ====================================================
        # 실제 Powered=True 확인
        # ====================================================
        power_targets = [
            (
                plc_name,
                route
            )
            for plc_name in prepared_plcs
            for route
            in plc_motion_routes[plc_name]
        ]

        powered_results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    plc_connections[
                        plc_name
                    ].read_by_name,

                    (
                        "GVL.gAxisState"
                        f"[{route['local_axis']}]"
                        ".Powered"
                    ),

                    pyads.PLCTYPE_BOOL
                )

                for plc_name, route
                in power_targets
            ]
        )


        not_powered_axes = [
            {
                "plc_name":
                    plc_name,

                "global_axis":
                    route["global_axis"],

                "local_axis":
                    route["local_axis"],

                "positioner":
                    route["positioner"],

                "motor":
                    route["motor"],
            }

            for (
                plc_name,
                route
            ), powered

            in zip(
                power_targets,
                powered_results
            )

            if not powered
        ]


        if not_powered_axes:
            raise RuntimeError(
                "Power ON에 실패한 "
                "0도 이동 대상 축이 있습니다: "
                f"{not_powered_axes}"
            )


        print(
            "전체 0도 이동 대상 축 "
            "Powered = True 확인 완료"
        )


        # ====================================================
        # PLC1 / PLC2에 0도 1-step 경로 전송
        # ====================================================
        await asyncio.gather(
            *[
                send_path_to_one_plc(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name],
                    zero_axis_points,
                    zero_total_steps
                )

                for plc_name in prepared_plcs
            ]
        )

        print(
            f"{prepared_plcs_text} "
            "0도 1-step 경로 데이터 전송 완료"
        )

        await asyncio.sleep(0.5)


        # ====================================================
        # Active=True
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

        print(
            f"{prepared_plcs_text} 0도 이동 대상 축 "
            "Active 설정 완료"
        )


        # ====================================================
        # 1-step 모션이므로
        # gAllowedStep = 1
        # ====================================================
        await set_allowed_step_all_plcs(
            plc_connections,
            prepared_plcs,
            1
        )

        print(
            "0도 이동 Step 동기화 초기화 완료: "
            "모든 구동 PLC에 1번 step까지 허가"
        )


        # ====================================================
        # StartSpline 전 MotionSequence 저장
        # ====================================================
        sequence_values = await asyncio.gather(
            *[
                asyncio.to_thread(
                    plc_connections[
                        plc_name
                    ].read_by_name,

                    "GVL.gMotionSequence",

                    pyads.PLCTYPE_UDINT
                )

                for plc_name in prepared_plcs
            ]
        )


        motion_sequence_before = {
            plc_name: int(sequence_value)

            for (
                plc_name,
                sequence_value
            )

            in zip(
                prepared_plcs,
                sequence_values
            )
        }


        print(
            "0도 이동 전 MotionSequence: "
            f"{motion_sequence_before}"
        )


        # ====================================================
        # StartSpline 동시 전송
        # StartSpline 전송을 시도하는 순간부터
        # 일부 PLC가 이미 움직일 수 있으므로 True
        # ====================================================
        zero_started = True

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
            f"{prepared_plcs_text} 0도 이동 "
            "StartSpline 전송 완료: "
            f"{started_command_plcs}"
        )


        # ====================================================
        # MotionSequence 변화로
        # 실제 모션 접수 확인
        # ====================================================
        start_results = await asyncio.gather(
            *[
                wait_one_plc_started(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name],
                    motion_sequence_before[
                        plc_name
                    ],
                    2.0
                )

                for plc_name in prepared_plcs
            ]
        )


        started_plcs = sorted(
            start_result["plc_name"]

            for start_result
            in start_results

            if start_result["started"]
        )


        not_started_plcs = sorted(
            start_result["plc_name"]

            for start_result
            in start_results

            if not start_result["started"]
        )


        start_failure_details = [
            start_result

            for start_result
            in start_results

            if not start_result["started"]
        ]


        start_failure_has_axis_error = any(
            start_result["reason"]
            == "axis_error"

            for start_result
            in start_failure_details
        )


        # ====================================================
        # 하나라도 출발 실패하면
        # 전체 PLC Stop
        # ====================================================
        if not_started_plcs:

            stop_result = await request_all_plcs_stop(
                plc_connections,
                opened_plcs
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
                    known_axis_error=
                        start_failure_has_axis_error
                )


            result = {
                "status": "fail",
                "message": (
                    "일부 PLC가 0도 이동 모션을 "
                    "정상 접수하지 않아 "
                    "전체 PLC에 정지를 요청했습니다."
                ),
                "data": {
                    "direction": "zero",
                    "started_plcs":
                        started_plcs,

                    "not_started_plcs":
                        not_started_plcs,

                    "start_failure_details":
                        start_failure_details,

                    "motion_axes":
                        motion_axes,

                    "locked_axes":
                        locked_axes,
                }
            }
            print(result["message"])
            save_result_json(result)
            return result


        print(
            f"{prepared_plcs_text} 0도 이동 모션 "
            "접수 확인 완료: "
            f"{started_plcs}"
        )


        # ====================================================
        # zero 1-step 전체 제한시간 시작
        # ====================================================
        move_start_time = time.time()


        # ====================================================
        # 0도 이동 상태 감시
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

                    for plc_name
                    in prepared_plcs
                ]
            )


            all_axis_states = [
                axis_state

                for snapshot
                in snapshot_results

                for axis_state
                in snapshot["axis_states"]
            ]


            completed_steps = {
                snapshot["plc_name"]:
                    snapshot["completed_step"]

                for snapshot
                in snapshot_results
            }


            allowed_steps = {
                snapshot["plc_name"]:
                    snapshot["allowed_step"]

                for snapshot
                in snapshot_results
            }


            status_parts = [
                (
                    f"{axis_state['positioner']}-"
                    f"{'α' if axis_state['motor'] == 'alpha' else 'β'}:"
                    f"{axis_state['actual_position']:7.2f}"
                )

                for axis_state
                in all_axis_states
            ]


            step_status_parts = [
                (
                    f"{snapshot['plc_name']}:"
                    f"{snapshot['completed_step']}/1"
                    f"(Target Step "
                    f"{snapshot['allowed_step']})"
                )

                for snapshot
                in snapshot_results
            ]


            print(
                "\033[1A\r\033[2K"
                + "Zero Step | "
                + "  ".join(step_status_parts)
                + "\n\033[2K"
                + "상태 | "
                + "  ".join(status_parts),
                end="\r",
                flush=True
            )

            # =================================================
            # 축 Error 발생
            # =================================================
            error_axes = [
                axis_state

                for axis_state
                in all_axis_states

                if axis_state["error"]
            ]


            if error_axes:

                stop_result = (
                    await request_all_plcs_stop(
                        plc_connections,
                        opened_plcs
                    )
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
                        "0도 이동 중 축 에러가 "
                        "발생하여 전체 PLC에 "
                        "정지를 요청했습니다."
                    ),
                    "data": {
                        "direction": "zero",
                        "error_axes":
                            error_axes,

                        "motion_axes":
                            motion_axes,

                        "locked_axes":
                            locked_axes,

                        "completed_steps":
                            completed_steps,

                        "allowed_steps":
                            allowed_steps,
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result


            # =================================================
            # 외부 Stop 감지
            # =================================================
            stop_detected_plcs = sorted(
                snapshot["plc_name"]

                for snapshot
                in snapshot_results

                if (
                    snapshot["stop_busy"]
                    or snapshot["stop_occurred"]
                )
            )


            if stop_detected_plcs:

                stop_result = (
                    await request_all_plcs_stop(
                        plc_connections,
                        opened_plcs
                    )
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

                stopped_snapshot_results = []

                if successful_stop_plcs:
                    stopped_snapshot_results = (
                        await wait_all_motion_axes_stopped(
                            plc_connections,
                            plc_motion_routes,
                            successful_stop_plcs,
                            timeout=5.0
                        )
                    )


                stopped_target_steps = {
                    snapshot["plc_name"]:
                        snapshot[
                            "stopped_target_step"
                        ]

                    for snapshot
                    in stopped_snapshot_results
                }


                stopped_axis_states = [
                    axis_state

                    for snapshot
                    in stopped_snapshot_results

                    for axis_state
                    in snapshot["axis_states"]
                ]


                stopped_positions = {
                    str(
                        axis_state["global_axis"]
                    ): {
                        "plc_name":
                            axis_state["plc_name"],

                        "local_axis":
                            axis_state["local_axis"],

                        "positioner":
                            axis_state["positioner"],

                        "motor":
                            axis_state["motor"],

                        "actual_position":
                            axis_state[
                                "actual_position"
                            ],

                        "busy":
                            axis_state["busy"],

                        "error":
                            axis_state["error"],
                    }

                    for axis_state
                    in stopped_axis_states
                }


                if stop_result["failed_plcs"]:
                    stop_status = "error"
                    stop_message = (
                        "사용자의 Stop 요청은 감지되었지만 "
                        "일부 PLC에 Stop 명령 재전송이 실패하여 "
                        "전체 PLC의 정지를 보장할 수 없습니다."
                    )
                else:
                    stop_status = "stopped"
                    stop_message = (
                        "사용자의 Stop 요청으로 "
                        "0도 이동이 중간에 "
                        "중단되었습니다."
                    )

                result = {
                    "status": stop_status,
                    "message": stop_message,
                    "data": {
                        "direction": "zero",

                        "stop_detected_plcs":
                            stop_detected_plcs,

                        "stop_success_plcs":
                            successful_stop_plcs,

                        "stop_failed_plcs":
                            stop_result["failed_plcs"],

                        "stopped_target_steps":
                            stopped_target_steps,

                        "stopped_positions":
                            stopped_positions,

                        "motion_axes":
                            motion_axes,

                        "locked_axes":
                            locked_axes,
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result


            # =================================================
            # 허가한 1번 step보다 앞서 진행했는지 확인
            # =================================================
            sync_overrun_plcs = [
                snapshot["plc_name"]

                for snapshot
                in snapshot_results

                if snapshot["completed_step"] > 1
            ]


            if sync_overrun_plcs:

                stop_result = (
                    await request_all_plcs_stop(
                        plc_connections,
                        opened_plcs
                    )
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
                        "0도 이동 중 PLC가 "
                        "허가된 1번 step보다 "
                        "먼저 진행했습니다."
                    ),
                    "data": {
                        "direction": "zero",

                        "sync_overrun_plcs":
                            sorted(
                                sync_overrun_plcs
                            ),

                        "completed_steps":
                            completed_steps,

                        "allowed_steps":
                            allowed_steps,
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result


            # =================================================
            # 0도 이동 timeout
            # =================================================
            if (
                time.time()
                - move_start_time
                > timeout
            ):

                timeout_plcs = [
                    snapshot["plc_name"]

                    for snapshot
                    in snapshot_results

                    if (
                        snapshot[
                            "completed_step"
                        ] < 1

                        or any(
                            axis_state["busy"]

                            for axis_state
                            in snapshot["axis_states"]
                        )
                    )
                ]


                stop_result = (
                    await request_all_plcs_stop(
                        plc_connections,
                        opened_plcs
                    )
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
                        f"0도 이동이 {timeout}초 동안 "
                        "완료되지 않아 "
                        "전체 PLC를 정지했습니다."
                    ),
                    "data": {
                        "direction": "zero",
                        "reason": "timeout",

                        "timeout_plcs":
                            timeout_plcs,

                        "completed_steps":
                            completed_steps,

                        "allowed_steps":
                            allowed_steps,
                    }
                }   
                print(result["message"])
                save_result_json(result)
                return result


            # =================================================
            # PLC1 / PLC2 모두 zero step 완료 확인
            # =================================================
            all_plcs_completed_zero_step = all(
                snapshot["completed_step"] >= 1

                for snapshot
                in snapshot_results
            )


            all_motion_axes_not_busy = not any(
                axis_state["busy"]

                for axis_state
                in all_axis_states
            )


            if (
                all_plcs_completed_zero_step
                and all_motion_axes_not_busy
            ):

                print()
                break


            await asyncio.sleep(0.05)


        # ====================================================
        # 실제 최종 0도 위치 확인
        # ====================================================
        final_snapshot_results = await asyncio.gather(
            *[
                read_one_plc_motion_snapshot(
                    plc_name,
                    plc_connections[plc_name],
                    plc_motion_routes[plc_name]
                )

                for plc_name
                in prepared_plcs
            ]
        )


        final_axis_states = [
            axis_state

            for snapshot
            in final_snapshot_results

            for axis_state
            in snapshot["axis_states"]
        ]


        final_positions = {}
        invalid_zero_axes = []


        for axis_state in final_axis_states:

            global_axis = axis_state["global_axis"]

            actual = float(
                axis_state["actual_position"]
            )

            position_error = abs(
                actual - 0.0
            )


            final_positions[
                str(global_axis)
            ] = {
                "plc_name":
                    axis_state["plc_name"],

                "local_axis":
                    axis_state["local_axis"],

                "positioner":
                    axis_state["positioner"],

                "motor":
                    axis_state["motor"],

                "target_position":
                    0.0,

                "actual_position":
                    actual,

                "position_error":
                    position_error,

                "busy":
                    axis_state["busy"],

                "error":
                    axis_state["error"],
            }


            if (
                position_error > zero_tolerance
                or axis_state["busy"]
                or axis_state["error"]
            ):

                invalid_zero_axes.append({
                    "global_axis":
                        global_axis,

                    "plc_name":
                        axis_state["plc_name"],

                    "target":
                        0.0,

                    "actual":
                        actual,

                    "position_error":
                        position_error,

                    "busy":
                        axis_state["busy"],

                    "error":
                        axis_state["error"],
                })


        if invalid_zero_axes:

            result = {
                "status": "fail",
                "message": (
                    "0도 이동은 종료되었지만 "
                    "일부 축이 0도 위치 "
                    "허용오차를 벗어났습니다."
                ),
                "data": {
                    "direction": "zero",

                    "zero_tolerance":
                        zero_tolerance,

                    "invalid_axes":
                        invalid_zero_axes,

                    "final_positions":
                        final_positions,

                    "motion_axes":
                        motion_axes,

                    "locked_axes":
                        locked_axes,
                }
            }
            print(result["message"])
            save_result_json(result)
            return result

        # ====================================================
        # zero Stop 이후 재실행 하여 0도까지 정상 도착한 경우 기존 Stop 기록 삭제
        # ====================================================
        zero_started = False

        if resume_zero_from_stop:

            try:
                await clear_stopped_info_all_plcs(
                    plc_connections,
                    zero_stop_plcs,
                    timeout = 2.0
                )

            except Exception as clear_exc:

                # 어떤 PLC에 Stop 기록이 아직 남아 있는지 확인
                stopped_valid_results = await asyncio.gather(
                    *[
                        asyncio.to_thread(
                            plc_connections[plc_name].read_by_name,
                            "GVL.gStoppedValid",
                            pyads.PLCTYPE_BOOL
                        )
                        for plc_name in zero_stop_plcs
                    ],
                    return_exceptions = True
                )

                remaining_stopped_plcs = []

                for plc_name, stopped_valid_results in zip(
                    zero_stop_plcs,
                    stopped_valid_results
                ):

                    if isinstance(stopped_valid_results, Exception):
                        remaining_stopped_plcs.append(plc_name)

                    elif stopped_valid_results:
                        remaining_stopped_plcs.append(plc_name)


                # 아직 기록이 남은 PLC만 한번 더 삭제
                if remaining_stopped_plcs:

                    try:
                        await clear_stopped_info_all_plcs(
                            plc_connections,
                            remaining_stopped_plcs,
                            timeout = 2.0
                        )

                        remaining_stopped_plcs = []
                    except Exception:
                        pass

                if remaining_stopped_plcs:

                    result = {
                        "status": "fail",
                        "message": (
                            "0도 이동, 최종 0도 위치 확인 완료했지만 일부 PLC Stop 기록 삭제에 실패했습니다."
                        ),
                        "data": {
                            "direction": "zero",
                            "reason": "stopped_info_clear_failed",
                            "remaining_stopped_plcs": remaining_stopped_plcs,
                            "clear_error": str(clear_exc),
                            "final_positions": final_positions,

                        }
                    }
                    print(result["message"])
                    save_result_json(result)
                    return result
            print("0도 이동 Stop 기록 삭제 완료")





        # ====================================================
        # 최종 성공
        # ====================================================
        result = {
            "status": "success",
            "message": (
                f"{prepared_plcs_text}의 0도 이동 대상 축이 "
                "0도까지 정상 이동했습니다."
            ),
            "data": {
                "direction": "zero",

                "start_tolerance":
                    start_tolerance,

                "zero_tolerance":
                    zero_tolerance,

                "motion_axes":
                    motion_axes,

                "locked_axes":
                    locked_axes,

                "start_positions":
                    start_positions,

                "final_positions":
                    final_positions,

                "zero_total_steps":
                    zero_total_steps,

                "json_total_steps":
                    total_steps,
            }
        }

        print(result["message"])
        save_result_json(result)
        return result


    # ========================================================
    # Stop 확인 중 축 Error
    # ========================================================
    except StopAxisError as e:

        result = {
            "status": "error",
            "message": str(e),
            "data": {
                "direction": "zero",
                "reason": "stop_axis_error"
            }
        }       
        print(result["message"])
        save_result_json(result)
        return result


    # ========================================================
    # 일반적인 실행 조건 실패
    # ========================================================
    except (
        ValueError,
        KeyError,
        TimeoutError,
        ConnectionError
    ) as e:

        result = {
            "status": "fail",
            "message": str(e),
            "data": {
                "direction": "zero"
            }
        }

        print(result["message"])
        save_result_json(result)
        return result


    # ========================================================
    # ADS 통신 에러
    # zero가 이미 시작되었다면 반드시 Stop 시도
    # ========================================================
    except pyads.ADSError as e:

        successful_stop_plcs = []
        stop_failed_plcs = {}
        stop_wait_error = None


        if opened_plcs and zero_started:

            stop_result = await request_all_plcs_stop(
                plc_connections,
                opened_plcs
            )

            stop_failed_plcs = (
                stop_result["failed_plcs"]
            )

            successful_stop_plcs = [
                plc_name

                for plc_name
                in stop_result["requested_plcs"]

                if plc_name
                not in stop_failed_plcs
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
                    stop_wait_error = str(
                        stop_wait_exc
                    )


        result = {
            "status": "error",
            "message": (
                "PLC 통신 또는 ADS 에러가 "
                "발생했습니다: "
                f"{e}"
            ),
            "data": {
                "direction": "zero",

                "stop_success_plcs":
                    successful_stop_plcs,

                "stop_failed_plcs":
                    stop_failed_plcs,

                "stop_wait_error":
                    stop_wait_error,
            }
        }
        print(result["message"])
        save_result_json(result)
        return result


    # ========================================================
    # 예상하지 못한 에러
    # zero 시작 이후라면 전체 Stop
    # ========================================================
    except Exception as e:

        successful_stop_plcs = []
        stop_failed_plcs = {}
        stop_wait_error = None


        if opened_plcs and zero_started:

            stop_result = await request_all_plcs_stop(
                plc_connections,
                opened_plcs
            )

            stop_failed_plcs = (
                stop_result["failed_plcs"]
            )

            successful_stop_plcs = [
                plc_name

                for plc_name
                in stop_result["requested_plcs"]

                if plc_name
                not in stop_failed_plcs
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

                    stop_wait_error = str(
                        stop_wait_exc
                    )


        result = {
            "status": "error",
            "message": (
                "0도 이동 중 예상하지 못한 "
                "에러가 발생했습니다: "
                f"{e}"
            ),
            "data": {
                "direction": "zero",

                "stop_success_plcs":
                    successful_stop_plcs,

                "stop_failed_plcs":
                    stop_failed_plcs,

                "stop_wait_error":
                    stop_wait_error,
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
