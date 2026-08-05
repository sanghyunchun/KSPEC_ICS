import time
import json
import pyads
import os
from datetime import datetime


AMS_NET_ID = "172.18.233.11.1.1" 
AMS_PORT = 851

VELOCITY = 10.0
ACC = 200.0
DEC = 200.0


ALPHA_FILE = "alpha_tile1001.json"
BETA_FILE = "beta_tile1001.json"

POSITIONER_AXIS_MAP = {
    "A1": {"alpha": 1, "beta": 2},
    "A2": {"alpha": 3, "beta": 4},
    "A3": {"alpha": 5, "beta": 6},
    "A4": {"alpha": 7, "beta": 8},
    "A5": {"alpha": 9, "beta": 10},
}

##
def read_json(alpha_filename: str, beta_filename: str):

    with open(alpha_filename, 'r', encoding='utf-8') as f:
        alpha_data = json.load(f)
    with open(beta_filename, 'r', encoding='utf-8') as f:
        beta_data = json.load(f)

    total_steps = len(alpha_data["step"])


    if total_steps > 3500:
        raise ValueError(f"json step 개수가 파이썬에서 설정한 step 이상으로 초과했습니다: {total_steps}")

    if len(beta_data["step"]) != total_steps:
        raise ValueError(
            f"alpha/beta step 개수가 다릅니다. "
            f"alpha={total_steps}, beta={len(beta_data['step'])}"
        )

    axis_points = {}

    for positioner, motors in POSITIONER_AXIS_MAP.items():
        if positioner not in alpha_data:
            raise KeyError(f"alpha JSON에 {positioner} 데이터가 없습니다.")

        if positioner not in beta_data:
            raise KeyError(f"beta JSON에 {positioner} 데이터가 없습니다.")

        if len(alpha_data[positioner]) != total_steps:
            raise ValueError(
                f"alpha {positioner} 데이터 길이가 step 개수와 다릅니다. "
                f"{len(alpha_data[positioner])} != {total_steps}"
            )

        if len(beta_data[positioner]) != total_steps:
            raise ValueError(
                f"beta {positioner} 데이터 길이가 step 개수와 다릅니다. "
                f"{len(beta_data[positioner])} != {total_steps}"
            )

        axis_points[motors["alpha"]] = alpha_data[positioner]
        axis_points[motors["beta"]] = beta_data[positioner]

    return axis_points, total_steps


##
def clear_motion_flags(plc):
    for motors in POSITIONER_AXIS_MAP.values():
        for axis in motors.values():
            plc.write_by_name(
                f"GVL.gAxisCmd[{axis}].StartSpline", 
                False, 
                pyads.PLCTYPE_BOOL
            )
            
            plc.write_by_name(
                f"GVL.gAxisCmd[{axis}].Active", 
                False, 
                pyads.PLCTYPE_BOOL
            )


##
def read_axis_lock_state(plc):
    """
    PLC의 gAxisLocked[1...10]을 읽어서
    잠긴 축과 잠기지 않은 축을 나누어 반환한다.
    """

    locked_axes = []
    unlocked_axes = []

    for motors in POSITIONER_AXIS_MAP.values():
        for axis in motors.values():

            is_locked = plc.read_by_name(
                f"GVL.gAxisLocked[{axis}]",
                pyads.PLCTYPE_BOOL
            )

            if is_locked:
                locked_axes.append(axis)
            else:
                unlocked_axes.append(axis)

    return sorted(locked_axes), sorted(unlocked_axes)


# =======================================================================
# 1
# rotate_one()
# 하나의 positioner(A1, B1, ...)에서 motor(alpha or beta)중에 하나 돌리고 싶을때
# region 
def get_axis_number(positioner: str, motor: str) -> int:
    """
    예:
    A1 alpha -> 1
    A1 beta  -> 2
    A2 alpha -> 3
    A2 beta  -> 4
    """
    positioner = positioner.upper()
    motor = motor.lower()
    return POSITIONER_AXIS_MAP[positioner][motor]

def rotate_one(
    positioner: str,
    motor: str, 
    angle: float,
    velocity: float = VELOCITY,
    acc: float = ACC,
    dec: float = DEC,
    timeout: float = 30.0,
):
    
    ### retion for simulation 
    target_axis = get_axis_number(positioner, motor)

    return {
        "status": "success",
        "message": f"{positioner.upper()} {motor.lower()} rotated successfully.",
        "data": {
            "positioner": positioner.upper(),
            "motor": motor.lower(),
            "axis": target_axis,
            "current_position_before_move": 20.0,
            "target_angle": angle,
            "actual_position": angle,
        }
    }
    ### end region for simulation


    # try:
    #     target_axis = get_axis_number(positioner, motor)

    # except Exception as e:
    #     return {
    #         "status": "fail",
    #         "message": f"positioner 또는 motor 입력이 잘못되었습니다: {e}",
    #     }

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    
    # try:
    #     plc.open()

    #     is_locked = plc.read_by_name(
    #         f"GVL.gAxisLocked[{target_axis}]",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     if is_locked:
    #         return {
    #             "status": "fail",
    #             "message": (
    #                 f"{positioner.upper()} {motor.lower()} 축은 "
    #                 "현재 잠금 상태이므로 움직일 수 없습니다."
    #             ),
    #             "data": {
    #                 "positioner": positioner.upper(),
    #                 "motor": motor.lower(),
    #                 "axis": target_axis,
    #                 "locked": True
    #             }
    #         }

   

    #     # -------------------------------------------------
    #     # 이전 명령 흔적 초기화
    #     # -------------------------------------------------
    #     clear_motion_flags(plc)
    #     time.sleep(0.1)

    #     # -------------------------------------------------
    #     # 선택 축 Power ON
    #     # -------------------------------------------------
    #     plc.write_by_name(
    #         f"GVL.gAxisCmd[{target_axis}].Power",
    #         True,
    #         pyads.PLCTYPE_BOOL
    #     )

    #     time.sleep(0.5)

    #     # -------------------------------------------------
    #     # 선택 축에 1 step짜리 목표 위치 전송
    #     # -------------------------------------------------
    #     prefix = f"GVL.gAxisCmd[{target_axis}]"

    #     plc.write_by_name(f"{prefix}.TotalPoints", 1, pyads.PLCTYPE_INT)
    #     plc.write_by_name(f"{prefix}.Velocity", velocity, pyads.PLCTYPE_LREAL)
    #     plc.write_by_name(f"{prefix}.Acc", acc, pyads.PLCTYPE_LREAL)
    #     plc.write_by_name(f"{prefix}.Dec", dec, pyads.PLCTYPE_LREAL)

    #     # --------------------------------------------------
    #     # 이동 전 현재 위치 읽기
    #     # --------------------------------------------------
    #     current_pos = plc.read_by_name(
    #         f"GVL.gAxisState[{target_axis}].ActPos",
    #         pyads.PLCTYPE_LREAL
    #     )

    
    #     target_pos_array = (pyads.PLCTYPE_LREAL * 3500)()
    #     target_pos_array[0] = float(angle)   # 절대 각도임 

    #     plc.write_by_name(
    #         f"{prefix}.TargetPos",
    #         target_pos_array,
    #         pyads.PLCTYPE_LREAL * 3500
    #     )

        # -------------------------------------------------
        # 5. Active / StartSpline 설정
        # Active TRUE인 축만 움직임
        # -------------------------------------------------
    #     plc.write_by_name(
    #         f"{prefix}.Active",
    #         True,
    #         pyads.PLCTYPE_BOOL
    #     )

    #     plc.write_by_name(
    #         f"{prefix}.StartSpline",
    #         True,
    #         pyads.PLCTYPE_BOOL
    #     )

    #     # -------------------------------------------------
    #     # PLC가 Busy로 들어가는지 확인
    #     # -------------------------------------------------
    #     plc_started = False
    #     start_time = time.time()

    #     while time.time() - start_time < 2.0:
    #         is_busy = plc.read_by_name(
    #             f"GVL.gAxisState[{target_axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         if is_busy:
    #             plc_started = True
    #             break

    #         time.sleep(0.05)

    #     if not plc_started:
    #         return {
    #             "status": "fail",
    #             "message": f"{positioner.upper()} {motor.lower()} 축이 시작되지 않았습니다.",
    #             "data": {
    #                 "positioner": positioner.upper(),
    #                 "motor": motor.lower(),
    #                 "axis": target_axis,
    #                 "target_angle": angle,
    #             }
    #         }

    #     # -------------------------------------------------
    #     # 이동 완료까지 대기
    #     # -------------------------------------------------
    #     start_time = time.time()

    #     while True:
    #         is_busy = plc.read_by_name(
    #             f"GVL.gAxisState[{target_axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         is_error = plc.read_by_name(
    #             f"GVL.gAxisState[{target_axis}].Error",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         act_pos = plc.read_by_name(
    #             f"GVL.gAxisState[{target_axis}].ActPos",
    #             pyads.PLCTYPE_LREAL
    #         )

    #         if is_error:
    #             return {
    #                 "status": "error",
    #                 "message": f"{positioner.upper()} {motor.lower()} 이동 중 PLC 축 에러가 발생했습니다.",
    #                 "data": {
    #                     "positioner": positioner.upper(),
    #                     "motor": motor.lower(),
    #                     "axis": target_axis,
    #                     "target_angle": angle,
    #                     "actual_position": act_pos,
    #                 }
    #             }

    #         if not is_busy:
    #             break

    #         if time.time() - start_time > timeout:
    #             return {
    #                 "status": "fail",
    #                 "message": f"{positioner.upper()} {motor.lower()} 이동 시간이 timeout을 초과했습니다.",
    #                 "data": {
    #                     "positioner": positioner.upper(),
    #                     "motor": motor.lower(),
    #                     "axis": target_axis,
    #                     "target_angle": angle,
    #                     "actual_position": act_pos,
    #                     "timeout": timeout,
    #                 }
    #             }

    #         time.sleep(0.1)

    #     # -------------------------------------------------
    #     # 최종 위치 읽기
    #     # -------------------------------------------------
    #     final_pos = plc.read_by_name(
    #         f"GVL.gAxisState[{target_axis}].ActPos",
    #         pyads.PLCTYPE_LREAL
    #     )

    #     return {
    #         "status": "success",
    #         "message": f"{positioner.upper()} {motor.lower()} rotated successfully.",
    #         "data": {
    #             "positioner": positioner.upper(),
    #             "motor": motor.lower(),
    #             "axis": target_axis,
    #             "current_position_before_move": current_pos,
    #             "target_angle": angle,
    #             "actual_position": final_pos,
    #         }
    #     }

    # except pyads.ADSError as e:
    #     return {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #     }

    # except Exception as e:
    #     return {
    #         "status": "error",
    #         "message": f"예상하지 못한 에러가 발생했습니다: {e}",
    #     }

    # finally:
    #     try:
    #         clear_motion_flags(plc)
    #     except Exception:
    #         pass

    #     try:
    #         plc.close()
    #     except Exception:
    #         pass

# endregion 



