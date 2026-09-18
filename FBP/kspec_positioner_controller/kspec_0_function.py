import time
import json
import pyads
import os
import asyncio
from datetime import datetime

######
##PLC 1
PLC1_AMS_NET_ID = "172.18.233.11.1.1" 
PLC1_AMS_PORT = 851

#PLC 2
PLC2_AMS_NET_ID = "172.18.233.112.1.1"
PLC2_AMS_PORT = 851


VELOCITY = 10.0
ACC = 200.0
DEC = 200.0

# ALPHA_FILE = "config55_0005.alpha.json"
# BETA_FILE = "config55_0005.beta.json"

# 알파, 베타 경로 json 파일
FBP_DIR = os.path.dirname(os.path.abspath(__file__))
# print(CONTROLLER_DIR)

# FBP_DIR = os.path.dirname(CONTROLLER_DIR)
# print(FBP_DIR)
DATA_DIR = os.path.join(FBP_DIR, "data")

#결과 json Log 파일
LOG_DIR = os.path.join(FBP_DIR, "Log")



# POSITIONER_AXIS_MAP 불러오기
LIB_DIR = os.path.join(FBP_DIR, "Lib")
POSITIONER_AXIS_MAP_FILE = os.path.join(LIB_DIR, "positioner_axis_map.json")

ALPHA_FILE = os.path.join(DATA_DIR, "config55_0005_converted3.alpha.json")
BETA_FILE = os.path.join(DATA_DIR, "config55_0005_converted3.beta.json")



# PLC step 동기화용 전역 변수 이름
# PLC 코드에도 동일한 이름/자료형(INT)으로 추가해야 한다.
STEP_SYNC_COMPLETED_TAG = "GVL.gCompletedStep"
STEP_SYNC_ALLOWED_TAG = "GVL.gAllowedStep"

# global_axis(실제 축 번호) 
# local_axis(PLC가 인식하는 축 번호)
# region
# POSITIONER_AXIS_MAP = {
#     "A1": {
#         "plc": "PLC1",
#         "alpha": {
#             "global_axis": 1,
#             "local_axis": 1,
#         },
#         "beta": {
#             "global_axis": 2,
#             "local_axis": 2,
#         },
#     },

#     "A2": {
#         "plc": "PLC1",
#         "alpha": {
#             "global_axis": 3,
#             "local_axis": 3,
#         },
#         "beta": {
#             "global_axis": 4,
#             "local_axis": 4,
#         },
#     },
#     "A3": {
#         "plc": "PLC1",
#         "alpha": {
#             "global_axis": 5,
#             "local_axis": 5,
#         },
#         "beta": {
#             "global_axis": 6,
#             "local_axis": 6,
#         },
#     },
#     "A4": {
#         "plc": "PLC2",
#         "alpha": {
#             "global_axis": 7,
#             "local_axis": 1,
#         },
#         "beta": {
#             "global_axis": 8,
#             "local_axis": 2,
#         },
#     },
#     "A5": {
#         "plc": "PLC2",
#         "alpha": {
#             "global_axis": 9,
#             "local_axis": 3,
#         },
#         "beta": {
#             "global_axis": 10,
#             "local_axis": 4,
#         },
#     },   
# }
# endregion

def load_positioner_axis_map():
    """
    
    Lib/positioner_axis_map.json 파일에서
    포지셔너 축 매핑 정보를 읽는다.
    
    """

    with open(POSITIONER_AXIS_MAP_FILE, "r", encoding="utf-8") as f:
        positioner_axis_map = json.load(f)


    return positioner_axis_map

POSITIONER_AXIS_MAP = load_positioner_axis_map()




##################################################################################
##################################################################################
##################################################################################
##################################################################################
##################################################################################
##################################################################################

##
def read_json(
        alpha_filename: str,
        beta_filename: str
        ):

    """
    alpha/beta JSON을 읽고 global_axis 기준 경로를 반환한다.

    """

    with open(alpha_filename, "r", encoding="utf-8") as f:
        alpha_data = json.load(f)
    with open(beta_filename, "r", encoding="utf-8") as f:
        beta_data = json.load(f)

    total_steps = len(alpha_data["step"])

    if total_steps <= 0:
        raise ValueError("JSON step 데이터가 비어 있습니다.")

    if total_steps > 3500:
        raise ValueError(
            f"JSON step 개수가 3500개를 초과했습니다: "
            f"{total_steps}"
        )

    if len(beta_data["step"]) != total_steps:
        raise ValueError(
            f"alpha/beta step 개수가 다릅니다. "
            f"alpha={total_steps}, "
            f"beta={len(beta_data['step'])}"
        )

    axis_points = {}

    for positioner, positioner_info in POSITIONER_AXIS_MAP.items():
        #positioner = "A1"
        #positioner_info = {"alpha": 1, "beta": 2}
    

        if positioner not in alpha_data:
            raise KeyError(f"alpha JSON에 {positioner} 데이터가 없습니다.")

        if positioner not in beta_data:
            raise KeyError(f"beta JSON에 {positioner} 데이터가 없습니다.")

        if len(alpha_data[positioner]) != total_steps:
            raise ValueError(
                f"alpha {positioner} 데이터 길이가 "
                f"step 개수와 다릅니다. "
                f"{len(alpha_data[positioner])} "
                f"!= {total_steps}"
            )

        if len(beta_data[positioner]) != total_steps:
            raise ValueError(
                f"beta {positioner} 데이터 길이가 "
                f"step 개수와 다릅니다. "
                f"{len(beta_data[positioner])} "
                f"!= {total_steps}"
            )

        alpha_global_axis = (positioner_info["alpha"]["global_axis"])

        beta_global_axis = (positioner_info["beta"]["global_axis"])

        axis_points[alpha_global_axis] = (alpha_data[positioner])

        axis_points[beta_global_axis] = (beta_data[positioner])

    return axis_points, total_steps

##
def get_plc_connection_info(
        plc_name: str
        ):

    """
    PLC 이름을 받아 AMS Net ID와 ADS Port를 반환한다.
    
    """

    plc_name = plc_name.strip().upper()

    if plc_name == "PLC1":
        return PLC1_AMS_NET_ID, PLC1_AMS_PORT

    if plc_name == "PLC2":
        return PLC2_AMS_NET_ID, PLC2_AMS_PORT

    raise ValueError(f"존재하지 않는 PLC입니다: {plc_name}")



##모션 플래그 초기화
def clear_motion_flags(
        plc, 
        plc_name: str
        ):

    """
    지정한 PLC가 담당하는 축의
    StartSpline과 Active를 False로 초기화한다.
    
    """

    plc_name = plc_name.strip().upper()

    get_plc_connection_info(plc_name)

    local_axes = set()

    for positioner_info in POSITIONER_AXIS_MAP.values():

        if positioner_info["plc"] != plc_name:
            continue

        local_axes.add(positioner_info["alpha"]["local_axis"])

        local_axes.add(positioner_info["beta"]["local_axis"])

    for local_axis in sorted(local_axes):

        plc.write_by_name(
            f"GVL.gAxisCmd[{local_axis}].StartSpline",
            False,
            pyads.PLCTYPE_BOOL
        )

        plc.write_by_name(
            f"GVL.gAxisCmd[{local_axis}].Active",
            False,
            pyads.PLCTYPE_BOOL
        )
## 
async def clear_one_plc_motion_flags(
        plc_name: str, 
        plc
        ):
    """
    PLC 한 대가 담당하는 축의 StartSpline과 Active를 False로 초기화 한다.
    
    """

    await asyncio.to_thread(
        clear_motion_flags,
        plc,
        plc_name
    )

    # print(f"{plc_name} 모션 플래그 초기화 완료")



## 요구사항 3번 : 코드 실행후 json파일 생성
def save_result_json(
        result: dict, 
        output_dir: str | None = None
        ) -> str:

    """
    실행 결과를 JSON 파일로 저장한다.

    """

    if output_dir is None:
        output_dir = LOG_DIR

    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_file = os.path.join(output_dir, f"result_{timestamp}.json")

    result["result_file"] = output_file

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    return output_file



##
def create_plc_connection(
        plc_name: str
        ):
    """
    PLC 이름에 맞는 pyads 연결 객체를 생성한다.
    
    여기서는 연결 객체만 만들며,
    실제 plc.open()은 비동기 함수에서 실행한다.
    
    """

    ams_net_id, ams_port = get_plc_connection_info(plc_name)

    return pyads.Connection(ams_net_id, ams_port)
##
async def open_one_plc(
        plc_name: str, 
        plc
        ):
    """
    pyads의 동기식 plc.open()을 별도 스레드에서 실행한다.
    
    """

    await asyncio.to_thread(plc.open) # PLC 연결 작업은 별도 스레드에서 실행

    # print(f"{plc_name} 연결 완료")

    return plc_name



##
def build_global_axis_routes(
        
):
    """
    global_axis를 기준으로 각 축의 전체 경로 정보를 만든다.
    
    예:
        global_axis 7
        -> PLC2
        -> local_axis 1
        -> A4 alpha
        
    """

    global_axis_routes = {}

    for positioner, positioner_info in POSITIONER_AXIS_MAP.items():

        plc_name = positioner_info["plc"]

        for motor in ("alpha", "beta"):

            motor_info = positioner_info[motor]

            global_axis = motor_info["global_axis"]
            local_axis = motor_info["local_axis"]

            global_axis_routes[global_axis] = {
                "positioner": positioner,
                "motor": motor,
                "plc_name": plc_name,
                "global_axis": global_axis,
                "local_axis": local_axis,
            }
    return global_axis_routes


