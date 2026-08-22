# 만약 main()의 마지막 step과 각도가 틀릴 경우 작동 안됨
# rotate_one을 실행후 reverse_main()을 실행한다면 만약 각도가 틀리게 되면 작동 안함
# lock 가 되어 있으면 위치 검사에서 제외

# 정말 특이한 케이스.
# 1. 기존 JSON 경로로 main()을 끝까지 정상 완료한다.
# 2. 모든 포지셔너가 기존 JSON의 마지막 Step 위치에 도착한 상태에서, 특정 포지셔너가 고장 난다.
# 3. 고장 난 포지셔너는 positioner_lock()으로 Lock한다.
# 4. 고장 난 포지셔너는 움직일 수 없으므로, 그 포지셔너를 고정한 상태에서 나머지 포지셔너만 안전하게 1단계까지 복귀할 수 있는 새로운 경로를 시뮬레이션한다.
# 5. 이때 새 시뮬레이션의 시작 위치는 기존 main()이 완료된 마지막 Step 위치를 기준으로 해야 한다.
# 6. 새 시뮬레이션 결과를 새로운 JSON 경로로 만든다.
# 7. reverse_main()을 실행하면 현재 Lock된 포지셔너는 motion_axes에서 제외되므로 실제 역방향 구동에서도 제외된다.
# 8. 대신 Lock되지 않은 나머지 축은 reverse_main() 시작 전에 현재 실제 위치와 새 JSON의 마지막 Step 위치가 일치하는지 검사한다. 허용오차는 현재 0.2도다.
# 9. 따라서 새 JSON의 마지막 Step이 기존 main() 완료 당시 정상 축들의 위치와 맞아야 reverse_main()이 실행될 수 있다.

import time
import asyncio
import pyads

from kspec_0_function import *

