"""metrology 한 바퀴가 만드는 파일 이름 규칙.

노출(mtlexp)이 쓰는 이름과 계산(findpeak/mtlcal)이 읽는 이름이 갈라지면 안 되므로
양쪽 모두 이 모듈의 함수만 쓴다. 규칙을 바꿀 일이 있으면 여기만 고치면 된다.

    이미지 : {data_dir}/{tile}_MetrologyTrial_{itrial}_{iexposure}.fits
    fiducial 전용 노출 : {data_dir}/{tile}_MetrologyTrial_{itrial}_fid{k}_{iexposure}.fits
    각도   : {json_dir}/{tile}_MetrologyTrial_{itrial}.json
    이동량 : {json_dir}/{tile}_MetrologyTrial_{itrial}_offset.txt
    fiducial 칩 좌표 : {json_dir}/{tile}_MetrologyTrial_{itrial}_fid.npy  (다음 trial 이 fiducial 을 찾는 기준)
    fiducial 칩 좌표 기준 파일 : {json_dir}/Fiducial_Chip_Positions.npy  (run 과 무관한 마지막 성공값)

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


def fid_image_head(tile, itrial, k):
    """fiducial 전용 노출 k번째 세트의 head (fiber와 다른 노출시간으로 찍을 때).

    fiber 이미지 head 뒤에 fid{k}_ 가 붙는다: {tile}_MetrologyTrial_{itrial}_fid{k}_
    """
    return STEM.format(tile=tile, itrial=itrial) + f'_fid{k}_'


def image_path(data_dir, head, iexposure):
    """노출 한 장의 경로."""
    return os.path.join(data_dir, f'{head}{iexposure}.fits')


def image_paths(data_dir, tile, itrial, nexposure):
    """한 trial이 찍는 이미지 경로 전부."""
    head = image_head(tile, itrial)
    return [image_path(data_dir, head, i) for i in range(nexposure)]


def fid_image_paths(data_dir, tile, itrial, k, nexposure):
    """fiducial 전용 노출 세트 k의 이미지 경로 전부."""
    head = fid_image_head(tile, itrial, k)
    return [image_path(data_dir, head, i) for i in range(nexposure)]


def offset_path(json_dir, tile, itrial):
    """한 trial의 fiber 이동량 표 (ID, dx, dy, 회전량) 경로."""
    return os.path.join(json_dir, STEM.format(tile=tile, itrial=itrial) + '_offset.txt')


def json_path(json_dir, tile, itrial):
    """한 trial의 positioner 각도 json 경로."""
    return os.path.join(json_dir, STEM.format(tile=tile, itrial=itrial) + '.json')


def coeff_path(json_dir, tile, itrial):
    """한 trial 에서 맞춘 camera->focal 변환 계수 (npy) 경로. 다음 trial 의 'Predict' mode 가 읽는다."""
    return os.path.join(json_dir, STEM.format(tile=tile, itrial=itrial) + '_coeff.npy')


def fid_path(json_dir, tile, itrial):
    """한 trial 에서 잰 fiducial 칩 좌표 (npy, (nfid, 2) [mm, 칩 중심 기준], 못 잰 것은 NaN).
    다음 trial 은 이 자리 주변에서만 fiducial 을 찾는다 (mtlcal.measure_fiducials_ref)."""
    return os.path.join(json_dir, STEM.format(tile=tile, itrial=itrial) + '_fid.npy')


FID_REF_ENV = 'KSPEC_FIDUCIAL_CHIP_REF'


def fid_ref_path(json_dir):
    """run 과 무관한 fiducial 칩 좌표 기준 파일. 성공한 trial 마다 갱신되고, 새 run 의 첫 trial 이 읽는다.
    환경변수 KSPEC_FIDUCIAL_CHIP_REF 로 다른 경로를 줄 수 있다."""
    return os.environ.get(FID_REF_ENV) or os.path.join(json_dir, 'Fiducial_Chip_Positions.npy')