# =======================================================================
# 2
# show_status()
# show_status용 전체 코드
# 포지셔너 하나의 alpha, beta의 싱태를 보여주는 것
# region  
def show_status(axis: str):
    
    ## region for simulation
    positioner = axis.upper()
    alpha_axis = POSITIONER_AXIS_MAP[positioner]["alpha"]
    beta_axis = POSITIONER_AXIS_MAP[positioner]["beta"]

    return {
        "status": "success",
        "message": f"Positioner {positioner} status. Alpha arm angle is 30.0. Beta arm angle is 150.0.",
        "data": {
            "positioner": positioner,
            "alpha": {
                "axis": alpha_axis,
                "current_angle_degree": 30.0,
                "busy": False,
                "error": False,
                "locked": False,
            },
            "beta": {
                "axis": beta_axis,
                "current_angle_degree": 150.0,
                "busy": False,
                "error": False,
                "locked": False,
            }
        }
    }
    ## end region for simulation


    # try:
    #     positioner = axis.upper()
    #     alpha_axis = POSITIONER_AXIS_MAP[positioner]["alpha"]
    #     beta_axis = POSITIONER_AXIS_MAP[positioner]["beta"]

    # except KeyError:
    #     return {
    #         "status": "fail",
    #         "message": f"존재하지 않는 fiber/positioner입니다: {positioner}",
    #         "data": {
    #             "input_axis": axis
    #         }
    #     }

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    # try:
    #     plc.open()

    #     # -----------------------------
    #     # alpha 모터 상태 읽기
    #     # -----------------------------
    #     alpha_angle = plc.read_by_name(
    #         f"GVL.gAxisState[{alpha_axis}].ActPos",
    #         pyads.PLCTYPE_LREAL
    #     )

    #     alpha_busy = plc.read_by_name(
    #         f"GVL.gAxisState[{alpha_axis}].Busy",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     alpha_error = plc.read_by_name(
    #         f"GVL.gAxisState[{alpha_axis}].Error",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     # alpha_powered = plc.read_by_name(
    #     #     f"GVL.gAxisState[{alpha_axis}].Powered",
    #     #     pyads.PLCTYPE_BOOL
    #     # )

    #     # alpha_homed = plc.read_by_name(
    #     #     f"GVL.gAxisState[{alpha_axis}].Homed",
    #     #     pyads.PLCTYPE_BOOL
    #     # )

    #     alpha_locked = plc.read_by_name(
    #         f"GVL.gAxisLocked[{alpha_axis}]",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     # -----------------------------
    #     # beta 모터 상태 읽기
    #     # -----------------------------
    #     beta_angle = plc.read_by_name(
    #         f"GVL.gAxisState[{beta_axis}].ActPos",
    #         pyads.PLCTYPE_LREAL
    #     )

    #     beta_busy = plc.read_by_name(
    #         f"GVL.gAxisState[{beta_axis}].Busy",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     beta_error = plc.read_by_name(
    #         f"GVL.gAxisState[{beta_axis}].Error",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     # beta_powered = plc.read_by_name(
    #     #     f"GVL.gAxisState[{beta_axis}].Powered",
    #     #     pyads.PLCTYPE_BOOL
    #     # )

    #     # beta_homed = plc.read_by_name(
    #     #     f"GVL.gAxisState[{beta_axis}].Homed",
    #     #     pyads.PLCTYPE_BOOL
    #     # )

    #     beta_locked = plc.read_by_name(
    #         f"GVL.gAxisLocked[{beta_axis}]",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     return {
    #         "status": "success",
    #         "message": f"Positioner {positioner} status. Alpha arm angle is {alpha_angle}. Beta arm angle  is {beta_angle}.",
    #         "data": {
    #             "positioner": positioner,

    #             "alpha": {
    #                 "axis": alpha_axis,
    #                 "current_angle_degree": alpha_angle,
    #                 "busy": alpha_busy,
    #                 "error": alpha_error,
    #                 # "powered": alpha_powered,
    #                 # "homed": alpha_homed,
    #                 "locked": alpha_locked,
    #             },

    #             "beta": {
    #                 "axis": beta_axis,
    #                 "current_angle_degree": beta_angle,
    #                 "busy": beta_busy,
    #                 "error": beta_error,
    #                 # "powered": beta_powered,
    #                 # "homed": beta_homed,
    #                 "locked": beta_locked,
    #             }
    #         }
    #     }

    # except pyads.ADSError as e:
    #     return {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #     }

    # except Exception as e:
    #     return {
    #         "status": "error",
    #         "message": f"예상하지 못한 에러가 발생했습니다: {e}",
    #     }

    # finally:
    #     try:
    #         plc.close()
    #     except Exception:
    #         pass

#endregion



# =======================================================================
# 3
# 각 함수에 return 값으로 dictionary 형태의 반환값 json 파일로 만들기.
# 쉽게 말하자면, 다 돌아간후 모든 포지셔너의 각도 상태를 보는 것임.
# main(), reverse_main(), zero_main()
# region 
def save_result_json(result: dict, output_dir: str = None) -> str:
    """
    main() 실행 결과 dictionary를 JSON 파일로 저장하는 함수.
    output_dir을 따로 안 주면 alpha/beta JSON 파일이 있는 폴더에 저장한다.
    """

    # alpha JSON 파일이 있는 폴더 기준
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(ALPHA_FILE))

    os.makedirs(output_dir, exist_ok=True)

    # 파일명 예: main_result_20260702_153012.json
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_file = os.path.join(output_dir, f"result_{timestamp}.json")

    # 저장된 파일 경로도 결과 dictionary 안에 넣기
    result["result_file"] = output_file

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    return output_file
# endregion



# =======================================================================
# 4
# reverse_stop_to_first_step()
# path의 역순으로 보내는 함수 (n단계 -> 1단계)
# region 
def reverse_step_to_firststep(
    axis_points: dict,
    max_points: int = 3500
):
    """
    JSON에 들어 있는 1단계 ~ n단계 path를 역순으로 뒤집는다.

    예:
        [10, 20, 30, 50]
        ->
        [50, 30, 20, 10]
    """

    reverse_axis_points = {}

    for axis, points in axis_points.items():
        reverse_points = list(reversed(points))   #n단계 -> 1단계

        if len(reverse_points) > max_points:
            raise ValueError(
                f"{axis}번 축 reverse path 개수가 {max_points}개를 초과했습니다. "
                f"현재 개수: {len(reverse_points)}"
            )

        reverse_axis_points[axis] = reverse_points

    reverse_total_steps = len(next(iter(reverse_axis_points.values())))

    return reverse_axis_points, reverse_total_steps

#endregion



