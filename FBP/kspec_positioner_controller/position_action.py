############### 코드 주의사항
# 네번째 요구사항은 역순이후 1단계에서 절대각도 0.0도로 맞추기때문에 step 단계가 하나 더 늘어남. 3001개의 step이 생기면 애러가 날 수 있음
# Homed 확인은 아직 없음.

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


ALPHA_FILE = "alpha_tile0001.json"
BETA_FILE = "beta_tile0001.json"

POSITIONER_AXIS_MAP = {
    "A1": {"alpha": 1, "beta": 2},
    "A2": {"alpha": 3, "beta": 4},
    "A3": {"alpha": 5, "beta": 6},
    "A4": {"alpha": 7, "beta": 8},
    "A5": {"alpha": 9, "beta": 10},
}

def read_json(alpha_filename: str, beta_filename: str):

    with open(alpha_filename, 'r', encoding='utf-8') as f:
        alpha_data = json.load(f)
    with open(beta_filename, 'r', encoding='utf-8') as f:
        beta_data = json.load(f)

    total_steps = len(alpha_data["step"])


    if total_steps > 3500:
        raise ValueError(f"step 개수가 3500개를 초과했습니다: {total_steps}")

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





# 첫번째 요구사항
# =======================================================================
# =======================================================================
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


def clear_motion_flags(plc):
    for motors in POSITIONER_AXIS_MAP.values():
        for axis in motors.values():
            plc.write_by_name(f"GVL.gAxisCmd[{axis}].StartSpline", False, pyads.PLCTYPE_BOOL)
            plc.write_by_name(f"GVL.gAxisCmd[{axis}].Active", False, pyads.PLCTYPE_BOOL)

def rotate_one(
    positioner: str,
    motor: str, 
    angle: float,
    velocity: float = VELOCITY,
    acc: float = ACC,
    dec: float = DEC,
    timeout: float = 30.0,
):
    return {
            "status": "success",
            "message": f"Rotate Positioner {positioner} {motor} by {angle} successfully.", "target_angle": angle
        }
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

    #     # -------------------------------------------------
    #     # 5. Active / StartSpline 설정
    #     # Active TRUE인 축만 움직임
    #     # -------------------------------------------------
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


# 두번째 요구사항
# =======================================================================
# =======================================================================
# show_status용 전체 코드
# region  
def show_status(axis: str):
    print('Hi')
    return {
            "status": "success",
            "message": f"현재 상태 확인 완료",
        }


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

    #     alpha_powered = plc.read_by_name(
    #         f"GVL.gAxisState[{alpha_axis}].Powered",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     alpha_homed = plc.read_by_name(
    #         f"GVL.gAxisState[{alpha_axis}].Homed",
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

    #     beta_powered = plc.read_by_name(
    #         f"GVL.gAxisState[{beta_axis}].Powered",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     beta_homed = plc.read_by_name(
    #         f"GVL.gAxisState[{beta_axis}].Homed",
    #         pyads.PLCTYPE_BOOL
    #     )

    #     return {
    #         "status": "success",
    #         "message": f"{positioner} 현재 상태 확인 완료",
    #         "data": {
    #             "fiber": positioner,

    #             "alpha": {
    #                 "axis": alpha_axis,
    #                 "current_angle_degree": alpha_angle,
    #                 "busy": alpha_busy,
    #                 "error": alpha_error,
    #                 "powered": alpha_powered,
    #                 "homed": alpha_homed,
    #             },

    #             "beta": {
    #                 "axis": beta_axis,
    #                 "current_angle_degree": beta_angle,
    #                 "busy": beta_busy,
    #                 "error": beta_error,
    #                 "powered": beta_powered,
    #                 "homed": beta_homed,
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



# 세번째 요구사항
# =======================================================================
# =======================================================================
# 각 함수에 return 값으로 dictionary 형태의 반환값 json 파일로 만들기.
# main()과 함꼐 실행
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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"main_result_{timestamp}.json")

    # 저장된 파일 경로도 결과 dictionary 안에 넣기
    result["result_file"] = output_file

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    return output_file
# endregion


