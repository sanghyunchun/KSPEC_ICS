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
DEFAULT_FIBER_TABLE_PATH = str(Path(__file__).with_name('Fiber_Configuration_config73.txt'))

FIBER_TABLE_PATH = os.environ.get(FIBER_TABLE_ENV) or DEFAULT_FIBER_TABLE_PATH

if not os.path.exists(FIBER_TABLE_PATH):
    raise FileNotFoundError(
        f"Fiber configuration table not found: {FIBER_TABLE_PATH}"
        + (f" (from ${FIBER_TABLE_ENV})" if os.environ.get(FIBER_TABLE_ENV)
           else ""))

# 관측할 타일/타겟 정보 (fiber별 목표 위치 xp, yp)
TARGET_INFO_PATH = '/home/kspecmtl/work/KSPEC_ICS/MTL/target/object.info'

# Fiducial 핀홀의 실제 위치.
#
# fiducial은 홀 한가운데가 아니라 조금 치우쳐 박혀 있고, 그 치우친 양(dx, dy)을
# 따로 재서 npz로 들고 있다. 그 npz의 index가 어느 홀인지는 map 파일에 적는다
# (현장에서 핀홀을 옮기면 map 파일의 ID만 고치면 된다).
#
# 두 파일이 다 있으면 load_configuration이 fiducial 기준 좌표를
# '표의 홀 좌표 + dx, dy' 로 쓴다. 없으면 표의 홀 좌표를 그대로 쓴다.
FIDUCIAL_PINHOLE_LOC_PATH = os.environ.get('KSPEC_FIDUCIAL_PINHOLE_LOC') or str(
    Path(__file__).with_name('Fiducial_pinhole_loc.npz'))
FIDUCIAL_PINHOLE_MAP_PATH = os.environ.get('KSPEC_FIDUCIAL_PINHOLE_MAP') or str(
    Path(__file__).with_name('Fiducial_pinhole_map.txt'))