# -------------------------------------------------------------------------
# 5
# 회전중에 정지
# kspec_stop.py 실행
# 회전 중인 모든 모터를 중간에 감속 정지시키는 함수
# run stop.py를 실행하면 됨.
# region
def stop_all_positioner(
        dec : float = DEC,
        start_timeout: float = 2.0, #python이 정지 명령을 보낸 뒤, PLC가 그 명령을 실제로 받았는지 확인하기 위한 제한 시간
        timeout: float = 30.0,
):
    """
    현재 회전 중인 모든 축을 중간에 감속 정지시키는 함수.
    
    사용 방법:
        첫번째 python 실행창: main()또는 reverse_main()
        두번째 python 실행창: stop()
        
    주의:
        clear_motion_flags()는 사용하지 않는다. 
        -> clear_motion_flags()를 실행하면 python이 보낸 명령 스위치는 꺼지지만,
           PLC의 MC_MoveAbsolute는 이미 다음 명령을 받아서 실행중일 수 있음.
        실제 정지는 PLC의 MC_Stop이 담당한다.
    """

    ## region for simulation
    return {
        "status": "success",
        "message": "회전 중이던 모든 모터가 이동 중 정지했습니다.",
        "data": {
            "stop_deceleration": dec,
            "stopped_axes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "positions_before_stop": {
                "1": 47.30,
                "2": 10.16,
                "3": 350.50,
                "4": 131.28,
                "5": 295.57,
                "6": 113.28,
                "7": 299.45,
                "8": 93.13,
                "9": 85.44,
                "10": 81.02,
            },
            "stop_step_information": {
                "last_completed_step": 100,
                "target_step": 101,
                "total_points": 1335,
                "plc_state_at_stop": "STOP"
            },
            "final_positions": {
                "1": {"actual_position": 47.30, "busy": False, "error": False, "was_moving": True},
                "2": {"actual_position": 10.16, "busy": False, "error": False, "was_moving": True},
                "3": {"actual_position": 350.50, "busy": False, "error": False, "was_moving": True},
                "4": {"actual_position": 131.28, "busy": False, "error": False, "was_moving": True},
                "5": {"actual_position": 295.57, "busy": False, "error": False, "was_moving": True},
                "6": {"actual_position": 113.28, "busy": False, "error": False, "was_moving": True},
                "7": {"actual_position": 299.45, "busy": False, "error": False, "was_moving": True},
                "8": {"actual_position": 93.13, "busy": False, "error": False, "was_moving": True},
                "9": {"actual_position": 85.44, "busy": False, "error": False, "was_moving": True},
                "10": {"actual_position": 81.02, "busy": False, "error": False, "was_moving": True},
            }
        }
    }
    ## end region for simulation


    # print("전체 모터 정지 요청")

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    # try:
    #     plc.open()

    #     axis_set = set()

    #     for motors in POSITIONER_AXIS_MAP.values():
    #         for axis in motors.values():
    #             axis_set.add(axis)

    #     all_axes = sorted(axis_set)

    #     # ---------
    #     # 현재 실제로 움직이고 있는 축 확인
    #     # ---------
    #     moving_axes = []  #list
    #     positions_before_stop = {} #딕셔너리 : 키:값 

    #     for axis in all_axes:
    #         is_busy = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         current_pos = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].ActPos",
    #             pyads.PLCTYPE_LREAL
    #         )

    #         positions_before_stop[str(axis)] = current_pos

    #         if is_busy:
    #             moving_axes.append(axis)

        
    #     # 움직이는 축이 없으면 Stop을 보내지 않음
    #     if not moving_axes:
    #         result = {
    #             "status": "idle",
    #             "message": "현재 회전 중인 모터가 없습니다",
    #             "data": {
    #                 "moving_axes": [],
    #                 "positions": positions_before_stop
    #             }
    #         }

    #         save_result_json(result)
    #         return result
        
    #     print(f"정지 대상 축: {moving_axes}")

    #     # -----
    #     # PLC에 정지 감속도와 전체 정지 요청 전송
    #     # -----
    #     plc.write_by_name(
    #         "GVL.gStopDec",
    #         float(dec),
    #         pyads.PLCTYPE_LREAL
    #     )

    #     plc.write_by_name(
    #         "GVL.gStopAll",
    #         True,
    #         pyads.PLCTYPE_BOOL
    #     )

        # # ---
        # # PLC가 정지 요청을 접수했는지 확인
        # # ---
        # request_accepted = False
        # request_start_time = time.time()

        # while time.time() - request_start_time < start_timeout:
        #     stop_busy = plc.read_by_name(
        #         "GVL.gStopBusy",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     stop_occurred = plc.read_by_name(
        #         "GVL.gStopOccurred",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     if stop_busy or stop_occurred:
        #         request_accepted = True
        #         break

        #     time.sleep(0.02)

        # if not request_accepted:
        #     result = {
        #         "status": "fail",
        #         "message": "PLC가 전체 정지 요청을 접수하지 않았습니다.",
        #         "data": {
        #             "moving_axes": moving_axes,
        #             "start_timeout": start_timeout
        #         }
        #     }

        #     save_result_json(result)
        #     return result
        
        # print("PLC 정지 요청 접수 완료")


        # # -----
        # # 모든 정지 대상 축이 멈출 때까지 대기
        # # -----
        # stop_start_time = time.time()

        # while True:
        #     stop_busy = plc.read_by_name(
        #         "GVL.gStopBusy",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     stop_done = plc.read_by_name(
        #         "GVL.gStopDone",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     stop_occurred = plc.read_by_name(
        #         "GVL.gStopOccurred",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     error_axes = []
        #     status_str = "정지 중 |"

        #     for axis in moving_axes:
        #         is_error = plc.read_by_name(
        #             f"GVL.gAxisState[{axis}].Error",
        #             pyads.PLCTYPE_BOOL
        #         )

        #         act_pos = plc.read_by_name(
        #             f"GVL.gAxisState[{axis}].ActPos",
        #             pyads.PLCTYPE_LREAL
        #         )

        #         status_str += f"축{axis}:{act_pos:7.2f}"

        #         if is_error:
        #             error_axes.append({
        #                 "axis": axis,
        #                 "actual_position": act_pos
        #             })

        #     print(status_str, end="\r")

    #         if error_axes:
    #             result = {
    #                 "status": "error",
    #                 "message": "전체 정지 처리 중 축 에러가 발생했습니다.",
    #                 "data": {
    #                     "error_axes": error_axes,
    #                     "moving_axes": moving_axes
    #                 }
    #             }

    #             save_result_json(result)
    #             return result
            

    #         # 정리 완료 + MC_Stop 축 잠금 해제 완료
    #         if stop_done and stop_occurred and not stop_busy:
    #             break

    #         if time.time() - stop_start_time > timeout:
    #             result = {
    #                 "status": "fail",
    #                 "message": "전체 모터 정지 시간이 timeout을 초과했습니다.",
    #                 "data": {
    #                     "moving_axes": moving_axes,
    #                     "timeout": timeout
    #                 }
    #             }

    #             save_result_json(result)
    #             return result
            

    #         time.sleep(0.05)

    #     ####################################
    #     # ==================================================    # print("전체 모터 정지 요청")

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    # try:
    #     plc.open()

    #     axis_set = set()

    #     for motors in POSITIONER_AXIS_MAP.values():
    #         for axis in motors.values():
    #             axis_set.add(axis)

    #     all_axes = sorted(axis_set)

    #     # ---------
    #     # 현재 실제로 움직이고 있는 축 확인
    #     # ---------
    #     moving_axes = []  #list
    #     positions_before_stop = {} #딕셔너리 : 키:값 

    #     for axis in all_axes:
    #         is_busy = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         current_pos = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].ActPos",
    #             pyads.PLCTYPE_LREAL
    #         )

    #         positions_before_stop[str(axis)] = current_pos

    #         if is_busy:
    #             moving_axes.append(axis)

        
        # # 움직이는 축이 없으면 Stop을 보내지 않음
        # if not moving_axes:
        #     result = {
        #         "status": "idle",
        #         "message": "현재 회전 중인 모터가 없습니다",
        #         "data": {
        #             "moving_axes": [],
        #             "positions": positions_before_stop
        #         }
        #     }

        #     save_result_json(result)
        #     return result
        
        # print(f"정지 대상 축: {moving_axes}")

        # # -----
        # # PLC에 정지 감속도와 전체 정지 요청 전송
        # # -----
        # plc.write_by_name(
        #     "GVL.gStopDec",
        #     float(dec),
        #     pyads.PLCTYPE_LREAL
        # )

        # plc.write_by_name(
        #     "GVL.gStopAll",
        #     True,
        #     pyads.PLCTYPE_BOOL
        # )

        # # ---
        # # PLC가 정지 요청을 접수했는지 확인
        # # ---
        # request_accepted = False
        # request_start_time = time.time()

        # while time.time() - request_start_time < start_timeout:
        #     stop_busy = plc.read_by_name(
        #         "GVL.gStopBusy",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     stop_occurred = plc.read_by_name(
        #         "GVL.gStopOccurred",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     if stop_busy or stop_occurred:
        #         request_accepted = True
        #         break

        #     time.sleep(0.02)

        # if not request_accepted:
        #     result = {
        #         "status": "fail",
        #         "message": "PLC가 전체 정지 요청을 접수하지 않았습니다.",
        #         "data": {
        #             "moving_axes": moving_axes,
        #             "start_timeout": start_timeout
        #         }
        #     }

        #     save_result_json(result)
        #     return result
        
        # print("PLC 정지 요청 접수 완료")


        # # -----
        # # 모든 정지 대상 축이 멈출 때까지 대기
        # # -----
        # stop_start_time = time.time()

        # while True:
        #     stop_busy = plc.read_by_name(
        #         "GVL.gStopBusy",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     stop_done = plc.read_by_name(
        #         "GVL.gStopDone",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     stop_occurred = plc.read_by_name(
        #         "GVL.gStopOccurred",
        #         pyads.PLCTYPE_BOOL
        #     )

        #     error_axes = []
        #     status_str = "정지 중 |"

        #     for axis in moving_axes:
        #         is_error = plc.read_by_name(
        #             f"GVL.gAxisState[{axis}].Error",
        #             pyads.PLCTYPE_BOOL
        #         )

        #         act_pos = plc.read_by_name(
        #             f"GVL.gAxisState[{axis}].ActPos",
        #             pyads.PLCTYPE_LREAL
        #         )

        #         status_str += f"축{axis}:{act_pos:7.2f}"

        #         if is_error:
        #             error_axes.append({
        #                 "axis": axis,
        #                 "actual_position": act_pos
        #             })

        #     print(status_str, end="\r")

        #     if error_axes:
        #         result = {
        #             "status": "error",
        #             "message": "전체 정지 처리 중 축 에러가 발생했습니다.",
        #             "data": {
        #                 "error_axes": error_axes,
        #                 "moving_axes": moving_axes
        #             }
        #         }

        #         save_result_json(result)
        #         return result
            

        #     # 정리 완료 + MC_Stop 축 잠금 해제 완료
        #     if stop_done and stop_occurred and not stop_busy:
        #         break

        #     if time.time() - stop_start_time > timeout:
        #         result = {
        #             "status": "fail",
        #             "message": "전체 모터 정지 시간이 timeout을 초과했습니다.",
        #             "data": {
        #                 "moving_axes": moving_axes,
        #                 "timeout": timeout
        #             }
        #         }

        #         save_result_json(result)
        #         return result
            

        #     time.sleep(0.05)

    #     ####################################
    #     # ==================================================
    #     # PLC에 저장된 Stop 당시 step 정보 읽기
    #     # 정지가 완전히 끝난 후 읽음
    #     # ==================================================
    #     stopped_last_step = plc.read_by_name(
    #         "GVL.gStoppedLastCompletedStep",
    #         pyads.PLCTYPE_INT
    #     )

    #     stopped_target_step = plc.read_by_name(
    #         "GVL.gStoppedTargetStep",
    #         pyads.PLCTYPE_INT
    #     )

    #     stopped_total_points = plc.read_by_name(
    #         "GVL.gStoppedTotalPoints",
    #         pyads.PLCTYPE_INT
    #     )

    #     stopped_state = plc.read_by_name(
    #         "GVL.gStoppedState",
    #         pyads.PLCTYPE_INT
    #     )
    #     #########################################

        
    #     final_positions = {}

    #     for axis in all_axes:
    #         final_pos = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].ActPos",
    #             pyads.PLCTYPE_LREAL
    #         )

    #         final_busy = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         final_error = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Error",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         final_positions[str(axis)] = {
    #             "actual_position": final_pos,
    #             "busy": final_busy,
    #             "error": final_error,
    #             "was_moving": axis in moving_axes   #False는 원래 정지해 있던 축
    #         }


    #     result = {
    #         "status": "success",
    #         "message": "회전 중이던 모든 모터가 이동 중 정지했습니다.",
    #         "data": {
    #             "stop_deceleration": dec,
    #             "stopped_axes": moving_axes,
    #             "positions_before_stop": positions_before_stop,

    #             "stop_step_information": {
    #                 "last_completed_step": stopped_last_step,
    #                 "target_step": stopped_target_step,
    #                 "total_points": stopped_total_points,
    #                 "plc_state_at_stop": stopped_state
    #             },    
                
    #             "final_positions": final_positions
    #         }
    #     }

    #     save_result_json(result)
    #     return result
    
    # except pyads.ADSError as e:
    #     result = {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # except Exception as e:
    #     result = {
    #         "status": "error",
    #         "message": f"전체 정지 중 예상하지 못한 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # finally:
    #     # 정지 요청 신호만 FALSE로 복구
    #     # 여기에서는 clear_motion_flags()를 호출하지 않음
    #     try:
    #         plc.write_by_name(
    #             "GVL.gStopAll",
    #             False,
    #             pyads.PLCTYPE_BOOL
    #         )
    #     except Exception:
    #         pass

    #     try:
    #         plc.close()
    #         print("\n정지 명령 연결 종료")
    #     except Exception:
    #         pass
    #     # PLC에 저장된 Stop 당시 step 정보 읽기
    #     # 정지가 완전히 끝난 후 읽음
    #     # ==================================================
    #     stopped_last_step = plc.read_by_name(
    #         "GVL.gStoppedLastCompletedStep",
    #         pyads.PLCTYPE_INT
    #     )

    #     stopped_target_step = plc.read_by_name(
    #         "GVL.gStoppedTargetStep",
    #         pyads.PLCTYPE_INT
    #     )

    #     stopped_total_points = plc.read_by_name(
    #         "GVL.gStoppedTotalPoints",
    #         pyads.PLCTYPE_INT
    #     )

    #     stopped_state = plc.read_by_name(
    #         "GVL.gStoppedState",
    #         pyads.PLCTYPE_INT
    #     )
    #     #########################################

        
    #     final_positions = {}

    #     for axis in all_axes:
    #         final_pos = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].ActPos",
    #             pyads.PLCTYPE_LREAL
    #         )

    #         final_busy = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         final_error = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Error",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         final_positions[str(axis)] = {
    #             "actual_position": final_pos,
    #             "busy": final_busy,
    #             "error": final_error,
    #             "was_moving": axis in moving_axes   #False는 원래 정지해 있던 축
    #         }


    #     result = {
    #         "status": "success",
    #         "message": "회전 중이던 모든 모터가 이동 중 정지했습니다.",
    #         "data": {
    #             "stop_deceleration": dec,
    #             "stopped_axes": moving_axes,
    #             "positions_before_stop": positions_before_stop,

    #             "stop_step_information": {
    #                 "last_completed_step": stopped_last_step,
    #                 "target_step": stopped_target_step,
    #                 "total_points": stopped_total_points,
    #                 "plc_state_at_stop": stopped_state
    #             },    
                
    #             "final_positions": final_positions
    #         }
    #     }

    #     save_result_json(result)
    #     return result
    
    # except pyads.ADSError as e:
    #     result = {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # except Exception as e:
    #     result = {
    #         "status": "error",
    #         "message": f"전체 정지 중 예상하지 못한 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # finally:
    #     # 정지 요청 신호만 FALSE로 복구
    #     # 여기에서는 clear_motion_flags()를 호출하지 않음
    #     try:
    #         plc.write_by_name(
    #             "GVL.gStopAll",
    #             False,
    #             pyads.PLCTYPE_BOOL
    #         )
    #     except Exception:
    #         pass

    #     try:
    #         plc.close()
    #         print("\n정지 명령 연결 종료")
    #     except Exception:
    #         pass

# endregion