## 정방향 // main()
MOTION_MODE_FORWARD = 1 
## 
def set_forward_mode_sync(
        plc_name: str,
        plc
        ):
    """
    PLC 한 대에 정방향 모드를 설정한다.

    Stop 기록은 여기서 삭제하지 않는다.
    Stop 기록은 Stop 후 복귀에 사용하기 위해 유지한다.
    """

    # 정방향 main() 명령
    plc.write_by_name(
        "GVL.gMotionModeCommand",
        1,
        pyads.PLCTYPE_INT
    )

    # print(
    #     f"{plc_name} 정방향 모드 설정 완료"
    # )
async def set_forward_mode(
        plc_name: str,
        plc
        ):
    """
    동기식 정방향 모드 설정 함수를
    별도 스레드에서 실행한다.
    """

    await asyncio.to_thread(
        set_forward_mode_sync,
        plc_name,
        plc
    )



## 역방향 // reverse_main()
MOTION_MODE_REVERSE = 2 
##
def reverse_step_to_firststep(
    axis_points: dict,
    max_points: int = 3500
):
    """
    JSON의 1단계 ~ n단계 경로를
    n단계 ~ 1단계 순서로 뒤집는다.

    alpha, beta가 0도까지 가는게 아니라 1단계 까지만 감.
    """

    reverse_axis_points = {}

    for axis, points in axis_points.items():

        reverse_points = list(reversed(points))

        if len(reverse_points) > max_points:
            raise ValueError(
                f"{axis}번 전역축 reverse path 개수가 "
                f"{max_points}개를 초과했습니다: "
                f"{len(reverse_points)}"
            )

        reverse_axis_points[axis] = reverse_points

    if not reverse_axis_points:
        raise ValueError(
            "reverse path로 변환할 축 데이터가 없습니다."
        )

    reverse_total_steps = len(
        next(iter(reverse_axis_points.values()))
    )

    return reverse_axis_points, reverse_total_steps
## 
def set_reverse_mode_sync(
    plc_name: str,
    plc
):
    """
    정상 main() 완료 위치에서
    1단계까지 복귀하는 reverse_main() 모드.
    """

    plc.write_by_name(
        "GVL.gMotionModeCommand",
        2,
        pyads.PLCTYPE_INT
    )
async def set_reverse_mode(
    plc_name: str,
    plc
):
    await asyncio.to_thread(
        set_reverse_mode_sync,
        plc_name,
        plc
    )



##
def power_on_one_plc_sync(
        plc_name: str, 
        plc, routes: list
        ):
    """
    PLC 한 대에서 이번에 실제로 움직일 축만 
    Power = True로 설정한다.
    
    routes 안의 local_axis를 사용한다.
    """

    for route in routes:
        local_axis = route["local_axis"]

        plc.write_by_name(
            f"GVL.gAxisCmd[{local_axis}].Power",
            True,
            pyads.PLCTYPE_BOOL
        )

    # print(f"{plc_name} 구동 축 Power ON 완료")
async def power_on_one_plc(
        plc_name: str, 
        plc, 
        routes: list
        ):
    """
    PLC 한 대의 Power ON 작업을 별도 스레드에서 실행한다.
    
    """
    await asyncio.to_thread(
        power_on_one_plc_sync,
        plc_name,
        plc,
        routes
    )

##
def send_path_to_one_plc_sync(
        plc_name: str,
        plc,
        routes: list,
        axis_points: dict,
        total_steps: int
):
    """
    PLC 한 대가 담당하는 구동 축에 경로 데이터를 전송한다.
    
    axis_points는 global_axis로 찾고,
    PLC 명령은 local_axis로 전송한다.
    
    """

    for route in routes:

        global_axis = route["global_axis"]
        local_axis = route["local_axis"]

        #Json에서 해당 전역 축의 경로를 가져온다.
        points = axis_points[global_axis]

        #PLC 내부에서는 local_axis를 사용한다.
        prefix = f"GVL.gAxisCmd[{local_axis}]"


        plc.write_by_name(
            f"{prefix}.TotalPoints",
            total_steps,
            pyads.PLCTYPE_INT
        )

        plc.write_by_name(
            f"{prefix}.Velocity",
            VELOCITY,
            pyads.PLCTYPE_LREAL
        )

        plc.write_by_name(
            f"{prefix}.Acc",
            ACC,
            pyads.PLCTYPE_LREAL
        )

        plc.write_by_name(
            f"{prefix}.Dec",
            DEC,
            pyads.PLCTYPE_LREAL
        )

        # PLC TargetPos 배열 크기와 같은 3500칸 배열 생성
        target_pos_array = (pyads.PLCTYPE_LREAL * 3500)()

        # 실제 JSON 경로를 배열 앞부분에 저장
        for index in range(total_steps):
            target_pos_array[index] = float(points[index])

        plc.write_by_name(
            f"{prefix}.TargetPos",
            target_pos_array,
            pyads.PLCTYPE_LREAL * 3500
        )

    # print(f"{plc_name} 경로 데이터 전송 완료")
async def send_path_to_one_plc(
        plc_name: str,
        plc,
        routes: list,
        axis_points: dict,
        total_steps: int
):
    """
    PLC 한 대의 경로 전송 작업을 
    별도 스레드에서 실행한다.
    
    """
    await asyncio.to_thread(
        send_path_to_one_plc_sync,
        plc_name,
        plc,
        routes,
        axis_points,
        total_steps
    )

##
def activate_one_plc_sync(
    plc_name: str,
    plc,
    routes: list
):
    """
    PLC 한 대에서 이번에 움직일 축의
    Active를 True로 설정한다.
    """

    for route in routes:

        local_axis = route["local_axis"]

        plc.write_by_name(
            f"GVL.gAxisCmd[{local_axis}].Active",
            True,
            pyads.PLCTYPE_BOOL
        )

    # print(f"{plc_name} 구동 축 Active 설정 완료")
async def activate_one_plc(
    plc_name: str,
    plc,
    routes: list
):
    """
    PLC 한 대의 Active 설정 작업을
    별도 스레드에서 실행한다.
    """

    await asyncio.to_thread(
        activate_one_plc_sync,
        plc_name,
        plc,
        routes
    )

##
def start_one_plc_sync(
    plc_name: str,
    plc,
    routes: list
):
    """
    PLC 한 대에서 이번에 움직일 축의
    StartSpline을 True로 설정한다.
    """

    for route in routes:

        local_axis = route["local_axis"]

        plc.write_by_name(
            f"GVL.gAxisCmd[{local_axis}].StartSpline",
            True,
            pyads.PLCTYPE_BOOL
        )

    # print(f"{plc_name} StartSpline 전송 완료")
async def start_one_plc(
    plc_name: str,
    plc,
    routes: list
):
    """
    PLC 한 대의 StartSpline 전송 작업을
    별도 스레드에서 실행한다.
    """

    await asyncio.to_thread(
        start_one_plc_sync,
        plc_name,
        plc,
        routes
    )

    return plc_name


################################################################
########################## step 동기화 ##########################
################################################################
def set_allowed_step_one_plc_sync(
    plc_name: str,
    plc,
    allowed_step: int
):
    """
    PLC 한 대에 진행 가능한 최대 step 번호를 전달한다.

    예:
        allowed_step = 1
        -> PLC는 1번 step까지만 실행 가능

        allowed_step = 2
        -> 1번 step 완료 후 2번 step 실행 가능

    PLC는 각 step을 완료하면 GVL.gCompletedStep을 갱신하고,
    다음 step 번호가 GVL.gAllowedStep 이하가 될 때까지 대기해야 한다.
    """

    if allowed_step < 1:
        raise ValueError(
            f"{plc_name} allowed_step은 1 이상이어야 합니다: "
            f"{allowed_step}"
        )

    plc.write_by_name(
        STEP_SYNC_ALLOWED_TAG,
        int(allowed_step),
        pyads.PLCTYPE_INT
    )

    return plc_name
async def set_allowed_step_all_plcs(
    plc_connections: dict,
    plc_names: list,
    allowed_step: int
):
    """
    실제 구동에 참여하는 모든 PLC에 같은 allowed step을
    최대한 동시에 전달한다.
    """

    return await asyncio.gather(
        *[
            asyncio.to_thread(
                set_allowed_step_one_plc_sync,
                plc_name,
                plc_connections[plc_name],
                allowed_step
            )
            for plc_name in plc_names
        ]
    )



