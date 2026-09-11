"""metrology 한 바퀴가 만드는 파일 이름 규칙.

노출(mtlexp)이 쓰는 이름과 계산(findpeak/mtlcal)이 읽는 이름이 갈라지면 안 되므로
양쪽 모두 이 모듈의 함수만 쓴다. 규칙을 바꿀 일이 있으면 여기만 고치면 된다.

    이미지 : {data_dir}/{tile}_MetrologyTrial_{itrial}_{iexposure}.fits
    각도   : {json_dir}/{tile}_MetrologyTrial_{itrial}.json

tile은 target 파일에서 읽은 타일 이름(target_info.tile_name), itrial은 몇 번째
metrology trial인지, iexposure는 그 trial 안에서 몇 번째 이미지인지를 뜻한다.
itrial = 0 은 관측 전에 저장하는 목표 각도 json이다.
"""

import os

STEM = '{tile}_MetrologyTrial_{itrial}'


def image_head(tile, itrial):
    """이미지 파일 이름에서 노출 번호 앞까지의 공통 부분.

    mtlexp와 findpeak이 주고받는 head가 바로 이 값이다.
    """
    return STEM.format(tile=tile, itrial=itrial) + '_'


def image_path(data_dir, head, iexposure):
    """노출 한 장의 경로."""
    return os.path.join(data_dir, f'{head}{iexposure}.fits')


def image_paths(data_dir, tile, itrial, nexposure):
    """한 trial이 찍는 이미지 경로 전부."""
    head = image_head(tile, itrial)
    return [image_path(data_dir, head, i) for i in range(nexposure)]


def json_path(json_dir, tile, itrial):
    """한 trial의 positioner 각도 json 경로."""
    return os.path.join(json_dir, STEM.format(tile=tile, itrial=itrial) + '.json')