# =======================================================================
# 6
# positioner_lock([])
# 입력한 포지셔너의 alpha, beta축을 모두 잠금 상태로 저장
# ex : positioner_lock(["A1", "A3"])
# region
def positioner_lock(positioners: list[str]):

    """
    움직이지 않아야 할 포지셔너를 PLC에 잠금 상태로 저장하는 함수.

    사용 예:
        positioner_lock(["A1", "A3"])
        positioner_lock(["A2"])

    결과:
        A1의 Alpha/Beta 축 잠금
        A3의 Alpha/Beta 축 잠금
        나머지 포지셔너는 잠금 해제

    전체 잠금 해제:
        positioner_lock([])

    주의:
        이 함수는 모터를 직접 움직이지 않는다.
        PLC에 어떤 포지셔너가 잠겨 있는지만 저장한다.
    """
    # positioner_lock("A1")
    # positioner_lock(["A1", "A2"])
    # positioner_lock([]

    # -----
    # A1 처럼 문자열 하나만 입력해도 리스트로 변경
    # -----
    if isinstance(positioners, str):
        positioners = [positioners]

    # -----
    # 입력값을 대문자로 통일하고 중복 제거
    # -----
    locked_positioners = []

    for positioner in positioners:
        positioner_name = positioner.strip().upper()

        if positioner_name not in locked_positioners:
            locked_positioners.append(positioner_name)

    # -----
    # 존재하지 않는 포지셔너가 입력됐는지 검사
    # -----
    invalid_positioners = [
        positioner
        for positioner in locked_positioners
        if positioner not in POSITIONER_AXIS_MAP
    ]

    if invalid_positioners:
        result = {
            "status": "fail",
            "message": "존재하지 않는 포지셔너가 입력되었습니다",
            "data": {
                "invalid_positioners": invalid_positioners,
                "available_positioners": list(POSITIONER_AXIS_MAP.keys())
            }
        }
        save_result_json(result)
        return result


    ## region for simulation
    return {
        "status": "success",
        "message": "포지셔너 잠금 상태가 PLC에 저장되었습니다",
        "data": {
            "locked_positioners": locked_positioners,
            "locked_axes": [1, 2, 5, 6],
            "unlocked_positioners": ["A2", "A4", "A5"],
            "unlocked_axes": [3, 4, 7, 8, 9, 10],
        }
    }

    ## end region for simulation

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    # try:
    #     plc.open()

    #     # ----
    #     # 현재 움직이는 축이 있는지 검사
    #     # 움직이는 중에는 잠금 상태를 변경하지 않음
    #     # ----
    #     busy_axes = []

    #     for motors in POSITIONER_AXIS_MAP.values():
    #         for axis in motors.values():

    #             is_busy = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             if is_busy:
    #                 busy_axes.append(axis)
        
    #     stop_busy = plc.read_by_name(
    #         "GVL.gStopBusy",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     if busy_axes or stop_busy:
    #         result = {
    #             "status": "fail",
    #             "message": (
    #                 "모터가 움직이거나 stop 처리가 진행중이므로 "
    #                 "잠금 상태를 변경할 수 없습니다."
    #             ),
    #             "data": {
    #                 "busy_axes": busy_axes,
    #                 "stop_busy": stop_busy
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     # -----
    #     # PLC 에 포지셔너 별 잠금 상태 저장
    #     # 
    #     # 예
    #     # A1 잠금 -> 1,2번축 TRUE
    #     # -----

    #     locked_axes = []
    #     unlocked_axes = []

    #     for positioner, motors in POSITIONER_AXIS_MAP.items():

    #         is_locked = positioner in locked_positioners

    #         for axis in motors.values():

    #             plc.write_by_name(
    #                 f"GVL.gAxisLocked[{axis}]",
    #                 is_locked,
    #                 pyads.PLCTYPE_BOOL
    #             )


    #             if is_locked:
    #                 locked_axes.append(axis)

    #             else:
    #                 unlocked_axes.append(axis)

        
    #     # -----
    #     # PLC에 잠금 상태가 정확하게 저장됐는지 확인
    #     # -----

    #     verification_errors = []

    #     for positioner, motors in POSITIONER_AXIS_MAP.items():

    #         expected_locked = positioner in locked_positioners

    #         for axis in motors.values():

    #             actual_locked = plc.read_by_name(
    #                 f"GVL.gAxisLocked[{axis}]",
    #                 pyads.PLCTYPE_BOOL
    #             )
                
    #             if actual_locked != expected_locked:
    #                 verification_errors.append({
    #                     "positioner": positioner,
    #                     "axis": axis,
    #                     "expected_locked": expected_locked,
    #                     "actual_locked": actual_locked
    #                 })

    #     if verification_errors:
    #         result = {
    #             "status": "fail",
    #             "message": "PLC 잠금 상태 확인 과정에서 값이 일치 하지 않는다.",
    #             "data": {
    #                 "verification_errors": verification_errors
    #             }
    #         }
    #         save_result_json(result)
    #         return result
        
    #     # -----
    #     # 잠기지 않은 포지셔너 목록
    #     # -----
    #     unlocked_positioners = [
    #         positioner
    #         for positioner in POSITIONER_AXIS_MAP
    #         if positioner not in locked_positioners
    #     ]

    #     result = {
    #         "status": "success",
    #         "message": "포지셔너 잠금 상태가 PLC에 저장되었습니다",
    #         "data": {
    #             "locked_positioners": locked_positioners,
    #             "locked_axes": sorted(locked_axes),
    #             "unlocked_positioners": unlocked_positioners,
    #             "unlocked_axes": sorted(unlocked_axes)
    #         }
    #     }
        
    #     save_result_json(result)
    #     return result
    
    # except pyads.ADSError as e:
    #     result = {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # except Exception as e:
    #     result = {
    #         "status": "error",
    #         "message": f"포지셔너 잠금 중 예상하지 못한 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # finally:
    #     try:
    #         plc.close()
    #         print("포지셔너 잠금 설정 연결 종료")
    #     except Exception:
    #         pass

# endregion    
        

    

# --------------------------------main()---------------------------------
# region 
def rotate_all():

    ## region for simulation
    result = {
    "status": "success",
    "message": "All positioners rotated successfully.",
    "data": {
        "total_steps": 1335,
        "axes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "motion_axes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "locked_axes": [],
        "final_positions": {
            "1": {"actual_position": 47.30, "busy": False, "error": False},
            "2": {"actual_position": 10.16, "busy": False, "error": False},
            "3": {"actual_position": 350.50, "busy": False, "error": False},
            "4": {"actual_position": 131.28, "busy": False, "error": False},
            "5": {"actual_position": 295.57, "busy": False, "error": False},
            "6": {"actual_position": 113.28, "busy": False, "error": False},
            "7": {"actual_position": 299.45, "busy": False, "error": True},
            "8": {"actual_position": 93.13, "busy": False, "error": False},
            "9": {"actual_position": 85.44, "busy": False, "error": False},
            "10": {"actual_position": 81.02, "busy": False, "error": False},
            }
        }
    }

    return result
    ## end region for simulation


    # print("포지셔너 구동 시작")

    # try:
    #     axis_points, total_steps = read_json(ALPHA_FILE, BETA_FILE)

    # except FileNotFoundError as e:
    #     result = {
    #         "status": "fail",
    #         "message": f"JSON 파일을 찾을 수 없습니다: {e.filename}",
    #         "data": {
    #             "missing_file": e.filename
    #         }
    #     }
    #     save_result_json(result)
    #     return result

    # except KeyError as e:
    #     result = {
    #         "status": "fail",
    #         "message": f"JSON 파일 내부 구조가 예상과 다릅니다. Key: {e}",
    #         "data": {
    #             "missing_key": str(e)
    #         }
    #     }
    #     save_result_json(result)
    #     return result
    
    # except ValueError as e:
    #     result = {
    #         "status": "fail",
    #         "message": f"JSON 데이터 값 또는 길이에 문제가 있습니다: {e}",
    #         "data": {
    #             "error": str(e)
    #         }
    #     }
    #     save_result_json(result)
    #     return result

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    
  
    # try:
    #     plc.open()

    #     # 다 잠기면 아래 오류가 뜸
    #     locked_axes, motion_axes = read_axis_lock_state(plc)

    #     if not motion_axes:
    #         result = {
    #             "status": "fail",
    #             "message": "모든 축이 잠겨 있어 정방향 구동을 시작할 수 없습니다.",
    #             "data": {
    #                 "locked_axes": locked_axes,
    #                 "motion_axes": []
    #             }
    #         }
            
    #         save_result_json(result)
    #         return result
    #     #

    # # 이번 명령은 정방향 main()
    #     plc.write_by_name(
    #         "GVL.gMotionModeCommand",
    #         1,
    #         pyads.PLCTYPE_INT
    #     )

    #     # 완전히 새로운 정방향 실행이므로 이전 Stop 기록 삭제
    #     plc.write_by_name(
    #         "GVL.gClearStoppedInfo",
    #         True,
    #         pyads.PLCTYPE_BOOL
    #     )

    #     clear_wait_start = time.time()

    #     while plc.read_by_name(
    #         "GVL.gClearStoppedInfo",
    #         pyads.PLCTYPE_BOOL
    #     ):
    #         if time.time() - clear_wait_start > 2.0:
    #             raise TimeoutError(
    #                 "이전 Stop 기록 초기화 시간이 초과되었습니다."
    #             )

    #         time.sleep(0.02)

    #         clear_motion_flags(plc)
    #         time.sleep(0.1)
    #  #########################################################
    #         for axis in motion_axes:   #for axis in axis_points.keys():
    #             plc.write_by_name(
    #                 f"GVL.gAxisCmd[{axis}].Power",
    #                 True,
    #                 pyads.PLCTYPE_BOOL
    #             )

    #         time.sleep(1.0)

    #         # for axis, points in axis_points.items():
    #         #     prefix = f"GVL.gAxisCmd[{axis}]"
    #         for axis in motion_axes:
    #             points = axis_points[axis]
    #             prefix = f"GVL.gAxisCmd[{axis}]"

    #             plc.write_by_name(f"{prefix}.TotalPoints", total_steps, pyads.PLCTYPE_INT)
    #             plc.write_by_name(f"{prefix}.Velocity", VELOCITY, pyads.PLCTYPE_LREAL)
    #             plc.write_by_name(f"{prefix}.Acc", ACC, pyads.PLCTYPE_LREAL)
    #             plc.write_by_name(f"{prefix}.Dec", DEC, pyads.PLCTYPE_LREAL)

    #             target_pos_array = (pyads.PLCTYPE_LREAL * 3500)()

    #             for i in range(total_steps):
    #                 target_pos_array[i] = float(points[i])

    #             plc.write_by_name(
    #                 f"{prefix}.TargetPos",
    #                 target_pos_array,
    #                 pyads.PLCTYPE_LREAL * 3500
    #             )

    #         time.sleep(0.5)

    #         for axis in motion_axes: #for axis in axis_points.keys():
    #             plc.write_by_name(
    #                 f"GVL.gAxisCmd[{axis}].Active",
    #                 True,
    #                 pyads.PLCTYPE_BOOL
    #             )

    #         for axis in motion_axes: #for axis in axis_points.keys():
    #             plc.write_by_name(
    #                 f"GVL.gAxisCmd[{axis}].StartSpline",
    #                 True,
    #                 pyads.PLCTYPE_BOOL
    #             )

    #         plc_started = False #처음에는 아직 PLC가 출발했는지 모름

    #         for _ in range(20):
    #             if any(
    #                 plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].Busy",
    #                     pyads.PLCTYPE_BOOL
    #                 )
    #                 for axis in motion_axes #for axis in axis_points.keys()
    #             ):
    #                 plc_started = True
    #                 break

    #             time.sleep(0.05)

    #         if not plc_started:
    #             result = {
    #                 "status": "fail",
    #                 "message": "PLC가 출발하지 않았습니다.",
    #                 "data": {
    #                     "reason": "No axis entered Busy state",
    #                     #"axes": list(axis_points.keys()),
    #                     "motion_axes": motion_axes,
    #                     "locked_axes": locked_axes,
    #                     "total_steps": total_steps
    #                 }
    #             }

    #             save_result_json(result)
    #             return result

    #         while True:
    #             moving_axes = 0     #이번 반복에서 몇 개 축이 움직이는지 세는 변수
    #             status_str = "📍 상태 | "  # 현재 축 상태를 보기 좋게 출력하기 위한 문자열

    #             for axis in motion_axes: #for axis in axis_points.keys():
    #                 is_busy = plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].Busy",
    #                     pyads.PLCTYPE_BOOL
    #                 )

    #                 is_error = plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].Error",
    #                     pyads.PLCTYPE_BOOL
    #                 )

    #                 act_pos = plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].ActPos",
    #                     pyads.PLCTYPE_LREAL
    #                 )

    #                 status_str += f"축{axis}:{act_pos:7.2f}  "

    #                 if is_error:
    #                     result = {
    #                         "status": "error",
    #                         "message": f"{axis}번 축에서 에러가 발생했습니다.",
    #                         "data": {
    #                             "error_axis": axis,
    #                             "actual_position": act_pos,
    #                             "total_steps": total_steps
    #                         }
    #                     }

    #                 save_result_json(result)
    #                 return result

    #             if is_busy:
    #                 moving_axes += 1

    #         print(status_str, end="\r")

    #         # ----------
    #         # 다른 Python 실행창에서 stop()이 실행되었는지 확인
    #         # ----------
    #         stop_occurred = plc.read_by_name(
    #             "GVL.gStopOccurred",
    #             pyads.PLCTYPE_BOOL
    #         )
            
    #         if stop_occurred:
    #             stopped_positions = {}

    #             for axis in motion_axes: #for axis in axis_points.keys():
    #                 final_pos = plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].ActPos",
    #                     pyads.PLCTYPE_LREAL
    #                 )

    #                 final_busy = plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].Busy",
    #                     pyads.PLCTYPE_BOOL
    #                 )

    #                 final_error = plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].Error",
    #                     pyads.PLCTYPE_BOOL
    #                 )



    #                 stopped_positions[str(axis)] = {
    #                     "actual_position": final_pos,
    #                     "busy": final_busy,
    #                     "error": final_error
    #                 }

    #             result = {
    #                 "status": "stopped",
    #                 "message": "사용자의 Stop 요청으로 정방향 구동이 중간에 중단되었습니다",
    #                 "data": {
    #                     "direction": "forward",
    #                     # "axes": list(axis_points.keys()),
    #                     "motion_axes": motion_axes,
    #                     "locked_axes": locked_axes,
    #                     "stopped_positions": stopped_positions
    #                 }
    #             }

    #             save_result_json(result)
    #             return result

    #         if moving_axes == 0:
    #             break

    #         time.sleep(0.1)

    #     final_positions = {}

    #     for axis in motion_axes: #for axis in axis_points.keys():
    #         final_pos = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].ActPos",
    #             pyads.PLCTYPE_LREAL
    #         )

    #         final_busy = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         final_error = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Error",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         final_positions[str(axis)] = {
    #             "actual_position": final_pos,
    #             "busy": final_busy,
    #             "error": final_error
    #         }

    #     result = {
    #         "status": "success",
    #         "message": "All positioners rotated successfully.",
    #         "data": {
    #             "total_steps": total_steps,
    #             "axes": list(axis_points.keys()),
    #             "motion_axes": motion_axes,
    #             "locked_axes": locked_axes,
    #             "final_positions": final_positions
    #         }
    #     }

    #     save_result_json(result)
    #     return result

    # except pyads.ADSError as e:
    #     result = {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # except Exception as e:
    #     result = {
    #         "status": "error",
    #         "message": f"예상하지 못한 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # finally:
    #     try:
    #         clear_motion_flags(plc)
    #     except Exception:
    #         pass
    #     try:
    #         plc.close()
    #         print(" 연결 종료")
    #     except Exception:
    #         pass
        
