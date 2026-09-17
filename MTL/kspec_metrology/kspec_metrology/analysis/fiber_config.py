"""사용하는 fiber / fiducial 목록과 positioner arm 길이 정의.

fiber 구성이 바뀌면 이 파일만 고치면 된다. fiber 개수와 arm 길이가 모두 여기서
나오므로 다른 코드는 손댈 필요가 없다.

지금은 Fiber_Configuration 표의 FiducialFlag == 0 인 홀을 "표에 적힌 순서대로"
모두 positioner로 쓴다 (load_fibers 참고). 어느 홀에 positioner를 꽂았는지가
바뀌면 코드가 아니라 표의 FiducialFlag를 고치면 된다 (0 = positioner,
1 = fiducial, -9 = 미장착). 설정별로 표를 여러 개 두고 쓰려면
KSPEC_FIBER_TABLE 환경변수를 보라.

표의 순서가 곧

    - object.info의 xp, yp 순서
    - mtlcal.angle_dict가 만드는 출력 json의 key 순서

라서, 표를 건드리면 target 파일도 같은 순서로 다시 만들어야 한다.

FIBERS의 각 행:
    ID      Fiber_Configuration 표의 fiber ID (= Hole ID)
    arm1    positioner 안쪽 arm 길이 (mm)
    arm2    positioner 바깥쪽 arm 길이 (mm)
"""

import os
from pathlib import Path

import numpy as np
from astropy.io import ascii

# fiber/fiducial의 설계 좌표가 들어 있는 표.
#
# 기본값은 패키지 안에 같이 들어 있는 파일이다. 설정(어느 홀에 positioner를
# 꽂았는지)이 여럿이면 표를 패키지 밖에 이름 붙여 따로 두고 KSPEC_FIBER_TABLE
# 환경변수로 고르는 편이 낫다. 패키지 안의 파일을 덮어쓰면 pip install 때
# 날아가고, 지금 어느 설정으로 돌고 있는지도 안 보인다.
#
#   KSPEC_FIBER_TABLE=~/configs/Fiber_Configuration_phase1.txt python ...
#
# 표를 바꾸면 positioner 개수와 순서가 바뀌므로 target 파일(object.info)의
# xp, yp도 같은 순서로 다시 만들어야 한다. xp가 더 많으면 앞에서 잘라 쓰면서
# 조용히 지나가므로(mtlcal.load_configuration) 특히 주의할 것.
FIBER_TABLE_ENV = 'KSPEC_FIBER_TABLE'
DEFAULT_FIBER_TABLE_PATH = str(Path(__file__).with_name('Fiber_Configuration_250415.txt'))

FIBER_TABLE_PATH = os.environ.get(FIBER_TABLE_ENV) or DEFAULT_FIBER_TABLE_PATH

if not os.path.exists(FIBER_TABLE_PATH):
    raise FileNotFoundError(
        f"Fiber configuration table not found: {FIBER_TABLE_PATH}"
        + (f" (from ${FIBER_TABLE_ENV})" if os.environ.get(FIBER_TABLE_ENV)
           else ""))

# 관측할 타일/타겟 정보 (fiber별 목표 위치 xp, yp)
TARGET_INFO_PATH = '/home/kspecmtl/work/KSPEC_ICS/MTL/target/object.info'

# arm 길이 측정값이 없는 positioner에 쓰는 설계값 (arm1, arm2) [mm]
DEFAULT_ARM = (5.2, 11.6)

# 측정된 arm 길이가 있는 positioner만 여기에 적는다. 나머지는 DEFAULT_ARM을 쓴다.
#
# 2025-08 시점에 14개 fiber만 측정값이 있었고, 그 값은 아래와 같았다. 지금은 전체
# positioner를 쓰는데 나머지 측정값이 없어서 전부 설계값으로 통일한다. 측정이
# 끝나면 아래 주석을 되살려 넣으면 된다.
#
#   B5  5.13 11.35 | C2  5.29 11.36 | D0  5.21 11.31 | E5  5.23 11.39
#   E8  5.23 11.31 | G4  5.28 11.34 | G11 5.21 11.49 | H7  5.23 11.43
#   I2  5.29 11.34 | I9  5.20 11.32 | K3  5.28 11.44 | K6  5.04 11.18
#   L10 4.98 11.42 | M7  4.98 11.49
ARM_OVERRIDES = {}


def load_fibers(path=None, arm_overrides=None):
    """Fiber_Configuration 표에서 positioner 행을 읽어 FIBERS 형식으로 돌려준다.

    FiducialFlag == 0 인 행이 positioner다. 표에 적힌 순서를 그대로 지킨다.
    """
    tab = ascii.read(path or FIBER_TABLE_PATH)
    tab.rename_columns(tab.colnames[:4], ["ID", "X", "Y", "FiducialFlag"])

    overrides = ARM_OVERRIDES if arm_overrides is None else arm_overrides

    rows = []
    for row in tab:
        if int(row["FiducialFlag"]) != 0:
            continue
        hole = str(row["ID"])
        arm1, arm2 = overrides.get(hole, DEFAULT_ARM)
        rows.append((hole, float(arm1), float(arm2)))

    return tuple(rows)


FIBERS = load_fibers()

# Fiducial은 Fiber_Configuration 표의 FiducialFlag == 1 에서 가져오되,
# 아래 ID는 사용하지 않는다. 지금은 전부 쓴다.
FIDUCIAL_EXCLUDE = ()

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
