"""metrology 시점의 하늘 보정: assign 목표 (xp, yp) 를 초점면 원점 둘레로 돌린다.

assign 파일 (planner) 의 xp, yp 는 ICRS RA/Dec 를 고정 회전각 (예: 15.00 deg) 으로 초점면에
옮긴 값이다. 실제로 필요한 회전은 두 가지가 더 있다.

1. 세차 (precession): 적도의 마운트는 관측 시점의 참 천구 북극을 따른다 (TETE). ICRS 북쪽과
   TETE 북쪽은 타일 위치에서 약 0.149 deg x sin(RA) / cos(Dec) (2026 년) 만큼 어긋나므로,
   초점면에서 그만큼 (-PA) 돌려야 한다. 날짜만 몇 주 정확하면 된다 (하룻밤 안에는 1e-5 deg).
2. 기기 회전 오프셋 (instrument offset): GFA 로 잰 기기 회전 (TETE) 에서 planner 가 쓴
   회전을 뺀 값. 2026-10-28 GFA 측정 15.18 deg - planner 15.00 deg = 0.18 deg.
   재설치하면 GFA 로 다시 재서 KSPEC.ini 의 MTL.sky_correction.instrument_offset_deg 를 고친다.

세차 쪽은 회전 하나가 아니라, 목표들의 ICRS 와 TETE gnomonic 좌표 (타일 중심 둘레) 를 잇는
닮음 변환 (회전 + 배율; 배율은 광행차의 ~5e-5) 을 목표들로 맞춰서 쓴다. planner 의 하늘 ->
초점면 매핑 (2x2 행렬, 반경 왜곡) 은 필요 없다. 초점면은 하늘의 거울상이라 (planner x = +E,
y = -N) 하늘에서의 회전은 초점면에서 반대 부호가 된다. 여기에 기기 오프셋 회전을 더해
초점면 원점 둘레로 적용한다 (planner 규약에서 반시계, +x -> +y). 타일별 정확한 TETE 매핑
(planner 매핑으로 다시 투영) 과의 차이는 9111 / 9140 에서 최대 0.2 um (회전만 쓰면 3-5 um)
이다 (proj-kspecdr note 2026-10-28-assign-rotation-correction). 계산은 ~30 ms.

보정 파일에는 planner 원래 값을 xp_planner / yp_planner 로 같이 남기고, 이미 보정된
파일을 다시 넣으면 그 원래 값에서 다시 계산한다 (보정이 두 번 들어가지 않는다).

calibration target 은 보정하지 않고 원래 파일을 그대로 쓴다: 파일 이름이나 project 에
'calib' 가 들어 있거나 (대소문자 무관, 예: Calib_2627_0001.assign.json), 하늘 좌표가 없는
경우 (각도만 적은 파일, 또는 ra/dec 가 모두 한 점, 예: Calib 의 ra = dec = 0). 보정 결과에
NaN 이 생기면 파일을 쓰지 않고 멈춘다.
"""

import json
import logging
import os
from datetime import datetime, timezone

import numpy as np

from kspec_metrology.analysis import fiber_config as cfg

log = logging.getLogger(__name__)

SUFFIX = '_skycorr'
# 파일 이름이나 project 에 이 글자가 들어 있으면 (대소문자 무관) calibration target 으로 본다
CALIB_TAG = 'calib'
# 목표들이 타일 중심에서 이보다 가까이 모여 있으면 하늘 좌표가 없는 target 으로 본다 [deg]
MIN_SKY_SPREAD_DEG = 1. / 3600.


def obs_time(time=None):
    """관측 시각을 astropy Time (UTC) 으로. None 이면 지금.

    astropy 는 '+00:00' / 'Z' 같은 시간대 꼬리가 붙은 ISO 문자열을 못 읽어서
    (datetime.isoformat() 의 기본 출력), 그런 문자열은 datetime 으로 읽어 UTC 로 바꾼다.
    """
    from astropy.time import Time

    if time is None:
        return Time(datetime.now(timezone.utc))
    if isinstance(time, str):
        try:
            return Time(time, scale='utc')
        except ValueError:
            t = datetime.fromisoformat(time.strip().replace('Z', '+00:00'))
            if t.tzinfo is not None:
                t = t.astimezone(timezone.utc)
            return Time(t.replace(tzinfo=None), scale='utc')
    return Time(time)


def precession_rotation_deg(ra_deg, dec_deg, time):
    """ICRS 로 만든 목표를 TETE 에 맞추는 초점면 회전 [deg] (planner 규약). = -PA(TETE 북쪽, ICRS)."""
    import astropy.units as u
    from astropy.coordinates import TETE, SkyCoord

    frame = TETE(obstime=obs_time(time))
    c = SkyCoord(ra_deg * u.deg, dec_deg * u.deg)
    ct = c.transform_to(frame)
    north = SkyCoord(ct.ra, ct.dec + 1 * u.arcmin, frame=frame).transform_to('icrs')
    pa = c.position_angle(north).wrap_at(180 * u.deg).deg
    return -float(pa)