## 초반 에러 검사
def wait_one_plc_started_sync(
        plc_name: str,
        plc,
        routes: list,
        sequence_before: int,
        timeout: float = 2.0
        ):

    """
    PLC가 새로운 모션 명령을 정상적으로 접수했는지
    gMotionSequence 변화로 확인한다.
    
    축 하나라도 Error=True이면 즉시 실패한다.
    
    """
    start_time = time.time()
    sequence_now = sequence_before

    while time.time() - start_time <= timeout:

        error_axes = []

        # 구동 대상 축 Error 확인
        for route in routes:

            global_axis = route["global_axis"]
            local_axis = route["local_axis"]

            is_error = plc.read_by_name(
                f"GVL.gAxisState[{local_axis}].Error",
                pyads.PLCTYPE_BOOL
            )

            if is_error:
                error_axes.append({
                    "global_axis": global_axis,
                    "local_axis": local_axis,
                    "positioner": route["positioner"],
                    "motor": route["motor"],
                })

        # 축 에러가 발생했다면 출발 실패
        if error_axes:
            return {
                "plc_name": plc_name,
                "started": False,
                "reason": "axis_error",
                "sequence_before": int(sequence_before),
                "sequence_now": int(sequence_now),
                "error_axes": error_axes
            }

        # 현재 MotionSequence 확인
        sequence_now = plc.read_by_name(
            "GVL.gMotionSequence",
            pyads.PLCTYPE_UDINT
        )

        # 값이 바뀌었다면 plc가 새 모션 명령을 접수한것
        if sequence_now != sequence_before:
            return {
                "plc_name": plc_name,
                "started": True,
                "reason": "motion_sequence_changed",
                "sequence_before": int(sequence_before),
                "sequence_now": int(sequence_now),
                "error_axes": [],
            }

        time.sleep(0.02)


    # 제한 시간 동안 MotionSequence가 변하지 않음
    return {
        "plc_name": plc_name,
        "started": False,
        "reason": "motion_sequence_timeout",
        "sequence_before": int(sequence_before),
        "sequence_now": int(sequence_now),
        "error_axes": [],
    }
async def wait_one_plc_started(
        plc_name: str,
        plc,
        routes: list,
        sequence_before: int,
        timeout: float = 2.0
        ):

    """
    PLC 한 대의 새 모션 명령 접수 여부를 
    별도 스레드에서 확인한다.
    
    """
    return await asyncio.to_thread(
        wait_one_plc_started_sync,
        plc_name,
        plc,
        routes,
        sequence_before,
        timeout
    )



##  구동 중 문제 발생시 "자동 정지"   AND    사용자 Stop명령 내리면 강제 정지 가능
def request_stop_one_plc_sync(
    plc_name: str,
    plc
):
    """
    PLC 한 대에 전체 감속 정지를 요청한다.
    """

    plc.write_by_name(
        "GVL.gStopDec",
        DEC,
        pyads.PLCTYPE_LREAL
    )

    plc.write_by_name(
        "GVL.gStopAll",
        True,
        pyads.PLCTYPE_BOOL
    )

    print(f"{plc_name} 전체 정지 요청 전송")
async def request_all_plcs_stop(
    plc_connections: dict,
    plc_names: list
):
    """
    지정된 여러 PLC에 전체 정지 명령을 동시에 보낸다.
    각 PLC의 Stop 명령 전송 성곡 여부를 확인한다.
    """

    stop_results = await asyncio.gather(
        *[
            asyncio.to_thread(
                request_stop_one_plc_sync,
                plc_name,
                plc_connections[plc_name]
            )
            for plc_name in plc_names
        ],
        return_exceptions=True
    )

    failed_plcs = {}

    for plc_name, stop_result in zip(
        plc_names,
        stop_results
    ):
        if isinstance(stop_result, Exception):
            failed_plcs[plc_name] = str(stop_result)

    return {
        "success": not failed_plcs,
        "requested_plcs": list(plc_names),
        "failed_plcs": failed_plcs,
    }


    
##
def read_one_plc_motion_snapshot_sync(
    plc_name: str,
    plc,
    routes: list
):
    """
    PLC 한 대의 구동 대상 축 상태와
    Stop 발생 여부를 한 번 읽는다.
    """

    axis_states = []

    for route in routes:

        global_axis = route["global_axis"]
        local_axis = route["local_axis"]

        is_busy = plc.read_by_name(
            f"GVL.gAxisState[{local_axis}].Busy",
            pyads.PLCTYPE_BOOL
        )

        is_error = plc.read_by_name(
            f"GVL.gAxisState[{local_axis}].Error",
            pyads.PLCTYPE_BOOL
        )

        actual_position = plc.read_by_name(
            f"GVL.gAxisState[{local_axis}].ActPos",
            pyads.PLCTYPE_LREAL
        )

        axis_states.append({
            "plc_name": plc_name,
            "positioner": route["positioner"],
            "motor": route["motor"],
            "global_axis": global_axis,
            "local_axis": local_axis,
            "busy": is_busy,
            "error": is_error,
            "actual_position": actual_position,
        })

    stop_occurred = plc.read_by_name(
        "GVL.gStopOccurred",
        pyads.PLCTYPE_BOOL
    )

    stop_busy = plc.read_by_name(
        "GVL.gStopBusy",
        pyads.PLCTYPE_BOOL
    )

    stop_done = plc.read_by_name(
        "GVL.gStopDone",
        pyads.PLCTYPE_BOOL
    )

    # 현재 PLC가 완료한 step과 Python이 허가한 step을 함께 읽는다.
    completed_step = plc.read_by_name(
        STEP_SYNC_COMPLETED_TAG,
        pyads.PLCTYPE_INT
    )

    allowed_step = plc.read_by_name(
        STEP_SYNC_ALLOWED_TAG,
        pyads.PLCTYPE_INT
    )

    stopped_target_step = plc.read_by_name(
        "GVL.gStoppedTargetStep",
        pyads.PLCTYPE_INT
    )

    return {
        "plc_name": plc_name,
        "stop_occurred": stop_occurred,
        "stop_busy": stop_busy,
        "stop_done": stop_done,
        "completed_step": int(completed_step),
        "allowed_step": int(allowed_step),
        "stopped_target_step": int(stopped_target_step),
        "axis_states": axis_states,
    }
async def read_one_plc_motion_snapshot(
    plc_name: str,
    plc,
    routes: list
):
    """
    PLC 한 대의 모션 상태를 별도 스레드에서 읽는다.
    """

    return await asyncio.to_thread(
        read_one_plc_motion_snapshot_sync,
        plc_name,
        plc,
        routes
    )



## 축 Error가 발생한 상태에서 Stop 처리
class StopAxisError(RuntimeError):
    pass
## 정지 잘 되었는지 확인하는것
async def wait_all_motion_axes_stopped(
    plc_connections: dict,
    plc_motion_routes: dict,
    prepared_plcs: list,
    timeout: float = 5.0,
    known_axis_error: bool = False
):
    """
    Stop 요청 후 모든 구동 축이 정지할 때까지
    제한 시간 동안 기다린다.
    """

    wait_start = time.time()
    last_snapshot_results = []

    while time.time() - wait_start <= timeout:

        last_snapshot_results = await asyncio.gather(
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
            for snapshot in last_snapshot_results
            for axis_state in snapshot["axis_states"]
        ]

        # Stop 처리 중 축 Error 확인
        error_axes = [
            axis_state
            for axis_state in all_axis_states
            if axis_state["error"]
        ]

        if error_axes:

            error_plcs = {
                axis_state["plc_name"]
                for axis_state in error_axes
            }

            all_axes_stopped_after_error = not any(
                axis_state["busy"]
                for axis_state in all_axis_states
            )

            normal_plcs_stop_completed = all(
                (
                    snapshot["plc_name"] in error_plcs
                    or (
                        snapshot["stop_done"]
                        and snapshot["stop_occurred"]
                        and not snapshot["stop_busy"]
                    )
                )
                for snapshot in last_snapshot_results
            )

            error_plcs_stop_finished = all(
                not snapshot["stop_busy"]
                for snapshot in last_snapshot_results
                if snapshot["plc_name"] in error_plcs
            )

            if (
                all_axes_stopped_after_error
                and normal_plcs_stop_completed
                and error_plcs_stop_finished
            ):
                await asyncio.gather(
                    *[
                        asyncio.to_thread(
                            plc_connections[plc_name].write_by_name,
                            "GVL.gStopAll",
                            False,
                            pyads.PLCTYPE_BOOL
                        )
                        for plc_name in prepared_plcs
                    ]
                )

                if known_axis_error:
                    return last_snapshot_results

                raise StopAxisError(
                    f"전체 정지 처리 중 축 에러가 발생: "
                    f"{error_axes}"
                )

        all_axes_stopped = not any(
            axis_state["busy"]
            for axis_state in all_axis_states
        )

        all_plcs_stop_completed = all(
            snapshot["stop_done"]
            and snapshot["stop_occurred"]
            and not snapshot["stop_busy"]
            for snapshot in last_snapshot_results
        )

        if all_axes_stopped and all_plcs_stop_completed:

            # Stop 완료 후 gStopAll 요청 신호 해제
            await asyncio.gather(
                *[
                    asyncio.to_thread(
                        plc_connections[plc_name].write_by_name,
                        "GVL.gStopAll",
                        False,
                        pyads.PLCTYPE_BOOL
                    )
                    for plc_name in prepared_plcs
                ]
            )

            return last_snapshot_results

        await asyncio.sleep(0.05)

        ## 여기 는 timeout  시간 안에 정상적인 stop완료를 확인하지 못했다는 뜻
    busy_axes = [
        {
            "plc_name": axis_state["plc_name"],
            "global_axis": axis_state["global_axis"],
            "local_axis": axis_state["local_axis"],
            "positioner": axis_state["positioner"],
            "motor": axis_state["motor"],
        }
        for snapshot in last_snapshot_results
        for axis_state in snapshot["axis_states"]
        if axis_state["busy"]
    ]

    incomplete_stop_plcs = [
        snapshot["plc_name"]
        for snapshot in last_snapshot_results
        if not (
            snapshot["stop_done"]
            and snapshot["stop_occurred"]
            and not snapshot["stop_busy"]
        )
    ]

    raise TimeoutError(
        f"전체 정지 확인 시간이 {timeout}초를 초과했습니다. "
        f"아직 Busy인 축: {busy_axes}, "
        f"Stop 완료되지 않은 PLC: {incomplete_stop_plcs}"
    )