# 네번째 요구사항
# =======================================================================
# =======================================================================
# path의 역순으로 보내는 함수 + 1단계에서 0도로 가는 기능 추가
# region 
def make_reverse_axis_points_to_zero(
    axis_points: dict,
    zero_position: float = 0.0,
    max_points: int = 3500
):
    """
    JSON에 들어 있는 1단계 ~ n단계 path를 역순으로 뒤집고,
    마지막에 0단계인 절대위치 0도를 추가하는 함수.

    예:
        [10, 20, 30, 50]
        ->
        [50, 30, 20, 10, 0.0]

    의미:
        n단계 -> ... -> 2단계 -> 1단계 까지는 기존 path 역순
        1단계 -> 0단계 는 PLC 절대위치 0.0도로 이동
    """

    reverse_axis_points = {}

    for axis, points in axis_points.items():
        reverse_points = list(reversed(points))   #n단계 -> 1단계

        # # 마지막에 0단계 절대위치 0도 추가
        # reverse_points.append(float(zero_position)) #1단계 -> 0단계

        if len(reverse_points) > max_points:
            raise ValueError(
                f"{axis}번 축 reverse path 개수가 {max_points}개를 초과했습니다. "
                f"현재 개수: {len(reverse_points)}"
            )

        reverse_axis_points[axis] = reverse_points

    reverse_total_steps = len(next(iter(reverse_axis_points.values())))

    return reverse_axis_points, reverse_total_steps

#endregion



# --------------------------------main()---------------------------------
# =======================================================================
# =======================================================================
# =======================================================================
# =======================================================================
# 세번째 요구사항을 실행 시 같이 실행
# region 
# def rotate_all():
def rotate_all():
    print("포지셔너 구동 시작")
    result = {
            "status": "success",
            "message": f"All Positioners movement finished.",
        }
    return result

    # try:
    #     axis_points, total_steps = read_json(ALPHA_FILE, BETA_FILE)
    #     axis_points, total_steps = make_reverse_axis_points_to_zero(axis_points)

    #     # # 네번째 요구사항 : 역순 path + 마지막 절대 위치 0도
    #     # for axis in axis_points.keys():
    #     #     axis_points[axis] = list(reversed(axis_points[axis]))
    #     #     axis_points[axis].append(0.0)

    #     # total_steps += 1

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

    #     clear_motion_flags(plc)
    #     time.sleep(0.1)

    #     for axis in axis_points.keys():
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].Power",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     time.sleep(1.0)

    #     for axis, points in axis_points.items():
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

    #     for axis in axis_points.keys():
    #         plc.write_by_name(
    #             f"GVL.gAxisCmd[{axis}].Active",
    #             True,
    #             pyads.PLCTYPE_BOOL
    #         )

    #     for axis in axis_points.keys():
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
    #             for axis in axis_points.keys()
    #         ):
    #             plc_started = True
    #             break

    #         time.sleep(0.05)

    #     if not plc_started:
    #         result = {
    #             "status": "fail",
    #             "message": "PLC가 출발하지 않았습니다.",
    #             "data": {
    #                 "reason": "No axis entered Busy state",
    #                 "axes": list(axis_points.keys()),
    #                 "total_steps": total_steps
    #             }
    #         }

    #         save_result_json(result)
    #         return result

    #     while True:
    #         moving_axes = 0     #이번 반복에서 몇 개 축이 움직이는지 세는 변수
    #         status_str = "📍 상태 | "  # 현재 축 상태를 보기 좋게 출력하기 위한 문자열

    #         for axis in axis_points.keys():
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
    #                     "message": f"{axis}번 축에서 에러가 발생했습니다.",
    #                     "data": {
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

    #         if moving_axes == 0:
    #             break

    #         time.sleep(0.1)

    #     final_positions = {}

    #     for axis in axis_points.keys():
    #         final_pos = plc.read_by_name(
    #             f"GVL.gAxisState[{axis}].ActPos",
    #             pyads.PLCTYPE_LREAL
    #         )

    #         final_positions[str(axis)] = {
    #             "actual_position": final_pos
    #         }

    #     result = {
    #         "status": "success",
    #         "message": "All positioners rotated successfully.",
    #         "data": {
    #             "total_steps": total_steps,
    #             "axes": list(axis_points.keys()),
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

# def initial():
            
if __name__ == "__main__":
    main()
# endregion