def icrs_to_tete_focal(ra_deg, dec_deg, centre, time):
    """ICRS 목표를 TETE 에 맞추는 초점면 (회전 [deg], 배율). planner 규약 (x = +E, y = -N).

    목표들의 gnomonic 좌표 z = xi + i eta 를 ICRS (타일 중심 둘레) 와 TETE (TETE 로 옮긴 타일
    중심 둘레) 에서 구해 z_tete = a z_icrs 로 맞춘다. 초점면 w = x + i y 는 conj(z) 에 비례하므로
    w_tete = conj(a) w_icrs: 회전 -arg(a), 배율 |a|.
    """
    import astropy.units as u
    from astropy.coordinates import TETE, SkyCoord, SkyOffsetFrame

    frame = TETE(obstime=obs_time(time))
    s = SkyCoord(np.asarray(ra_deg, float) * u.deg, np.asarray(dec_deg, float) * u.deg)
    c = SkyCoord(centre[0] * u.deg, centre[1] * u.deg)
    oi = s.transform_to(SkyOffsetFrame(origin=c))
    st, ct = s.transform_to(frame), c.transform_to(frame)
    # TETE 좌표를 같은 방식으로 투영하려고 icrs 이름표만 붙인다 (값은 TETE RA/Dec)
    ot = SkyCoord(st.ra, st.dec, frame='icrs').transform_to(
        SkyOffsetFrame(origin=SkyCoord(ct.ra, ct.dec, frame='icrs')))
    zi = oi.lon.rad + 1j * oi.lat.rad
    zt = ot.lon.rad + 1j * ot.lat.rad
    a = np.vdot(zi, zt) / np.vdot(zi, zi)
    return float(-np.degrees(np.angle(a))), float(abs(a))


def field_centre(target):
    """타일 중심 (RA, Dec) [deg]. tile_ra / tile_dec 가 있으면 그것, 없으면 목표들의 벡터 평균.

    목표 평균은 타일 중심에서 0.1 deg 안쪽이라 세차 회전 차이는 1e-3 deg 미만이다.
    """
    if target.get('tile_ra') is not None and target.get('tile_dec') is not None:
        return float(target['tile_ra']), float(target['tile_dec'])
    ra = np.radians(np.asarray(target['ra'], float))
    dec = np.radians(np.asarray(target['dec'], float))
    v = np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)]).mean(axis=1)
    return (float(np.degrees(np.arctan2(v[1], v[0])) % 360.),
            float(np.degrees(np.arcsin(v[2] / np.linalg.norm(v)))))


def _reach(xp, yp, use_measured=None):
    """목표의 positioner 도달 여유 [mm] (음수면 닿지 않음). 설계 홀 중심, arm 길이."""
    ids = cfg.fiber_ids()
    if len(ids) != len(xp):
        return None
    hole = cfg.hole_xy(ids)
    a1, a2 = cfg.arm_lengths(use_measured)
    r = np.hypot(xp - hole[:, 0], yp - hole[:, 1])
    rmin, rmax = np.abs(a1 - a2), a1 + a2
    return np.minimum(r - rmin, rmax - r), hole, rmin, rmax


def no_sky_reason(target, target_file=None):
    """하늘 보정을 하지 않을 target 이면 그 이유 (문자열), 아니면 None.

    calibration target (파일 이름이나 project 에 CALIB_TAG) 이거나 하늘 좌표가 없는 경우.
    """
    name = os.path.basename(str(target_file or ''))
    project = str(target.get('project', '') or '')
    if CALIB_TAG in name.lower() or CALIB_TAG in project.lower():
        return f"calibration target ('{CALIB_TAG}' in the file name or project: {name or project})"
    missing = [k for k in ('xp', 'yp', 'ra', 'dec') if k not in target]
    if missing:
        return f"no {'/'.join(missing)} in the target (angle target, e.g. a calibration run)"
    ra = np.asarray(target['ra'], float)
    dec = np.asarray(target['dec'], float)
    if ra.size == 0 or not (np.isfinite(ra).all() and np.isfinite(dec).all()):
        return "ra/dec missing or not finite"
    ra0, dec0 = np.radians(field_centre(target))
    ra, dec = np.radians(ra), np.radians(dec)
    cosd = np.sin(dec) * np.sin(dec0) + np.cos(dec) * np.cos(dec0) * np.cos(ra - ra0)
    if np.degrees(np.arccos(np.clip(cosd, -1., 1.))).max() < MIN_SKY_SPREAD_DEG:
        return "all targets at one sky position (no sky coordinates, e.g. a calibration run)"
    return None