##################################################################################
##################################################################################
MOTION_MODE_STOP_REVERSE = 3 # reverse_from_stop_step

## Stop 기록 읽기
def read_stop_record_one_plc_sync(plc_name: str, plc):
    """PLC 한 대에 저장된 Stop 복귀 정보를 읽는다."""

    stopped_valid = plc.read_by_name(
        "GVL.gStoppedValid",
        pyads.PLCTYPE_BOOL
    )

    stop_occurred = plc.read_by_name(
        "GVL.gStopOccurred",
        pyads.PLCTYPE_BOOL
    )

    stop_busy = plc.read_by_name(
        "GVL.gStopBusy",
        pyads.PLCTYPE_BOOL
    )

    stop_done = plc.read_by_name(
        "GVL.gStopDone",
        pyads.PLCTYPE_BOOL
    )

    last_completed_step = plc.read_by_name(
        "GVL.gStoppedLastCompletedStep",
        pyads.PLCTYPE_INT
    )

    target_step = plc.read_by_name(
        "GVL.gStoppedTargetStep",
        pyads.PLCTYPE_INT
    )

    stopped_total_points = plc.read_by_name(
        "GVL.gStoppedTotalPoints",
        pyads.PLCTYPE_INT
    )

    stopped_mode = plc.read_by_name(
        "GVL.gStoppedMotionMode",
        pyads.PLCTYPE_INT
    )

    stopped_selected_axes = []
    stopped_locked_axes = []

    for positioner, positioner_info in POSITIONER_AXIS_MAP.items():

        if positioner_info["plc"] != plc_name:
            continue

        for motor in ("alpha", "beta"):

            global_axis = (positioner_info[motor]["global_axis"])

            local_axis = (positioner_info[motor]["local_axis"])

            was_selected = plc.read_by_name(
                f"GVL.gStoppedAxisSelected[{local_axis}]",
                pyads.PLCTYPE_BOOL
            )

            was_locked = plc.read_by_name(
                f"GVL.gStoppedAxisLocked[{local_axis}]",
                pyads.PLCTYPE_BOOL
            )

            if was_selected:
                stopped_selected_axes.append(global_axis)

            if was_locked:
                stopped_locked_axes.append(global_axis)


    return {
        "plc_name": plc_name,
        "stopped_valid": bool(stopped_valid),
        "stop_occurred": bool(stop_occurred),
        "stop_busy": bool(stop_busy),
        "stop_done": bool(stop_done),
        "last_completed_step": int(last_completed_step),
        "target_step": int(target_step),
        "stopped_total_points": int(stopped_total_points),
        "stopped_mode": int(stopped_mode),
        "stopped_selected_axes": sorted(stopped_selected_axes),
        "stopped_locked_axes": sorted(stopped_locked_axes),
    }
async def read_stop_record_one_plc(plc_name: str, plc):
    """PLC 한 대의 Stop 기록 읽기를 별도 스레드에서 실행한다."""

    return await asyncio.to_thread(
        read_stop_record_one_plc_sync,
        plc_name,
        plc
    )

## Stop 지점 복귀 mode = 3
def set_stop_reverse_mode_sync(plc_name: str, plc):
    """PLC 한 대에 Stop 지점 복귀 모드(mode 3)를 설정한다."""

    plc.write_by_name(
        "GVL.gMotionModeCommand",
        MOTION_MODE_STOP_REVERSE,
        pyads.PLCTYPE_INT
    )
async def set_stop_reverse_mode(plc_name: str, plc):
    """Stop 지점 복귀 모드 설정을 별도 스레드에서 실행한다."""

    await asyncio.to_thread(
        set_stop_reverse_mode_sync,
        plc_name,
        plc
    )

## 복귀 성공 후 Stop 기록 삭제
def clear_stopped_info_one_plc_sync(
    plc_name: str,
    plc,
    timeout: float = 2.0
):
    """PLC 한 대의 Stop 기록을 삭제하고 완료 여부를 확인한다."""

    plc.write_by_name(
        "GVL.gClearStoppedInfo",
        True,
        pyads.PLCTYPE_BOOL
    )

    start_time = time.time()

    while plc.read_by_name(
        "GVL.gClearStoppedInfo",
        pyads.PLCTYPE_BOOL
    ):
        if time.time() - start_time > timeout:
            raise TimeoutError(
                f"{plc_name} Stop 기록 삭제 시간이 "
                f"{timeout}초를 초과했습니다."
            )

        time.sleep(0.02)

    stopped_valid = plc.read_by_name(
        "GVL.gStoppedValid",
        pyads.PLCTYPE_BOOL
    )

    if stopped_valid:
        raise RuntimeError(
            f"{plc_name} Stop 기록 삭제 후에도 "
            "gStoppedValid=True 입니다."
        )

    return plc_name
async def clear_stopped_info_all_plcs(

        
    plc_connections: dict,
    plc_names: list,
    timeout: float = 2.0
):
    """여러 PLC의 Stop 기록을 최대한 동시에 삭제하고 확인한다."""

    clear_results = await asyncio.gather(
        *[
            asyncio.to_thread(
                clear_stopped_info_one_plc_sync,
                plc_name,
                plc_connections[plc_name],
                timeout
            )
            for plc_name in plc_names
        ],
        return_exceptions=True
    )

    failed_plcs = {}

    for plc_name, clear_result in zip(plc_names, clear_results):
        if isinstance(clear_result, Exception):
            failed_plcs[plc_name] = str(clear_result)

    if failed_plcs:
        raise RuntimeError(
            "Stop 기록 삭제 또는 확인에 실패한 PLC가 있습니다: "
            f"{failed_plcs}"
        )

    return list(plc_names)







##################################################################################
# zero_main() 함수들
##################################################################################
MOTION_MODE_ZERO = 4

## 0도 이동 mode = 4
def set_zero_mode_sync(
    plc_name: str,
    plc
):
    """
    PLC 한 대에 0도 이동 모드(mode 4)를 설정한다.
    """

    plc.write_by_name(
        "GVL.gMotionModeCommand",
        MOTION_MODE_ZERO,
        pyads.PLCTYPE_INT
    )
async def set_zero_mode(
    plc_name: str,
    plc
):
    """
    0도 이동 모드 설정을 별도 스레드에서 실행한다.
    """

    await asyncio.to_thread(
        set_zero_mode_sync,
        plc_name,
        plc
    )

## 0도 1-step 경로 생성
def create_zero_axis_points(
    motion_axes: list,
    zero_position: float = 0.0
):
    """
    0도 이동 대상 global_axis마다
    1-step짜리 절대위치 0도 경로를 만든다.

    예:
        motion_axes = [1, 2, 7, 8]

        ->
        {
            1: [0.0],
            2: [0.0],
            7: [0.0],
            8: [0.0]
        }

    PLC의 새 모션 기준으로는
    TotalPoints = 1
    TargetPos[0] = 0.0
    이 된다.
    """

    if not motion_axes:
        raise ValueError(
            "0도 이동 경로를 생성할 축이 없습니다."
        )

    zero_axis_points = {
        int(global_axis): [float(zero_position)]
        for global_axis in motion_axes
    }

    zero_total_steps = 1

    return zero_axis_points, zero_total_steps





##################################################################################
# rotate_one() 함수들
##################################################################################
MOTION_MODE_ROTATE_ONE = 5
##
def get_one_axis_route(
    positioner: str,
    motor: str
):
    """
    positioner / motor 입력을
    현재 2-PLC 구조의 route 정보로 변환한다.

    예:
        A4 alpha
        -> PLC2
        -> global_axis 7
        -> local_axis 1
    """

    positioner = positioner.strip().upper()
    motor = motor.strip().lower()

    if positioner not in POSITIONER_AXIS_MAP:
        raise ValueError(
            f"존재하지 않는 포지셔너입니다: {positioner}"
        )

    if motor not in ("alpha", "beta"):
        raise ValueError(
            f"motor는 alpha 또는 beta만 가능합니다: {motor}"
        )

    positioner_info = POSITIONER_AXIS_MAP[positioner]
    motor_info = positioner_info[motor]

    return {
        "positioner": positioner,
        "motor": motor,
        "plc_name": positioner_info["plc"],
        "global_axis": motor_info["global_axis"],
        "local_axis": motor_info["local_axis"],
    }
##
def send_rotate_one_path_sync(
    plc,
    local_axis: int,
    angle: float,
    velocity: float,
    acc: float,
    dec: float
):
    """
    rotate_one()용 1-step 절대각도 경로를 전송한다.
    """

    prefix = f"GVL.gAxisCmd[{local_axis}]"

    plc.write_by_name(
        f"{prefix}.TotalPoints",
        1,
        pyads.PLCTYPE_INT
    )

    plc.write_by_name(
        f"{prefix}.Velocity",
        float(velocity),
        pyads.PLCTYPE_LREAL
    )

    plc.write_by_name(
        f"{prefix}.Acc",
        float(acc),
        pyads.PLCTYPE_LREAL
    )

    plc.write_by_name(
        f"{prefix}.Dec",
        float(dec),
        pyads.PLCTYPE_LREAL
    )

    target_pos_array = (
        pyads.PLCTYPE_LREAL * 3500
    )()

    # 절대각도
    target_pos_array[0] = float(angle)

    plc.write_by_name(
        f"{prefix}.TargetPos",
        target_pos_array,
        pyads.PLCTYPE_LREAL * 3500
    )