# endregion



# ----------------------------reverse_main()-----------------------------
# main()으로 이동 완료 후 다시 1단계로 돌리고 싶을때
# region
def reverse_all():

    ## region for simulation
    return {
    "status": "success",
    "message": "All positioners returned from step n to step 1 successfully.",
    "data": {
        "direction": "reverse",
        "total_steps": 1335,
        "motion_axes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "locked_axes": [],
        "final_positions": {
            "1": {"actual_position": 30.0, "busy": False, "error": False},
            "2": {"actual_position": 150.0, "busy": False, "error": False},
            "3": {"actual_position": 30.0, "busy": False, "error": False},
            "4": {"actual_position": 150.0, "busy": False, "error": False},
            "5": {"actual_position": 30.0, "busy": False, "error": False},
            "6": {"actual_position": 150.0, "busy": False, "error": False},
            "7": {"actual_position": 30.0, "busy": False, "error": False},
            "8": {"actual_position": 150.0, "busy": False, "error": False},
            "9": {"actual_position": 30.0, "busy": False, "error": False},
            "10": {"actual_position": 150.0, "busy": False, "error": False},
        }
    }
    }
    ## end region for simulation


    # print("포지셔너 역방향 구동 시작")

    # try:
    #     axis_points, total_steps = read_json(ALPHA_FILE, BETA_FILE)
    #     # 역순으로 변환
    #     axis_points, total_steps = reverse_step_to_firststep(axis_points, max_points = 3500)

    # except FileNotFoundError as e:
    #     result = {
    #         "status": "fail",
    #         "message": f"JSON 파일을 찾을 수 없습니다: {e.filename}",
    #         "data": {
    #             "missing_file": e.filename,
    #             "direction": "reverse"
    #         }
    #     }
    #     save_result_json(result)
    #     return result

    # except KeyError as e:
    #     result = {
    #         "status": "fail",
    #         "message": f"JSON 파일 내부 구조가 예상과 다릅니다. Key: {e}",
    #         "data": {
    #             "missing_key": str(e),
    #             "direction": "reverse"
    #         }
    #     }
    #     save_result_json(result)
    #     return result
    
    # except ValueError as e:
    #     result = {
    #         "status": "fail",
    #         "message": f"JSON 데이터 값 또는 길이에 문제가 있습니다: {e}",
    #         "data": {
    #             "error": str(e),
    #             "direction": "reverse"
    #         }
    #     }
    #     save_result_json(result)
    #     return result

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    # try:
    #     plc.open()

    #     locked_axes, motion_axes = read_axis_lock_state(plc)

    #     if not motion_axes:
    #         result = {
    #             "status": "fail",
    #             "message": "모든 축이 잠겨 있어 역방향 구동을 시작할 수 없습니다.",
    #             "data": {
    #                 "direction": "reverse",
    #                 "locked_axes": locked_axes,
    #                 "motion_axes": []
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     clear_motion_flags(plc)
    #     time.sleep(0.1)

    #     for axis in motion_axes: # for axis in axis_points.keys():
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].Power",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         ) 

    #     for axis in motion_axes:
    #         points = axis_points[axis]
    #         prefix = f"GVL.gAxisCmd[{axis}]"

    #         plc.write_by_name(f"{prefix}.TotalPoints", total_steps, pyads.PLCTYPE_INT)
    #         plc.write_by_name(f"{prefix}.Velocity", VELOCITY, pyads.PLCTYPE_LREAL)
    #         plc.write_by_name(f"{prefix}.Acc", ACC, pyads.PLCTYPE_LREAL)
    #         plc.write_by_name(f"{prefix}.Dec", DEC, pyads.PLCTYPE_LREAL)

    #         target_pos_array = (pyads.PLCTYPE_LREAL * 3500)()

    #         for i in range(total_steps):
    #             target_pos_array[i] = float(points[i])

    #         plc.write_by_name(
    #             f"{prefix}.TargetPos",
    #             target_pos_array,
    #             pyads.PLCTYPE_LREAL * 3500
    #         )

    #     time.sleep(0.5)

    #     for axis in motion_axes: #for axis in axis_points.keys():
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].Active",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     for axis in motion_axes: #for axis in axis_points.keys():
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].StartSpline",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     plc_started = False #처음에는 아직 PLC가 출발했는지 모름

    #     for _ in range(20):
    #         if any(
    #             plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )
    #             for axis in motion_axes #for axis in axis_points.keys()
    #         ):
    #             plc_started = True
    #             break

    #         time.sleep(0.05)

    #     if not plc_started:
    #         result = {
    #             "status": "fail",
    #             "message": "PLC 역방향 구동이 시작되지 않았습니다.",
    #             "data": {
    #                 "reason": "No axis entered Busy state",
    #                 "direction": "reverse",
    #                 # "axes": list(axis_points.keys()),
    #                 "motion_axes": motion_axes,
    #                 "locked_axes": locked_axes,
    #                 "total_steps": total_steps
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     while True:
    #         moving_axes = 0     #이번 반복에서 몇 개 축이 움직이는지 세는 변수
    #         status_str = "📍 역방향 상태 | "  # 현재 축 상태를 보기 좋게 출력하기 위한 문자열

    #         for axis in motion_axes: #for axis in axis_points.keys():
    #             is_busy = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             is_error = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Error",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             act_pos = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].ActPos",
    #                 pyads.PLCTYPE_LREAL
    #             )

    #             status_str += f"축{axis}:{act_pos:7.2f}  "

    #             if is_error:
    #                 result = {
    #                     "status": "error",
    #                     "message": f"{axis}번 축에서 역방향 이동 중 에러가 발생했습니다.",
    #                     "data": {
    #                         "direction": "reverse",
    #                         "error_axis": axis,
    #                         "actual_position": act_pos,
    #                         "total_steps": total_steps
    #                     }
    #                 }

    #                 save_result_json(result)
    #                 return result

    #             if is_busy:
    #                 moving_axes += 1

    #         print(status_str, end="\r")

    #         # ----------
    #         # 다른 Python 실행창에서 stop()이 실행되었는지 확인
    #         # ----------
    #         stop_occurred = plc.read_by_name(
    #             "GVL.gStopOccurred",
    #             pyads.PLCTYPE_BOOL
    #         )
            
    #         if stop_occurred:
    #             stopped_positions = {}

    #             for axis in motion_axes: #for axis in axis_points.keys():
    #                 final_pos = plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].ActPos",
    #                     pyads.PLCTYPE_LREAL
    #                 )

    #                 final_busy = plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].Busy",
    #                     pyads.PLCTYPE_BOOL
    #                 )

    #                 final_error = plc.read_by_name(
    #                     f"GVL.gAxisState[{axis}].Error",
    #                     pyads.PLCTYPE_BOOL
    #                 )

    #                 stopped_positions[str(axis)] = {
    #                     "actual_position": final_pos,
    #                     "busy": final_busy,
    #                     "error": final_error
    #                 }

    #             result = {
    #                 "status": "stopped",
    #                 "message": "사용자의 Stop 요청으로 역방향 구동이 중간에 중단되었습니다",
    #                 "data": {
    #                     "direction": "reverse",
    #                     # "axes": list(axis_points.keys()),
    #                     "motion_axes": motion_axes,
    #                     "locked_axes": locked_axes,
    #                     "stopped_positions": stopped_positions
    #                 }
    #             }

    #             save_result_json(result)
    #             return result

    #         if moving_axes == 0:
    #             break

    #         time.sleep(0.1)

    #     final_positions = {}

    #     for axis in motion_axes: #for axis in axis_points.keys():
    #         final_pos = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].ActPos",
    #             pyads.PLCTYPE_LREAL
    #         )

    #         final_busy = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         final_error = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Error",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         final_positions[str(axis)] = {
    #             "actual_position": final_pos,
    #             "busy": final_busy,
    #             "error": final_error
    #         }

    #     result = {
    #         "status": "success",
    #         "message": "All positioners returned from step n to step 1 successfully.",
    #         "data": {
    #             "direction": "reverse",
    #             "total_steps": total_steps,
    #             #"axes": list(axis_points.keys()),
    #             "motion_axes": motion_axes,
    #             "locked_axes": locked_axes,
    #             "final_positions": final_positions
    #         }
    #     }

    #     save_result_json(result)
    #     return result

    # except pyads.ADSError as e:
    #     result = {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #         "data": {
    #             "direction": "reverse"
    #         }
    #     }

    #     save_result_json(result)
    #     return result

    # except Exception as e:
    #     result = {
    #         "status": "error",
    #         "message": f"예상하지 못한 에러가 발생했습니다: {e}",
    #         "data": {
    #             "direction": "reverse"
    #         }
    #     }

    #     save_result_json(result)
    #     return result

    # finally:
    #     try:
    #         clear_motion_flags(plc)
    #     except Exception:
    #         pass
    #     try:
    #         plc.close()
    #         print(" 연결 종료")
    #     except Exception:
    #         pass
        
#endregion



# -----------------------reverse_from_stop_step()-------------------------
# main() 실행 중 Stop된 위치에서 원래 JSON 경로를 따라 1단계로 복귀
# 복귀 중 다시 stop.py()를 실행하고 다시 reverse_from_stop_step()하는 기능은 포함되어 있지 않음.
# region
MOTION_MODE_FORWARD = 1
MOTION_MODE_STOP_REVERSE = 3
MAX_PATH_POINTS = 3500


class RecoveryStoppedError(Exception):
    pass


def _safe_stop_recovery(plc, dec: float, timeout: float = 30.0) -> bool:
    """복귀 timeout 시 움직이는 축을 감속 정지한다."""
    plc.write_by_name("GVL.gStopDec", float(dec), pyads.PLCTYPE_LREAL)
    plc.write_by_name("GVL.gStopAll", True, pyads.PLCTYPE_BOOL)

    try:
        start = time.time()
        while time.time() - start < timeout:
            stop_busy = plc.read_by_name("GVL.gStopBusy", pyads.PLCTYPE_BOOL)
            stop_done = plc.read_by_name("GVL.gStopDone", pyads.PLCTYPE_BOOL)
            stop_occurred = plc.read_by_name("GVL.gStopOccurred", pyads.PLCTYPE_BOOL)

            if stop_done and stop_occurred and not stop_busy:
                return True
            time.sleep(0.05)

        return False

    finally:
        try:
            plc.write_by_name("GVL.gStopAll", False, pyads.PLCTYPE_BOOL)
        except Exception:
            pass