def correct_target(target, time=None, precession=True, instrument_offset_deg=0.0,
                   use_measured=None, target_file=None):
    """보정한 target dict 과 요약 (dict) 을 돌려준다. target 은 바꾸지 않는다.

    time : 관측 시각 (UTC; astropy Time 이 받는 값, 또는 '+09:00' 같은 시간대가 붙은 ISO
        문자열). None 이면 지금.
    닿지 않게 된 목표: class 9 (목표 없음) 는 planner 값을 그대로 두고, 나머지는 닿는
    끝까지만 옮기고 요약의 clipped 에 적는다 (그 fiber 는 다시 배정해야 한다).
    calibration target 이나 하늘 좌표가 없는 target (no_sky_reason; target_file 은 이름 검사용)
    은 그대로 돌려주고 요약에 skipped 를 적는다.
    """
    time = obs_time(time or None)
    reason = no_sky_reason(target, target_file)
    if reason is not None:
        return dict(target), {'time_utc': time.utc.isot, 'skipped': reason}
    xp0 = np.asarray(target.get('xp_planner', target['xp']), float)
    yp0 = np.asarray(target.get('yp_planner', target['yp']), float)

    ra0, dec0 = field_centre(target)
    if precession:
        prec, scale = icrs_to_tete_focal(target['ra'], target['dec'], (ra0, dec0), time)
    else:
        prec, scale = 0.0, 1.0
    rot = prec + float(instrument_offset_deg)
    c, s = scale * np.cos(np.radians(rot)), scale * np.sin(np.radians(rot))
    xp, yp = c * xp0 - s * yp0, s * xp0 + c * yp0
    bad = np.isfinite(xp0) & np.isfinite(yp0) & ~(np.isfinite(xp) & np.isfinite(yp))
    if bad.any():
        raise ValueError(f"sky correction gave non-finite targets (rotation {rot}, scale {scale}); "
                         "the target file is not written")

    kept, clipped = [], []
    reach = _reach(xp, yp, use_measured)
    if reach is None:
        log.warning("target 개수 (%d) 가 fiber 표 (%d) 와 달라 도달 검사를 건너뜁니다",
                    len(xp), len(cfg.fiber_ids()))
    else:
        margin, hole, rmin, rmax = reach
        cls = [str(v) for v in target.get('class', [''] * len(xp))]
        ids = cfg.fiber_ids()
        for k in np.flatnonzero(margin < 0):
            if cls[k] == '9':
                xp[k], yp[k] = xp0[k], yp0[k]
                kept.append(ids[k])
                continue
            dx, dy = xp[k] - hole[k, 0], yp[k] - hole[k, 1]
            r = np.hypot(dx, dy)
            lim = rmax[k] - 1e-3 if r > rmax[k] else rmin[k] + 1e-3
            xp[k], yp[k] = hole[k, 0] + dx * lim / r, hole[k, 1] + dy * lim / r
            clipped.append({'fiber': ids[k], 'class': cls[k], 'miss_um': round(float(abs(r - lim)) * 1e3, 1)})

    d = np.hypot(xp - xp0, yp - yp0)
    summary = {
        'time_utc': time.utc.isot,
        'centre_deg': [round(ra0, 6), round(dec0, 6)],
        'precession': bool(precession),
        'precession_deg': round(prec, 5),
        'scale': round(scale, 8),
        'instrument_offset_deg': float(instrument_offset_deg),
        'rotation_deg': round(rot, 5),
        'shift_max_um': round(float(d.max()) * 1e3, 1),
        'kept_class9': kept,
        'clipped': clipped,
    }
    out = dict(target)
    out['xp'], out['yp'] = xp.tolist(), yp.tolist()
    out['xp_planner'], out['yp_planner'] = xp0.tolist(), yp0.tolist()
    out['sky_correction'] = summary
    return out, summary


def corrected_path(target_file):
    """<이름>.json -> <이름>_skycorr.json (이미 보정 파일이면 같은 이름)."""
    stem, ext = os.path.splitext(target_file)
    if stem.endswith(SUFFIX):
        return target_file
    return f'{stem}{SUFFIX}{ext or ".json"}'


def write_corrected_target(target_file, out_file=None, **kwargs):
    """target 파일을 읽어 보정 파일을 쓰고 (경로, 요약) 을 돌려준다. kwargs 는 correct_target 로.

    calibration target 이나 하늘 좌표가 없는 target 이면 파일을 쓰지 않고 (target_file, 요약) 을
    돌려준다 (요약의 skipped).
    """
    with open(target_file, 'r') as f:
        target = json.load(f)
    out, summary = correct_target(target, target_file=target_file, **kwargs)
    if summary.get('skipped'):
        log.info("Sky correction skipped for %s: %s", target_file, summary['skipped'])
        return target_file, summary

    out_file = out_file or corrected_path(target_file)
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(out, f)
    log.info("Sky correction %s -> %s: rotation %.4f deg (precession %.4f + instrument %.4f), "
             "max shift %.0f um, clipped %s", target_file, out_file, summary['rotation_deg'],
             summary['precession_deg'], summary['instrument_offset_deg'],
             summary['shift_max_um'], [c['fiber'] for c in summary['clipped']])
    return out_file, summary