##
async def rotate_one(
    plc_connections,
    positioner: str,
    motor: str,
    angle: float,
    velocity: float = VELOCITY,
    acc: float = ACC,
    dec: float = DEC,
    start_timeout: float = 2.0,
    timeout: float = 30.0,
):

    """
    선택한 포지셔너의 alpha 또는 beta 축 하나만
    지정한 절대각도로 이동한다.

    예:
        await rotate_one(
            positioner="A4",
            motor="alpha",
            angle=70
        )

    A4 alpha
    -> global_axis = 7
    -> PLC2
    -> local_axis = 1
    -> 절대각도 70도로 이동

    이동 중 kspec_3_stop_run.py의
    stop_all_positioner()로 정지 가능.

    rotate_one() 중 Stop 후 다시 rotate_one()을
    실행하면 이전 rotate_one Stop 기록(mode 5)만
    삭제한 뒤 새로운 이동을 시작한다.
    """

    # ========================================================
    # 입력값 -> PLC / global axis / local axis 변환
    # ========================================================
    try:
        route = get_one_axis_route(
            positioner,
            motor
        )

    except Exception as e:

        result = {
            "status": "fail",
            "message": (
                "positioner 또는 motor 입력이 "
                f"잘못되었습니다: {e}"
            ),
            "data": {}
        }

        print(result["message"])
        return result


    plc_name = route["plc_name"]
    global_axis = route["global_axis"]
    local_axis = route["local_axis"]

    plc = plc_connections[plc_name]


    plc_motion_routes = {
        "PLC1": [],
        "PLC2": [],
    }

    plc_motion_routes[plc_name] = [route]


    try:

        # ====================================================
        # 담당 PLC만 연결
        # ====================================================


        print(
            f"{route['positioner']} "
            f"{route['motor']} 이동 준비"
        )

        print(
            f"{plc_name} | "
            f"global axis {global_axis} | "
            f"local axis {local_axis}"
        )


        # ====================================================
        # 해당 축 Lock 여부 확인
        # ====================================================
        is_locked = await asyncio.to_thread(
            plc.read_by_name,
            f"GVL.gAxisLocked[{local_axis}]",
            pyads.PLCTYPE_BOOL
        )

        if is_locked:

            result = {
                "status": "fail",
                "message": (
                    f"{route['positioner']} "
                    f"{route['motor']} 축은 "
                    "현재 Lock 상태이므로 움직일 수 없습니다."
                ),
                "data": {
                    "positioner":
                        route["positioner"],

                    "motor":
                        route["motor"],

                    "plc_name":
                        plc_name,

                    "global_axis":
                        global_axis,

                    "local_axis":
                        local_axis,

                    "locked":
                        True,
                }
            }

            print(result["message"])
            return result


        print(
            f"{route['positioner']} "
            f"{route['motor']} Lock 해제 상태 확인 완료"
        )


        # ====================================================
        # Stop 처리 상태 및 이전 Stop 기록 확인
        # ====================================================

        # Stop 처리가 현재 진행 중이면
        # 이전 Stop 기록 mode와 관계없이 rotate_one 실행 금지
        stop_busy = await asyncio.to_thread(
            plc.read_by_name,
            "GVL.gStopBusy",
            pyads.PLCTYPE_BOOL
        )

        if stop_busy:

            result = {
                "status": "fail",
                "message": (
                    "현재 PLC의 Stop 처리가 진행 중이므로 "
                    "rotate_one()을 실행할 수 없습니다. "
                    "Stop 완료 후 다시 실행해 주세요."
                ),
                "data": {
                    "plc_name": plc_name,
                    "global_axis": global_axis,
                    "local_axis": local_axis,
                }
            }

            print(result["message"])
            return result


        # 이전 Stop 기록 확인
        stopped_valid = await asyncio.to_thread(
            plc.read_by_name,
            "GVL.gStoppedValid",
            pyads.PLCTYPE_BOOL
        )

        if stopped_valid:

            stopped_mode = await asyncio.to_thread(
                plc.read_by_name,
                "GVL.gStoppedMotionMode",
                pyads.PLCTYPE_INT
            )

            stopped_mode = int(stopped_mode)

            # rotate_one 자체의 Stop 기록이면 삭제 후 재실행
            if stopped_mode == MOTION_MODE_ROTATE_ONE:

                await asyncio.to_thread(
                    clear_stopped_info_one_plc_sync,
                    plc_name,
                    plc,
                    2.0
                )

                print(
                    f"{plc_name} 이전 rotate_one "
                    "Stop 기록 삭제 완료"
                )

            # main / reverse / reverse_from_stop / zero 등의
            # 기존 복귀용 Stop 기록은 그대로 보존
            else:

                print(
                    f"{plc_name} 기존 Stop 복귀 기록 "
                    f"(mode {stopped_mode})을 보존한 채 "
                    "rotate_one() 보정을 실행합니다."
                )

        # ====================================================
        # rotate_one mode = 5
        # ====================================================
        await asyncio.to_thread(
            plc.write_by_name,
            "GVL.gMotionModeCommand",
            MOTION_MODE_ROTATE_ONE,
            pyads.PLCTYPE_INT
        )


        # ====================================================
        # 이전 StartSpline / Active 초기화
        # ====================================================
        await clear_one_plc_motion_flags(
            plc_name,
            plc
        )

        await asyncio.sleep(0.1)


        # ====================================================
        # 해당 축만 Power ON
        # ====================================================
        await power_on_one_plc(
            plc_name,
            plc,
            [route]
        )

        await asyncio.sleep(0.5)


        # ====================================================
        # 실제 Powered=True 확인
        # ====================================================
        powered = await asyncio.to_thread(
            plc.read_by_name,
            (
                f"GVL.gAxisState"
                f"[{local_axis}].Powered"
            ),
            pyads.PLCTYPE_BOOL
        )

        if not powered:

            result = {
                "status": "fail",
                "message": (
                    f"{route['positioner']} "
                    f"{route['motor']} 축의 "
                    "Power ON을 확인하지 못했습니다."
                ),
                "data": {
                    "plc_name":
                        plc_name,

                    "global_axis":
                        global_axis,

                    "local_axis":
                        local_axis,
                }
            }

            print(result["message"])
            return result


        # ====================================================
        # 이동 전 현재 위치
        # ====================================================
        current_position = await asyncio.to_thread(
            plc.read_by_name,
            (
                f"GVL.gAxisState"
                f"[{local_axis}].ActPos"
            ),
            pyads.PLCTYPE_LREAL
        )


        print(
            f"현재 위치: "
            f"{float(current_position):.3f}도"
        )


        # ====================================================
        # 1-step 절대각도 경로 전송
        # ====================================================
        await asyncio.to_thread(
            send_rotate_one_path_sync,
            plc,
            local_axis,
            angle,
            velocity,
            acc,
            dec
        )


        # ====================================================
        # 1-step이므로 gAllowedStep = 1
        # ====================================================
        await set_allowed_step_all_plcs(
            plc_connections,
            [plc_name],
            1
        )


        # ====================================================
        # StartSpline 전 MotionSequence 저장
        # ====================================================
        motion_sequence_before = (
            await asyncio.to_thread(
                plc.read_by_name,
                "GVL.gMotionSequence",
                pyads.PLCTYPE_UDINT
            )
        )


        # ====================================================
        # 해당 축 Active = True
        # ====================================================
        await activate_one_plc(
            plc_name,
            plc,
            [route]
        )


        # ====================================================
        # 해당 축 StartSpline = True
        # ====================================================
        await start_one_plc(
            plc_name,
            plc,
            [route]
        )


        # ====================================================
        # PLC가 새 모션을 접수했는지 확인
        # ====================================================
        start_result = await wait_one_plc_started(
            plc_name,
            plc,
            [route],
            int(motion_sequence_before),
            start_timeout
        )


        if not start_result["started"]:

            result = {
                "status": "fail",
                "message": (
                    f"{route['positioner']} "
                    f"{route['motor']} 축의 "
                    "이동 명령이 시작되지 않았습니다."
                ),
                "data": {
                    "plc_name":
                        plc_name,

                    "global_axis":
                        global_axis,

                    "local_axis":
                        local_axis,

                    "target_angle":
                        float(angle),

                    "start_result":
                        start_result,
                }
            }

            print(result["message"])
            return result


        print(
            f"{route['positioner']} "
            f"{route['motor']} "
            f"절대각도 {float(angle):.3f}도 "
            "이동 시작"
        )


        # ====================================================
        # 이동 상태 감시
        # ====================================================
        move_start_time = time.time()


        while True:

            snapshot = (
                await read_one_plc_motion_snapshot(
                    plc_name,
                    plc,
                    [route]
                )
            )


            axis_state = (
                snapshot["axis_states"][0]
            )


            is_busy = axis_state["busy"]

            is_error = axis_state["error"]

            actual_position = (
                axis_state["actual_position"]
            )


            print(
                f"{route['positioner']}-"
                f"{route['motor']}: "
                f"{actual_position:7.2f}",
                end="\r"
            )


            # ================================================
            # 축 Error
            # ================================================
            if is_error:

                print()

                result = {
                    "status": "error",
                    "message": (
                        f"{route['positioner']} "
                        f"{route['motor']} "
                        "이동 중 축 Error가 발생했습니다."
                    ),
                    "data": {
                        "plc_name":
                            plc_name,

                        "global_axis":
                            global_axis,

                        "local_axis":
                            local_axis,

                        "target_angle":
                            float(angle),

                        "actual_position":
                            actual_position,
                    }
                }

                print(result["message"])
                return result


            # ================================================
            # 외부 stop.py로 Stop 완료
            # ================================================
            if (
                snapshot["stop_occurred"]
                and not is_busy
            ):

                print()

                result = {
                    "status": "stopped",
                    "message": (
                        "사용자의 Stop 요청으로 "
                        f"{route['positioner']} "
                        f"{route['motor']} 이동이 "
                        "중간에 정지했습니다."
                    ),
                    "data": {
                        "positioner":
                            route["positioner"],

                        "motor":
                            route["motor"],

                        "plc_name":
                            plc_name,

                        "global_axis":
                            global_axis,

                        "local_axis":
                            local_axis,

                        "target_angle":
                            float(angle),

                        "stopped_position":
                            actual_position,
                    }
                }

                print(result["message"])
                return result


            # ================================================
            # 1-step 정상 완료
            # ================================================
            if (
                snapshot["completed_step"] >= 1
                and not is_busy
            ):

                print()
                break


            # ================================================
            # Timeout
            # ================================================
            if (
                time.time()
                - move_start_time
                > timeout
            ):

                stop_result = (
                    await request_all_plcs_stop(
                        plc_connections,
                        [plc_name]
                    )
                )


                stop_wait_error = None


                if stop_result["success"]:

                    try:

                        await wait_all_motion_axes_stopped(
                            plc_connections,
                            plc_motion_routes,
                            [plc_name],
                            timeout=5.0
                        )

                    except Exception as e:

                        stop_wait_error = str(e)


                result = {
                    "status": "fail",
                    "message": (
                        f"{route['positioner']} "
                        f"{route['motor']} 이동 시간이 "
                        f"{timeout}초를 초과했습니다."
                    ),
                    "data": {
                        "plc_name":
                            plc_name,

                        "global_axis":
                            global_axis,

                        "local_axis":
                            local_axis,

                        "target_angle":
                            float(angle),

                        "actual_position":
                            actual_position,

                        "timeout":
                            timeout,

                        "stop_failed_plcs":
                            stop_result[
                                "failed_plcs"
                            ],

                        "stop_wait_error":
                            stop_wait_error,
                    }
                }

                print()
                print(result["message"])
                return result


            await asyncio.sleep(0.05)


        # ====================================================
        # 최종 실제 위치
        # ====================================================
        final_position = await asyncio.to_thread(
            plc.read_by_name,
            (
                f"GVL.gAxisState"
                f"[{local_axis}].ActPos"
            ),
            pyads.PLCTYPE_LREAL
        )


        result = {
            "status": "success",
            "message": (
                f"{route['positioner']} "
                f"{route['motor']} 축이 "
                f"절대각도 {float(angle):.3f}도 "
                "이동을 완료했습니다."
            ),
            "data": {
                "positioner":
                    route["positioner"],

                "motor":
                    route["motor"],

                "plc_name":
                    plc_name,

                "global_axis":
                    global_axis,

                "local_axis":
                    local_axis,

                "current_position_before_move":
                    float(current_position),

                "target_angle":
                    float(angle),

                "actual_position":
                    float(final_position),

                "locked":
                    False,
            }
        }


        print(result["message"])
        return result


    except pyads.ADSError as e:

        result = {
            "status": "error",
            "message": (
                "PLC 통신 또는 ADS 에러가 "
                f"발생했습니다: {e}"
            ),
            "data": {
                "plc_name":
                    plc_name,

                "global_axis":
                    global_axis,

                "local_axis":
                    local_axis,
            }
        }

        print(result["message"])
        return result


    except Exception as e:

        result = {
            "status": "error",
            "message": (
                "rotate_one() 실행 중 "
                f"예상하지 못한 에러가 발생했습니다: {e}"
            ),
            "data": {
                "plc_name":
                    plc_name,

                "global_axis":
                    global_axis,

                "local_axis":
                    local_axis,
            }
        }

        print(result["message"])
        return result


    finally:

        try:
            await clear_one_plc_motion_flags(
                plc_name,
                plc
            )

        except Exception:
            pass