def _run_stop_reverse_path(
    plc,
    path_by_axis: dict,
    velocity: float,
    acc: float,
    dec: float,
    start_timeout: float,
    timeout: float
):
    """[n단계, n-1단계, ..., 1단계] 경로를 PLC에 보내 실행한다."""
    axes = sorted(path_by_axis)
    total_steps = len(path_by_axis[axes[0]])

    clear_motion_flags(plc)
    time.sleep(0.1)

    plc.write_by_name(
        "GVL.gMotionModeCommand",
        MOTION_MODE_STOP_REVERSE,
        pyads.PLCTYPE_INT
    )

    for axis in axes:
        plc.write_by_name(
            f"GVL.gAxisCmd[{axis}].Power",
            True,
            pyads.PLCTYPE_BOOL
        )

    time.sleep(1.0)

    for axis in axes:
        prefix = f"GVL.gAxisCmd[{axis}]"
        target_array = (pyads.PLCTYPE_LREAL * MAX_PATH_POINTS)()

        for index, target in enumerate(path_by_axis[axis]):
            target_array[index] = float(target)

        plc.write_by_name(f"{prefix}.TotalPoints", total_steps, pyads.PLCTYPE_INT)
        plc.write_by_name(f"{prefix}.Velocity", float(velocity), pyads.PLCTYPE_LREAL)
        plc.write_by_name(f"{prefix}.Acc", float(acc), pyads.PLCTYPE_LREAL)
        plc.write_by_name(f"{prefix}.Dec", float(dec), pyads.PLCTYPE_LREAL)
        plc.write_by_name(f"{prefix}.TargetPos", target_array, pyads.PLCTYPE_LREAL * MAX_PATH_POINTS)

    time.sleep(0.5)

    # 새 명령 접수 여부는 Busy가 아니라 실행 번호 증가로 확인
    sequence_before = plc.read_by_name(
        "GVL.gMotionSequence",
        pyads.PLCTYPE_UDINT
    )

    for axis in axes:
        plc.write_by_name(
            f"GVL.gAxisCmd[{axis}].Active",
            True,
            pyads.PLCTYPE_BOOL
        )

    for axis in axes:
        plc.write_by_name(
            f"GVL.gAxisCmd[{axis}].StartSpline",
            True,
            pyads.PLCTYPE_BOOL
        )

        

    start = time.time()
    while time.time() - start < start_timeout:
        sequence_now = plc.read_by_name(
            "GVL.gMotionSequence",
            pyads.PLCTYPE_UDINT
        )
        error_axes = [
            axis for axis in axes
            if plc.read_by_name(
                f"GVL.gAxisState[{axis}].Error",
                pyads.PLCTYPE_BOOL
            )
        ]

        if error_axes:
            raise RuntimeError(f"복귀 시작 중 축 에러: {error_axes}")
        if sequence_now != sequence_before:
            break

        time.sleep(0.02)
    else:
        raise RuntimeError("PLC가 새 복귀 명령을 접수하지 않았습니다.")

    # 마지막 step 완료까지 대기
    motion_start = time.time()
    while True:
        moving_axes = 0
        error_axes = []

        for axis in axes:
            if plc.read_by_name(
                f"GVL.gAxisState[{axis}].Busy",
                pyads.PLCTYPE_BOOL
            ):
                moving_axes += 1

            if plc.read_by_name(
                f"GVL.gAxisState[{axis}].Error",
                pyads.PLCTYPE_BOOL
            ):
                error_axes.append(axis)

        if error_axes:
            raise RuntimeError(f"복귀 중 축 에러: {error_axes}")

        # 복귀 도중 stop.py를 다시 실행한 경우
        if plc.read_by_name("GVL.gStopOccurred", pyads.PLCTYPE_BOOL):
            raise RecoveryStoppedError(
                "사용자의 Stop 요청으로 복귀 동작이 중단되었습니다."
            )

        completed_step = plc.read_by_name(
            "GVL.gLastCompletedStep",
            pyads.PLCTYPE_INT
        )

        if completed_step >= total_steps and moving_axes == 0:
            return

        if time.time() - motion_start > timeout:
            stopped = _safe_stop_recovery(plc, dec=dec)
            if stopped:
                raise TimeoutError(
                    f"복귀 시간이 {timeout}초를 초과하여 감속 정지했습니다."
                )
            raise TimeoutError(
                f"복귀 시간이 {timeout}초를 초과했고 정지 완료도 확인하지 못했습니다."
            )

        time.sleep(0.1)


