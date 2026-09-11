"""사용하는 fiber / fiducial 목록과 positioner arm 길이 정의.

fiber 구성이 바뀌면 이 파일의 FIBERS 표만 고치면 된다. fiber 개수와 arm 길이가
모두 이 표에서 나오므로 다른 코드는 손댈 필요가 없다.

FIBERS의 각 행:
    ID      Fiber_Configuration 표의 fiber ID (= Hole ID)
    arm1    positioner 안쪽 arm 길이 (mm)
    arm2    positioner 바깥쪽 arm 길이 (mm)

행의 "순서"는 target 파일(object.info, tile assign 파일)의 fiber 순서와 같아야
하고, 계산과 출력 모두 이 순서를 그대로 쓴다.
"""

from pathlib import Path

import numpy as np

# fiber/fiducial의 설계 좌표가 들어 있는 표
FIBER_TABLE_PATH = str(Path(__file__).with_name('Fiber_Configuration_250415.txt'))

# 관측할 타일/타겟 정보 (fiber별 목표 위치 xp, yp)
TARGET_INFO_PATH = '/home/kspecmtl/work/KSPEC_ICS/MTL/target/object.info'

FIBERS = (
    # ID     arm1    arm2
    ("B5",   5.13,  11.35),
    ("C2",   5.29,  11.36),
    ("D0",   5.21,  11.31),
    ("E5",   5.23,  11.39),
    ("E8",   5.23,  11.31),
    ("G4",   5.28,  11.34),
    ("G11",  5.21,  11.49),
    ("H7",   5.23,  11.43),
    ("I2",   5.29,  11.34),
    ("I9",   5.20,  11.32),
    ("K3",   5.28,  11.44),
    ("K6",   5.04,  11.18),
    ("L10",  4.98,  11.42),
    ("M7",   4.98,  11.49),
)

# ---------------------------------------------------------------------------
# fiber 수가 늘어나면 위 표를 직접 적는 대신 텍스트 파일에서 읽어올 수 있다.
# 아래 형식의 파일(주석은 #, 공백 구분)을 두고 load_fibers()로 바꿔치기하면
# 나머지 코드는 그대로 동작한다.
#
#   # ID   arm1   arm2
#   B5     5.13   11.35
#   C2     5.29   11.36
#   ...
#
# FIBER_LIST_PATH = str(Path(__file__).with_name('fiber_list.txt'))
#
# def load_fibers(path=None):
#     """텍스트 파일에서 FIBERS와 같은 형식의 tuple을 읽어온다."""
#     rows = []
#     with open(path or FIBER_LIST_PATH) as ff:
#         for line in ff:
#             line = line.split('#')[0].strip()
#             if not line:
#                 continue
#             fid, arm1, arm2 = line.split()
#             rows.append((fid, float(arm1), float(arm2)))
#     return tuple(rows)
#
# FIBERS = load_fibers()
# ---------------------------------------------------------------------------

# Fiducial은 Fiber_Configuration 표의 FiducialFlag == 1 에서 가져오되,
# 아래 ID는 사용하지 않는다.
FIDUCIAL_EXCLUDE = ('A0', 'Z1', 'Z4', 'Z10')

# find_angle_double_method2_select_elbow에 넘기는 자세 정의
ELBOW = "down"
CLOCKWISE = False


def fiber_ids():
    """FIBERS 순서 그대로의 fiber ID(= Hole ID) 리스트.

    출력 json의 key가 이 값에서 나온다 (mtlcal.angle_dict 참고).
    """
    return [row[0] for row in FIBERS]


def arm_lengths():
    """FIBERS 순서 그대로의 (arm1, arm2) 배열."""
    return (np.array([row[1] for row in FIBERS], dtype=float),
            np.array([row[2] for row in FIBERS], dtype=float))