##################################################################################
# show_status()
##################################################################################
async def show_status(
    plc_connections,
    axis: str
):
    """
    포지셔너 하나의 alpha / beta 현재 상태를 확인한다.

    예:
        await show_status("A1")
        await show_status("A4")

    A1~A3 -> PLC1
    A4~A5 -> PLC2

    읽는 정보:
        - 현재 각도 ActPos
        - Busy
        - Error
        - Locked

    모션 관련 값은 전혀 변경하지 않는다.
    """

    # ========================================================
    # 입력한 포지셔너 확인
    # ========================================================
    positioner = axis.strip().upper()

    if positioner not in POSITIONER_AXIS_MAP:

        result = {
            "status": "fail",
            "message": (
                f"존재하지 않는 fiber/positioner입니다: "
                f"{positioner}"
            ),
            "data": {
                "input_axis": axis
            }
        }

        print(result["message"])
        return result


    # ========================================================
    # 포지셔너의 PLC / global axis / local axis 정보
    # ========================================================
    positioner_info = POSITIONER_AXIS_MAP[positioner]

    plc_name = positioner_info["plc"]

    alpha_global_axis = (
        positioner_info["alpha"]["global_axis"]
    )

    alpha_local_axis = (
        positioner_info["alpha"]["local_axis"]
    )

    beta_global_axis = (
        positioner_info["beta"]["global_axis"]
    )

    beta_local_axis = (
        positioner_info["beta"]["local_axis"]
    )


    # ========================================================
    # 해당 포지셔너가 있는 PLC만 연결
    # ========================================================
    plc = plc_connections[plc_name]

    


    try:

        # ====================================================
        # Alpha 상태 읽기
        # ====================================================
        alpha_angle = await asyncio.to_thread(
            plc.read_by_name,
            f"GVL.gAxisState[{alpha_local_axis}].ActPos",
            pyads.PLCTYPE_LREAL
        )

        alpha_busy = await asyncio.to_thread(
            plc.read_by_name,
            f"GVL.gAxisState[{alpha_local_axis}].Busy",
            pyads.PLCTYPE_BOOL
        )

        alpha_error = await asyncio.to_thread(
            plc.read_by_name,
            f"GVL.gAxisState[{alpha_local_axis}].Error",
            pyads.PLCTYPE_BOOL
        )

        alpha_locked = await asyncio.to_thread(
            plc.read_by_name,
            f"GVL.gAxisLocked[{alpha_local_axis}]",
            pyads.PLCTYPE_BOOL
        )


        # ====================================================
        # Beta 상태 읽기
        # ====================================================
        beta_angle = await asyncio.to_thread(
            plc.read_by_name,
            f"GVL.gAxisState[{beta_local_axis}].ActPos",
            pyads.PLCTYPE_LREAL
        )

        beta_busy = await asyncio.to_thread(
            plc.read_by_name,
            f"GVL.gAxisState[{beta_local_axis}].Busy",
            pyads.PLCTYPE_BOOL
        )

        beta_error = await asyncio.to_thread(
            plc.read_by_name,
            f"GVL.gAxisState[{beta_local_axis}].Error",
            pyads.PLCTYPE_BOOL
        )

        beta_locked = await asyncio.to_thread(
            plc.read_by_name,
            f"GVL.gAxisLocked[{beta_local_axis}]",
            pyads.PLCTYPE_BOOL
        )


        # ====================================================
        # 결과
        # ====================================================
        result = {
            "status": "success",
            "message": (
                f"{positioner} 현재 상태 확인 완료"
            ),

           
            "alpha": {
                "current_angle_degree": float(alpha_angle)
            },

            "beta": {
                "current_angle_degree": float(beta_angle)
            },

            "data": {
                "positioner": positioner,
                "plc_name": plc_name,

                "alpha": {
                    "global_axis": alpha_global_axis,
                    "local_axis": alpha_local_axis,
                    "current_angle_degree": float(alpha_angle),
                    "busy": bool(alpha_busy),
                    "error": bool(alpha_error),
                    "locked": bool(alpha_locked),
                },

                "beta": {
                    "global_axis": beta_global_axis,
                    "local_axis": beta_local_axis,
                    "current_angle_degree": float(beta_angle),
                    "busy": bool(beta_busy),
                    "error": bool(beta_error),
                    "locked": bool(beta_locked),
                }
            }
        }
        print(result["message"])

        print(
            f"Alpha | "
            f"{float(alpha_angle):.3f}도 | "
            f"Busy={bool(alpha_busy)} | "
            f"Error={bool(alpha_error)} | "
            f"Locked={bool(alpha_locked)}"
        )

        print(
            f"Beta  | "
            f"{float(beta_angle):.3f}도 | "
            f"Busy={bool(beta_busy)} | "
            f"Error={bool(beta_error)} | "
            f"Locked={bool(beta_locked)}"
        )


        return result


    except pyads.ADSError as e:

        result = {
            "status": "error",
            "message": (
                "PLC 통신 또는 ADS 에러가 "
                f"발생했습니다: {e}"
            ),
            "data": {
                "positioner": positioner,
                "plc_name": plc_name,
            }
        }

        print(result["message"])
        return result


    except Exception as e:

        result = {
            "status": "error",
            "message": (
                "show_status() 실행 중 "
                f"예상하지 못한 에러가 발생했습니다: {e}"
            ),
            "data": {
                "positioner": positioner,
                "plc_name": plc_name,
            }
        }

        print(result["message"])
        return result





