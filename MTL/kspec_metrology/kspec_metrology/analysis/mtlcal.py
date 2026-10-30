import json
import os

import numpy as np
from astropy.io import ascii
from scipy.spatial import cKDTree
from scipy.optimize import linear_sum_assignment

from kspec_metrology.analysis.findpeak import findpeak
from kspec_metrology.analysis.matchfiber import matchfiber
from kspec_metrology.analysis.fitdistortion import fitdistortion
from kspec_metrology.analysis.utils import (find_angle_double_method2_select_elbow, transform,
                                            camera2focal_coeff, invert_transform)
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


def load_configuration(target_file=None, apply_zenith_offset=True,
                       apply_pinhole_offset=False, use_measured=None, use_measured_positioners=None):
    """설계 좌표와 목표 위치를 읽는다.

    target 파일의 목표 위치 (xp, yp)는 천정거리 0도 기준이라, 관측 고도가 함께
    적혀 있으면 ADC 광학계의 sky -> focal plane 매핑 변화만큼 옮겨준다
    (zenith_offset 참고). 고도 정보가 없으면 보정 없이 그대로 쓴다.
    fiducial은 초점면에 박혀 있는 물체라 보정하지 않는다.

    apply_pinhole_offset=True 면 fiducial 기준 좌표에 핀홀이 홀 중심에서 치우친
    양(dx, dy)을 더한다 (fiber_config.pinhole_offsets). 이 값이 fitdistortion의
    기준이 되므로 맞게 넣으면 그만큼 왜곡 fit이 정확해진다.
    xorigin, yorigin은 홀 설계 좌표 그대로 둔다.

    use_measured 면 설계 좌표와 arm 길이를 실측값으로 바꾼다 (fiducial 핀홀 위치, arm 길이).
    use_measured_positioners 면 positioner 회전 중심도 실측값(arm scan) 으로 바꾼다 (별개 스위치, 기본 꺼짐;
    fiber_config.USE_MEASURED_POSITIONERS / KSPEC_USE_MEASURED_POSITIONERS)
    (fiber_config.measured_geometry). None이면 fiber_config.USE_MEASURED를
    따르고 그 기본값은 True다 (KSPEC_USE_MEASURED=0 으로 끈다). 실측 위치가
    있는 fiducial에는 핀홀 오프셋을 더하지 않는다 (이중 계산이 되므로).
    실측 파일이 없으면, 인자로 명시해 켠 경우에만 예외를 내고 아니면 경고만
    남기고 설계값을 쓴다. 실측 좌표가 설계 좌표에서 MEASURED_MAX_DEV 보다 멀면
    다른 plate 의 파일로 보고 멈춘다.

    기본값이 False인 이유: 핀홀 측정값은 plate마다 다시 재야 하는데, 표를 바꿔도
    fiducial ID가 상당수 겹치는 탓에 옛 plate의 값이 조용히 적용될 수 있다.
    지금 들어 있는 파일은 d = 16.8 mm plate 기준이다. 새로 측정해 파일을 갈아
    끼운 뒤 True로 켜면 된다.

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

    log.info("Fiber table %s: %d positioners + %d fiducials",
             cfg.FIBER_TABLE_PATH, nfib, len(fid_ids))

    xy_map = {r["ID"]: (r["X"], r["Y"]) for r in tab}
    xy = np.array([xy_map[i] for i in pick_ids], dtype=float)
    xorigin, yorigin = xy[:, 0], xy[:, 1]

    #---설계 좌표를 실측값으로 교체------------------------------------------
    # positioner는 회전 중심, fiducial은 핀홀 위치다. 안 잰 홀은 설계값을 쓴다.
    measured = {}
    if cfg._use_measured(use_measured):
        measured = cfg.measured_geometry()
        if not measured:
            msg = ("use_measured가 켜져 있는데 실측 기하 파일이 없습니다: "
                   f"{cfg.MEASURED_GEOMETRY_PATH}")
            if use_measured:                     # 인자로 명시해 켠 경우만 멈춘다
                raise FileNotFoundError(msg)
            log.warning("%s -- 설계값을 씁니다", msg)

        nhit = 0; nskip_pos = 0
        use_pos = cfg._use_measured_positioners(use_measured_positioners)
        for k, hole in enumerate(pick_ids):
            m = measured.get(hole)
            if m is None or m['x'] is None or m['y'] is None:
                continue
            if k < nfib and not use_pos:                     # positioner 중심 실측은 별개 스위치
                nskip_pos += 1
                continue
            dev = float(np.hypot(m['x']-xorigin[k], m['y']-yorigin[k]))
            if dev > cfg.MEASURED_MAX_DEV:
                raise ValueError(
                    f"실측 기하 {cfg.MEASURED_GEOMETRY_PATH}: {hole} 의 실측 좌표가 "
                    f"설계 좌표에서 {dev:.2f} mm 떨어져 있습니다 (한계 "
                    f"{cfg.MEASURED_MAX_DEV} mm). 다른 plate 의 실측 파일이거나 "
                    f"표({cfg.FIBER_TABLE_PATH})가 다릅니다. 맞는 파일로 바꾸거나 "
                    "KSPEC_USE_MEASURED=0 (use_measured=False) 로 끄십시오.")
            xorigin[k], yorigin[k] = m['x'], m['y']
            nhit += 1

        unknown = [h for h, m in measured.items() if h not in set(pick_ids)
                   and (m['x'] is not None or m['arm1'] is not None)]
        log.info("Measured geometry %s: %d/%d holes replaced (positioner centres %s%s)",
                 cfg.MEASURED_GEOMETRY_PATH, nhit, len(pick_ids),
                 'ON' if use_pos else 'OFF',
                 f', {nskip_pos} measured but not used' if nskip_pos else '')
        if unknown:
            log.warning("Measured file lists %d hole(s) not in the fiber "
                        "table; ignored: %s", len(unknown),
                        ', '.join(sorted(unknown)[:10]))

    x, y = np.copy(xorigin), np.copy(yorigin)
    fid_flag = np.zeros(x.size, dtype=bool)
    fid_flag[nfib:] = True

    #---Fiducial 핀홀 오프셋----------------------------------------------------
    if apply_pinhole_offset:
        off = cfg.pinhole_offsets()
        if not off:
            log.warning("No fiducial pinhole offsets found (%s); "
                        "using the hole centres as the fiducial reference",
                        os.path.basename(cfg.FIDUCIAL_PINHOLE_MAP_PATH))
        else:
            # fiducial에만 더한다. fiber 자리는 곧 target 파일 값으로 덮인다.
            def _done(h):
                m = measured.get(h)
                return m is not None and m['x'] is not None and m['y'] is not None

            # 실측 위치로 이미 바꾼 fiducial에는 오프셋을 또 더하지 않는다
            dxy = np.array([off[i] if (f and i in off and not _done(i))
                            else (0., 0.)
                            for i, f in zip(pick_ids, fid_flag)])
            x += dxy[:, 0]
            y += dxy[:, 1]

            nhit = int(np.any(dxy != 0., axis=1).sum())
            log.info("Fiducial pinhole offsets applied to %d/%d fiducials "
                     "(max %.0f um)", nhit, int(fid_flag.sum()),
                     np.hypot(*dxy.T).max()*1e3)

            unused = [i for i in off
                      if i not in {h for h, f in zip(pick_ids, fid_flag) if f}]
            if unused:
                log.warning("Pinhole map lists %d hole(s) that are not used as "
                            "fiducials; ignored: %s", len(unused),
                            ', '.join(sorted(unused)[:10]))

    target = read_target(target_file)
    xp, yp = _target_xy(target, xorigin[:nfib], yorigin[:nfib], use_measured, target_file)

    # 개수가 다르면 예전에는 앞에서 잘라 쓰며 조용히 지나갔다. fiber 표를 바꾸고
    # target 파일을 안 바꾼 경우가 대표적인데, 엉뚱한 fiber에 엉뚱한 목표가
    # 붙으므로 바로 멈춘다.
    if xp.size != nfib or yp.size != nfib:
        raise ValueError(
            f"target 파일의 xp/yp 개수({xp.size}/{yp.size})가 fiber 표의 "
            f"positioner 개수({nfib})와 다릅니다.\n"
            f"  표    : {cfg.FIBER_TABLE_PATH}\n"
            f"  target: {target_file or cfg.TARGET_INFO_PATH}\n"
            "표를 바꿨다면 target 파일도 같은 순서로 다시 만들어야 합니다 "
            "(KSPEC_FIBER_TABLE로 표를 지정할 수 있습니다).")

    x[:nfib] = xp
    y[:nfib] = yp

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


def _target_xy(target, xorigin, yorigin, use_measured, target_file=None):
    """target dict -> fiber 목표 (xp, yp) [mm].
    {"xp", "yp"} 면 그대로, {"alpha", "beta"} (deg, 명령각 = 출력 규약) 또는 각도 json ({"C4_a", "C4_b"})
    이면 positioner 회전 중심과 arm 길이로 (x, y) 를 만든다 (calibration run 처럼 모든 arm 을
    같은 각도로 둘 때 object.info 에 각도만 적어도 된다). 명령각 (0, 0) 은 기하각 ANGLE_ZERO 다."""
    low = {str(k).lower(): v for k, v in target.items()}
    if 'xp' in low and 'yp' in low:
        return np.asarray(low['xp'], dtype=float), np.asarray(low['yp'], dtype=float)
    ids = list(cfg.fiber_ids())
    if 'alpha' in low and 'beta' in low:
        al, be = np.asarray(low['alpha'], dtype=float), np.asarray(low['beta'], dtype=float)
    elif all(f"{i}_{ALPHA_SUFFIX}" in target and f"{i}_{BETA_SUFFIX}" in target for i in ids):
        al = np.array([target[f"{i}_{ALPHA_SUFFIX}"] for i in ids], dtype=float)
        be = np.array([target[f"{i}_{BETA_SUFFIX}"] for i in ids], dtype=float)
    else:
        raise ValueError(f"target 파일 {target_file or cfg.TARGET_INFO_PATH} 에 'xp'/'yp', "
                         f"'alpha'/'beta', 또는 '{{ID}}_a'/'{{ID}}_b' 키가 필요합니다")
    if al.size != len(ids) or be.size != len(ids):
        raise ValueError(f"target 파일의 각도 개수({al.size}/{be.size})가 positioner 개수({len(ids)})와 다릅니다")
    sa, sb = cfg.ANGLE_SIGN
    za, zb = cfg.ANGLE_ZERO
    theta, phi = sa*(al + za)/rtod, sb*(be + zb)/rtod      # 명령각 -> 기하각 (부호 x 부호 = 1)
    if cfg.CLOCKWISE:
        theta, phi = -theta, -phi
    a1, a2 = cfg.arm_lengths(use_measured)
    xp = xorigin + a1*np.cos(theta) + a2*np.cos(theta + phi)
    yp = yorigin + a1*np.sin(theta) + a2*np.sin(theta + phi)
    return xp, yp


def _arm_angles(xorigin, yorigin, xtarget, ytarget, use_measured=None, what='target'):
    """각 positioner가 (xtarget, ytarget)을 가리키는 (theta, phi)를 구한다.

    회전 중심에서 (a1 + a2 - cfg.REACH_MARGIN) 보다 먼 점은 완전히 편 자세 (phi = 0, theta = 그 방향) 로
    푼다 (fiber_config.REACH_MARGIN 참고). what 은 경고 문구용 ('target' / 'measured')."""
    arm1s, arm2s = cfg.arm_lengths(use_measured)

    theta = np.full(arm1s.size, np.nan)
    phi = np.full(arm1s.size, np.nan)
    at_limit = []
    for i in range(arm1s.size):
        if not (np.isfinite(xtarget[i]) and np.isfinite(ytarget[i])):
            continue                                            # 끊어진 fiber: 측정값 없음
        dx, dy = xtarget[i] - xorigin[i], ytarget[i] - yorigin[i]
        if cfg.REACH_MARGIN > 0 and np.hypot(dx, dy) > arm1s[i] + arm2s[i] - cfg.REACH_MARGIN:
            gamma = float(np.arctan2(dy, dx)) % (2*np.pi)       # 완전히 편 자세: solver 의 도달 불가 처리와 같다
            theta[i], phi[i] = (-gamma if cfg.CLOCKWISE else gamma), 0.0
            at_limit.append(i)
            continue
        theta[i], phi[i] = find_angle_double_method2_select_elbow(
            xorigin[i], yorigin[i], xtarget[i], ytarget[i], arm1s[i], arm2s[i],
            elbow=cfg.ELBOW,
            clockwise=cfg.CLOCKWISE,
        )
    if at_limit:
        ids = list(cfg.fiber_ids())
        get_logger().warning("%d %s position(s) within %.2f mm of the arm reach limit -> solved as fully "
                             "extended (beta at its end, alpha toward the point): %s", len(at_limit), what,
                             cfg.REACH_MARGIN, ", ".join(f"{ids[i]} ({np.hypot(xtarget[i]-xorigin[i], ytarget[i]-yorigin[i]):.2f}"
                                                         f"/{arm1s[i]+arm2s[i]:.2f} mm)" for i in at_limit))
    return theta, phi


def _wrap(theta, phi):
    """theta는 (-pi, pi], phi는 (-pi/2, pi/2] 범위로 접는다."""
    theta = theta % (2.*np.pi)
    theta = np.where(theta > np.pi, theta - 2.*np.pi, theta)

    phi = phi % np.pi
    phi = np.where(phi > np.pi/2., phi - np.pi, phi)

    return theta, phi


def _flatten_angles(theta, phi, absolute=True):
    """fiber 순서의 (theta, phi)를 (alpha, beta)가 번갈아 놓인 degree 배열로 편다.

    출력은 positioner 명령각이다: 명령각 = fiber_config.ANGLE_SIGN x 계산각 - fiber_config.ANGLE_ZERO
    (부호와 영점은 fiber_config 참고; 기하각 (30, 150) = positioner 의 (0, 0)).
    absolute=True 면 alpha 는 경로 계획기와 같은 범위의 절대각이다 (fiber_config.command_alpha).
    absolute=False 면 회전량(차이)이라 영점을 빼지 않고 alpha 를 짧은 쪽 (-180, 180] 로 접는다.
    """
    sa, sb = cfg.ANGLE_SIGN
    angles = np.empty(2*theta.size)
    if absolute:
        angles[0::2] = cfg.command_alpha(theta)
        angles[1::2] = sb*phi*rtod - cfg.ANGLE_ZERO[1]
    else:
        angles[0::2] = (sa*theta*rtod + 180.) % 360. - 180.
        angles[1::2] = sb*phi*rtod

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
    """각도 배열을 trial별 json으로 저장한다. positioner 범위 밖의 각도가 있으면 쓰지 않고 ValueError."""
    cfg.check_command_angles(angles, where=f"(trial {itrial})")      # 범위 밖 명령은 절대 내보내지 않는다
    os.makedirs(json_dir, exist_ok=True)

    path = json_path(json_dir, target_name, itrial)
    with open(path, 'w') as ff:
        json.dump(angle_dict(angles), ff, indent=2)

    return path


def save_initial_angles(json_dir, target_name, target_file=None,
                        use_measured=None, use_measured_positioners=None):
    """관측 전에 목표 각도를 Trial 0 json으로 저장한다.

    이후 trial의 누적 각도는 이 파일에서 출발한다.
    """
    log = get_logger()

    xorigin, yorigin, x, y, _, _ = load_configuration(
        target_file, use_measured=use_measured, use_measured_positioners=use_measured_positioners)
    theta_true, phi_true = _arm_angles(xorigin, yorigin, x, y, use_measured)

    angles = _flatten_angles(theta_true, phi_true)
    path = save_angles(json_dir, target_name, 0, angles)
    log.info("Saved target angles to %s", path)

    return angles


def save_offsets(json_dir, target_name, itrial, dx, dy, angle_rot, nfib):
    """fiber 마다 남은 위치 오차와 이번 trial 회전량을 표로 저장한다.

    positioner 를 옮기는 쪽이 json(누적 각도) 대신 "얼마나 더 가야 하는지" 를
    바로 보고 싶을 때 쓴다. 열: ID, dx, dy [um] (측정 - 목표), dalpha, dbeta [deg]
    (이번 trial 회전량, json 과 같은 부호 규약).
    """
    os.makedirs(json_dir, exist_ok=True)
    path = naming.offset_path(json_dir, target_name, itrial)
    with open(path, 'w') as ff:
        ff.write("# fiber position error (measured - target) and this trial's rotation; "
                 "nan = excluded (broken) fiber\n")
        ff.write(f"# {'ID':<6} {'dx[um]':>9} {'dy[um]':>9} {'dalpha[deg]':>12} {'dbeta[deg]':>12}\n")
        for k, hole in enumerate(cfg.fiber_ids()[:nfib]):
            ff.write(f"  {hole:<6} {dx[k]*1e3:9.1f} {dy[k]*1e3:9.1f} "
                     f"{angle_rot[2*k]:12.4f} {angle_rot[2*k+1]:12.4f}\n")
    return path


# fiducial 이 이만큼은 보여야 변환을 맞춘다 (full+affine 17 계수에 30 개 중 20 개면 넉넉하다).
# 모자라면 그 trial 은 실패로 둔다 (fiducial 이 대부분 안 보이면 조명·카메라 문제다).
MIN_FIDUCIALS = 20
# 찾은 fiducial 가운데 fit 잔차가 이보다 크면 잘못 붙인 것(fiber 점 등)으로 보고 빼고 다시 맞춘다 [mm].
FID_RESID_MAX = 0.3
# fiducial 기준 칩 좌표 주변에서 찾는 창 반경 [px] (60 px x 3.76 um x 배율 8.9 = 2 mm).
FID_WINDOW_PX = 60


def min_found(nfid):
    return min(MIN_FIDUCIALS, max(3, nfid//2))


def load_fid_ref(json_dir, target_name, itrial, nfid):
    """fiducial 칩 좌표 기준: 직전 trial 의 _fid.npy, 없으면 run 과 무관한 기준 파일. 없으면 None."""
    if json_dir is None:
        return None, None
    cands = []
    if target_name is not None and itrial is not None and itrial >= 1:
        cands.append(naming.fid_path(json_dir, target_name, itrial - 1))
    cands.append(naming.fid_ref_path(json_dir))
    for path in cands:
        if os.path.exists(path):
            ref = np.load(path)
            if ref.shape == (nfid, 2) and int(np.isfinite(ref).all(axis=1).sum()) >= min_found(nfid):
                return ref, path
            get_logger().warning("fiducial reference %s ignored: shape %s or too few finite rows", path, ref.shape)
    return None, None


def save_fid_ref(json_dir, target_name, itrial, xo_fid, yo_fid):
    """이 trial 의 fiducial 칩 좌표를 trial 파일과 기준 파일에 저장한다 (기준 파일은 잰 것만 갱신)."""
    if json_dir is None:
        return
    os.makedirs(json_dir, exist_ok=True)
    cur = np.column_stack((xo_fid, yo_fid))
    if target_name is not None and itrial is not None:
        np.save(naming.fid_path(json_dir, target_name, itrial), cur)
    path = naming.fid_ref_path(json_dir)
    ref = cur.copy()
    if os.path.exists(path):
        old = np.load(path)
        if old.shape == cur.shape:
            keep = ~np.isfinite(cur).all(axis=1)
            ref[keep] = old[keep]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    np.save(path, ref)


def measure_fiducials_ref(fid_heads, xf, yf, ref, data_dir, nexposure, nfib, set_nexposure=None, n_extra=0,
                          sat_level=65000., fid_min_peak=0., fallback=None, window_px=FID_WINDOW_PX,
                          exclude=None, **pk):
    """기준 칩 좌표(ref, (nfid, 2)) 주변에서만 fiducial 을 찾는다. 패턴 매칭이 필요 없다.

    fiducial 은 초점면에 고정되어 있고 카메라도 고정이므로 칩 좌표는 trial 사이에 거의 변하지 않는다.
    세트(노출)마다 peak 을 모두 찾은 뒤
      1. 기준 좌표마다 가장 가까운 검출을 보고 공통 이동량(중앙값)을 구해 기준을 통째로 옮기고
         (카메라가 조금 움직였을 때),
      2. fiducial 마다 옮긴 기준에서 window_px 안의 **가장 가까운** 검출을 그 fiducial 로 본다
         (밝기는 쓰지 않는다: fiber 점이 창에 들어와도 자리가 다르면 안 잡힌다). 한 검출은 한 fiducial 에만.
    세트 선택은 measure_fiducials 와 같다 (포화되지 않은 가장 밝은 세트, fallback 세트는 뒤로).
    절반도 못 찾으면 None 을 돌려주고 호출자가 패턴 매칭으로 돌아간다.
    exclude : (xchip, ychip) 이미 아는 fiber 자리. 주면 그 자리를 지우고 찾는다 (cross_exclude 2차).

    반환: xobs, yobs (fiducial 순서, 못 찾은 것은 NaN), choice
    """
    log = get_logger()
    nfid = xf.size
    win = window_px * 3.76e-3                               # 칩 좌표 [mm]
    sets = []
    for k, head in enumerate(fid_heads):
        nexp = nexposure if set_nexposure is None else set_nexposure[k]
        _, xobs, yobs, peak, nsat = findpeak((min_found(nfid), nfid + nfib + n_extra + 20), data_dir=data_dir,
                                             head=head, nexposure=nexp, sat_level=sat_level,
                                             exclude=exclude, ReturnNsat=True, **pk)
        obs = np.column_stack((xobs, yobs))
        tree = cKDTree(obs)
        ok_ref = np.isfinite(ref).all(axis=1)
        d, j = tree.query(ref[ok_ref])
        near = d < 3*win
        shift = np.median(obs[j[near]] - ref[ok_ref][near], axis=0) if near.sum() >= 3 else np.zeros(2)
        # cKDTree.query rejects non-finite coordinates. Keep missing reference rows out of
        # the query and leave their distances infinite so they cannot be selected.
        # (ICS 담당자 수정 2026-10-27, KSPEC_ICS 980d52b)
        d = np.full(nfid, np.inf)
        j = np.zeros(nfid, dtype=int)
        d[ok_ref], j[ok_ref] = tree.query(ref[ok_ref] + shift)
        found = ok_ref & (d < win)
        for jj in np.unique(j[found]):                       # 한 검출에 둘 이상 붙으면 가까운 쪽만
            same = np.where(found & (j == jj))[0]
            if same.size > 1:
                found[same] = False; found[same[np.argmin(d[same])]] = True
        sets.append(dict(x=xobs[j], y=yobs[j], peak=peak[j], nsat=nsat[j], found=found))
        log.info("Fiducial set %d (%s): %d peaks, %d/%d fiducials within %d px of the reference "
                 "(common shift %.1f, %.1f px), %d saturated, peak %.0f..%.0f", k, head, xobs.size,
                 int(found.sum()), nfid, window_px, shift[0]/3.76e-3, shift[1]/3.76e-3,
                 int((nsat[j][found] > 0).sum()),
                 peak[j][found].min() if found.any() else np.nan, peak[j][found].max() if found.any() else np.nan)

    fallback = [False]*len(sets) if fallback is None else list(fallback)
    choice = np.full(nfid, -1, dtype=int)
    for i in range(nfid):
        cand = [k for k, st in enumerate(sets) if st['found'][i] and not fallback[k]]
        if not cand:
            cand = [k for k, st in enumerate(sets) if st['found'][i]]
        if not cand:
            continue
        ok = [k for k in cand if sets[k]['nsat'][i] == 0 and sets[k]['peak'][i] >= fid_min_peak]
        choice[i] = max(ok, key=lambda k: sets[k]['peak'][i]) if ok else \
            min(cand, key=lambda k: (sets[k]['nsat'][i], -sets[k]['peak'][i]))
    nfound = int((choice >= 0).sum())
    if nfound < min_found(nfid):
        log.warning("Fiducial reference search found only %d/%d fiducials; falling back to pattern matching",
                    nfound, nfid)
        return None
    missing = np.where(choice < 0)[0]
    if missing.size:
        log.warning("fiducial %s not found near the reference in any set; continuing with %d/%d",
                    ", ".join(str(i) for i in missing), nfound, nfid)
    xobs = np.array([sets[choice[i]]['x'][i] if choice[i] >= 0 else np.nan for i in range(nfid)])
    yobs = np.array([sets[choice[i]]['y'][i] if choice[i] >= 0 else np.nan for i in range(nfid)])
    if len(sets) > 1:
        log.info("Fiducial exposure chosen per fiducial: %s",
                 ", ".join(f"set {k}: {int((choice == k).sum())}" for k in range(len(sets))))
    bad = [i for i in range(nfid) if choice[i] >= 0 and sets[choice[i]]['nsat'][i] > 0]
    if bad:
        log.warning("%d fiducial(s) saturated in every set where found (used anyway): %s", len(bad),
                    ", ".join(str(i) for i in bad))
    return xobs, yobs, choice


def fit_fiducials(x_fid, y_fid, xo_fid, yo_fid, theta_guess, xoff_guess, yoff_guess, model, m_init,
                  resid_max=FID_RESID_MAX):
    """찾은 fiducial (NaN 아닌 것) 로 변환을 맞추고, 잔차가 resid_max 를 넘는 것은 잘못 붙인 것으로 보고
    빼고 다시 맞춘다 (남는 수가 min_found 이상일 때만). 반환: xf, yf (fiducial 순서, 안 쓴 것은 NaN), coeff, used."""
    log = get_logger()
    nfid = x_fid.size
    used = np.isfinite(xo_fid) & np.isfinite(yo_fid)
    for _ in range(3):
        idx = np.where(used)[0]
        xf_u, yf_u, _, _, coeff = fitdistortion(x_fid[idx], y_fid[idx], np.ones(idx.size, bool),
                                                xo_fid[idx], yo_fid[idx], np.arange(idx.size),
                                                theta_guess, xoff_guess, yoff_guess, model=model, m_init=m_init)
        resid = np.hypot(xf_u - x_fid[idx], yf_u - y_fid[idx])
        bad = resid > resid_max
        if not bad.any() or idx.size - bad.sum() < min_found(nfid):
            break
        log.warning("%d fiducial(s) with fit residual > %.2f mm dropped as misidentified: %s",
                    int(bad.sum()), resid_max, ", ".join(f"{i} ({r*1e3:.0f} um)" for i, r in zip(idx[bad], resid[bad])))
        used[idx[bad]] = False
    xf = np.full(nfid, np.nan); yf = np.full(nfid, np.nan)
    xf[idx], yf[idx] = xf_u, yf_u
    return xf, yf, coeff, used


def measure_fiducials(fid_heads, x, y, fid_flag, data_dir, nexposure,
                      m_init=None, sat_level=65000., fid_min_peak=0., n_extra=0, exclude=None,
                      set_nexposure=None, match_tol=1.5, fallback=None, **pk):
    """fiducial 전용 노출 세트들에서 fiducial 의 카메라 좌표를 잰다.

    x, y 는 fiber 목표 + fiducial 설계 위치 전체, fid_flag 는 그중 fiducial.
    세트마다 peak 을 찾고 (fiber 가 보일 수도 있으므로 nfid..nfid+nfib 개 허용)
    설계 패턴에 매칭한다. fiber 가 보이면 (검출이 fiducial 수보다 많으면) fiber
    목표까지 넣어 전체 패턴으로 매칭한다 -- fiducial 30개만으로는 그 사이에
    fiber 가 빽빽이 있을 때 회전각이 정해지지 않는다. 세트가 여럿이면 fiducial
    마다 포화되지 않은 것 중 가장 밝은 세트를 고르고, 전부 포화면 포화 화소가
    가장 적은 세트를 쓴다. fid_min_peak 보다 어두운 검출은 (다른 세트가 있으면)
    피한다.

    exclude : (xchip, ychip) 이미 아는 fiber 의 칩 좌표. 주면 그 자리를 지우고 찾는다
              (findpeak 의 exclude). 그러면 fiducial 수만 기대한다.
    set_nexposure : 세트마다 다른 장수 (리스트). None 이면 모두 nexposure.
    fallback : 세트별 bool 리스트. True 인 세트(예: fiducial 이 같이 찍힌 fiber 노출)는 다른
              세트에서 못 찾은 fiducial 에만 쓴다 (보통 포화 직전이라 뒤로 민다).
    match_tol : 매칭을 인정하는 거리 [mm, 초점면]. 세트에 fiducial 이 일부만 찍혔으면
              (너무 어둡거나) 그 세트에서는 없는 것으로 두고 다른 세트에서 가져온다.

    세트가 fiducial 을 다 담지 못해도 된다: 세트마다 찾은 것만 쓰고, fiducial 마다 포화되지
    않은 것 중 가장 밝은 세트를, 그것도 없으면 포화 화소가 가장 적은 세트를 쓴다. 어느 세트에도
    없는 fiducial 이 있으면 예외.

    반환: xobs, yobs (fiducial 순서), choice (fiducial 마다 고른 세트 번호),
          theta_guess, (xoff, yoff) (마지막 매칭의 초기값; fitdistortion 용)
    """
    log = get_logger()
    nfid, nfib = int(fid_flag.sum()), int((~fid_flag).sum())
    xf, yf = x[fid_flag], y[fid_flag]
    sets = []
    for k, head in enumerate(fid_heads):
        nexp = nexposure if set_nexposure is None else set_nexposure[k]
        # 검출 상한은 fiber 자리를 지웠을 때도 nfid + nfib + n_extra 로 둔다. 지운 것은 "매칭된" fiber 자리만이라
        # 목표에서 멀어져 매칭 안 된 fiber 의 점이 남는데, 상한을 nfid + n_extra 로 잡으면 findpeak 이 문턱을
        # 올리거나 가장 어두운 검출을 버려 상한에 맞추다가 어두운 fiducial 을 버린다 (2026-10-27 trial 3: Z11).
        # 여분은 패턴 매칭에서 자연히 빠지므로 상한을 넉넉히 두는 쪽이 안전하다.
        nmax = nfid + nfib + n_extra
        nmin = max(3, nfid//2)                          # 일부가 안 보여도 받아들인다
        _, xobs, yobs, peak, nsat = findpeak((nmin, nmax), data_dir=data_dir, head=head,
                                             nexposure=nexp, sat_level=sat_level,
                                             exclude=exclude, ReturnNsat=True, **pk)
        def _assign(px, py):
            """예측 초점면 위치 (px, py) 의 검출을 fiducial 마다 match_tol 안 가장 가까운 것으로, 중복 없이."""
            d, j = cKDTree(np.column_stack((px, py))).query(np.column_stack((xf, yf)))
            found = d < match_tol
            for jj in np.unique(j[found]):               # 같은 검출을 두 fiducial 이 쓰면 가까운 쪽만
                same = np.where(found & (j == jj))[0]
                if same.size > 1:
                    found[same] = False; found[same[np.argmin(d[same])]] = True
            return j, found

        def _check(theta_guess, xoff, yoff):
            """matchfiber 의 회전·offset 으로 옮긴 검출을 설계 위치에 붙이고 (match_tol 안, 중복 없이),
            붙은 쌍으로 1차(affine) 변환을 최소제곱으로 다시 맞춰 다시 붙인다 (lab.match_fiducials 와 같다).
            반환: (fiducial 마다 검출 번호 j, found)

            왜곡 항은 기본 계수(camera2focal_coeff) 그대로 둔다. matchfiber 가 그 계수로 옮긴 좌표에서
            회전·offset 을 찾았으므로 여기서 0 으로 두면 본 장비 광학계에서는 가장자리 fiducial 이 2-3 mm
            어긋나 match_tol 안에 못 든다 (2026-10-27 수정: 그래서 fiducial 이 4-9 개만 "찾아졌다").
            matchfiber 의 격자(0.5 deg, 0.5 mm)만으로는 가장자리에서 1 mm 넘게 틀리므로 affine 재적합이
            있어야 30 개가 다 붙는다."""
            coeff_s = np.copy(camera2focal_coeff); coeff_s[0] = m_init or coeff_s[0]
            coeff_s[1], coeff_s[2], coeff_s[3] = theta_guess, xoff, yoff   # fitdistortion 과 같은 자리
            xs, ys = transform(xobs, yobs, coeff_s)
            j, found = _assign(xs, ys)
            for _ in range(8):
                if found.sum() < 3:
                    break
                z = xobs[j[found]] + 1j*yobs[j[found]]; w = xf[found] + 1j*yf[found]
                A = np.column_stack((z, np.conj(z), np.ones(z.size)))
                M = np.vstack([np.column_stack([A.real, -A.imag]), np.column_stack([A.imag, A.real])])
                c, *_ = np.linalg.lstsq(M, np.r_[w.real, w.imag], rcond=None)
                cc = c[:3] + 1j*c[3:]
                pz = np.column_stack((xobs + 1j*yobs, xobs - 1j*yobs, np.ones(xobs.size))) @ cc
                j2, found2 = _assign(pz.real, pz.imag)
                if found2.sum() < found.sum():
                    break
                improved = found2.sum() > found.sum()
                j, found = j2, found2
                if not improved:
                    break
            return j, found

        # 먼저 fiducial 패턴만으로 맞춘다. 검출이 fiducial 수보다 많아도 (back-illumination 이 꺼져
        # 있으면 여분은 반사광·쪼개진 spot 몇 개뿐이다) 이것이 맞으면 그대로 쓴다.
        _, theta_guess, (xoff, yoff) = matchfiber(xf, yf, xobs, yobs, m_init=m_init)
        imatch, found = _check(theta_guess, xoff, yoff)
        if found.sum() < max(3, nfid//2) and xobs.size > nfid and exclude is None:
            # fiber 가 같이 켜져 있으면 fiducial 사이에 fiber 가 빽빽해 fiducial 30 개만으로는 회전각이
            # 정해지지 않을 수 있다: fiber 목표까지 넣은 전체 패턴으로 다시 맞추고 fiducial 자리만 쓴다
            # (fiber 자리를 지운 뒤(exclude)라면 남은 여분은 고정 점·sky fiber 뿐이므로 하지 않는다).
            _, theta2, (xoff2, yoff2) = matchfiber(x, y, xobs, yobs, m_init=m_init)
            imatch2, found2 = _check(theta2, xoff2, yoff2)
            log.info("Fiducial set %d: fiducial-only pattern matched %d/%d, with fiber targets %d/%d",
                     k, int(found.sum()), nfid, int(found2.sum()), nfid)
            if found2.sum() > found.sum():
                imatch, theta_guess, xoff, yoff, found = imatch2, theta2, xoff2, yoff2, found2
        sets.append(dict(x=xobs[imatch], y=yobs[imatch], peak=peak[imatch], nsat=nsat[imatch],
                         found=found, theta=theta_guess, off=(xoff, yoff),
                         all_x=xobs, all_y=yobs, all_peak=peak, all_nsat=nsat))
        log.info("Fiducial set %d (%s): %d peaks, %d/%d fiducials found, %d saturated, peak %.0f..%.0f",
                 k, head, xobs.size, int(found.sum()), nfid, int((nsat[imatch][found] > 0).sum()),
                 peak[imatch][found].min() if found.any() else np.nan,
                 peak[imatch][found].max() if found.any() else np.nan)
        if not found.all():
            log.warning("Fiducial set %d: not found %s", k,
                        ", ".join(str(i) for i in np.where(~found)[0]))

    # 패턴 매칭이 일부만 맞은 세트는, 가장 잘 맞은 세트의 변환(배율·회전·offset)으로 fiducial 이
    # 있을 자리를 예측해 그 근처(match_tol)의 검출을 다시 붙인다. 세트 사이의 카메라 이동은
    # 몇 px 라 이 방법이 패턴 매칭보다 믿을 만하다 (fiber 가 목표에서 멀리 있는 fiber 노출에서
    # 특히: 전체 패턴 매칭이 틀어진다).
    # matchfiber 의 회전·offset 은 격자 탐색값(0.5 deg, 0.5 mm)이라 시야 가장자리에서 1 mm 넘게
    # 틀릴 수 있다. 가장 잘 맞은 세트의 찾은 쌍으로 변환을 맞춰 (쌍이 적으면 affine 최소제곱,
    # 많으면 왜곡 모델 radial+affine) 예측 정밀도를 올린 뒤 모든 세트에서 다시 붙인다.
    # 찾은 수가 늘지 않을 때까지 되풀이한다 (왜곡이 큰 광학계에서는 몇 번 걸린다).
    def _predict(st, zz_x, zz_y):
        f = st['found']
        if f.sum() >= 10:
            # 쌍이 넉넉하면 전체 왜곡 모델 (시야 가장자리 외삽이 좋아진다)
            mdl = 'full+affine' if f.sum() >= 18 else 'radial+affine'
            _, _, _, _, cf = fitdistortion(xf[f], yf[f], np.ones(int(f.sum()), bool), st['x'][f], st['y'][f],
                                           np.arange(int(f.sum())), st['theta'], *st['off'],
                                           model=mdl, m_init=m_init)
            px, py = transform(st['x'][f], st['y'][f], cf)
            err = np.hypot(px - xf[f], py - yf[f])
            return transform(zz_x, zz_y, cf), err
        z = st['x'][f] + 1j*st['y'][f]; w = xf[f] + 1j*yf[f]
        A = np.column_stack((z, np.conj(z), np.ones(z.size)))
        M = np.vstack([np.column_stack([A.real, -A.imag]), np.column_stack([A.imag, A.real])])
        c, *_ = np.linalg.lstsq(M, np.r_[w.real, w.imag], rcond=None)
        cc = c[:3] + 1j*c[3:]
        zz = zz_x + 1j*zz_y
        p = np.column_stack((zz, np.conj(zz), np.ones(zz.size))) @ cc
        return (p.real, p.imag), np.abs(A @ cc - w)

    ref = max(range(len(sets)), key=lambda k: int(sets[k]['found'].sum()))
    if sets[ref]['found'].sum() >= max(3, nfid//3):
        for _ in range(8):
            improved = False
            for k, st in enumerate(sets):
                (px, py), pred_err = _predict(sets[ref], st['all_x'], st['all_y'])
                tree = cKDTree(np.column_stack((px, py)))
                d, j = tree.query(np.column_stack((xf, yf)))
                found = d < match_tol
                for jj in np.unique(j[found]):               # 한 검출에 둘 이상 붙으면 가까운 쪽만
                    same = np.where(found & (j == jj))[0]
                    if same.size > 1:
                        found[same] = False; found[same[np.argmin(d[same])]] = True
                if found.sum() >= st['found'].sum():
                    if found.sum() > st['found'].sum():
                        improved = True
                        log.info("Fiducial set %d: re-matched with set %d's transform "
                                 "(fit rms %.2f mm): %d -> %d found", k, ref, np.sqrt(np.mean(pred_err**2)),
                                 int(st['found'].sum()), int(found.sum()))
                    st.update(x=st['all_x'][j], y=st['all_y'][j], peak=st['all_peak'][j],
                              nsat=st['all_nsat'][j], found=found)
            ref = max(range(len(sets)), key=lambda k: int(sets[k]['found'].sum()))
            if not improved:
                break
        # (2026-10-27 제거: 남은 fiducial 을 허용 거리 2 배(3 mm)로 다시 붙이던 단계. 핀홀 실측 위치를
        #  쓰면 맞는 검출은 1.5 mm 안에 들어오고, 넓히면 fiber 점이 fiducial 로 잡힐 수 있다.)

    fallback = [False]*len(sets) if fallback is None else list(fallback)
    choice = np.full(nfid, -1, dtype=int)
    for i in range(nfid):
        cand = [k for k, st in enumerate(sets) if st['found'][i] and not fallback[k]]
        if not cand:
            cand = [k for k, st in enumerate(sets) if st['found'][i]]
        if not cand:
            continue
        ok = [k for k in cand if sets[k]['nsat'][i] == 0 and sets[k]['peak'][i] >= fid_min_peak]
        if ok:
            choice[i] = max(ok, key=lambda k: sets[k]['peak'][i])
        else:
            choice[i] = min(cand, key=lambda k: (sets[k]['nsat'][i], -sets[k]['peak'][i]))
    missing = np.where(choice < 0)[0]
    if nfid - missing.size < min_found(nfid):
        raise RuntimeError(f"fiducial {', '.join(str(i) for i in missing)} not found in any set "
                           f"({len(sets)} set(s)); only {nfid - missing.size}/{nfid} found -- add an exposure "
                           "where they are visible (fid_images / fid_exptime) or allow the fiber frame (fid_fallback_fiber)")
    if missing.size:
        log.warning("fiducial %s not found in any set (%d set(s)); continuing with %d/%d fiducials",
                    ", ".join(str(i) for i in missing), len(sets), nfid - missing.size, nfid)
    xobs = np.array([sets[choice[i]]['x'][i] if choice[i] >= 0 else np.nan for i in range(nfid)])
    yobs = np.array([sets[choice[i]]['y'][i] if choice[i] >= 0 else np.nan for i in range(nfid)])
    bad = [i for i in range(nfid) if choice[i] >= 0 and sets[choice[i]]['nsat'][i] > 0]
    if len(sets) > 1:
        log.info("Fiducial exposure chosen per fiducial: %s",
                 ", ".join(f"set {k}: {int((choice == k).sum())}" for k in range(len(sets))))
    if bad:
        log.warning("%d fiducial(s) saturated in every set where found (used anyway): %s", len(bad),
                    ", ".join(str(i) for i in bad))
    best = sets[ref]                                                   # 가장 잘 맞은 세트의 초기값
    return xobs, yobs, choice, best['theta'], best['off']


def _all_hole_ids(nfib, fid_flag):
    """load_configuration 순서의 홀 ID (fiber 표 순서 + fiducial)."""
    tab = ascii.read(cfg.FIBER_TABLE_PATH)
    ids = [str(v).strip() for v in tab[tab.colnames[0]]]; flags = [int(v) for v in tab[tab.colnames[3]]]
    return list(cfg.fiber_ids()) + [i for i, f in zip(ids, flags) if f == 1 and i not in cfg.FIDUCIAL_EXCLUDE]


def measure_fibers(head, x, y, nfib, coeff, data_dir, nexposure, max_dist=None, n_extra=0,
                   exclude=None, mode='Raw', leftover=None, origins=None, **pk):
    """fiber 노출에서 peak 을 찾아 (fiducial 로 맞춘) 변환으로 focal 좌표로 옮기고
    목표 위치에 가장 가까운 것을 그 fiber 로 본다. x, y 는 fiber + fiducial 전체
    목표 (fiducial 은 그 자리의 검출을 fiber 로 잘못 잡지 않게 하려고 넣는다).

    exclude : (xchip, ychip) 이미 아는 fiducial 의 칩 좌표. 주면 그 자리를 지우고 찾는다.
    mode : 'Raw' (검출 뒤 매칭) 또는 'Predict' (coeff 로 예측한 자리의 창 안에서만 잰다, 매칭 없음).
    leftover : dict 를 주면 목표에 할당되지 않은 검출(xf, yf, xobs, yobs, near_fixed)을 채워 준다 (Raw).

    반환: xfocal, yfocal (x, y 순서), dist (매칭 거리 [mm]), (xobs, yobs) (같은 순서의 칩 좌표)
    """
    log = get_logger()
    nfid = x.size - nfib
    if max_dist is None:
        max_dist = 3.0                                   # fiber 최소 이격(~3 mm) 정도
    if mode == 'Predict':
        # 이번 trial 의 fiducial 로 맞춘 변환으로 각 fiber 목표의 칩 좌표를 예측해 그 창 안에서만 잰다.
        # 창에 아무것도 없으면 (끊어졌는데 목록에 없는 fiber 등) 그 fiber 는 이번 trial 에 못 잰 것으로 둔다.
        xc, yc = invert_transform(x[:nfib], y[:nfib], coeff)
        _, xobs, yobs, peak = findpeak(nfib, data_dir=data_dir, head=head, nexposure=nexposure,
                                       mode='Predict', predict=(xc, yc), exclude=exclude, **pk)
        xf, yf = transform(xobs, yobs, coeff)
        dist = np.hypot(xf - x[:nfib], yf - y[:nfib])
        lost = peak < pk.get('threshold', 0.)
        ids = list(cfg.fiber_ids()); alive = [i for i, d in zip(ids, cfg.dead_mask()) if not d]
        if lost.any():
            log.warning("Predict: no spot above threshold at %d predicted position(s): %s -- "
                        "left unmeasured this trial (NaN); if the fiber is dark add it to FIBER_EXCLUDE",
                        int(lost.sum()), ", ".join(alive[i] for i in np.where(lost)[0]))
            xf[lost] = np.nan; yf[lost] = np.nan; dist[lost] = np.nan
        # 창 반폭(초점면 mm)의 80 % 보다 멀리 잰 fiber 는 창이 spot 전체를 담지 못했을 수 있다 (꼬리만 잡힘)
        lim = 0.8*pk.get('nwindow', 40)*3.76e-3*abs(coeff[0])
        far = np.where(dist > lim)[0]
        if far.size:
            log.warning("Predict: %d fiber(s) measured farther than %.2f mm (80%% of the window) from the "
                        "predicted position: %s -- the window may not contain the whole spot; verify with "
                        "mode='Raw'", far.size, lim, ", ".join(f"{alive[i]} ({dist[i]:.2f} mm)" for i in far))
        log.info("Fiber image (%s, Predict): %d windows; fiber-target distance median %.1f um, max %.1f um",
                 head, nfib, np.nanmedian(dist)*1e3, np.nanmax(dist)*1e3)
        xfocal = np.full(x.size, np.nan); yfocal = np.full(y.size, np.nan)
        xfocal[:nfib], yfocal[:nfib] = xf, yf
        return xfocal, yfocal, np.r_[dist, np.full(nfid, np.nan)], (xobs, yobs)
    nmax = nfib + n_extra if exclude is not None else nfib + nfid + n_extra
    _, xobs, yobs, _ = findpeak((nfib, nmax), data_dir=data_dir, head=head,
                                nexposure=nexposure, exclude=exclude, **pk)
    xf, yf = transform(xobs, yobs, coeff)
    keep = np.ones(xf.size, bool)
    fixed = cfg.fixed_spots()
    if fixed:
        # 자리를 아는 고정 점 (Fixed_Spots.txt): 그 자리의 검출은 fiber 후보에서 뺀다
        fx = np.array([v[0] for v in fixed.values()]); fy = np.array([v[1] for v in fixed.values()])
        dfix, _ = cKDTree(np.column_stack((fx, fy))).query(np.column_stack((xf, yf)))
        keep &= dfix > cfg.FIXED_SPOT_TOL
        log.info("Fixed spots (%s): %d detection(s) removed from the fiber candidates",
                 os.path.basename(cfg.FIXED_SPOTS_PATH), int((dfix <= cfg.FIXED_SPOT_TOL).sum()))
    kidx = np.where(keep)[0]; xf0, yf0, xo0, yo0 = xf, yf, xobs, yobs       # 전체 검출 (leftover 용)
    xobs, yobs, xf, yf = xobs[keep], yobs[keep], xf[keep], yf[keep]
    # 목표 <-> 검출 할당: 한 검출은 한 목표에만 (거리 합 최소). 너무 먼 짝은 큰 비용으로 막는다.
    # 자리를 모르는 고정 점(FIBER_FIXED, SKY_FIBERS)은 먼저 지우지 않는다: 살아 있는 fiber 가 목표에서
    # 몇 mm 벗어나 있으면 그 점이 이웃 고정 홀의 arm 범위에도 들어가므로, 지우면 그 fiber 를 잃는다.
    # 대신 할당하고 남은 검출을 고정 홀 것으로 본다 (아래). 자리를 아는 고정 점은 Fixed_Spots.txt 로.
    D = np.hypot(x[:, None] - xf[None, :], y[:, None] - yf[None, :])
    C = np.where(D > 3*max_dist, 1e6 + D, D)
    # fiducial 자리를 지운 이미지(exclude)라면 fiducial 목표는 할당에서 뺀다 (fiber 검출을 가져가지 않게);
    # 그 행은 아래에서 가장 가까운 검출로 채우지만 결과에는 쓰이지 않는다 (mtlcal 이 fiducial 노출 값으로 덮는다)
    nrow = nfib if exclude is not None else x.size
    rows, cols = linear_sum_assignment(C[:nrow]) if xf.size else (np.array([], int), np.array([], int))
    j = np.full(x.size, -1, dtype=int); dist = np.full(x.size, np.nan)
    j[rows] = cols; dist[rows] = D[rows, cols]
    ids = list(cfg.fiber_ids())
    alive = [i for i, d in zip(ids, cfg.dead_mask()) if not d]
    # fiber: 검출이 모자라거나 3*max_dist 보다 먼 짝은 이번 trial 에 못 잰 것으로 (NaN; mtlcal 이 회전 0 으로 둔다)
    lost = np.array([k < nfib and (j[k] < 0 or dist[k] > 3*max_dist) for k in range(x.size)])
    if lost.any():
        log.warning("%d fiber(s) with no detection within %.1f mm of the target: %s -- left unmeasured "
                    "this trial (NaN); if the fiber is dark add it to FIBER_EXCLUDE, if it is stuck to FIBER_FIXED",
                    int(lost.sum()), 3*max_dist,
                    ", ".join(f"{alive[k]}" + (f" (nearest {D[k].min():.1f} mm)" if xf.size else "")
                              for k in np.where(lost)[0]))
        j[lost] = -1; dist[lost] = np.nan
        # 목표 9 mm 안에 검출이 없는 fiber (positioner 가 크게 어긋났거나 안 움직인 경우): 그 positioner 의 arm
        # 도달 범위 (중심에서 |a2-a1| .. a1+a2, 여유 1 mm) 안에 남은 검출이 **하나뿐** 이면 그것을 그 fiber 로 본다.
        # 그래야 몇 도를 돌려야 제자리로 가는지(회전량) 가 나온다. 후보가 없거나 둘 이상이면 그대로 NaN (애매).
        # 다른 살아 있는 fiber 에 이미 할당된 검출은 후보에서 뺀다. (2026-10-28)
        a1_all, a2_all = cfg.arm_lengths()
        arm = {i: (a, b) for i, a, b in zip(ids, a1_all, a2_all)}
        if origins is not None:
            ox, oy = np.asarray(origins[0], float), np.asarray(origins[1], float)
        else:
            oxy = cfg.hole_xy(alive); ox, oy = oxy[:, 0], oxy[:, 1]
        taken = set(int(j[k]) for k in range(nrow) if j[k] >= 0)
        for k in np.where(lost)[0]:
            aa, bb = arm[alive[k]]
            r = np.hypot(xf - ox[k], yf - oy[k])
            cand = [q for q in range(xf.size) if q not in taken and (abs(bb - aa) - 1.0) <= r[q] <= (aa + bb + 1.0)]
            if len(cand) == 1:
                q = cand[0]; j[k] = q; dist[k] = D[k, q]; lost[k] = False; taken.add(q)
                log.warning("%s: no detection near the target, but exactly one unassigned detection within its arm "
                            "reach (%.1f mm from the centre, %.1f mm from the target) -- taken as this fiber "
                            "(check the image before trusting the rotation)", alive[k], r[q], dist[k])
            elif len(cand) > 1:
                log.warning("%s: %d unassigned detections within its arm reach (%s mm from the centre) -- ambiguous, "
                            "left NaN", alive[k], len(cand), ", ".join(f"{r[q]:.1f}" for q in cand))
    for i in np.setdiff1d(np.arange(nfib, x.size), rows):   # fiducial 행 (단일 이미지일 때만 쓰임): 가장 가까운 것
        if xf.size:
            j[i] = int(np.argmin(D[i])); dist[i] = D[i, j[i]]
    # 할당하고 남은 검출 (Fixed_Spots 로 지운 것 포함): 고정 positioner / sky 홀의 arm 범위 안이면 그 점으로 본다 (기록만)
    holes = cfg.lit_unmatched_holes()
    used = set(int(kidx[j[k]]) for k in range(nrow) if j[k] >= 0)   # 할당된 행만 (fiducial 행의 임시 채움은 제외)
    left = np.array([k for k in range(xf0.size) if k not in used], dtype=int)
    near_fixed0 = np.zeros(xf0.size, bool)
    if len(holes) and xf0.size:
        a1, a2 = cfg.arm_lengths()
        reach = float((a1 + a2).max()) + 1.0
        dh, _ = cKDTree(holes).query(np.column_stack((xf0, yf0)))
        near_fixed0 = dh < reach
        n_stuck = int(near_fixed0[left].sum()) if left.size else 0
        log.info("Lit but unmatched holes (%d fixed positioner(s), %d sky fiber(s)): %d leftover detection(s) "
                 "within arm reach taken as theirs, %d leftover elsewhere",
                 len(cfg.FIBER_FIXED), len(cfg.SKY_FIBERS), n_stuck, int(left.size) - n_stuck)
    elif left.size:
        log.info("%d detection(s) not assigned to any target", int(left.size))
    near_fixed = near_fixed0[kidx]
    if leftover is not None:                                # lab.find_fixed_spots 용: 남은 검출의 초점면 좌표
        leftover.update(xf=xf0[left], yf=yf0[left], xobs=xo0[left], yobs=yo0[left], near_fixed=near_fixed0[left])
    far = np.where(np.nan_to_num(dist[:nfib], nan=0.) > max_dist)[0]
    if far.size:
        log.warning("%d fiber(s) matched farther than %.1f mm from the target: %s -- a large positioner error, "
                    "or the spot may be a stuck positioner's / sky fiber's (write Fixed_Spots.txt with "
                    "lab.find_fixed_spots to make this unambiguous)", far.size, max_dist,
                    ", ".join(f"{alive[i]} ({dist[i]:.1f} mm" + (", within reach of a fixed/sky hole)"
                              if near_fixed[j[i]] else ")") for i in far))
    log.info("Fiber image (%s): %d peaks; fiber-target distance median %.1f um, max %.1f um",
             head, xobs.size, np.nanmedian(dist[:nfib])*1e3, np.nanmax(dist[:nfib])*1e3)
    if xf.size == 0:
        nanv = np.full(x.size, np.nan)
        return nanv, nanv.copy(), dist, (nanv.copy(), nanv.copy())
    jj = np.where(j >= 0, j, 0)
    xr, yr, xor, yor = xf[jj].copy(), yf[jj].copy(), xobs[jj].copy(), yobs[jj].copy()
    xr[j < 0] = np.nan; yr[j < 0] = np.nan; xor[j < 0] = np.nan; yor[j < 0] = np.nan
    return xr, yr, dist, (xor, yor)


def mtlcal(data_dir='./MTL/data/'
           , head='test'
           , mode='Raw'
           , threshold=3e3
           , nwindow=40
           , niter_recenter=0
           , apply_pinhole_offset=False
           , use_measured=None
           , use_measured_positioners=None
           , finder='sep'
           , finder_opts=None
           , background='crop'
           , background_opts=None
           , nexposure=1
           , fid_head=None
           , fid_nexposure=None
           , model='full'
           , magnification=None
           , sat_level=65000.
           , fid_min_peak=0.
           , n_extra=0
           , cross_exclude=True
           , min_dist=40
           , fid_fallback_fiber=True
           , fid_fiber_set=False
           , target_file=None
           , json_dir=None
           , target_name=None
           , itrial=1):
    """이미지에서 fiber 위치를 재고 positioner 보정각을 구한다.

    fid_head 가 None 이면 이미지 한 벌(head)에 fiber 와 fiducial 이 같이 찍혀
    있다고 보고 한 번에 처리한다 (기본). fiber 와 fiducial 의 밝기 차이가 커서
    노출을 나눠 찍었으면 fiducial 노출의 head 를 fid_head 에 준다 (하나 또는
    여러 개의 리스트: fiducial 밝기 차이가 심해 두 노출로 나눠 찍은 경우). 그러면

        1. fiducial 노출(들)에서 fiducial 위치를 재고  (measure_fiducials)
        2. fiducial 로 camera -> focal 변환을 맞춘 뒤 (fitdistortion)
        3. fiber 노출(head)의 peak 을 그 변환으로 옮겨 목표에 매칭한다 (measure_fibers)

    두 노출 사이에 카메라와 plate 가 움직이지 않았다고 가정한다.

    model 은 왜곡 다항식에서 풀 항이다 (utils.DISTORTION_MODELS: 'full', 'optics',
    'radial', 'similarity'). 렌즈가 적은 실험실 광학계에서는 'radial' 처럼 줄인다.
    magnification 은 camera -> focal 배율 초기값으로, 본 장비와 광학계가 다르면
    (실험실) 꼭 주어야 fiber 매칭이 된다 (utils.CAMERA2FOCAL_M 참고; 부호 포함).
    sat_level 은 포화 판정 수준 [ADU], fid_min_peak 은 fiducial 노출을 고를 때 이보다
    어두운 검출을 피하는 기준이다. n_extra 는 표에 없는데 이미지에 보이는 밝은 점의 수
    (예: 고정된 sky fiber 9개). 그만큼 검출을 더 허용하고 매칭에서 자연히 빠진다.
    min_dist 는 가까운 검출을 하나로 합치는 거리 [px] (findpeak 참고; 큰 PSF 면 80 정도).
    fid_fiber_set (기본 False) 이면 fiber 노출을 예비가 아니라 정식 fiducial 세트로 쓴다 (fiber 노출시간이
    fiducial 노출시간 중 하나와 같아서 그 세트를 따로 찍지 않았을 때; MetrologyRun 이 정한다).
    fid_fallback_fiber (기본 True) 는 fiducial 전용 노출에서 안 보이는 fiducial 을 fiber
    노출(fiducial 이 같이 켜져 있을 때, 보통 포화)에서라도 가져오는 것이다.
    cross_exclude (기본 True) 는 노출을 나눠 찍었을 때 fiber 노출의 fiducial 자리와
    fiducial 노출의 fiber 자리를 서로 지우고 찾는 것이다 (양쪽 다 켜 놓고 찍은 경우).

    mode: "Raw"(기본) 는 threshold 를 조절해 가며 peak 을 찾고 패턴에 매칭한다. "Predict" 는
    이미 맞춘 변환으로 각 목표의 칩 좌표를 예측해 그 창(nwindow) 안의 가장 밝은 픽셀에서 잰다
    (매칭 없음). 노출을 나눴으면 fiducial 은 Raw 로 찾아 변환을 맞추고 fiber 만 Predict 로 잰다;
    한 벌 이미지면 직전 trial 이 저장한 변환(_coeff.npy)을 쓰고, 없으면 그 trial 은 Raw 로 돈다.
    끊어진/고정된/sky fiber 처리는 Raw 와 같다 (목록의 fiber 자리는 보지 않는다). 창 안에 threshold
    이상의 화소가 없는 fiber 는 그 trial 에 못 잰 것(NaN, 회전 0)으로 두고 경고한다. 목표에서
    창 반폭(nwindow × 3.76 µm × 배율 ≈ 1.3 mm) 넘게 벗어난 fiber 는 Predict 로 잴 수 없으므로
    위치 오차가 그 안으로 들어온 뒤(보통 trial 2 부터) 쓴다.

    nwindow는 findpeak이 center of mass를 잴 때 쓰는 crop 반폭 [pixel]이다.
    이 창 안에 이웃 spot이 들어오면 무게중심이 끌려가 위치를 잘못 잰다. 창의
    반폭을 focal plane 거리로 환산하면 nwindow * 3.76e-3 mm/px * 배율(~8.47)
    이므로, fiber 사이 최소 이격 거리의 절반보다 작아야 한다.
    최소 이격 3mm 기준이면 nwindow <= 40 이어야 한다.

    use_measured 는 설계 좌표와 arm 길이를 실측값으로 바꿀지다
    (load_configuration 참고). None이면 fiber_config.USE_MEASURED를 따른다.

    apply_pinhole_offset 은 fiducial 기준 좌표에 핀홀 오프셋을 더할지다
    (load_configuration 참고). 기본값은 False이고, 쓰는 plate에서 측정한
    핀홀 파일을 넣은 뒤에 True로 켠다.

    niter_recenter 는 창을 무게중심으로 옮겨 다시 재는 횟수다 (findpeak 참고).
    PSF가 창에 비해 크면 켜는 것이 좋다.

    finder / finder_opts 는 peak을 찾는 방법과 그 인자다 ('find_peaks',
    'daofind', 'sep', 'segmentation'). background / background_opts 는 배경
    제거 방식이다. 둘 다 findpeak으로 그대로 넘어간다 (peakfind 참고).

    json_dir와 target_name을 주면 누적 각도를 trial별 json으로 저장한다.
    누적 각도는 직전 trial의 json에 이번 회전량을 더한 값이라, itrial-1 파일이
    있어야 한다 (없으면 목표 각도에서 출발한다).

    반환:
        dx, dy    : fiber와 fiducial 전체의 목표 대비 위치 오차 (mm)
        angle_rot : fiber 순서의 이번 trial 회전량 (deg)
        angle_cum : fiber 순서의 누적 각도 (deg). json에 저장하는 값과 같다.
    """
    log = get_logger()

    xorigin, yorigin, x, y, fid_flag, nfib = load_configuration(
        target_file, apply_pinhole_offset=apply_pinhole_offset,
        use_measured=use_measured, use_measured_positioners=use_measured_positioners)

    pk = dict(threshold=threshold, nwindow=nwindow, niter_recenter=niter_recenter,
              finder=finder, finder_opts=finder_opts, background=background,
              background_opts=background_opts, min_dist=min_dist)

    # 빛이 안 나는 positioner (FIBER_EXCLUDE: 끊어졌거나 분광기에 fiber 가 안 연결된 홀) 와 고장나
    # 고정된 positioner (FIBER_FIXED): 매칭에서 뺀다.
    # 배열 순서는 그대로. 고정된 positioner 와 sky fiber (SKY_FIBERS) 는 이미지에 켜져 있으므로
    # 검출 개수 상한에 더한다 (measure_fibers 가 홀 근처에서 걸러낸다).
    # cross_exclude: 노출을 나눠 찍었는데 fiber 노출에 fiducial 이, fiducial 노출에 fiber 가
    # 같이 찍힌 경우. fiducial 노출에서 찾은 fiducial 자리를 fiber 노출에서 지우고 fiber 를
    # 찾은 뒤, 그 fiber 자리를 fiducial 노출에서 지우고 fiducial 을 한 번 더 찾는다.
    dead = np.r_[cfg.dead_mask(), np.zeros(x.size-nfib, dtype=bool)]
    n_extra = n_extra + len(cfg.FIBER_FIXED) + len(cfg.SKY_FIBERS)
    if dead.any() or cfg.SKY_FIBERS:
        log.info("Excluded fiber(s): unlit (broken / not connected) %s; fixed (lit, not matched) %s; sky fibers %s",
                 [h for h in cfg.fiber_ids() if h in cfg.FIBER_EXCLUDE] or '-',
                 list(cfg.FIBER_FIXED) or '-', list(cfg.SKY_FIBERS) or '-')
    xa, ya, fa = x[~dead], y[~dead], fid_flag[~dead]
    nfib_a = int((~dead[:nfib]).sum())

    prev_coeff = None
    if mode == 'Predict' and fid_head is None:
        # 한 벌 이미지의 Predict 는 직전 trial 에서 맞춘 변환이 있어야 한다 (없으면 Raw 로)
        cp = naming.coeff_path(json_dir, target_name, itrial-1) if (json_dir is not None and target_name is not None) else None
        if cp is not None and os.path.exists(cp):
            prev_coeff = np.load(cp)
        else:
            log.warning("Predict mode: no transform from the previous trial (%s) -- using Raw for this trial", cp)
            mode = 'Raw'

    if fid_head is None:
        #---이미지 한 벌: fiber 와 fiducial 을 같이 찾는다-------------------------
        if mode == 'Predict':
            xc, yc = invert_transform(xa, ya, prev_coeff)
            _, xobs, yobs, peak, nsat = findpeak(xa.size, data_dir=data_dir, head=head, nexposure=nexposure,
                                                 mode='Predict', predict=(xc, yc), sat_level=sat_level,
                                                 ReturnNsat=True, **pk)
            found = peak >= threshold
            if not found.all():
                ids_a = [i for i, d in zip(_all_hole_ids(nfib, fid_flag), dead) if not d]
                log.warning("Predict: no spot above threshold at %d predicted position(s): %s -- left unmeasured "
                            "this trial", int((~found).sum()), ", ".join(ids_a[i] for i in np.where(~found)[0]))
            px, py = transform(xobs, yobs, prev_coeff)
            dpred = np.hypot(px - xa, py - ya); lim = 0.8*nwindow*3.76e-3*abs(prev_coeff[0])
            far = np.where(found & (dpred > lim))[0]
            if far.size:
                ids_a = [i for i, d in zip(_all_hole_ids(nfib, fid_flag), dead) if not d]
                log.warning("Predict: %d spot(s) measured farther than %.2f mm (80%% of the window) from the "
                            "predicted position: %s -- the window may not contain the whole spot; verify with "
                            "mode='Raw'", far.size, lim, ", ".join(f"{ids_a[i]} ({dpred[i]:.2f} mm)" for i in far))
            imatch = np.arange(int(found.sum()))
            theta_guess, xoff_guess, yoff_guess = prev_coeff[1], prev_coeff[2], prev_coeff[3]
            xf_f, yf_f, _, _, coeff = fitdistortion(xa[found], ya[found], fa[found], xobs[found], yobs[found],
                                                    imatch, theta_guess, xoff_guess, yoff_guess,
                                                    model=model, m_init=magnification)
            xf_a = np.full(xa.size, np.nan); yf_a = np.full(ya.size, np.nan)
            xf_a[found], yf_a[found] = xf_f, yf_f
            nsat_fid = int((nsat[fa & found] > 0).sum())
        else:
            npeaks = xa.size if n_extra == 0 else (xa.size, xa.size + n_extra)
            _, xobs, yobs, _, nsat = findpeak(npeaks, data_dir=data_dir, head=head,
                                              nexposure=nexposure, mode='Raw', x=xa, y=ya,
                                              sat_level=sat_level, ReturnNsat=True, **pk)

            imatch, theta_guess, (xoff_guess, yoff_guess) = matchfiber(
                xa, ya, xobs, yobs, m_init=magnification)

            nsat_fid = int((nsat[imatch][fa] > 0).sum())
            xf_a, yf_a, _, _, coeff = fitdistortion(xa, ya, fa
                                                    , xobs, yobs
                                                    , imatch, theta_guess
                                                    , xoff_guess, yoff_guess
                                                    , model=model, m_init=magnification)
        if nsat_fid:
            log.warning("%d fiducial(s) saturated; consider a separate fiducial "
                        "exposure (fid_head / fid_exptime)", nsat_fid)
    else:
        #---노출을 나눠 찍은 경우: fiducial 노출로 변환을 맞추고 fiber 노출에 적용----
        fid_heads = [fid_head] if isinstance(fid_head, str) else list(fid_head)
        fid_nexposure = nexposure if fid_nexposure is None else fid_nexposure
        x_fid, y_fid = x[fid_flag], y[fid_flag]
        # fiber 노출도 마지막 후보로 (전용 노출에서 안 보이는 fiducial 을 위해; 보통 포화라 뒤로 밀린다)
        heads_all = fid_heads + ([head] if fid_fallback_fiber else [])
        nexp_all = [fid_nexposure]*len(fid_heads) + ([nexposure] if fid_fallback_fiber else [])

        fb_all = [False]*len(fid_heads) + ([not fid_fiber_set] if fid_fallback_fiber else [])

        # fiducial 찾기. 기준 칩 좌표(직전 trial / 기준 파일)가 있으면 그 주변에서만 찾고 (패턴 매칭 없음),
        # 없거나 절반도 못 찾으면 패턴 매칭 (measure_fiducials) 으로 처음부터 찾는다.
        ref, ref_path = load_fid_ref(json_dir, target_name, itrial, x_fid.size)
        used_ref = False
        if ref is not None:
            got = measure_fiducials_ref(heads_all, x_fid, y_fid, ref, data_dir, fid_nexposure, nfib_a,
                                        set_nexposure=nexp_all, n_extra=n_extra, sat_level=sat_level,
                                        fid_min_peak=fid_min_peak, fallback=fb_all, **pk)
            if got is not None:
                xo_fid, yo_fid, _ = got
                used_ref = True
                log.info("Fiducials identified from the reference chip positions (%s)", ref_path)
                # fitdistortion 초기값: 직전 trial 의 변환이 있으면 그것, 없으면 찾은 쌍으로 격자 탐색
                prev_c = naming.coeff_path(json_dir, target_name, itrial - 1) if target_name is not None else None
                if prev_c and os.path.exists(prev_c):
                    pc = np.load(prev_c); theta_guess, xoff_guess, yoff_guess = pc[1], pc[2], pc[3]
                else:
                    ok = np.isfinite(xo_fid)
                    _, theta_guess, (xoff_guess, yoff_guess) = matchfiber(x_fid[ok], y_fid[ok], xo_fid[ok], yo_fid[ok],
                                                                          m_init=magnification)
        if not used_ref:
            xo_fid, yo_fid, _, theta_guess, (xoff_guess, yoff_guess) = measure_fiducials(
                heads_all, xa, ya, fa, data_dir, fid_nexposure, set_nexposure=nexp_all, n_extra=n_extra,
                m_init=magnification, sat_level=sat_level, fid_min_peak=fid_min_peak, fallback=fb_all, **pk)

        xf_fid, yf_fid, coeff, fid_used = fit_fiducials(x_fid, y_fid, xo_fid, yo_fid, theta_guess, xoff_guess,
                                                        yoff_guess, model, magnification)
        xo_fid = np.where(fid_used, xo_fid, np.nan); yo_fid = np.where(fid_used, yo_fid, np.nan)
        ok_fid = np.isfinite(xo_fid)

        origins_a = (xorigin[~dead][:nfib_a], yorigin[~dead][:nfib_a])      # 살아 있는 positioner 의 회전 중심
        xf_a, yf_a, _, (xo_fib, yo_fib) = measure_fibers(
            head, xa, ya, nfib_a, coeff, data_dir, nexposure, n_extra=n_extra,
            exclude=(xo_fid[ok_fid], yo_fid[ok_fid]) if cross_exclude else None, mode=mode, origins=origins_a, **pk)
        if cross_exclude:
            # fiber 자리를 지우고 fiducial 을 다시 찾아 변환을 다시 맞춘다 (fiducial 가까이 있는 fiber 의 빛이
            # 무게중심을 끌지 않게). 이 2차 탐색은 다듬기일 뿐이므로 여기서 fiducial 을 잃으면 (예: 어두운
            # fiducial 이 검출 상한 때문에 버려짐) 1차 결과를 그대로 쓴다.
            try:
                if used_ref:
                    got = measure_fiducials_ref(heads_all, x_fid, y_fid, ref, data_dir, fid_nexposure, nfib_a,
                                                set_nexposure=nexp_all, n_extra=n_extra, sat_level=sat_level,
                                                fid_min_peak=fid_min_peak, fallback=fb_all,
                                                exclude=(xo_fib[:nfib_a], yo_fib[:nfib_a]), **pk)
                    if got is None:
                        raise RuntimeError("reference search found too few fiducials with fiber spots masked")
                    xo_fid2, yo_fid2, _ = got
                    theta2, xoff2, yoff2 = theta_guess, xoff_guess, yoff_guess
                else:
                    xo_fid2, yo_fid2, _, theta2, (xoff2, yoff2) = measure_fiducials(
                        heads_all, xa, ya, fa, data_dir, fid_nexposure, set_nexposure=nexp_all,
                        n_extra=n_extra, m_init=magnification, sat_level=sat_level, fid_min_peak=fid_min_peak,
                        fallback=fb_all, exclude=(xo_fib[:nfib_a], yo_fib[:nfib_a]), **pk)
            except RuntimeError as err:
                log.warning("cross_exclude: fiducial re-detection with fiber spots masked failed (%s); "
                            "keeping the first-pass fiducial positions", err)
            else:
                xo_fid, yo_fid, theta_guess, xoff_guess, yoff_guess = xo_fid2, yo_fid2, theta2, xoff2, yoff2
                xf_fid, yf_fid, coeff, fid_used = fit_fiducials(x_fid, y_fid, xo_fid, yo_fid, theta_guess,
                                                                xoff_guess, yoff_guess, model, magnification)
                xo_fid = np.where(fid_used, xo_fid, np.nan); yo_fid = np.where(fid_used, yo_fid, np.nan)
                ok_fid = np.isfinite(xo_fid)
                xf_a, yf_a, _, _ = measure_fibers(
                    head, xa, ya, nfib_a, coeff, data_dir, nexposure, n_extra=n_extra,
                    exclude=(xo_fid[ok_fid], yo_fid[ok_fid]), mode=mode, origins=origins_a, **pk)
        xf_a[fa], yf_a[fa] = xf_fid, yf_fid                      # fiducial 은 전용 노출 값 (안 쓴 fiducial 은 NaN)
        save_fid_ref(json_dir, target_name, itrial, xo_fid, yo_fid)   # 다음 trial 의 fiducial 찾기 기준

    xfocal = np.full(x.size, np.nan); yfocal = np.full(y.size, np.nan)
    xfocal[~dead], yfocal[~dead] = xf_a, yf_a                   # 끊어진 fiber 는 NaN
    dx, dy = xfocal-x, yfocal-y

    #---보정각 계산 (fiber만)---------------------------------------------------
    theta_true, phi_true = _arm_angles(xorigin, yorigin, x, y, use_measured, what='target')
    theta_obs, phi_obs = _arm_angles(xorigin, yorigin, xfocal, yfocal,
                                     use_measured, what='measured')

    dtheta, dphi = _wrap(theta_true - theta_obs, phi_true - phi_obs)
    dtheta[dead[:nfib]] = 0.; dphi[dead[:nfib]] = 0.             # 끊어진 fiber 는 안 움직인다
    lost = ~dead[:nfib] & ~np.isfinite(dtheta)                   # 이번 trial 에 못 잰 fiber (Predict 창이 빔)
    if lost.any():
        ids = list(cfg.fiber_ids())
        log.warning("%d fiber(s) not measured this trial (rotation set to 0): %s",
                    int(lost.sum()), ", ".join(ids[i] for i in np.where(lost)[0]))
        dtheta[lost] = 0.; dphi[lost] = 0.

    angle_rot = _flatten_angles(dtheta, dphi, absolute=False)   # 회전량: 영점과 무관

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
    # alpha: 360 도 돌면 같은 위치라 해가 여럿이다. 직전 각도에서 가장 적게 도는 해가 리밋 (여유 포함) 안이면 그대로, 밖이면
    # 반대로 도는 해, 그것도 밖이면 리밋에서 자른다. 한 바퀴로 wrap 하지 않는다 (30.5 -> -329.5 는 반대로 360 도 도는 명령).
    a_new, other_way, clipped = cfg.alpha_cum_in_range(prev[0::2], angle_rot[0::2])
    lo_a, hi_a = cfg.alpha_cmd_range()
    if other_way.any():
        ids_a = list(cfg.fiber_ids())
        log.warning("alpha goes the other way around to stay inside the positioner range (%g, %g] for %s",
                    lo_a, hi_a, ", ".join(f"{ids_a[i]} ({prev[2*i]:.1f} {angle_rot[2*i]:+.1f} -> {a_new[i]:.1f})"
                                          for i in np.where(other_way)[0]))
    if clipped.any():
        ids_a = list(cfg.fiber_ids())
        log.warning("cumulative alpha outside the positioner range (%g, %g] for %s -- clipped (arm at its end stop)",
                    lo_a, hi_a, ", ".join(f"{ids_a[i]} ({angle_cum[2*i]:.1f} -> {a_new[i]:.1f})" for i in np.where(clipped)[0]))
    angle_cum[0::2] = a_new
    angle_rot[0::2] = np.where(np.isfinite(a_new), a_new - prev[0::2], angle_rot[0::2])   # offset 표의 dalpha = 실제 보낸 회전량
    out_b = np.isfinite(angle_cum[1::2]) & ((angle_cum[1::2] < cfg.BETA_RANGE[0]) | (angle_cum[1::2] > cfg.BETA_RANGE[1]))
    if out_b.any():                                             # positioner 가 실행할 수 없는 beta: 범위로 자른다
        ids_b = list(cfg.fiber_ids())
        log.warning("cumulative beta outside the positioner range %s for %s -- clipped (arm at its end stop)",
                    cfg.BETA_RANGE, ", ".join(f"{ids_b[i]} ({angle_cum[2*i+1]:.1f})" for i in np.where(out_b)[0]))
        angle_cum[1::2] = cfg.clip_beta(angle_cum[1::2])
    # 그래도 범위 밖인 fiber (정상 경로에서는 없어야 한다) 는 그 fiber 만 직전 각도로 되돌리고 (회전 0) 나머지는
    # 그대로 내보낸다. fiber 하나 때문에 trial 전체를 버리지 않는다.
    bad = cfg.out_of_range_mask(angle_cum)
    if bad.any():
        ids_b = list(cfg.fiber_ids())
        log.error("command angles outside the positioner range for %s -- these fibers keep their previous "
                  "angles this trial (rotation 0); the others are written normally",
                  ", ".join(f"{ids_b[i]} ({angle_cum[2*i]:.1f}, {angle_cum[2*i+1]:.1f})" for i in np.where(bad)[0]))
        for i in np.where(bad)[0]:
            angle_cum[2*i:2*i+2] = prev[2*i:2*i+2]; angle_rot[2*i:2*i+2] = 0.

    if json_dir is not None and target_name is not None:
        np.save(naming.coeff_path(json_dir, target_name, itrial), coeff)   # 다음 trial 의 Predict 가 읽는다
        log.info("Saved angles to %s",
                 save_angles(json_dir, target_name, itrial, angle_cum))
        log.info("Saved fiber offsets to %s",
                 save_offsets(json_dir, target_name, itrial, dx, dy, angle_rot, nfib))

    dist = np.sqrt(dx[~fid_flag & ~dead]**2 + dy[~fid_flag & ~dead]**2)*1e3
    log.info("Fiber position error: max %.1f um, median %.1f um",
             dist.max(), np.median(dist))

    return dx, dy, angle_rot, angle_cum