def pinhole_offsets(map_path=None, loc_path=None):
    """Hole ID -> (dx, dy) [mm]. 파일이 없으면 빈 dict을 돌려준다.

    map 파일은 "index  ID" 두 칸이고 '#' 뒤는 주석이다. ID가 '-' 인 줄은
    쓰지 않는 index로 보고 건너뛴다.
    """
    map_path = map_path or FIDUCIAL_PINHOLE_MAP_PATH
    loc_path = loc_path or FIDUCIAL_PINHOLE_LOC_PATH

    missing = [q for q in (map_path, loc_path) if not os.path.exists(q)]
    if missing:
        return {}

    with np.load(loc_path) as d:
        off = {int(i): (float(a), float(b))
               for i, a, b in zip(d['index'], d['dx'], d['dy'])}

    out = {}
    with open(map_path) as ff:
        for nline, line in enumerate(ff, 1):
            line = line.split('#')[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(
                    f"{map_path}:{nline}: 'index ID' 두 칸이어야 한다: {line!r}")
            idx, hole = parts
            if hole == '-':
                continue
            try:
                key = int(idx)
            except ValueError:
                raise ValueError(
                    f"{map_path}:{nline}: index가 정수가 아니다: {idx!r}") from None
            if key not in off:
                raise ValueError(
                    f"{map_path}:{nline}: index {key} 가 "
                    f"{os.path.basename(loc_path)} 에 없다")
            if hole in out:
                raise ValueError(f"{map_path}:{nline}: {hole} 가 중복이다")
            out[hole] = off[key]

    return out


# 실측 기하 (plate 중심 기준).
#
# 설계도 값 대신 실제로 재서 쓰려는 것이 세 가지다.
#   1. positioner 회전 중심 위치 (X, Y)
#   2. fiducial 핀홀 위치        (X, Y)
#   3. positioner arm 길이       (arm1, arm2)
#
# 셋을 한 파일에 홀 ID로 적는다. 아직 안 잰 값은 '-' 로 두면 그 항목만 설계값을
# 쓴다. 측정이 끝나는 대로 한 줄씩 채워 나가면 된다.
#
#   # ID     X          Y        arm1    arm2
#   C4      -9.5123    82.2810   5.21   11.58
#   D2       -          -        5.19   11.61     <- arm만 쟀을 때
#
# 기본은 켜져 있다 (USE_MEASURED=True). 끄는 방법은 두 가지다.
#   - 환경변수 : KSPEC_USE_MEASURED=0
#   - 호출 인자: mtlcal(..., use_measured=False)
# 파일이 없으면 (인자로 명시해 켠 경우가 아니면) 경고만 남기고 설계값을 쓴다.
# 파일 경로는 KSPEC_MEASURED_GEOMETRY 로 바꿀 수 있다.
MEASURED_GEOMETRY_ENV = 'KSPEC_MEASURED_GEOMETRY'
DEFAULT_MEASURED_GEOMETRY_PATH = str(
    Path(__file__).with_name('Measured_Geometry.txt'))
MEASURED_GEOMETRY_PATH = (os.environ.get(MEASURED_GEOMETRY_ENV)
                          or DEFAULT_MEASURED_GEOMETRY_PATH)

USE_MEASURED_ENV = 'KSPEC_USE_MEASURED'
# 기본은 켜져 있다 (2026-10 부터: 새 plate 의 fiducial 핀홀 실측값이 패키지에 들어 있다).
# 끄려면 KSPEC_USE_MEASURED=0 또는 mtlcal(..., use_measured=False).
USE_MEASURED = os.environ.get(USE_MEASURED_ENV, '1').strip().lower() not in (
    '0', 'false', 'no', 'off')

# positioner 회전 중심 실측값 (Measured_Geometry 의 positioner 행 X, Y; arm scan 결과) 을 쓸지.
# fiducial 핀홀 실측값 (use_measured) 과 **별개 스위치** 다 (2026-10-27). 2026-10-27 arm scan 결과를
# 기본으로 쓴다 (사용자 결정, 같은 날). 끄는 방법:
#   - 환경변수 : KSPEC_USE_MEASURED_POSITIONERS=0
#   - 호출 인자: mtlcal(..., use_measured_positioners=False) / MetrologyRun(..., use_measured_positioners=False)
#   - 기본값을 바꾸려면 아래 한 줄.
# 꺼져 있으면 positioner 중심은 설계값, arm 길이는 use_measured 를 따른다 (Positioner_Arm_Table + Map).
USE_MEASURED_POSITIONERS_ENV = 'KSPEC_USE_MEASURED_POSITIONERS'
USE_MEASURED_POSITIONERS = os.environ.get(USE_MEASURED_POSITIONERS_ENV, '1').strip().lower() not in (
    '0', 'false', 'no', 'off')


def _use_measured_positioners(flag):
    """None 이면 모듈 기본값(USE_MEASURED_POSITIONERS)을 쓴다."""
    return USE_MEASURED_POSITIONERS if flag is None else bool(flag)


# 실측 좌표가 설계 좌표에서 이보다 멀면 다른 plate 의 파일로 보고 멈춘다 [mm].
# 핀홀은 홀 중심에서 0.5 mm 안에 있고, 표를 바꿔도 fiducial ID 가 상당수 겹치므로
# 옛 plate 의 실측값이 조용히 적용되는 것을 이 검사로 막는다.
MEASURED_MAX_DEV = 1.0


def measured_geometry(path=None):
    """홀 ID -> {'x':, 'y':, 'arm1':, 'arm2':}. 안 잰 항목은 None.

    'ID X Y arm1 arm2' 다섯 칸이고 '#' 뒤는 주석이다. 값이 '-' 면 안 잰 것으로
    보고 그 항목만 설계값을 쓴다. 파일이 없으면 빈 dict을 돌려준다.
    """
    path = path or MEASURED_GEOMETRY_PATH
    if not os.path.exists(path):
        return {}

    out = {}
    with open(path) as ff:
        for nline, line in enumerate(ff, 1):
            line = line.split('#')[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 5:
                raise ValueError(
                    f"{path}:{nline}: 'ID X Y arm1 arm2' 다섯 칸이어야 한다: "
                    f"{line!r}")
            hole = parts[0]
            if hole in out:
                raise ValueError(f"{path}:{nline}: {hole} 가 중복이다")

            def val(tok, name):
                if tok == '-':
                    return None
                try:
                    return float(tok)
                except ValueError:
                    raise ValueError(
                        f"{path}:{nline}: {name} 가 숫자가 아니다: "
                        f"{tok!r}") from None

            out[hole] = dict(zip(('x', 'y', 'arm1', 'arm2'),
                                 (val(t, n) for t, n in
                                  zip(parts[1:], ('X', 'Y', 'arm1', 'arm2')))))

    return out


# positioner 개체별 arm 길이 측정표와, 어느 개체가 어느 홀에 꽂혔는지.
#
# 제작된 positioner 전체를 번호별로 잰 표가 Positioner_Arm_Table.txt 다
# (final_alpha, final_beta 열을 쓴다). 어느 번호가 어느 홀에 들어갔는지는
# 설치가 끝나야 알 수 있으므로 Positioner_Map.txt 에 따로 적는다.
#
#   # ID   positioner
#   C4     17
#   C5     42
#
# 맵이 없거나 홀이 적혀 있지 않으면 그 positioner는 설계값을 쓴다.
# 2026-10-25 부터 설치표(Positioner_Map.txt) 가 패키지에 들어 있어 기본으로 실측 arm 을 쓴다.
# 둘 다 use_measured 스위치 아래에서만 쓰인다.
POSITIONER_ARM_TABLE_ENV = 'KSPEC_POSITIONER_ARM_TABLE'
POSITIONER_MAP_ENV = 'KSPEC_POSITIONER_MAP'
POSITIONER_ARM_TABLE_PATH = (os.environ.get(POSITIONER_ARM_TABLE_ENV)
                             or str(Path(__file__).with_name('Positioner_Arm_Table.txt')))
POSITIONER_MAP_PATH = (os.environ.get(POSITIONER_MAP_ENV)
                       or str(Path(__file__).with_name('Positioner_Map.txt')))


def positioner_arms(path=None):
    """positioner 번호 -> (arm1, arm2). final_alpha / final_beta 열을 쓴다.

    result 가 OK 가 아닌 행은 건너뛴다. 파일이 없으면 빈 dict.
    """
    path = path or POSITIONER_ARM_TABLE_PATH
    if not os.path.exists(path):
        return {}

    out = {}
    with open(path) as ff:
        for nline, line in enumerate(ff, 1):
            line = line.split('#')[0].strip()
            if not line:
                continue
            p = line.split()
            if len(p) < 7:
                raise ValueError(f"{path}:{nline}: 열이 모자란다: {line!r}")
            if len(p) >= 8 and p[7].upper() != 'OK':
                continue
            try:
                out[int(p[0])] = (float(p[5]), float(p[6]))   # final_alpha/beta
            except ValueError:
                raise ValueError(
                    f"{path}:{nline}: 숫자로 읽을 수 없다: {line!r}") from None

    return out


def positioner_map(path=None):
    """홀 ID -> positioner 번호. 'ID 번호' 두 칸, '#' 주석, '-' 는 건너뛴다."""
    path = path or POSITIONER_MAP_PATH
    if not os.path.exists(path):
        return {}

    out = {}
    with open(path) as ff:
        for nline, line in enumerate(ff, 1):
            line = line.split('#')[0].strip()
            if not line:
                continue
            p = line.split()
            if len(p) != 2:
                raise ValueError(
                    f"{path}:{nline}: 'ID 번호' 두 칸이어야 한다: {line!r}")
            if p[1] == '-':
                continue
            if p[0] in out:
                raise ValueError(f"{path}:{nline}: {p[0]} 가 중복이다")
            try:
                out[p[0]] = int(p[1])
            except ValueError:
                raise ValueError(
                    f"{path}:{nline}: positioner 번호가 정수가 아니다: "
                    f"{p[1]!r}") from None

    dup = [v for v in set(out.values()) if list(out.values()).count(v) > 1]
    if dup:
        raise ValueError(f"{path}: 같은 positioner가 여러 홀에 적혀 있다: {dup}")

    return out


def _use_measured(flag):
    """None이면 모듈 기본값(USE_MEASURED)을 쓴다."""
    return USE_MEASURED if flag is None else bool(flag)


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

# 어느 positioner 가 켜지는가 (2026-10-26 확정, 설치표 Positioner mapping_20261012 의 obj / sky 열).
#
# 분광기에 연결된 fiber 는 43 개뿐이다 (obj 37 + sky 6). back-illumination 은 분광기에서 나오므로
# 이 43 개만 켜지고, 나머지 positioner 30 개 (고장나 고정된 25 + fiber 가 안 꽂힌 8) 는 빛이
# 나지 않는다. 설치표의 obj 가운데 G4 는 fiber 가 끊어져 그 자리 대신 H3 를 쓴다 (사용자 확인 2026-10-26).
#
#   FIBER_OBJ      분광기 obj fiber 가 꽂힌 positioner 홀 37 개 (설치표 obj 에서 G4 -> H3). 전부 매칭.
#   FIBER_EXCLUDE  빛이 안 나는 positioner 홀 33 개 (obj 도 FIXED 도 아닌 것; 끊어진 G4 포함). 이미지에서
#                  찾지 않고 매칭에서 뺀다. 표·target·json 순서는 그대로 두고 (positioner 는 꽂혀 있다) 그 fiber 의
#                  위치 오차는 NaN, 회전량은 0 으로 나온다 (누적 각도는 직전 값 유지).
#   FIBER_FIXED    빛은 나지만 움직이지 않는 positioner 홀: sky fiber 가 꽂힌 고정 positioner 3 개 (G7, H8, J6).
#                  목표·json 에서는 FIBER_EXCLUDE 처럼 빠지고(회전량 0, 오차 NaN), 이미지에서는 켜져 있다고 본다.
#   SKY_FIBERS     표에서 -9 인 홀에 꽂힌 sky fiber 3 개 (B7, H1, N7). 켜져 있다고 본다.
#
# FIXED 와 SKY 는 "그 홀 중심에서 arm 길이 안에 있으면서 살아 있는 fiber 의 목표 근처는 아닌" 검출을
# 그 점으로 보고 fiber 매칭에서 뺀다. 자리를 정확히 아는 경우는 아래 Fixed_Spots 파일.
#
# 켜진 점 기대 수 = 37 (obj) + 3 (FIXED) + 3 (SKY) = 43 (+ fiducial 30 = 73). 매칭하는 fiber = 37.
#
#   환경변수 : KSPEC_FIBER_EXCLUDE="G4,C6,..."  KSPEC_FIBER_FIXED="G7,H8,J6"  KSPEC_SKY_FIBERS="B7,H1,N7"
#   파일     : 아래 목록 (또는 import 뒤 fiber_config.FIBER_EXCLUDE = [...])
FIBER_OBJ = ['C4', 'C5', 'D2', 'D3', 'D4', 'D5', 'D7', 'E8', 'E9', 'F8', 'F9',
             'G3', 'G5', 'G6', 'G9', 'H3', 'H4', 'H5', 'H6', 'H7',
             'I3', 'I5', 'I6', 'I7', 'I8', 'J2', 'J3', 'J4', 'J5',
             'K2', 'K3', 'K4', 'L3', 'L5', 'L6', 'L7', 'M3']          # <- 분광기 obj fiber 홀 (37; 설치표 "F19" 는 F9, G4 대신 H3)
FIBER_FIXED = ['G7', 'H8', 'J6']        # <- sky fiber 가 꽂힌, 고장나 고정된 positioner 홀 (켜짐, 매칭 안 함)
SKY_FIBERS = ['B7', 'H1', 'N7']         # <- 표에서 -9 인 홀의 sky fiber (켜짐, 매칭 안 함)

# 빛이 안 나는 positioner = obj 도 FIXED 도 아닌 것 (고정 25: C6 E2 E4 E5 E6 E7 F2 F3 F4 F5 F6 F7
# H9 H10 H11 I9 I10 J7 J8 J9 J10 K5 K6 K7 K9, fiber 없음 8: F10 G4 G10 G11 I2 L8 M4 M5).
FIBER_EXCLUDE = [h for h, _a1, _a2 in FIBERS if h not in FIBER_OBJ and h not in FIBER_FIXED]

FIBER_EXCLUDE_ENV = 'KSPEC_FIBER_EXCLUDE'
if os.environ.get(FIBER_EXCLUDE_ENV, '').strip():      # 환경변수가 있으면 그것이 우선
    FIBER_EXCLUDE = [t.strip() for t in
                     os.environ[FIBER_EXCLUDE_ENV].replace(';', ',').split(',') if t.strip()]

for _env, _name in (('KSPEC_FIBER_FIXED', 'FIBER_FIXED'), ('KSPEC_SKY_FIBERS', 'SKY_FIBERS')):
    if os.environ.get(_env, '').strip():
        globals()[_name] = [t.strip() for t in os.environ[_env].replace(';', ',').split(',') if t.strip()]


def fixed_mask():
    """fiber_ids() 순서로, 고장나 고정된 positioner (FIBER_FIXED) 면 True."""
    ids = list(fiber_ids())
    unknown = [f for f in FIBER_FIXED if f not in ids]
    if unknown:
        raise ValueError(f"FIBER_FIXED 에 표의 positioner 가 아닌 ID 가 있다: {unknown}")
    return np.array([i in FIBER_FIXED for i in ids], dtype=bool)


def hole_xy(hole_ids):
    """표(FIBER_TABLE_PATH)에서 홀 ID 들의 (x, y) [mm] (flag 와 무관하게 모든 홀)."""
    tab = ascii.read(FIBER_TABLE_PATH)
    c = tab.colnames
    xy = {str(r[c[0]]).strip(): (float(r[c[1]]), float(r[c[2]])) for r in tab}
    unknown = [h for h in hole_ids if h not in xy]
    if unknown:
        raise ValueError(f"표 {FIBER_TABLE_PATH} 에 없는 홀 ID: {unknown}")
    return np.array([xy[h] for h in hole_ids], dtype=float).reshape(-1, 2)


def lit_unmatched_holes():
    """켜져 있지만 매칭하지 않을 점들의 홀 중심 [(x, y)] = FIBER_FIXED + SKY_FIBERS."""
    return hole_xy(list(FIBER_FIXED) + list(SKY_FIBERS))


# 자리를 정확히 아는 고정 점 (선택). 초점면 좌표 [mm] 를 파일에 적어 두면 그 자리(반지름
# FIXED_SPOT_TOL)의 검출은 fiber 매칭에서 뺀다. 위 FIBER_FIXED / SKY_FIBERS 와 같이 써도 된다.
#   # name   X        Y
#   sky1    47.5   115.18
#   C6      35.3    97.6     # 고장: 이 자리에 고정
# 파일: analysis/Fixed_Spots.txt (KSPEC_FIXED_SPOTS 로 바꿀 수 있다). 없으면 빈 dict.
FIXED_SPOTS_ENV = 'KSPEC_FIXED_SPOTS'
FIXED_SPOTS_PATH = os.environ.get(FIXED_SPOTS_ENV) or str(Path(__file__).with_name('Fixed_Spots.txt'))
FIXED_SPOT_TOL = 1.5          # 이 거리 [mm] 안의 검출을 고정 점으로 본다


def fixed_spots(path=None):
    """{name: (x, y)} [mm]. 파일이 없으면 빈 dict."""
    path = path or FIXED_SPOTS_PATH
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path) as ff:
        for n, line in enumerate(ff, 1):
            line = line.split('#')[0].strip()
            if not line:
                continue
            p = line.replace(',', ' ').split()
            if len(p) != 3:
                raise ValueError(f"{path}:{n}: 'name X Y' 세 칸이어야 한다: {line!r}")
            if p[0] in out:
                raise ValueError(f"{path}:{n}: {p[0]} 가 중복이다")
            out[p[0]] = (float(p[1]), float(p[2]))
    return out


def dead_mask():
    """fiber_ids() 순서로, 목표 매칭에서 빼는 fiber 면 True (끊어진 FIBER_EXCLUDE + 고정된 FIBER_FIXED)."""
    ids = list(fiber_ids())
    unknown = [f for f in FIBER_EXCLUDE if f not in ids]
    if unknown:
        raise ValueError(f"FIBER_EXCLUDE 에 표의 positioner 가 아닌 ID 가 있다: {unknown} "
                         f"(표 {FIBER_TABLE_PATH})")
    return np.array([i in FIBER_EXCLUDE for i in ids], dtype=bool) | fixed_mask()

# find_angle_double_method2_select_elbow에 넘기는 자세 정의
# 출력 각도의 부호 (alpha, beta). 명령각 = ANGLE_SIGN x 기하각 - ANGLE_ZERO (아래).
# 기하각: 초점면 +x 에서 반시계 theta, elbow-down phi ([0, 180]).
#
# 2026-10-27 본 장비 (ICS fbpoffset 으로 positioner 를 움직인 trial 1 -> 2 -> 3) 에서 확인:
# positioner 는 json 의 alpha, beta 와 **반대 방향** 으로 돌았다 (오차가 trial 마다 0.8 -> 1.6 -> 2.9 mm
# 로 늘었고, 측정 위치에서 json 의 -1 배를 돌린 예측만 실측과 0.2 mm 안에서 맞았다). 그래서 둘 다 -1.
# 사용자 확인 (2026-10-27): FBP 제어는 반시계를 음수로 쓴다. 기하각 정의는 그대로이고 부호만 붙인다.
# 2026-10-23 실험실 (다른 제어 소프트웨어) 에서는 (+1, +1) 이었다. 다른 규약이면
# KSPEC_ANGLE_SIGN="1,1" 또는 fiber_config.ANGLE_SIGN 으로 바꾼다 (ANGLE_ZERO 도 같이).
ANGLE_SIGN_ENV = 'KSPEC_ANGLE_SIGN'
ANGLE_SIGN = (-1., -1.)
if os.environ.get(ANGLE_SIGN_ENV, '').strip():
    ANGLE_SIGN = tuple(float(t) for t in os.environ[ANGLE_SIGN_ENV].replace(';', ',').split(','))
    if len(ANGLE_SIGN) != 2 or any(abs(v) != 1. for v in ANGLE_SIGN):
        raise ValueError(f"{ANGLE_SIGN_ENV} must be two values of +1/-1, e.g. '-1,1'")

# positioner 명령각의 영점 (2026-10-27 확정). 기하학적으로 (alpha, beta) = (30, 150) 인 자세가 positioner
# 제어에서는 (0, 0) 이다. 이 패키지가 내보내는 각도 (json, offset 표의 누적각, lab.xy2ab) 와 받는 각도
# (target 파일의 alpha/beta, 각도 json, lab.make_target(angles=...)) 는 모두 **명령각** 이다:
#     명령각 = ANGLE_SIGN x 기하각 - ANGLE_ZERO
# ANGLE_SIGN = (-1, -1) 이므로 기하각 (30, 150) 이 명령 (0, 0) 이 되려면 ANGLE_ZERO = (-30, -150) 이다
# (명령 0 = -30 - za -> za = -30). 이번 trial 의 회전량 (dalpha, dbeta) 은 차이라서 영점과 무관하다.
#   환경변수 : KSPEC_ANGLE_ZERO="-30,-150"   (부호 (1, 1) 이면 "30,150"; 기하각을 그대로 쓰려면 "0,0")
ANGLE_ZERO_ENV = 'KSPEC_ANGLE_ZERO'
ANGLE_ZERO = (-30., -150.)
if os.environ.get(ANGLE_ZERO_ENV, '').strip():
    ANGLE_ZERO = tuple(float(t) for t in os.environ[ANGLE_ZERO_ENV].replace(';', ',').split(','))
    if len(ANGLE_ZERO) != 2:
        raise ValueError(f"{ANGLE_ZERO_ENV} must be two values (alpha, beta) in deg, e.g. '30,150'")



def command_alpha(theta):
    """기하각 theta [rad] -> alpha 명령각 [deg] (절대각).

    기하각을 타일 경로 계획기 (.path.txt) 와 같은 [0, 360) 로 둔 뒤 명령각으로 바꾼다. 기본 규약에서는
    명령 alpha 가 (-330, 30] 이고, FBP 경로 끝각도 같은 범위다 (예: ASPECS_2627_0005 끝각 -329.3 ~ 28.0).
    positioner 리밋은 여기에 ALPHA_MARGIN 을 더한 (-420, 120] 이다 (alpha_cmd_range); 누적 alpha 는 그 안에서
    가장 적게 도는 해를 따라 움직인다 (alpha_cum_in_range).
    (-180, 180] 로 접으면 안 된다: 기하각 210 도 넘는 positioner 가 360 도 다른 명령각 (-220 -> 140) 을
    받고, fbpoffset 은 절대각으로 움직이므로 그 positioner 가 반대 방향으로 한 바퀴 돈다 (2026-10-29).
    """
    sa, za = ANGLE_SIGN[0], ANGLE_ZERO[0]
    return sa*(np.degrees(np.asarray(theta, dtype=float)) % 360.) - za


# arm 도달 한계 근처의 보호 (2026-10-29). 목표나 측정 위치가 회전 중심에서 (a1 + a2 - REACH_MARGIN) 보다 멀면
# 완전히 편 자세 (phi = 0, alpha 는 그 방향) 로 푼다. 이유: 거의 편 자세에서는 반지름이 beta 에 둔감해서
# (phi 6 도에서 7 um/deg) 수백 um 의 위치 오차가 수십 도의 beta 보정으로 바뀌고, 표의 arm 길이와 실제가
# 0.1-0.3 mm 만 달라도 "조금 더 펴라" 는 명령이 trial 마다 커져 beta 가 범위를 넘고 positioner 가 날아간다
# (2026-10-29 9111: 목표가 한계 22-108 um 안쪽이던 G3, M3, L5). 이 보정은 방향(alpha)만 맞추고 radial 오차는
# 실제 arm 길이 차이만큼 남기는 것이 물리적으로 최선이다.
#   환경변수 : KSPEC_REACH_MARGIN="0.3"   (mm; 0 이면 끔)
REACH_MARGIN_ENV = 'KSPEC_REACH_MARGIN'
REACH_MARGIN = float(os.environ.get(REACH_MARGIN_ENV, '0.3') or 0.3)

# positioner 리밋 여유 [deg] (아래쪽, 위쪽). 한 바퀴 범위 alpha (-330, 30], beta [-30, 150] 에 더해 positioner 가
# 실제로 갈 수 있는 범위다 (FBP 쪽 리밋과 같아야 한다).
# alpha (2026-10-30, 기본 90 도씩 -> (-420, 120]): alpha 는 360 도 돌면 같은 위치라 한 xy 에 해가 여럿이다 (5 = 365 = -355).
#   이전에는 누적 alpha 를 한 바퀴로 wrap 해서 리밋을 조금만 넘어도 (tile01 J4: 16.50 + 13.98 = 30.48 -> -329.52)
#   positioner 가 반대로 360 도 도는 명령이 되었다. 이제는 직전 각도에서 가장 적게 도는 해를 고르고 (alpha_cum_in_range),
#   그 해가 리밋 밖이면 반대로 도는 해, 그것도 밖이면 리밋에서 자른다. 여유는 리밋 근처 목표를 넘어가는 보정을 받아 주는
#   폭이고 (한없이 돌지 않게 하는 한계), 되돌아올 때는 온 길대로 0 으로 간다.
# beta (기본 30 도씩 -> [-60, 180]): 150 을 넘는 beta 는 팔이 곧게 펴진 자세를 지나 elbow-up 으로 접히는 것이라
#   elbow-down 목표에 도움이 되지 않는다. 위쪽 여유는 0 으로 두는 것이 안전하다 (KSPEC_BETA_MARGIN="30,0").
#   환경변수 : KSPEC_ALPHA_MARGIN="90,90", KSPEC_BETA_MARGIN="30,30"   ("0,0" 이면 2026-10-29 까지의 범위)
def _margin(env, default):
    v = os.environ.get(env, '').strip()
    if not v:
        return default
    m = tuple(float(t) for t in v.replace(';', ',').split(','))
    if len(m) != 2 or any(x < 0 for x in m):
        raise ValueError(f"{env} must be two non-negative values (low, high) in deg, e.g. '30,30'")
    return m

ALPHA_MARGIN_ENV = 'KSPEC_ALPHA_MARGIN'
ALPHA_MARGIN = _margin(ALPHA_MARGIN_ENV, (90., 90.))
BETA_MARGIN_ENV = 'KSPEC_BETA_MARGIN'
BETA_MARGIN = _margin(BETA_MARGIN_ENV, (30., 30.))

# 가장 적게 도는 alpha 해가 리밋 밖일 때 반대로 도는 해 (회전 180 도 넘음) 를 쓸지. FBP 의 한 번 이동 제한 (45 도) 에
# 걸리므로 기본은 끔 (리밋에서 자름). 환경변수 KSPEC_ALPHA_OTHER_WAY=1 로 켠다.
ALPHA_OTHER_WAY_ENV = 'KSPEC_ALPHA_OTHER_WAY'
ALPHA_OTHER_WAY = os.environ.get(ALPHA_OTHER_WAY_ENV, '0').strip().lower() in ('1', 'true', 'yes', 'on')

# beta 명령각 범위: positioner raw beta -180 .. 0 에 FBP 영점 150 을 더한 -30 .. 150 (= 기하각 180 .. 0,
# elbow-down) 에 위 여유를 더한 것 (기본 [-60, 180]). 150 을 넘는 beta 는 팔이 곧게 펴진 자세를 지나 elbow-up 으로
# 접히는 것이라, 2026-10-29 9111 의 발산 (README 참고) 은 도달 한계 보호 (REACH_MARGIN) 가 막아야 한다.
# 누적각이 이 밖으로 나가면 positioner 가 실행할 수 없는 명령이라 잘라 둔다 (경고).
BETA_RANGE = (-30. - BETA_MARGIN[0], 150. + BETA_MARGIN[1])

def clip_alpha_cmd(alpha):
    """절대 alpha 명령각을 positioner 범위 (lo, hi] (여유 포함, 기본 (-420, 120]) 끝에서 자른다 (NaN 은 그대로).
    범위 끝은 하드 리밋이라 wrap 으로 반대편 값을 주면 한 바퀴 되돌아가는 명령이 되므로, beta 처럼 리밋에 붙여 둔다."""
    lo, hi = alpha_cmd_range()
    return np.clip(np.asarray(alpha, float), lo + 1e-6, hi)


def alpha_cum_in_range(prev, rot):
    """직전 alpha 명령각 prev 에서 회전량 rot [deg] 만큼 돈 뒤의 누적 alpha 를, positioner 범위 (lo, hi] 안에서 가장 적게
    도는 해로 고른다. alpha 는 360 도 돌면 같은 위치이므로 후보는 prev + rot + k*360 (k = 0, -1, +1) 이다.
      1) prev + rot (가장 짧은 회전) 이 범위 안이면 그대로
      2) 범위 밖이면 (ALPHA_OTHER_WAY 가 참일 때만) 반대로 도는 해 (prev + rot -/+ 360) 가운데 범위 안인 것.
         회전이 180 도를 넘으므로 FBP 의 한 번 이동 제한 (45 도) 에 걸린다. 기본은 끔.
      3) 그 밖에는 범위 끝에서 자른다 (arm 이 리밋에 붙고, 그만큼 모자란 채 멈춘다)
    반환: (alpha, other_way, clipped) -- other_way 는 2) 를 쓴 fiber, clipped 는 3) 인 fiber (NaN 은 둘 다 False, alpha 는 NaN)."""
    prev = np.asarray(prev, float); rot = np.asarray(rot, float)
    lo, hi = alpha_cmd_range()
    cand = prev[:, None] + rot[:, None] + 360.*np.array([0., -1., 1.])[None, :]
    ok = (cand > lo) & (cand <= hi)
    if not ALPHA_OTHER_WAY:
        ok[:, 1:] = False
    travel = np.where(ok, np.abs(cand - prev[:, None]), np.inf)
    pick = np.argmin(travel, axis=1)
    alpha = cand[np.arange(prev.size), pick]
    finite = np.isfinite(prev + rot)
    clipped = finite & ~ok.any(axis=1)
    alpha[clipped] = clip_alpha_cmd(prev + rot)[clipped]
    alpha[~finite] = np.nan
    other_way = finite & ~clipped & (pick != 0)
    return alpha, other_way, clipped


def wrap_alpha_cmd(alpha):
    """절대 alpha 명령각을 한 바퀴 범위로 접는다 (기본 규약에서 (-330, 30]; 여유 없음).
    command_alpha 와 같은 범위다: 명령각 -> 기하각 [0, 360) -> 명령각.
    2026-10-30 부터 누적 alpha 에는 쓰지 않는다 (리밋을 조금 넘은 값이 반대로 한 바퀴 도는 명령이 되므로 alpha_cum_in_range)."""
    sa, za = ANGLE_SIGN[0], ANGLE_ZERO[0]
    a = np.asarray(alpha, float)
    geom = (sa*(a + za)) % 360.                              # 기하각 [0, 360)
    return sa*geom - za


def alpha_cmd_range(margin=True):
    """positioner 가 받는 alpha 명령각 범위 (lo, hi]. 한 바퀴 범위 (기본 (-330, 30]) 에 ALPHA_MARGIN 을 더한
    (-420, 120] 이 기본이고, margin=False 면 한 바퀴 범위 (command_alpha / wrap_alpha_cmd 의 출력 범위)."""
    sa, za = ANGLE_SIGN[0], ANGLE_ZERO[0]
    lo, hi = sorted([sa*0. - za, sa*360. - za])
    if margin:
        lo, hi = lo - ALPHA_MARGIN[0], hi + ALPHA_MARGIN[1]
    return (lo, hi)


def out_of_range_mask(angles):
    """fiber 순서로, (alpha, beta) 가운데 하나라도 positioner 범위 밖이면 True (NaN 은 False)."""
    a = np.asarray(angles, float)[0::2]; b = np.asarray(angles, float)[1::2]
    lo, hi = alpha_cmd_range()
    bad_a = np.isfinite(a) & ((a <= lo - 1e-9) | (a > hi + 1e-9))
    bad_b = np.isfinite(b) & ((b < BETA_RANGE[0] - 1e-9) | (b > BETA_RANGE[1] + 1e-9))
    return bad_a | bad_b


def check_command_angles(angles, where=''):
    """내보낼 (alpha, beta, alpha, beta, ...) 가 positioner 범위 안인지 확인한다. 밖이면 ValueError.
    alpha 는 alpha_cmd_range() (여유 포함), beta 는 BETA_RANGE. NaN 은 (끊어진 fiber) 통과.
    (정상 경로에서는 alpha_cum_in_range / clip_beta 가 먼저 적용되고, mtlcal 은 그래도 밖인 fiber 를 직전 각도로
    되돌리므로 여기까지 오지 않는다. 마지막 방어선.)"""
    a = np.asarray(angles, float)[0::2]; b = np.asarray(angles, float)[1::2]
    lo, hi = alpha_cmd_range()
    bad_a = np.isfinite(a) & ((a <= lo - 1e-9) | (a > hi + 1e-9))
    bad_b = np.isfinite(b) & ((b < BETA_RANGE[0] - 1e-9) | (b > BETA_RANGE[1] + 1e-9))
    if bad_a.any() or bad_b.any():
        ids = fiber_ids()
        what = [f"{ids[i]} alpha {a[i]:.1f}" for i in np.where(bad_a)[0]] + \
               [f"{ids[i]} beta {b[i]:.1f}" for i in np.where(bad_b)[0]]
        raise ValueError(f"command angles outside the positioner range (alpha ({lo:g}, {hi:g}], beta "
                         f"[{BETA_RANGE[0]:g}, {BETA_RANGE[1]:g}]) {where}: {', '.join(what)} -- not written")


def clip_beta(beta):
    """절대 beta 명령각을 positioner 범위 [BETA_RANGE[0], BETA_RANGE[1]] 로 자른다 (NaN 은 그대로)."""
    lo, hi = BETA_RANGE
    return np.clip(np.asarray(beta, float), lo, hi)


ELBOW = "down"
CLOCKWISE = False


def fiber_ids():
    """FIBERS 순서 그대로의 fiber ID(= Hole ID) 리스트.

    출력 json의 key가 이 값에서 나온다 (mtlcal.angle_dict 참고).
    """
    return [row[0] for row in FIBERS]


def arm_lengths(use_measured=None):
    """FIBERS 순서 그대로의 (arm1, arm2) 배열.

    use_measured 면 실측값으로 바꾼다. 우선순위는 뒤로 갈수록 높다.

        1. 설계값 (DEFAULT_ARM / ARM_OVERRIDES)
        2. positioner 개체 측정표 (Positioner_Arm_Table + Positioner_Map)
        3. Measured_Geometry 의 arm 열 (손으로 적는 최종 보정)

    해당하는 값이 없는 positioner는 그 전 단계 값을 그대로 쓴다.
    """
    a1 = np.array([row[1] for row in FIBERS], dtype=float)
    a2 = np.array([row[2] for row in FIBERS], dtype=float)

    if _use_measured(use_measured):
        # 1) positioner 개체 측정표 (설치 맵이 있어야 쓸 수 있다)
        arms, pmap = positioner_arms(), positioner_map()
        for k, hole in enumerate(fiber_ids()):
            sn = pmap.get(hole)
            if sn is not None and sn in arms:
                a1[k], a2[k] = arms[sn]

        # 2) Measured_Geometry 의 arm 값이 있으면 그쪽이 우선 (손으로 적는 값)
        meas = measured_geometry()
        for k, hole in enumerate(fiber_ids()):
            m = meas.get(hole)
            if m is None:
                continue
            if m['arm1'] is not None:
                a1[k] = m['arm1']
            if m['arm2'] is not None:
                a2[k] = m['arm2']

    return a1, a2

# fiducial 밝기 조정 그룹 (사용자 제공, 2026-10-24). lab.fiducial_brightness(groups=FIDUCIAL_GROUPS).
FIDUCIAL_GROUPS = {
    'G1': ['Z2', 'Z3', 'B1', 'B3', 'D6', 'D9', 'A7', 'Z1', 'Z0', 'F1', 'Z5'],
    'G2': ['H13', 'J11', 'Z11'],
    'G3': ['K8', 'Z10', 'O7', 'N5', 'Z9', 'Z8', 'L4', 'N1', 'L1', 'Z7', 'I4'],
    'G4': ['Z6', 'H0', 'Z4', 'E3', 'G8'],
}