def reverse_from_stop_step(
    position_tolerance: float = 0.2,
    velocity: float = VELOCITY,
    acc: float = ACC,
    dec: float = DEC,
    start_timeout: float = 2.0,
    timeout: float = 1800.0
):


    ## region for simulation
    return {
    "status": "success",
    "message": "정지 위치에서 100단계를 거쳐 1단계까지 복귀했습니다.",
    "data": {
        "return_from_step": 100,
        "returned_axes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "locked_axes": [],
        "final_positions": {
            "1": {
                "expected_step_1_position": 30.0,
                "actual_position": 30.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
            "2": {
                "expected_step_1_position": 150.0,
                "actual_position": 150.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
            "3": {
                "expected_step_1_position": 30.0,
                "actual_position": 30.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
            "4": {
                "expected_step_1_position": 150.0,
                "actual_position": 150.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
            "5": {
                "expected_step_1_position": 30.0,
                "actual_position": 30.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
            "6": {
                "expected_step_1_position": 150.0,
                "actual_position": 150.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
            "7": {
                "expected_step_1_position": 30.0,
                "actual_position": 30.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
            "8": {
                "expected_step_1_position": 150.0,
                "actual_position": 150.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
            "9": {
                "expected_step_1_position": 30.0,
                "actual_position": 30.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
            "10": {
                "expected_step_1_position": 150.0,
                "actual_position": 150.0,
                "position_error": 0.0,
                "busy": False,
                "error": False,
            },
        }
    }
    }
 

    """
    사용 순서:
        1. main()
        2. stop.py에서 stop_all_positioner()
        3. reverse_from_stop_step()

    전제:
        위 과정 사이에 JSON 파일과 PLC 프로그램을 변경하지 않는다.
    """
    print("Stop 위치에서 1단계까지 역방향 복귀 준비")
    # plc = None

    # try:
    #     # 기존 read_json()의 기본 형식/길이 검사만 재사용
    #     axis_points, total_steps = read_json(ALPHA_FILE, BETA_FILE)

    #     plc = pyads.Connection(AMS_NET_ID, AMS_PORT)
    #     plc.open()

    #     stopped_valid = plc.read_by_name("GVL.gStoppedValid", pyads.PLCTYPE_BOOL)
    #     stop_occurred = plc.read_by_name("GVL.gStopOccurred", pyads.PLCTYPE_BOOL)
    #     stop_busy = plc.read_by_name("GVL.gStopBusy", pyads.PLCTYPE_BOOL)
    #     last_step = plc.read_by_name(
    #         "GVL.gStoppedLastCompletedStep",
    #         pyads.PLCTYPE_INT
    #     )
    #     stopped_mode = plc.read_by_name(
    #         "GVL.gStoppedMotionMode",
    #         pyads.PLCTYPE_INT
    #     )

    #     # 복귀에 반드시 필요한 검사만 유지
    #     if not stopped_valid:
    #         raise ValueError("사용 가능한 Stop step 정보가 없습니다.")
    #     if stop_busy or not stop_occurred:
    #         raise ValueError("Stop 처리가 아직 완전히 끝나지 않았습니다.")
    #     if stopped_mode != MOTION_MODE_FORWARD:
    #         raise ValueError("main() 정방향 실행 중 발생한 Stop이 아닙니다.")
    #     if not 1 <= last_step <= total_steps:
    #         raise ValueError("마지막 완료 step 정보가 올바르지 않습니다.")
        
    #     locked_axes, unlocked_axes = read_axis_lock_state(plc)

    #     axes = [
    #         axis 
    #         for axis in sorted(axis_points)
    #         if axis in unlocked_axes
    #     ]

    #     if not axes:
    #         raise ValueError(
    #             "모든 축이 잠겨 있어 정지 위치에서 복귀할 축이 없습니다."
    #         )

    #     busy_axes = [
    #         axis for axis in axes
    #         if plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )
    #     ]
    #     if busy_axes:
    #         raise ValueError(f"아직 움직이는 축이 있습니다: {busy_axes}")

    #     # last_step=5라면 각 축 경로는 [5, 4, 3, 2, 1]
    #     # 현재 정지 위치에서 먼저 5단계로 돌아간 뒤 계속 1단계까지 이동
    #     reverse_path = {
    #         axis: list(reversed(axis_points[axis][:last_step]))
    #         for axis in axes
    #     }

    #     print(f"복귀 경로: 정지 위치 -> {last_step}단계 -> ... -> 1단계")

    #     _run_stop_reverse_path(
    #         plc=plc,
    #         path_by_axis=reverse_path,
    #         velocity=velocity,
    #         acc=acc,
    #         dec=dec,
    #         start_timeout=start_timeout,
    #         timeout=timeout
    #     )

    #     # 마지막 1단계 위치만 검사
    #     final_positions = {}
    #     invalid_axes = []

    #     for axis in axes:
    #         actual = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].ActPos",
    #             pyads.PLCTYPE_LREAL
    #         )

    #         final_busy = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Busy",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         final_error = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].Error",
    #             pyads.PLCTYPE_BOOL
    #         )

    #         expected = float(axis_points[axis][0])
    #         error = abs(actual - expected)

    #         final_positions[str(axis)] = {
    #             "expected_step_1_position": expected,
    #             "actual_position": actual,
    #             "position_error": error,
    #             "busy": final_busy,
    #             "error": final_error
    #         }

    #         if error > position_tolerance:
    #             invalid_axes.append(axis)

    #     if invalid_axes:
    #         raise ValueError(
    #             f"1단계 위치 허용오차를 벗어난 축이 있습니다: {invalid_axes}"
    #         )

    #     # 완전히 성공한 경우에만 Stop 기록 삭제
    #     plc.write_by_name("GVL.gClearStoppedInfo", True, pyads.PLCTYPE_BOOL)

    #     clear_start = time.time()
    #     while plc.read_by_name("GVL.gClearStoppedInfo", pyads.PLCTYPE_BOOL):
    #         if time.time() - clear_start > 2.0:
    #             raise TimeoutError("Stop 기록 삭제 시간이 초과되었습니다.")
    #         time.sleep(0.02)

    #     result = {
    #         "status": "success",
    #         "message": f"정지 위치에서 {last_step}단계를 거쳐 1단계까지 복귀했습니다.",
    #         "data": {
    #             "return_from_step": last_step,
    #             "returned_axes": axes,
    #             "locked_axes": locked_axes,
    #             "final_positions": final_positions
    #         }
    #     }

    # except RecoveryStoppedError as e:
    #     result = {"status": "stopped", "message": str(e), "data": {}}

    # except (FileNotFoundError, KeyError, ValueError, TimeoutError) as e:
    #     result = {"status": "fail", "message": str(e), "data": {}}

    # except pyads.ADSError as e:
    #     result = {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    # except Exception as e:
    #     result = {
    #         "status": "error",
    #         "message": f"Stop 역방향 복귀 중 예상하지 못한 에러: {e}",
    #         "data": {}
    #     }

    # finally:
    #     if plc is not None:
    #         try:
    #             clear_motion_flags(plc)
    #             plc.write_by_name("GVL.gStopAll", False, pyads.PLCTYPE_BOOL)
    #         except Exception:
    #             pass

    #         try:
    #             plc.close()
    #             print("\nStop 역방향 복귀 연결 종료")
    #         except Exception:
    #             pass

    # save_result_json(result)
    # return result

# endregion



# ------------------------------zero_main()------------------------------
# alpha, beta 축이 30, 150일때 모두 0, 0도로 가게 하기 위한 코드
# region
def zero_main(
    start_tolerance: float = 0.1,
    zero_tolerance: float = 0.1,
    timeout: float = 60.0
):
    """
    reverse_main() 종료 후 실행하는 함수.

    실행 조건:
        모든 Alpha 축이 30도
        모든 Beta 축이 150도

    조건을 만족하면:
        모든 Alpha/Beta 축을 절대위치 0도로 이동

    하나라도 조건을 만족하지 않으면:
        아무 축도 움직이지 않고 에러 반환
    """


    ## region for simulation
    return {
        "status": "success",
        "message": "잠기지 않은 모든 포지셔너 축이 0도로 이동했습니다.",
        "data": {
            "start_tolerance": start_tolerance,
            "zero_tolerance": zero_tolerance,
            "motion_axes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "locked_axes": [],
            "final_positions": {
                "1": {"positioner": "A1", "motor": "alpha", "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
                "2": {"positioner": "A1", "motor": "beta",  "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
                "3": {"positioner": "A2", "motor": "alpha", "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
                "4": {"positioner": "A2", "motor": "beta",  "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
                "5": {"positioner": "A3", "motor": "alpha", "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
                "6": {"positioner": "A3", "motor": "beta",  "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
                "7": {"positioner": "A4", "motor": "alpha", "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
                "8": {"positioner": "A4", "motor": "beta",  "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
                "9": {"positioner": "A5", "motor": "alpha", "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
                "10": {"positioner": "A5", "motor": "beta", "target_position": 0.0, "actual_position": 0.0, "position_error": 0.0, "busy": False, "error": False},
            }
        }
    }

    ## end for simulation



    # print("전 축 0도 이동 준비")

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    # try:
    #     plc.open()


    #     clear_motion_flags(plc)
    #     time.sleep(0.1)

    #     locked_axes, all_axes = read_axis_lock_state(plc)
    #     # all_axes는 잠기지 않는 축만 들어있는 목록

    #     if not all_axes:
    #         result = {
    #             "status": "fail",
    #             "message": "모든 축이 잠겨 있어 0도 이동을 실행할 수 없습니다",
    #             "data": {
    #                 "locked_axes": locked_axes,
    #                 "motion_axes": []
    #             }
    #         }
    #         save_result_json(result)
    #         return result

    #     # ==================================================
    #     # 현재 모든 축이 Alpha=30도, Beta=150도인지 검사
    #     # ==================================================
    #     start_check_errors = [] #리스트
    #     current_positions = {} #딕셔너리

    #     for positioner, motors in POSITIONER_AXIS_MAP.items():

    #         for motor, axis in motors.items():

    #             # 시작 위치 검사에서 잠긴 축 제외
    #             if axis in locked_axes:
    #                 continue
            

    #             current_pos = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].ActPos",
    #                 pyads.PLCTYPE_LREAL
    #             )

    #             # Alpha는 30도, Beta는 150도가 정상 시작 위치
    #             if motor == "alpha":
    #                 expected_pos = 30.0
    #             else:
    #                 expected_pos = 150.0

    #             position_error = abs(current_pos - expected_pos)

    #             current_positions[str(axis)] = {
    #                 "positioner": positioner,
    #                 "motor": motor,
    #                 "expected_position": expected_pos,
    #                 "actual_position": current_pos,
    #                 "position_error": position_error
    #             }

    #             if position_error > start_tolerance:
    #                 start_check_errors.append({
    #                     "positioner": positioner,
    #                     "motor": motor,
    #                     "axis": axis,
    #                     "expected_position": expected_pos,
    #                     "actual_position": current_pos,
    #                     "position_error": position_error
    #                 })

    #     # 하나라도 30도/150도 조건을 벗어나면 이동 금지
    #     if start_check_errors:
    #         result = {
    #             "status": "fail",
    #             "message": (
    #                 "일부 축이 시작 조건인 Alpha 30도, "
    #                 "Beta 150도를 만족하지 않아 0도 이동을 중단했습니다."
    #             ),
    #             "data": {
    #                 "start_tolerance": start_tolerance,
    #                 "invalid_axes": start_check_errors,
    #                 "current_positions": current_positions
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     print("시작 위치 확인 완료: 모든 Alpha=30도, Beta=150도")

    #     # ==================================================
    #     # 모든 축 Power ON
    #     # ==================================================    # print("전 축 0도 이동 준비")

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    # try:
    #     plc.open()


    #     clear_motion_flags(plc)
    #     time.sleep(0.1)

    #     locked_axes, all_axes = read_axis_lock_state(plc)
    #     # all_axes는 잠기지 않는 축만 들어있는 목록

    #     if not all_axes:
    #         result = {
    #             "status": "fail",
    #             "message": "모든 축이 잠겨 있어 0도 이동을 실행할 수 없습니다",
    #             "data": {
    #                 "locked_axes": locked_axes,
    #                 "motion_axes": []
    #             }
    #         }
    #         save_result_json(result)
    #         return result

    #     # ==================================================
    #     # 현재 모든 축이 Alpha=30도, Beta=150도인지 검사
    #     # ==================================================
    #     start_check_errors = [] #리스트
    #     current_positions = {} #딕셔너리

    #     for positioner, motors in POSITIONER_AXIS_MAP.items():

    #         for motor, axis in motors.items():

    #             # 시작 위치 검사에서 잠긴 축 제외
    #             if axis in locked_axes:
    #                 continue
            

    #             current_pos = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].ActPos",
    #                 pyads.PLCTYPE_LREAL
    #             )

    #             # Alpha는 30도, Beta는 150도가 정상 시작 위치
    #             if motor == "alpha":
    #                 expected_pos = 30.0
    #             else:
    #                 expected_pos = 150.0

    #             position_error = abs(current_pos - expected_pos)

    #             current_positions[str(axis)] = {
    #                 "positioner": positioner,
    #                 "motor": motor,
    #                 "expected_position": expected_pos,
    #                 "actual_position": current_pos,
    #                 "position_error": position_error
    #             }

    #             if position_error > start_tolerance:
    #                 start_check_errors.append({
    #                     "positioner": positioner,
    #                     "motor": motor,
    #                     "axis": axis,
    #                     "expected_position": expected_pos,
    #                     "actual_position": current_pos,
    #                     "position_error": position_error
    #                 })

    #     # 하나라도 30도/150도 조건을 벗어나면 이동 금지
    #     if start_check_errors:
    #         result = {
    #             "status": "fail",
    #             "message": (
    #                 "일부 축이 시작 조건인 Alpha 30도, "
    #                 "Beta 150도를 만족하지 않아 0도 이동을 중단했습니다."
    #             ),
    #             "data": {
    #                 "start_tolerance": start_tolerance,
    #                 "invalid_axes": start_check_errors,
    #                 "current_positions": current_positions
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     print("시작 위치 확인 완료: 모든 Alpha=30도, Beta=150도")

    #     # ==================================================
    #     # 모든 축 Power ON
    #     # ==================================================
    #     # all_axes = []

    #     # for motors in POSITIONER_AXIS_MAP.values():
    #     #     for axis in motors.values():
    #     #         all_axes.append(axis)

    #     #         plc.write_by_name(
    #     #             f"GVL.gAxisCmd[{axis}].Power",
    #     #             True,
    #     #             pyads.PLCTYPE_BOOL
    #     #         )

    #     for axis in all_axes:
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].Power",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     time.sleep(1.0)

    #     # ==================================================
    #     # 모든 축에 절대위치 0도 전송
    #     # ==================================================
    #     for axis in all_axes:
    #         prefix = f"GVL.gAxisCmd[{axis}]"

    #         plc.write_by_name(
    #             f"{prefix}.TotalPoints",
    #             1,
    #             pyads.PLCTYPE_INT
    #         )

    #         plc.write_by_name(
    #             f"{prefix}.Velocity",
    #             VELOCITY,
    #             pyads.PLCTYPE_LREAL
    #         )

    #         plc.write_by_name(
    #             f"{prefix}.Acc",
    #             ACC,
    #             pyads.PLCTYPE_LREAL
    #         )

    #         plc.write_by_name(
    #             f"{prefix}.Dec",
    #             DEC,
    #             pyads.PLCTYPE_LREAL
    #         )

    #         # PLC의 TargetPos 배열 크기와 동일해야 함
    #         target_pos_array = (pyads.PLCTYPE_LREAL * 3500)()

    #         # 첫 번째 목표 위치를 절대위치 0도로 지정
    #         target_pos_array[0] = 0.0

    #         plc.write_by_name(
    #             f"{prefix}.TargetPos",
    #             target_pos_array,
    #             pyads.PLCTYPE_LREAL * 3500
    #         )

    #     time.sleep(0.5)

    #     # ==================================================
    #     # 모든 축 Active TRUE
    #     # ==================================================
    #     for axis in all_axes:
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].Active",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     # ==================================================
    #     # 모든 축 StartSpline TRUE
    #     # ==================================================
    #     for axis in all_axes:
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].StartSpline",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     # ==================================================
    #     # PLC가 실제로 출발했는지 확인
    #     # ==================================================
    #     plc_started = False
    #     start_wait_time = time.time()

    #     while time.time() - start_wait_time < 2.0:

    #         if any(
    #             plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )
    #             for axis in all_axes
    #         ):
    #             plc_started = True
    #             break

    #         time.sleep(0.05)

    #     if not plc_started:
    #         result = {
    #             "status": "fail",
    #             "message": "전 축 0도 이동이 시작되지 않았습니다.",
    #             "data": {
    #                 "reason": "No axis entered Busy state",
    #                 "axes": all_axes
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     # ==================================================
    #     # 모든 축의 이동 완료까지 대기
    #     # ==================================================
    #     motion_start_time = time.time()

    #     while True:
    #         moving_axes = 0
    #         status_str = "📍 0도 이동 상태 | "

    #         for axis in all_axes:

    #             is_busy = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             is_error = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Error",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             act_pos = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].ActPos",
    #                 pyads.PLCTYPE_LREAL
    #             )

    #             status_str += f"축{axis}:{act_pos:7.2f}  "

    #             if is_error:
    #                 result = {
    #                     "status": "error",
    #                     "message": (
    #                         f"{axis}번 축의 0도 이동 중 "
    #                         f"PLC 에러가 발생했습니다."
    #                     ),
    #                     "data": {
    #                         "error_axis": axis,
    #                         "actual_position": act_pos
    #                     }
    #                 }

    #                 save_result_json(result)
    #                 return result

    #             if is_busy:
    #                 moving_axes += 1

    #         print(status_str, end="\r")

    #         if moving_axes == 0:
    #             break

    #         if time.time() - motion_start_time > timeout:
    #             result = {
    #                 "status": "fail",
    #                 "message": "전 축 0도 이동 시간이 timeout을 초과했습니다.",
    #                 "data": {
    #                     "timeout": timeout
    #                 }
    #             }

    #             save_result_json(result)
    #             return result

    #         time.sleep(0.1)

    #     # ==================================================
    #     # 최종적으로 모든 축이 0도인지 검사
    #     # ==================================================
    #     final_positions = {}
    #     zero_check_errors = []

    #     for positioner, motors in POSITIONER_AXIS_MAP.items():

    #         for motor, axis in motors.items():

    #             #최종 0도 검사에서 잠긴 축 제외
    #             if axis in locked_axes:
    #                 continue

    #             final_pos = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].ActPos",
    #                 pyads.PLCTYPE_LREAL
    #             )

    #             final_busy = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )
                
    #             final_error = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Error",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             zero_error = abs(final_pos - 0.0)

    #             final_positions[str(axis)] = {
    #                 "positioner": positioner,
    #                 "motor": motor,
    #                 "target_position": 0.0,
    #                 "actual_position": final_pos,
    #                 "position_error": zero_error,
    #                 "busy": final_busy,
    #                 "error": final_error
    #             }

    #             if zero_error > zero_tolerance:
    #                 zero_check_errors.append({
    #                     "positioner": positioner,
    #                     "motor": motor,
    #                     "axis": axis,
    #                     "target_position": 0.0,
    #                     "actual_position": final_pos,
    #                     "position_error": zero_error
    #                 })

    #     if zero_check_errors:
    #         result = {
    #             "status": "fail",
    #             "message": (
    #                 "0도 이동은 종료되었지만 일부 축이 "
    #                 "0도 허용오차를 벗어났습니다."
    #             ),
    #             "data": {
    #                 "zero_tolerance": zero_tolerance,
    #                 "invalid_axes": zero_check_errors,
    #                 "final_positions": final_positions
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     result = {
    #         "status": "success",
    #         "message": "잠기지 않은 모든 포지셔너 축이 0도로 이동했습니다.",
    #         "data": {
    #             "start_tolerance": start_tolerance,
    #             "zero_tolerance": zero_tolerance,
    #             "motion_axes": all_axes,
    #             "locked_axes": locked_axes,
    #             "final_positions": final_positions
    #         }
    #     }

    #     save_result_json(result)
    #     return result

    # except pyads.ADSError as e:
    #     result = {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # except Exception as e:
    #     result = {
    #         "status": "error",
    #         "message": f"예상하지 못한 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # finally:
    #     try:
    #         clear_motion_flags(plc)
    #     except Exception:
    #         pass

    #     try:
    #         plc.close()
    #         print("\n연결 종료")
    #     except Exception:
    #         pass
    #     # all_axes = []

    #     # for motors in POSITIONER_AXIS_MAP.values():
    #     #     for axis in motors.values():
    #     #         all_axes.append(axis)

    #     #         plc.write_by_name(
    #     #             f"GVL.gAxisCmd[{axis}].Power",
    #     #             True,
    #     #             pyads.PLCTYPE_BOOL
    #     #         )

    #     for axis in all_axes:
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].Power",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     time.sleep(1.0)

    #     # ==================================================
    #     # 모든 축에 절대위치 0도 전송
    #     # ==================================================
    #     for axis in all_axes:
    #         prefix = f"GVL.gAxisCmd[{axis}]"

    #         plc.write_by_name(
    #             f"{prefix}.TotalPoints",
    #             1,
    #             pyads.PLCTYPE_INT
    #         )

    #         plc.write_by_name(
    #             f"{prefix}.Velocity",
    #             VELOCITY,
    #             pyads.PLCTYPE_LREAL
    #         )

    #         plc.write_by_name(
    #             f"{prefix}.Acc",
    #             ACC,
    #             pyads.PLCTYPE_LREAL
    #         )

    #         plc.write_by_name(
    #             f"{prefix}.Dec",
    #             DEC,
    #             pyads.PLCTYPE_LREAL
    #         )

    #         # PLC의 TargetPos 배열 크기와 동일해야 함
    #         target_pos_array = (pyads.PLCTYPE_LREAL * 3500)()

    #         # 첫 번째 목표 위치를 절대위치 0도로 지정
    #         target_pos_array[0] = 0.0

    #         plc.write_by_name(
    #             f"{prefix}.TargetPos",
    #             target_pos_array,
    #             pyads.PLCTYPE_LREAL * 3500
    #         )

    #     time.sleep(0.5)

    #     # ==================================================
    #     # 모든 축 Active TRUE
    #     # ==================================================
    #     for axis in all_axes:
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].Active",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     # ==================================================
    #     # 모든 축 StartSpline TRUE
    #     # ==================================================
    #     for axis in all_axes:
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].StartSpline",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     # ==================================================
    #     # PLC가 실제로 출발했는지 확인
    #     # ==================================================
    #     plc_started = False
    #     start_wait_time = time.time()

    #     while time.time() - start_wait_time < 2.0:

    #         if any(
    #             plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )
    #             for axis in all_axes
    #         ):
    #             plc_started = True
    #             break

    #         time.sleep(0.05)

    #     if not plc_started:
    #         result = {
    #             "status": "fail",
    #             "message": "전 축 0도 이동이 시작되지 않았습니다.",
    #             "data": {
    #                 "reason": "No axis entered Busy state",
    #                 "axes": all_axes
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     # ==================================================
    #     # 모든 축의 이동 완료까지 대기
    #     # ==================================================
    #     motion_start_time = time.time()

    #     while True:
    #         moving_axes = 0
    #         status_str = "📍 0도 이동 상태 | "

    #         for axis in all_axes:

    #             is_busy = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             is_error = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Error",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             act_pos = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].ActPos",
    #                 pyads.PLCTYPE_LREAL
    #             )

    #             status_str += f"축{axis}:{act_pos:7.2f}  "

    #             if is_error:
    #                 result = {
    #                     "status": "error",
    #                     "message": (
    #                         f"{axis}번 축의 0도 이동 중 "
    #                         f"PLC 에러가 발생했습니다."
    #                     ),
    #                     "data": {
    #                         "error_axis": axis,
    #                         "actual_position": act_pos
    #                     }
    #                 }

    #                 save_result_json(result)
    #                 return result

    #             if is_busy:
    #                 moving_axes += 1

    #         print(status_str, end="\r")

    #         if moving_axes == 0:
    #             break

    #         if time.time() - motion_start_time > timeout:
    #             result = {
    #                 "status": "fail",
    #                 "message": "전 축 0도 이동 시간이 timeout을 초과했습니다.",
    #                 "data": {
    #                     "timeout": timeout
    #                 }
    #             }

    #             save_result_json(result)
    #             return result

    #         time.sleep(0.1)

    #     # ==================================================
    #     # 최종적으로 모든 축이 0도인지 검사
    #     # ==================================================
    #     final_positions = {}
    #     zero_check_errors = []

    #     for positioner, motors in POSITIONER_AXIS_MAP.items():

    #         for motor, axis in motors.items():

    #             #최종 0도 검사에서 잠긴 축 제외
    #             if axis in locked_axes:
    #                 continue

    #             final_pos = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].ActPos",
    #                 pyads.PLCTYPE_LREAL
    #             )

    #             final_busy = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )
                
    #             final_error = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Error",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             zero_error = abs(final_pos - 0.0)

    #             final_positions[str(axis)] = {
    #                 "positioner": positioner,
    #                 "motor": motor,
    #                 "target_position": 0.0,
    #                 "actual_position": final_pos,
    #                 "position_error": zero_error,
    #                 "busy": final_busy,
    #                 "error": final_error
    #             }

    #             if zero_error > zero_tolerance:
    #                 zero_check_errors.append({
    #                     "positioner": positioner,
    #                     "motor": motor,
    #                     "axis": axis,
    #                     "target_position": 0.0,
    #                     "actual_position": final_pos,
    #                     "position_error": zero_error
    #                 })

    #     if zero_check_errors:
    #         result = {
    #             "status": "fail",
    #             "message": (
    #                 "0도 이동은 종료되었지만 일부 축이 "
    #                 "0도 허용오차를 벗어났습니다."
    #             ),
    #             "data": {
    #                 "zero_tolerance": zero_tolerance,
    #                 "invalid_axes": zero_check_errors,
    #                 "final_positions": final_positions
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     result = {
    #         "status": "success",
    #         "message": "잠기지 않은 모든 포지셔너 축이 0도로 이동했습니다.",
    #         "data": {
    #             "start_tolerance": start_tolerance,
    #             "zero_tolerance": zero_tolerance,
    #             "motion_axes": all_axes,
    #             "locked_axes": locked_axes,
    #             "final_positions": final_positions
    #         }
    #     }

    #     save_result_json(result)
    #     return result

    # except pyads.ADSError as e:
    #     result = {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # except Exception as e:
    #     result = {
    #         "status": "error",
    #         "message": f"예상하지 못한 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }

    #     save_result_json(result)
    #     return result

    # finally:
    #     try:
    #         clear_motion_flags(plc)
    #     except Exception:
    #         pass

    #     try:
    #         plc.close()
    #         print("\n연결 종료")
    #     except Exception:
    #         pass

# if __name__ == "__main__":
#     zero_main()
#endregion




# --------------------------- check zero positions -------------------------
# region
def check_all_zero_positions(
    zero_tolerance: float = 0.1,
    include_locked_axes: bool = False
):
    """
    현재 모든 positioner 축이 0도인지 확인하는 독립 함수.

    include_locked_axes=True이면 잠긴 축까지 포함해서 1~10번 모든 축을 검사한다.
    include_locked_axes=False이면 잠긴 축은 검사에서 제외한다.
    """

    ## region for simulation
    result = {
                "status": "success",
                "message": "검사 대상 모든 축이 0도 위치에 있습니다.",
                "data": {
                    "zero_tolerance": zero_tolerance,
                    "include_locked_axes": include_locked_axes,
                    "locked_axes": 1,
                    "unlocked_axes": 2,
                    "final_positions": 2
                }
            }
    return result

    ## end region for simulation

    # print("전 축 0도 위치 확인")

    # plc = pyads.Connection(AMS_NET_ID, AMS_PORT)

    # try:
    #     plc.open()

    #     locked_axes, unlocked_axes = read_axis_lock_state(plc)
    #     locked_axis_set = set(locked_axes)

    #     final_positions = {}
    #     zero_check_errors = []

    #     for positioner, motors in POSITIONER_AXIS_MAP.items():

    #         for motor, axis in motors.items():

    #             if not include_locked_axes and axis in locked_axis_set:
    #                 continue

    #             final_pos = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].ActPos",
    #                 pyads.PLCTYPE_LREAL
    #             )

    #             final_busy = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Busy",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             final_error = plc.read_by_name(
    #                 f"GVL.gAxisState[{axis}].Error",
    #                 pyads.PLCTYPE_BOOL
    #             )

    #             zero_error = abs(final_pos - 0.0)

    #             final_positions[str(axis)] = {
    #                 "positioner": positioner,
    #                 "motor": motor,
    #                 "target_position": 0.0,
    #                 "actual_position": final_pos,
    #                 "position_error": zero_error,
    #                 "busy": final_busy,
    #                 "error": final_error,
    #                 "locked": axis in locked_axis_set
    #             }

    #             if zero_error > zero_tolerance:
    #                 zero_check_errors.append({
    #                     "positioner": positioner,
    #                     "motor": motor,
    #                     "axis": axis,
    #                     "target_position": 0.0,
    #                     "actual_position": final_pos,
    #                     "position_error": zero_error,
    #                     "locked": axis in locked_axis_set
    #                 })

    #     if zero_check_errors:
    #         result = {
    #             "status": "fail",
    #             "message": "일부 축이 0도 허용오차를 벗어났습니다.",
    #             "data": {
    #                 "zero_tolerance": zero_tolerance,
    #                 "include_locked_axes": include_locked_axes,
    #                 "locked_axes": locked_axes,
    #                 "unlocked_axes": unlocked_axes,
    #                 "invalid_axes": zero_check_errors,
    #                 "final_positions": final_positions
    #             }
    #         }
    #     else:
    #         result = {
    #             "status": "success",
    #             "message": "검사 대상 모든 축이 0도 위치에 있습니다.",
    #             "data": {
    #                 "zero_tolerance": zero_tolerance,
    #                 "include_locked_axes": include_locked_axes,
    #                 "locked_axes": locked_axes,
    #                 "unlocked_axes": unlocked_axes,
    #                 "final_positions": final_positions
    #             }
    #         }

    #     save_result_json(result)
    #     return result

    # except pyads.ADSError as e:
    #     result = {
    #         "status": "error",
    #         "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }
    #     save_result_json(result)
    #     return result

    # except Exception as e:
    #     result = {
    #         "status": "error",
    #         "message": f"예상하지 못한 에러가 발생했습니다: {e}",
    #         "data": {}
    #     }
    #     save_result_json(result)
    #     return result

    # finally:
    #     try:
    #         plc.close()
    #     except Exception:
    #         pass

# endregion
