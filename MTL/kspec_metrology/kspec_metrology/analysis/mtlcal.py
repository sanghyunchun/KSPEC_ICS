import json
import os

import numpy as np
from astropy.io import ascii

from kspec_metrology.analysis.findpeak import findpeak
from kspec_metrology.analysis.matchfiber import matchfiber
from kspec_metrology.analysis.fitdistortion import fitdistortion
from kspec_metrology.analysis.utils import find_angle_double_method2_select_elbow
from kspec_metrology.analysis.zenith_offset import zenith_offset
from kspec_metrology.analysis.target_info import read_target, zenith_angle
from kspec_metrology.analysis import fiber_config as cfg
from kspec_metrology import naming
from kspec_metrology.logging.log import get_logger

rtod = 180. / np.pi

# 출력 json의 key 형식: {hole ID}_{arm}. alpha arm은 'a', beta arm은 'b'.
# 예) hole D0 -> "D0_a" (alpha), "D0_b" (beta)
ALPHA_SUFFIX = 'a'
BETA_SUFFIX = 'b'


def load_configuration(target_file=None, apply_zenith_offset=True):
    """설계 좌표와 목표 위치를 읽는다.

    target 파일의 목표 위치 (xp, yp)는 천정거리 0도 기준이라, 관측 고도가 함께
    적혀 있으면 ADC 광학계의 sky -> focal plane 매핑 변화만큼 옮겨준다
    (zenith_offset 참고). 고도 정보가 없으면 보정 없이 그대로 쓴다.
    fiducial은 초점면에 박혀 있는 물체라 보정하지 않는다.

    반환:
        xorigin, yorigin : positioner 회전 중심 (fiber -> fiducial 순)
        x, y             : 목표 위치. fiber는 target 파일 값, fiducial은 설계 값
        fid_flag         : fiducial이면 True
        nfib             : fiber 개수 (배열 앞쪽 nfib개가 fiber)
    """
    log = get_logger()

    tab = ascii.read(cfg.FIBER_TABLE_PATH)
    tab.rename_columns(tab.colnames[:4], ["ID", "X", "Y", "FiducialFlag"])

    ids = cfg.fiber_ids()
    nfib = len(ids)

    fid_ids = [i for i in tab["ID"][tab["FiducialFlag"] == 1]
               if i not in cfg.FIDUCIAL_EXCLUDE]
    pick_ids = list(dict.fromkeys(list(ids) + list(fid_ids)))

    xy_map = {r["ID"]: (r["X"], r["Y"]) for r in tab}
    xy = np.array([xy_map[i] for i in pick_ids], dtype=float)
    xorigin, yorigin = xy[:, 0], xy[:, 1]

    x, y = np.copy(xorigin), np.copy(yorigin)
    fid_flag = np.zeros(x.size, dtype=bool)
    fid_flag[nfib:] = True

    target = read_target(target_file)
    x[:nfib] = np.asarray(target['xp'], dtype=float)[:nfib]
    y[:nfib] = np.asarray(target['yp'], dtype=float)[:nfib]

    #---관측 고도에 따른 보정 (fiber만)-----------------------------------------
    if apply_zenith_offset:
        za = zenith_angle(target)
        if za is None:
            log.warning("No altitude in %s; skipping the zenith angle correction",
                        target_file or cfg.TARGET_INFO_PATH)
        else:
            dx, dy = zenith_offset(x[:nfib], y[:nfib], za)
            x[:nfib] += dx
            y[:nfib] += dy

            log.info("Zenith angle %.2f deg: target shifted by max %.1f um, "
                     "median %.1f um", za,
                     np.sqrt(dx**2 + dy**2).max()*1e3,
                     np.median(np.sqrt(dx**2 + dy**2))*1e3)

    return xorigin, yorigin, x, y, fid_flag, nfib


def _arm_angles(xorigin, yorigin, xtarget, ytarget):
    """각 positioner가 (xtarget, ytarget)을 가리키는 (theta, phi)를 구한다."""
    arm1s, arm2s = cfg.arm_lengths()

    theta = np.zeros(arm1s.size)
    phi = np.zeros(arm1s.size)
    for i in range(arm1s.size):
        theta[i], phi[i] = find_angle_double_method2_select_elbow(
            xorigin[i], yorigin[i], xtarget[i], ytarget[i], arm1s[i], arm2s[i],
            elbow=cfg.ELBOW,
            clockwise=cfg.CLOCKWISE,
        )
    return theta, phi


def _wrap(theta, phi):
    """theta는 (-pi, pi], phi는 (-pi/2, pi/2] 범위로 접는다."""
    theta = theta % (2.*np.pi)
    theta = np.where(theta > np.pi, theta - 2.*np.pi, theta)

    phi = phi % np.pi
    phi = np.where(phi > np.pi/2., phi - np.pi, phi)

    return theta, phi


def _flatten_angles(theta, phi):
    """fiber 순서의 (theta, phi)를 (alpha, beta)가 번갈아 놓인 degree 배열로 편다.

    출력 부호는 positioner 제어 규약에 맞춰 뒤집는다 (출력 각도 = -계산각).
    """
    angles = np.empty(2*theta.size)
    angles[0::2] = -theta*rtod
    angles[1::2] = -phi*rtod

    return angles