async def reverse_main(plc_connections):

    print("전체 포지셔너 역방향 구동 시작")

    try:
        original_axis_points, original_total_steps = read_json(ALPHA_FILE, BETA_FILE)

        axis_points, total_steps = reverse_step_to_firststep(original_axis_points, max_points=3500)

    except FileNotFoundError as e:
        result = {
            "status": "fail",
            "message": f"JSON 파일을 찾을 수 없습니다: {e.filename}",
            "data": {
                "missing_file": e.filename
            }
        }

        print(result["message"])
        save_result_json(result)
        return result

    except KeyError as e:
        result = {
            "status": "fail",
            "message": (
                f"JSON 파일 내부 구조가 예상과 다릅니다. "
                f"Key: {e}"
            ),
            "data": {
                "missing_key": str(e)
            }
        }
        print(result["message"])
        save_result_json(result)
        return result

    except ValueError as e:
        result = {
            "status": "fail",
            "message": (
                f"JSON 데이터 값 또는 길이에 문제가 있습니다: {e}"
            ),
            "data": {
                "error": str(e)
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

    
    try:
        
        # ==========================
        # 이전 Stop 기록 존재 여부 확인
        # Stop 기록이 남아있으면 reverse_main() 실행 금지. 즉 reverse_from_stop 에서 실행
        # ==========================
        stopped_valid_results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    plc_connections[plc_name].read_by_name,
                    "GVL.gStoppedValid",
                    pyads.PLCTYPE_BOOL
                )
                for plc_name in opened_plcs
            ]
        )

        stopped_valid_plcs = [
            plc_name
            for plc_name, stopped_valid
            in zip(opened_plcs, stopped_valid_results)
            if stopped_valid
        ]

        if stopped_valid_plcs:

            result = {
                "status": "fail",
                "message": (
                    "이전 Stop 기록이 남아 있어 역방향 구동을 "
                    "시작할 수 없습니다. "
                    "reverse_from_stop_step을 실행후 main()실행 후 완료된 다음 실행해주세요."
                ),
                "data": {
                    "stopped_valid_plcs": stopped_valid_plcs
                }
            }

            print(result["message"])
            save_result_json(result)
            return result



        # ==========================
        # PLC1, PLC2 잠금 상태 동시 확인
        # 반환되는 축 번호는 global_axis
        # ==========================
        lock_results = await asyncio.gather(
            read_one_plc_lock_state("PLC1", plc_connections["PLC1"]),
            read_one_plc_lock_state("PLC2", plc_connections["PLC2"]),
        )

        locked_axes = []
        motion_axes = []

        for lock_result in lock_results:
            locked_axes.extend(lock_result["locked_axes"])
            motion_axes.extend(lock_result["motion_axes"])

        locked_axes = sorted(locked_axes)
        motion_axes = sorted(motion_axes)

        print(f"잠금 축: {locked_axes}")
        print(f"구동 가능 축: {motion_axes}")

        if not motion_axes:
            result = {
                "status": "fail",
                "message": (
                    "모든 PLC의 모든 축이 잠겨 있습니다. "
                    "따라서 역방향 구동을 시작할 수 없습니다."
                ),
                "data": {
                    "locked_axes": locked_axes,
                    "motion_axes": []
                }
            }

            print(result["message"])
            save_result_json(result)
            return result



        # ==========================
        # global_axis별 경로 정보 생성
        # ==========================
        global_axis_routes = build_global_axis_routes()


        # ==========================
        # 이번 reverse_main()에서 실제로 움직일 축을 PLC1, PLC2별로 분리
        # ==========================
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
            plc_name = route["plc_name"]

            plc_motion_routes[plc_name].append(route)

        print(
            "PLC1 구동 전역축:",
            [
                route["global_axis"]
                for route in plc_motion_routes["PLC1"]
            ]
        )
        print(
            "PLC2 구동 전역축:",
            [
                route["global_axis"]
                for route in plc_motion_routes["PLC2"]
            ]
        )

        # ===========================
        # reverse_main() 시작 위치 확인
        # 현재 실제 위치가 원본 JSON 마지막 Step 위치인지 검사
        # main()의 마지막  step위치인지 확인
        # lock 된 축은 검사대상에서 제외
        # ===========================
        positioner_tolerance = 0.2

        position_check_targets = [
            (plc_name, route)
            for plc_name, routes in plc_motion_routes.items()
            for route in routes
        ]

        actual_positions = await asyncio.gather(
            *[
                asyncio.to_thread(
                    plc_connections[plc_name].read_by_name,
                    f"GVL.gAxisState[{route['local_axis']}].ActPos",
                    pyads.PLCTYPE_LREAL
                )
                for plc_name, route in position_check_targets
            ]
        )

        invalid_start_axes = []

        for (plc_name, route), actual_position in zip(position_check_targets, actual_positions):
            global_axis = route["global_axis"]

            expected_position = float(original_axis_points[global_axis][-1])

            actual_position = float(actual_position)


            if abs(actual_position - expected_position) > positioner_tolerance:
                invalid_start_axes.append(
                    {
                        "plc_name": plc_name,
                        "global_axis": global_axis,
                        "local_axis": route["local_axis"],
                        "positioner": route["positioner"],
                        "motor": route["motor"],
                        "expected_position": expected_position,
                        "actual_position": actual_position,
                        "difference": abs(actual_position - expected_position),
                    }
                )

        if invalid_start_axes:
            print("역방향 시작 위치가 맞지 않는 축이 있습니다:")

            for axis_info in invalid_start_axes:
                motor_name = (
                    "α"
                    if axis_info["motor"] == "alpha"
                    else "β"
                )

                print(
                    f"- {axis_info['positioner']}-{motor_name} | "
                    f"현재 위치: {axis_info['actual_position']:.3f}도 | "
                    f"필요한 위치: {axis_info['expected_position']:.3f}도 | "
                    f"차이: {axis_info['difference']:.3f}도"
                )

            result = {
                "status": "fail",
                "message": (
                    "현재 위치가 원본 JSON 마지막 Step 위치와 "
                    "일치하지 않아 역방향 구동을 시작할 수 없습니다. "
                ),
                "data": {
                    "position_tolerance": positioner_tolerance,
                    "invalid_start_axes": invalid_start_axes,
                }
            }

            print(result["message"])
            save_result_json(result)
            return result

        print("전체 포지셔너 마지막 단계 위치 확인 완료")






        # ==========================
        # PLC1, PLC2에 역방향 모드 설정 및 이전 Stop 기록 삭제하지 않음
        # ==========================
        await asyncio.gather(
            set_reverse_mode(
                "PLC1",
                plc_connections["PLC1"]
            ),
            set_reverse_mode(
                "PLC2",
                plc_connections["PLC2"]
            )
        )

        print("PLC1, PLC2 역방향 모드 설정 완료")




        # ==========================
        # PLC1, PLC2 모션 명령 플래그 동시 초기화
        # StartSpline = False, Active = False
        # ==========================
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
        print("PLC1, PLC2 모션 플래그 초기화 완료")

        # PLC가 초기화 값을 처리할 잠깐의 대기 시간
        await asyncio.sleep(0.1)




        # ===========================
        # PLC1, PLC2의 구동 가능 축 Power 동시 ON
        # 잠긴 축은 plc_motion_routes에 없음으로 제외됨
        # ===========================
        await asyncio.gather(
            power_on_one_plc(
                "PLC1",
                plc_connections["PLC1"],
                plc_motion_routes["PLC1"]
            ),

            power_on_one_plc(
                "PLC2",
                plc_connections["PLC2"],
                plc_motion_routes["PLC2"]
            )
        )

        print("PLC1, PLC2 구동 축 Power ON 완료")

        # Power 상태가 PLC에 적용될 시간
        await asyncio.sleep(1.0)



        # ==========================
        # 실제 Power ON 상태 확인
        # ==========================
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
                f"Power ON에 실패한 축이 있습니다: "
                f"{not_powered_axes}"
            )

        print("전체 구동 대상 축 Powered = True 확인 완료")



        # ==========================
        # PLC1, PLC2에 담당 축 경로 동시 전송
        # ==========================
        await asyncio.gather(
            send_path_to_one_plc(
                "PLC1",
                plc_connections["PLC1"],
                plc_motion_routes["PLC1"],
                axis_points,
                total_steps
            ),
            send_path_to_one_plc(
                "PLC2",
                plc_connections["PLC2"],
                plc_motion_routes["PLC2"],
                axis_points,
                total_steps
            )
        )

        print("PLC1, PLC2 경로 데이터 전송 완료")


        await asyncio.sleep(0.5)



        # ==========================================
        # PLC1, PLC2 구동 축 Active 동시 설정
        # 잠긴 축은 routes에 없으므로 제외됨
        # ==========================================
        await asyncio.gather(
            activate_one_plc(
                "PLC1",
                plc_connections["PLC1"],
                plc_motion_routes["PLC1"]
            ),
            activate_one_plc(
                "PLC2",
                plc_connections["PLC2"],
                plc_motion_routes["PLC2"]
            )
        )

        print("PLC1, PLC2 구동 축 Active 설정 완료")


        
        # ==========================================
        # 실제로 움직일 축이 있는 PLC만 시작 대상으로 선택
        # ==========================================
        prepared_plcs = [
            plc_name
            for plc_name, routes in plc_motion_routes.items()
            if routes
        ]

        if not prepared_plcs:
            raise RuntimeError("구동 준비가 완료된 PLC가 없습니다.")

        # ==========================================
        # Step 동기화 초기값 설정
        # 첫 번째 step만 실행 가능하도록 모든 구동 PLC에
        # gAllowedStep = 1을 전달한다.
        # ==========================================
        await set_allowed_step_all_plcs(
            plc_connections,
            prepared_plcs,
            1
        )

        # Python이 현재까지 허가한 마지막 step
        last_allowed_step = 1

        print(
            "Step 동기화 초기화 완료: "
            "모든 구동 PLC에 1번 step까지 허가"
        )


        # ==========================================
        # StartSpline 전 각 PLC의 MotionSequence 저장
        # 이후 값이 변하면 새 모션 명령을 접수한 것으로 판단
        # ==========================================
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
            f"구동 전 MotionSequence: "
            f"{motion_sequence_before}"
        )





        # ==========================================
        # 준비된 PLC에 StartSpline 동시 전송
        # 실제 모션 시작 요청
        # ==========================================
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
            f"전체 PLC StartSpline 전송 완료: "
            f"{started_command_plcs}"
        )

        # ==========================================
        # 각 PLC가 새 모션 명령을 접수했는지
        # gMotionSequence 변화로 동시 확인
        # ==========================================
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

        # 구동 대상 축 중 하나라도 출발하지 못한 PLC
        not_started_plcs = sorted(
            start_result["plc_name"]
            for start_result in start_results
            if not start_result["started"]
        )

        # 출발하지 못한 축과 에러 축의 상세 정보
        start_failure_details = [
            start_result
            for start_result in start_results
            if not start_result["started"]
        ]

        # 출발 실패 원인 중 실제 축 Error가 있었는지 확인
        start_failure_has_axis_error = any(
            start_result["reason"] == "axis_error"
            for start_result in start_failure_details
        )

        # ==========================================
        # PLC 한 대라도 정상 출발하지 못했다면
        # 연결된 모든 PLC에 정지 요청
        # ==========================================
        if not_started_plcs:

            stop_result = await request_all_plcs_stop(
                plc_connections,
                opened_plcs
            )

            if not stop_result["success"]:
                print(
                    f"Stop 명령 전송 실패 PLC: "
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
                    "일부 PLC의 구동 대상 축이 모두 출발하지 않아 "
                    "전체 PLC에 정지를 요청했습니다."
                ),
                "data": {
                    "started_plcs": started_plcs,
                    "not_started_plcs": not_started_plcs,
                    "start_failure_details": start_failure_details,
                    "motion_axes": motion_axes,
                    "locked_axes": locked_axes,
                    "total_steps": total_steps
                }
            }
            print(result["message"])
            save_result_json(result)
            return result

        print(
            f"전체 PLC의 모든 구동 대상 축 출발 확인 완료: "
            f"{started_plcs}"
        )



        # ==========================================
        # 스탭 간 이동 시간 초기화 되었을 시 작동
        # ==========================================
        step_wait_start_time = time.time()
        step_timeout = 300.0




        # ==========================================
        # 구동 중 상태 감시
        # ==========================================
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


                # 현재 완료 위치를 원본 JSON Step 번호로 변환
                if internal_completed_step == 0:
                    original_completed_step = original_total_steps
                else:
                    original_completed_step = (
                        original_total_steps
                        - internal_completed_step
                        + 1
                    )

                # 현재 목표 위치를 원본 JSON Step 번호로 변환
                original_target_step = (
                    original_total_steps
                    - internal_allowed_step
                    + 1
                )

                step_status_parts.append(
                    (
                        f"{snapshot['plc_name']}:"
                        f"{original_completed_step}/{original_total_steps}"
                        f"(Target Step {original_target_step})"
                    )
                )


            print(
                "Step | "
                + "  ".join(step_status_parts)
                + "\n상태 | "
                + "  ".join(status_parts)
            )



            # ==============================
            # 구동 도중 축 Error 확인
            # ==============================
            error_axes = [
                axis_state
                for axis_state in all_axis_states
                if axis_state["error"]
            ]

            if error_axes:

                stop_result = await request_all_plcs_stop(
                    plc_connections,
                    opened_plcs
                )

                if not stop_result["success"]:
                    print(
                        f"Stop 명령 전송 실패 PLC: "
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

                print()

                result = {
                    "status": "error",
                    "message": (
                        "역방향 구동 중 축 에러가 발생하여 "
                        "전체 PLC에 정지를 요청했습니다."
                    ),
                    "data": {
                        "direction": "reverse",
                        "error_axes": error_axes,
                        "total_steps": total_steps,
                        "motion_axes": motion_axes,
                        "locked_axes": locked_axes,
                        "completed_steps": completed_steps,
                        "allowed_steps": allowed_steps
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result

            # ==============================
            # 외부 stop.py 실행 확인
            # ==============================
            stop_detected_plcs = sorted(
                snapshot["plc_name"]
                for snapshot in snapshot_results
                if (snapshot["stop_busy"] or snapshot["stop_occurred"])
            )

            if stop_detected_plcs:

                # 한 PLC에서 외부 Stop이 감지되면
                # 연결된 모든 PLC에 Stop을 다시 전송
                stop_result = await request_all_plcs_stop(
                    plc_connections,
                    opened_plcs
                )

                if not stop_result["success"]:
                    print(
                        f"Stop 명령 전송 실패 PLC: "
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
                    snapshot["plc_name"]: snapshot["stopped_target_step"]
                    for snapshot in stopped_snapshot_results
                }
                   

                stopped_axis_states = [
                    axis_state
                    for snapshot in stopped_snapshot_results
                    for axis_state in snapshot["axis_states"]
                ]

                stopped_positions = {
                    str(axis_state["global_axis"]): {
                        "plc_name": (
                            axis_state["plc_name"]
                        ),
                        "local_axis": (
                            axis_state["local_axis"]
                        ),
                        "positioner": (
                            axis_state["positioner"]
                        ),
                        "motor": axis_state["motor"],
                        "actual_position": (
                            axis_state["actual_position"]
                        ),
                        "busy": axis_state["busy"],
                        "error": axis_state["error"],
                    }
                    for axis_state in stopped_axis_states
                }

                print()

                

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
                        "사용자의 Stop 요청으로 전체 PLC의 "
                        "역방향 구동이 중간에 중단되었습니다."
                    )

                result = {
                    "status": stop_status,
                    "message": stop_message,
                    "data": {
                        "direction": "reverse",
                        "stop_detected_plcs": (
                            stop_detected_plcs
                        ),
                        "stop_success_plcs": successful_stop_plcs,
                        "stop_failed_plcs": stop_result["failed_plcs"],
                        "total_steps": total_steps,
                        "motion_axes": motion_axes,
                        "locked_axes": locked_axes,
                        "completed_steps": completed_steps,
                        "allowed_steps": allowed_steps,
                        "stopped_target_steps": stopped_target_steps,
                        "stopped_positions": (
                            stopped_positions
                        )
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result

            # ==============================
            # Step 동기화 검사
            # PLC가 Python이 허가한 step보다 앞서갔다면
            # PLC 쪽 동기화 대기 로직이 정상적으로 적용되지 않은 것이다.
            # ==============================
            sync_overrun_plcs = [
                snapshot["plc_name"]
                for snapshot in snapshot_results
                if snapshot["completed_step"] > last_allowed_step
            ]

            if sync_overrun_plcs:

                stop_result = await request_all_plcs_stop(
                        plc_connections,
                        opened_plcs
                    )

                if not stop_result["success"]:
                    print(
                        f"Stop 명령 전송 실패 PLC: "
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

                print()

                result = {
                    "status": "error",
                    "message": (
                        "PLC가 Python에서 허가한 step보다 먼저 진행했습니다. "
                        "PLC step 동기화 대기 로직을 확인해야 합니다."
                    ),
                    "data": {
                        "direction": "reverse",
                        "sync_overrun_plcs": sorted(sync_overrun_plcs),
                        "last_allowed_step": last_allowed_step,
                        "completed_steps": completed_steps,
                        "allowed_steps": allowed_steps,
                        "total_steps": total_steps,
                        "motion_axes": motion_axes,
                        "locked_axes": locked_axes
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result

            # =================================
            # Step Timeout 검사
            # =================================
            if (last_allowed_step <= total_steps and time.time() - step_wait_start_time > step_timeout):

                timeout_plcs = [
                    snapshot["plc_name"]
                    for snapshot in snapshot_results if snapshot["completed_step"] < last_allowed_step
                ]

                stop_result = await request_all_plcs_stop(
                        plc_connections,
                        opened_plcs
                    )

                if not stop_result["success"]:
                    print(
                        f"Stop 명령 전송 실패 PLC: "
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
                        f"Step {last_allowed_step - 1}에서 "
                        f"Step {last_allowed_step}로 이동 중 "
                        f"{step_timeout}초 동안 완료되지 않아 "
                        f"전체 PLC를 정지했습니다."
                    ),
                    "data": {
                        "reason": "step_timeout",
                        "timeout_plcs": timeout_plcs,
                        "from_step": last_allowed_step - 1,
                        "target_step": last_allowed_step,
                        "completed_steps": completed_steps,
                        "allowed_step": allowed_steps
                    }
                }
                print(result["message"])
                save_result_json(result)
                return result

            # 현재 허가된 step을 모든 구동 PLC가 완료한 경우에만
            # 다음 step을 모든 구동 PLC에 동시에 허가한다.
            if last_allowed_step < total_steps:

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

            # ==============================
            # 최종 step 완료 확인
            # 중간 step의 동기화 대기 중에는 모든 축 Busy=False가
            # 될 수 있으므로 Busy만으로 전체 완료를 판정하지 않는다.
            # ==============================
            all_plcs_completed_final_step = all(
                snapshot["completed_step"] >= total_steps
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






        # ==========================================
        # 정상 완료 결과
        # ==========================================
        final_positions = {
            str(axis_state["global_axis"]): {
                "plc_name": axis_state["plc_name"],
                "local_axis": axis_state["local_axis"],
                "positioner": axis_state["positioner"],
                "motor": axis_state["motor"],
                "actual_position": (
                    axis_state["actual_position"]
                ),
                "busy": axis_state["busy"],
                "error": axis_state["error"],
            }
            for axis_state in all_axis_states
        }

        result = {
            "status": "success",
            "message": (
                "PLC1과 PLC2의 모든 구동 대상 포지셔너가 "
                "1단계까지 역방향 구동을 완료했습니다."
            ),
            "data": {
                "direction": "reverse",
                "total_steps": total_steps,
                "active_plcs": prepared_plcs,
                "motion_axes": motion_axes,
                "locked_axes": locked_axes,
                "completed_steps": completed_steps,
                "allowed_steps": allowed_steps,
                "final_positions": final_positions
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
                "reason": "stop_axis_error"
            }
        }
        print(result["message"])
        save_result_json(result)
        return result




    
    except pyads.ADSError as e:
        successful_stop_plcs = []
        stop_failed_plcs = {}
        stop_wait_error = None

        if opened_plcs:
            stop_result = await request_all_plcs_stop(
                plc_connections,
                opened_plcs
            )

            stop_failed_plcs = stop_result["failed_plcs"]

            successful_stop_plcs = [
                plc_name
                for plc_name in stop_result["requested_plcs"]
                if plc_name not in stop_failed_plcs
            ]

            if stop_failed_plcs:
                print(
                    f"Stop 명령 전송 실패 PLC: "
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

                    print(
                        f"Stop 완료 확인 중 에러: "
                        f"{stop_wait_exc}"
                    )

        result = {
            "status": "error",
            "message": (
                f"PLC 통신 또는 ADS 에러가 발생했습니다: "
                f"{e}"
            ),
            "data": {
                "stop_success_plcs": successful_stop_plcs,
                "stop_failed_plcs": stop_failed_plcs,
                "stop_wait_error": stop_wait_error
            }
        }
        print(result["message"])
        save_result_json(result)
        return result




    
    except Exception as e:
        successful_stop_plcs = []
        stop_failed_plcs = {}
        stop_wait_error = None

        if opened_plcs:
            stop_result = await request_all_plcs_stop(
                plc_connections,
                opened_plcs
            )

            stop_failed_plcs = stop_result["failed_plcs"]

            successful_stop_plcs = [
                plc_name
                for plc_name in stop_result["requested_plcs"]
                if plc_name not in stop_failed_plcs
            ]

            if stop_failed_plcs:
                print(
                    f"Stop 명령 전송 실패 PLC: "
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

                    print(
                        f"Stop 완료 확인 중 에러: "
                        f"{stop_wait_exc}"
                    )

        result = {
            "status": "error",
            "message": (
                f"예상하지 못한 에러가 발생했습니다: "
                f"{e}"
            ),
            "data": {
                "stop_success_plcs": successful_stop_plcs,
                "stop_failed_plcs": stop_failed_plcs,
                "stop_wait_error": stop_wait_error
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

            