##########################################################################
##########################################################################
# positioner_lock()
async def positioner_lock(plc_connections, positioners: list[str]):

    """
    입력한 포지셔너의 Alpha / Beta 축을 모두 Lock한다.

    예:
        await positioner_lock(["A1", "A4"])

    전체 Lock 해제:
        await positioner_lock([])

    입력하지 않은 포지셔너는 모두 Unlock된다.
    모터가 움직이거나 Stop 처리 중이면 Lock 상태를 변경하지 않는다.

    Lock 변경 중 쓰기/검증 오류가 발생하면,
    변경 시작 전에 저장해 둔 A1~A5 전체 Lock 상태로 원상 복구를 시도한다.
    """

    # ========================================================
    # "A1" 하나만 입력해도 ["A1"]로 변경
    # ========================================================
    if isinstance(positioners, str): #isinstance(값, 자료형) ->isinstance("A1", str(문자열))
        positioners = [positioners] #positioner가 문자열이면 리스트로 바꿈

    # ========================================================
    # 대문자 통일 + 중복 제거
    # ========================================================
    try:
        locked_positioners = []

        for positioner in positioners:
            positioner_name = positioner.strip().upper()

            if positioner_name not in locked_positioners:
                locked_positioners.append(positioner_name)

    except Exception as e:
        result = {
            "status": "fail",
            "message": f"positioner 입력값이 올바르지 않습니다: {e}",
            "data": {}
        }

        print(result["message"])
        save_result_json(result)
        return result

    # ========================================================
    # 존재하지 않는 포지셔너 확인
    # ========================================================
    invalid_positioners = [
        positioner
        for positioner in locked_positioners
        if positioner not in POSITIONER_AXIS_MAP
    ]

    if invalid_positioners:
        result = {
            "status": "fail",
            "message": "존재하지 않는 포지셔너가 입력되었습니다.",
            "data": {
                "invalid_positioners": invalid_positioners,
                "available_positioners": list(POSITIONER_AXIS_MAP.keys())
            }
        }

        print(result["message"])
        save_result_json(result)
        return result

  

    opened_plcs = ["PLC1", "PLC2"]

    # Lock 변경 전 상태를 저장하는 곳
    original_lock_states = {}

    async def rollback_original_lock_states():
        """
        positioner_lock() 실행 전에 저장한 전체 축 Lock 상태로 복구한다.

        통신 오류 때문에 일부 축 복구가 실패할 수도 있으므로
        쓰기 실패와 최종 검증 실패를 모두 결과로 반환한다.
        """

        rollback_write_errors = []

        # ----------------------------------------------------
        # 원래 Lock 상태로 되돌리기
        # ----------------------------------------------------
        rollback_targets = list(original_lock_states.values())

        rollback_results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    plc_connections[state["plc_name"]].write_by_name,
                    f"GVL.gAxisLocked[{state['local_axis']}]",
                    state["locked"],
                    pyads.PLCTYPE_BOOL
                )
                for state in rollback_targets
            ],
            return_exceptions=True
        )

        for state, rollback_result in zip(
            rollback_targets,
            rollback_results
        ):
            if isinstance(rollback_result, Exception):
                rollback_write_errors.append({
                    "positioner": state["positioner"],
                    "motor": state["motor"],
                    "plc_name": state["plc_name"],
                    "global_axis": state["global_axis"],
                    "local_axis": state["local_axis"],
                    "original_locked": state["locked"],
                    "error": str(rollback_result),
                })

        # ----------------------------------------------------
        # 실제로 원래 상태로 돌아왔는지 다시 확인
        # ----------------------------------------------------
        rollback_verification_errors = []

        verification_results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    plc_connections[state["plc_name"]].read_by_name,
                    f"GVL.gAxisLocked[{state['local_axis']}]",
                    pyads.PLCTYPE_BOOL
                )
                for state in rollback_targets
            ],
            return_exceptions=True
        )

        for state, verification_result in zip(
            rollback_targets,
            verification_results
        ):
            if isinstance(verification_result, Exception):
                rollback_verification_errors.append({
                    "positioner": state["positioner"],
                    "motor": state["motor"],
                    "plc_name": state["plc_name"],
                    "global_axis": state["global_axis"],
                    "local_axis": state["local_axis"],
                    "expected_original_locked": state["locked"],
                    "actual_locked": None,
                    "error": str(verification_result),
                })
                continue

            actual_locked = bool(verification_result)

            if actual_locked != state["locked"]:
                rollback_verification_errors.append({
                    "positioner": state["positioner"],
                    "motor": state["motor"],
                    "plc_name": state["plc_name"],
                    "global_axis": state["global_axis"],
                    "local_axis": state["local_axis"],
                    "expected_original_locked": state["locked"],
                    "actual_locked": actual_locked,
                    "error": "rollback verification mismatch",
                })

        rollback_success = (
            not rollback_write_errors
            and not rollback_verification_errors
        )

        return {
            "rollback_success": rollback_success,
            "rollback_write_errors": rollback_write_errors,
            "rollback_verification_errors": rollback_verification_errors,
        }

    try:

        # ====================================================
        # 현재 Busy인 축 확인
        # ====================================================
        busy_axes = []

        for positioner, positioner_info in POSITIONER_AXIS_MAP.items():
            plc_name = positioner_info["plc"]
            plc = plc_connections[plc_name]

            for motor in ("alpha", "beta"):
                global_axis = positioner_info[motor]["global_axis"]
                local_axis = positioner_info[motor]["local_axis"]

                is_busy = await asyncio.to_thread(
                    plc.read_by_name,
                    f"GVL.gAxisState[{local_axis}].Busy",
                    pyads.PLCTYPE_BOOL
                )

                if is_busy:
                    busy_axes.append({
                        "positioner": positioner,
                        "motor": motor,
                        "plc_name": plc_name,
                        "global_axis": global_axis,
                        "local_axis": local_axis,
                    })

        # ====================================================
        # PLC1 / PLC2 Stop 처리 중인지 확인
        # ====================================================
        stop_busy_results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    plc_connections[plc_name].read_by_name,
                    "GVL.gStopBusy",
                    pyads.PLCTYPE_BOOL
                )
                for plc_name in opened_plcs
            ]
        )

        stop_busy_plcs = [
            plc_name
            for plc_name, stop_busy in zip(
                opened_plcs,
                stop_busy_results
            )
            if stop_busy
        ]

        # ====================================================
        # 움직이는 중 / Stop 처리 중이면 변경 금지
        # ====================================================
        if busy_axes or stop_busy_plcs:
            result = {
                "status": "fail",
                "message": (
                    "모터가 움직이거나 Stop 처리가 진행 중이므로 "
                    "잠금 상태를 변경할 수 없습니다."
                ),
                "data": {
                    "busy_axes": busy_axes,
                    "stop_busy_plcs": stop_busy_plcs,
                }
            }

            print(result["message"])
            save_result_json(result)
            return result

        # ====================================================
        # Lock 변경 전에 현재 A1~A5 전체 Lock 상태 저장
        # ====================================================
        for positioner, positioner_info in POSITIONER_AXIS_MAP.items():
            plc_name = positioner_info["plc"]
            plc = plc_connections[plc_name]

            for motor in ("alpha", "beta"):
                global_axis = positioner_info[motor]["global_axis"]
                local_axis = positioner_info[motor]["local_axis"]

                current_locked = await asyncio.to_thread(
                    plc.read_by_name,
                    f"GVL.gAxisLocked[{local_axis}]",
                    pyads.PLCTYPE_BOOL
                )

                original_lock_states[global_axis] = {
                    "positioner": positioner,
                    "motor": motor,
                    "plc_name": plc_name,
                    "global_axis": global_axis,
                    "local_axis": local_axis,
                    "locked": bool(current_locked),
                }

        print("Lock 변경 전 전체 축 Lock 상태 저장 완료")

        # ====================================================
        # Lock 값 PLC1 / PLC2에 저장
        # ====================================================
        locked_axes = []
        unlocked_axes = []

        try:
            for positioner, positioner_info in POSITIONER_AXIS_MAP.items():
                # 입력된 포지셔너 = True
                # 입력되지 않은 포지셔너 = False
                is_locked = positioner in locked_positioners

                plc_name = positioner_info["plc"]
                plc = plc_connections[plc_name]

                for motor in ("alpha", "beta"):
                    global_axis = positioner_info[motor]["global_axis"]
                    local_axis = positioner_info[motor]["local_axis"]

                    await asyncio.to_thread(
                        plc.write_by_name,
                        f"GVL.gAxisLocked[{local_axis}]",
                        is_locked,
                        pyads.PLCTYPE_BOOL
                    )

                    if is_locked:
                        locked_axes.append(global_axis)
                    else:
                        unlocked_axes.append(global_axis)

            # ====================================================
            # 실제 저장됐는지 다시 읽어서 확인
            # ====================================================
            verification_errors = []

            for positioner, positioner_info in POSITIONER_AXIS_MAP.items():
                expected_locked = positioner in locked_positioners

                plc_name = positioner_info["plc"]
                plc = plc_connections[plc_name]

                for motor in ("alpha", "beta"):
                    global_axis = positioner_info[motor]["global_axis"]
                    local_axis = positioner_info[motor]["local_axis"]

                    actual_locked = await asyncio.to_thread(
                        plc.read_by_name,
                        f"GVL.gAxisLocked[{local_axis}]",
                        pyads.PLCTYPE_BOOL
                    )

                    if bool(actual_locked) != expected_locked:
                        verification_errors.append({
                            "positioner": positioner,
                            "motor": motor,
                            "plc_name": plc_name,
                            "global_axis": global_axis,
                            "local_axis": local_axis,
                            "expected_locked": expected_locked,
                            "actual_locked": bool(actual_locked),
                        })

            # 검증 불일치도 부분 적용 상태이므로 원상 복구
            if verification_errors:
                rollback_result = await rollback_original_lock_states()

                if rollback_result["rollback_success"]:
                    message = (
                        "PLC 잠금 상태 확인 과정에서 저장된 값이 일치하지 않아 "
                        "이번 Lock 변경을 취소하고 이전 Lock 상태로 복구했습니다."
                    )
                else:
                    message = (
                        "PLC 잠금 상태 확인 과정에서 저장된 값이 일치하지 않았고, "
                        "이전 Lock 상태로의 복구도 일부 실패했습니다. "
                        "현재 Lock 상태를 반드시 다시 확인해 주세요."
                    )

                result = {
                    "status": "fail" if rollback_result["rollback_success"] else "error",
                    "message": message,
                    "data": {
                        "verification_errors": verification_errors,
                        **rollback_result,
                    }
                }

                print(result["message"])
                save_result_json(result)
                return result

        except Exception as change_error:
            # Lock 쓰기 또는 검증 도중 통신/예상치 못한 오류가 발생하면
            # 변경 전 상태로 전체 원상 복구를 시도한다.
            rollback_result = await rollback_original_lock_states()

            if rollback_result["rollback_success"]:
                message = (
                    "Lock 변경 중 오류가 발생하여 이번 변경을 취소하고 "
                    "A1~A5 전체를 변경 전 Lock 상태로 복구했습니다. "
                    f"원인: {change_error}"
                )
            else:
                message = (
                    "Lock 변경 중 오류가 발생했고, 변경 전 Lock 상태로의 "
                    "복구도 일부 실패했습니다. 현재 Lock 상태를 반드시 다시 확인해 주세요. "
                    f"원인: {change_error}"
                )

            result = {
                "status": "error",
                "message": message,
                "data": {
                    "change_error": str(change_error),
                    **rollback_result,
                }
            }

            print(result["message"])
            save_result_json(result)
            return result

        # ====================================================
        # Unlock 포지셔너 목록
        # ====================================================
        unlocked_positioners = [
            positioner
            for positioner in POSITIONER_AXIS_MAP
            if positioner not in locked_positioners
        ]

        # ====================================================
        # 성공
        # ====================================================
        result = {
            "status": "success",
            "message": (
                "포지셔너 잠금 상태가 "
                "PLC1과 PLC2에 저장되었습니다."
            ),
            "data": {
                "locked_positioners": locked_positioners,
                "locked_axes": sorted(locked_axes),
                "unlocked_positioners": unlocked_positioners,
                "unlocked_axes": sorted(unlocked_axes),
            }
        }

        print(result["message"])
        save_result_json(result)
        return result

    except pyads.ADSError as e:
        result = {
            "status": "error",
            "message": f"PLC 통신 또는 ADS 에러가 발생했습니다: {e}",
            "data": {}
        }

        print(result["message"])
        save_result_json(result)
        return result

    except Exception as e:
        result = {
            "status": "error",
            "message": (
                "포지셔너 잠금 중 예상하지 못한 "
                f"에러가 발생했습니다: {e}"
            ),
            "data": {}
        }

        print(result["message"])
        save_result_json(result)
        return result