def angle_dict(angles):
    """각도 배열을 {"B5_a": ..., "B5_b": ...} 형태로 만든다.

    key는 Fiber_Configuration 표의 hole ID에 arm 접미사를 붙인 것이고,
    순서는 FIBERS 표 순서(= target 파일의 fiber 순서)를 그대로 따른다.
    """
    data = {}
    for k, hole in enumerate(cfg.fiber_ids()):
        data[f"{hole}_{ALPHA_SUFFIX}"] = float(angles[2*k])
        data[f"{hole}_{BETA_SUFFIX}"] = float(angles[2*k+1])
    return data


def angle_array(data):
    """angle_dict의 역변환. json dict을 각도 배열로 되돌린다."""
    return np.array([data[f"{hole}_{suffix}"]
                     for hole in cfg.fiber_ids()
                     for suffix in (ALPHA_SUFFIX, BETA_SUFFIX)], dtype=float)


def json_path(json_dir, target_name, itrial):
    """각도 json 경로. 이미지 파일 이름과 같은 규칙을 쓴다 (naming 참고)."""
    return naming.json_path(json_dir, target_name, itrial)


def save_angles(json_dir, target_name, itrial, angles):
    """각도 배열을 trial별 json으로 저장한다."""
    os.makedirs(json_dir, exist_ok=True)

    path = json_path(json_dir, target_name, itrial)
    with open(path, 'w') as ff:
        json.dump(angle_dict(angles), ff, indent=2)

    return path


def save_initial_angles(json_dir, target_name, target_file=None):
    """관측 전에 목표 각도를 Trial 0 json으로 저장한다.

    이후 trial의 누적 각도는 이 파일에서 출발한다.
    """
    log = get_logger()

    xorigin, yorigin, x, y, _, _ = load_configuration(target_file)
    theta_true, phi_true = _arm_angles(xorigin, yorigin, x, y)

    angles = _flatten_angles(theta_true, phi_true)
    path = save_angles(json_dir, target_name, 0, angles)
    log.info("Saved target angles to %s", path)

    return angles


def mtlcal(data_dir='./MTL/data/'
           , head='test'
           , mode='Raw'
           , threshold=3e3
           , nexposure=1
           , target_file=None
           , json_dir=None
           , target_name=None
           , itrial=1):
    """이미지에서 fiber 위치를 재고 positioner 보정각을 구한다.

    mode는 findpeak에 그대로 넘어간다. "Raw"는 threshold를 조절해 가며 peak을
    찾고, "Predict"는 목표 위치에서 출발해 가장 밝은 픽셀로 정렬한다.

    json_dir와 target_name을 주면 누적 각도를 trial별 json으로 저장한다.
    누적 각도는 직전 trial의 json에 이번 회전량을 더한 값이라, itrial-1 파일이
    있어야 한다 (없으면 목표 각도에서 출발한다).

    반환:
        dx, dy    : fiber와 fiducial 전체의 목표 대비 위치 오차 (mm)
        angle_rot : fiber 순서의 이번 trial 회전량 (deg)
        angle_cum : fiber 순서의 누적 각도 (deg). json에 저장하는 값과 같다.
    """
    log = get_logger()

    xorigin, yorigin, x, y, fid_flag, nfib = load_configuration(target_file)

    #---관측된 peak 위치--------------------------------------------------------
    npeaks = x.size
    _, xobs, yobs, _ = findpeak(npeaks
                                , data_dir=data_dir
                                , head=head
                                , nexposure=nexposure
                                , threshold=threshold
                                , mode=mode
                                , x=x, y=y)

    imatch, theta_guess, (xoff_guess, yoff_guess) = matchfiber(x, y, xobs, yobs)

    xfocal, yfocal, dx, dy, _ = fitdistortion(x, y, fid_flag
                                              , xobs, yobs
                                              , xorigin, yorigin
                                              , imatch, theta_guess
                                              , xoff_guess, yoff_guess)

    #---보정각 계산 (fiber만)---------------------------------------------------
    theta_true, phi_true = _arm_angles(xorigin, yorigin, x, y)
    theta_obs, phi_obs = _arm_angles(xorigin, yorigin, xfocal, yfocal)

    dtheta, dphi = _wrap(theta_true - theta_obs, phi_true - phi_obs)

    angle_rot = _flatten_angles(dtheta, dphi)

    #---누적 각도---------------------------------------------------------------
    prev = None
    if json_dir is not None and target_name is not None:
        prev_path = json_path(json_dir, target_name, itrial-1)
        if os.path.exists(prev_path):
            with open(prev_path, 'r') as ff:
                prev_data = json.load(ff)
            prev = angle_array(prev_data)
        else:
            log.warning("Previous trial file not found: %s", prev_path)

    if prev is None:
        prev = _flatten_angles(theta_true, phi_true)

    angle_cum = prev + angle_rot

    if json_dir is not None and target_name is not None:
        log.info("Saved angles to %s",
                 save_angles(json_dir, target_name, itrial, angle_cum))

    dist = np.sqrt(dx[~fid_flag]**2 + dy[~fid_flag]**2)*1e3
    log.info("Fiber position error: max %.1f um, median %.1f um",
             dist.max(), np.median(dist))

    return dx, dy, angle_rot, angle_cum
