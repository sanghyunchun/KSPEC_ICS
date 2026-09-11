"""관측 타일 정보 파일(target.info) 읽기.

fiber별 목표 위치 (xp, yp) 말고도 타일 이름, 관측 고도처럼 metrology 한 바퀴에
필요한 값들이 이 파일에 같이 들어온다. 파일 형식이 바뀌거나 key 이름이 달라지면
이 모듈만 고치면 된다.
"""

import json
import os

import numpy as np

from kspec_metrology.analysis import fiber_config as cfg

# 타일 이름을 찾을 때 순서대로 시도하는 key
_TILE_KEYS = ('tile', 'tile_id', 'tileid', 'tile_name', 'tilename',
              'target_name', 'target', 'name')

# 고도/천정거리 key. (key, 고도인가) - 고도면 ZA = 90 - value, 아니면 값이 곧 ZA다.
_ANGLE_KEYS = (
    ('alt', True), ('altitude', True), ('el', True), ('elevation', True),
    ('za', False), ('zd', False), ('zenith', False), ('zenith_angle', False),
)


def read_target(target_file=None):
    """target 파일을 dict으로 읽는다."""
    with open(target_file or cfg.TARGET_INFO_PATH, 'r') as ff:
        return json.load(ff)


def _lookup(target, key):
    """대소문자 무시하고 key를 찾는다. 리스트면 첫 값을 쓴다 (타일당 하나)."""
    lowered = {str(k).lower(): v for k, v in target.items()}

    value = lowered.get(key)
    if isinstance(value, (list, tuple, np.ndarray)):
        value = value[0] if len(value) else None

    return value


def tile_name(target, target_file=None):
    """타일 이름. 파일 이름에 그대로 쓰므로 곤란한 문자는 '_'로 바꾼다.

    target 파일에 타일 key가 없으면 파일 이름을, 그것도 없으면 'metrology'를 쓴다.
    """
    name = None
    for key in _TILE_KEYS:
        value = _lookup(target, key)
        if value is not None and str(value).strip():
            name = str(value).strip()
            break

    if name is None:
        stem = os.path.splitext(os.path.basename(
            target_file or cfg.TARGET_INFO_PATH))[0]
        name = stem or 'metrology'

    return ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in name)


def zenith_angle(target):
    """천정거리 (deg). 고도로 적혀 있으면 90 - 고도로 바꾼다. 없으면 None."""
    for key, is_altitude in _ANGLE_KEYS:
        value = _lookup(target, key)
        if value is None:
            continue

        value = float(value)

        return 90. - value if is_altitude else value

    return None