def read_axis_lock_state(plc, plc_name: str):

    """
    PLC에서는 local_axis로 잠금 상태를 읽고,
    Python에는 global_axis 기준으로 반환한다.
    
    """

    plc_name = plc_name.strip().upper()

    get_plc_connection_info(plc_name)

    locked_axes = []
    motion_axes = []

    for positioner_info in POSITIONER_AXIS_MAP.values():

        if positioner_info["plc"] != plc_name:
            continue

        for motor in ("alpha", "beta"):

            global_axis = (
                positioner_info[motor]["global_axis"]
            )

            local_axis = (
                positioner_info[motor]["local_axis"]
            )

            is_locked = plc.read_by_name(
                f"GVL.gAxisLocked[{local_axis}]",
                pyads.PLCTYPE_BOOL
            )

            if is_locked:
                locked_axes.append(global_axis)

            else:
                motion_axes.append(global_axis)

    return (
        sorted(locked_axes),
        sorted(motion_axes)
    )
async def read_one_plc_lock_state(plc_name: str, plc):
    """
    PLC 한 대의 축 잠금 상태를 별도 스레드에서 읽는다.
    
    반환되는 축 번호는 global_axis 기준이다.
    
    """

    locked_axes, motion_axes = await asyncio.to_thread(
        read_axis_lock_state,
        plc,
        plc_name
    )

    return {
        "plc_name": plc_name,
        "locked_axes": locked_axes,
        "motion_axes": motion_axes,
    }
##########################################################################
##########################################################################



##################################################################################
# show_status_all()
##################################################################################
async def show_status_all(plc_connections):

    """
    PLC1 / PLC2에 연결하여
    A1 ~ A5 전체 포지셔너 상태를 확인하고
    save_result_json()으로 JSON 파일에 저장한다.

    확인 항목:
        - 현재 각도
        - Busy
        - Error
        - Locked

    PLC 연결은 함수 종료 후 close하지 않는다.
    """


    try:
        # ========================================================
        # 전체 포지셔너 상태 저장
        # ========================================================
        all_status = {}


        # ========================================================
        # A1 ~ A5 상태 확인
        # ========================================================
        for positioner, positioner_info \
                in POSITIONER_AXIS_MAP.items():

            plc_name = (positioner_info["plc"])

            plc = (plc_connections[plc_name])


            # ====================================================
            # Alpha, beta 축 번호
            # ====================================================
            alpha_global_axis = (positioner_info["alpha"]["global_axis"])
            alpha_local_axis = (positioner_info["alpha"]["local_axis"])

            beta_global_axis = (positioner_info["beta"]["global_axis"])
            beta_local_axis = (positioner_info["beta"]["local_axis"])


            # ====================================================
            # Alpha 현재 상태 읽기
            # ====================================================
            alpha_angle = await asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisState[{alpha_local_axis}].ActPos",
                pyads.PLCTYPE_LREAL
            )


            alpha_busy = await asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisState[{alpha_local_axis}].Busy",
                pyads.PLCTYPE_BOOL
            )


            alpha_error = await asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisState[{alpha_local_axis}].Error",
                pyads.PLCTYPE_BOOL
            )


            alpha_locked = await asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisLocked[{alpha_local_axis}]",
                pyads.PLCTYPE_BOOL
            )


            # ====================================================
            # Beta 현재 상태 읽기
            # ====================================================
            beta_angle = await asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisState[{beta_local_axis}].ActPos",
                pyads.PLCTYPE_LREAL
            )


            beta_busy = await asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisState[{beta_local_axis}].Busy",
                pyads.PLCTYPE_BOOL
            )


            beta_error = await asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisState[{beta_local_axis}].Error",
                pyads.PLCTYPE_BOOL
            )


            beta_locked = await asyncio.to_thread(
                plc.read_by_name,
                f"GVL.gAxisLocked[{beta_local_axis}]",
                pyads.PLCTYPE_BOOL
            )


            # ====================================================
            # 해당 포지셔너 상태 저장
            # ====================================================
            all_status[positioner] = {

                "plc_name":
                    plc_name,

                "alpha": {

                    "global_axis":
                        alpha_global_axis,

                    "local_axis":
                        alpha_local_axis,

                    "current_angle_degree":
                        float(alpha_angle),

                    "busy":
                        bool(alpha_busy),

                    "error":
                        bool(alpha_error),

                    "locked":
                        bool(alpha_locked),
                },

                "beta": {

                    "global_axis":
                        beta_global_axis,

                    "local_axis":
                        beta_local_axis,

                    "current_angle_degree":
                        float(beta_angle),

                    "busy":
                        bool(beta_busy),

                    "error":
                        bool(beta_error),

                    "locked":
                        bool(beta_locked),
                },
            }


        # ========================================================
        # JSON 파일 저장용 결과
        # ========================================================
        save_data = {

            "status": "success",

            "message": (
                "전체 포지셔너 현재 상태 확인 완료"
            ),

            "data": {
                "positioners":
                    all_status
            }
        }


        # ========================================================
        # 기존 save_result_json() 사용
        # ========================================================
        status_file = save_result_json(save_data)


        # ========================================================
        # 최종 반환
        # ========================================================
        result = {

            "status": "success",

            "message": (
                "모든 포지셔너의 현재 상태가 "
                f"{status_file} 파일에 저장되었습니다."
            )
        }


        return result


    # ============================================================
    # ADS 에러
    # ============================================================
    except pyads.ADSError as e:

        result = {

            "status": "error",

            "message": (
                "전체 포지셔너 상태 확인 중 "
                "PLC 통신 또는 ADS 에러가 발생했습니다: "
                f"{e}"
            )
        }

        return result


    # ============================================================
    # 기타 에러
    # ============================================================
    except Exception as e:

        result = {

            "status": "error",

            "message": (
                "전체 포지셔너 상태 확인 중 "
                "예상하지 못한 에러가 발생했습니다: "
                f"{e}"
            )
        }

        return result
