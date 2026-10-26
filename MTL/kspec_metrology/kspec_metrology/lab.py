"""실험실 시험용 도우미: 목표 파일 만들기, fiber 표 줄이기, 단계별 확인 그림.

실험실에서는 목표가 관측 타일이 아니라 사람이 정한 (x, y) 나 (alpha, beta) 로
주어진다. 이 모듈이 그것을 mtlcal 이 읽는 target 파일(object.info 형식) 로
바꾸고, 꽂힌 positioner 만 남긴 fiber 표를 만들고, 각 단계의 결과를 그림으로
보여 준다. 분석 자체는 analysis/ 의 함수를 그대로 쓴다.

    measure            목표 파일 + 이미지 1-3장 -> fiber 위치 오차와 회전량 (한 번 측정)
    show_steps         measure 의 결과를 단계별 그림으로 (검출 / fiducial 매칭 / fiber 매칭)
    read_targets       object.info 형식(xp, yp 또는 각도) 목표 파일 읽기
    make_target        같은 각도 / 같은 offset / 개별 (x, y) 로 목표 파일 만들기
    check_peaks        이미지 한 장의 peak 검출 점검 (개수, 밝기, 쪼개짐)
    make_fiber_table   꽂힌 홀만 positioner 로 둔 Fiber_Configuration 표
    ab2xy, xy2ab       positioner 각도 <-> 초점면 좌표 (패키지 각도 규약 그대로)
    make_target_file   'ID x y' 또는 'ID alpha beta' 텍스트 -> target json
    inspect_trial      MetrologyRun 의 한 trial 을 단계별 그림으로
    show_image, show_detections, show_matching, show_offsets   확인 그림
"""

import json
import os
import re

import numpy as np
from astropy.io import ascii, fits

from kspec_metrology.analysis import fiber_config as cfg
from kspec_metrology.analysis.utils import find_angle_double_method2_select_elbow
from kspec_metrology.analysis.findpeak import findpeak
from kspec_metrology.analysis.matchfiber import matchfiber
from kspec_metrology.analysis.fitdistortion import fitdistortion
from kspec_metrology.naming import image_path
from kspec_metrology import naming
from kspec_metrology.logging.log import get_logger

PIX_MM = 3.76e-3          # 카메라 화소 크기 [mm]
rtod = 180./np.pi


# ============================================================================ 표와 목표
def make_fiber_table(positioners, out_path, src_table=None, fiducials=None):
    """src_table 에서 positioners 에 적힌 홀만 FiducialFlag 0 으로, fiducials (None 이면
    원래 표의 fiducial 전부) 만 1 로 두고 나머지는 -9 로 바꾼 표를 out_path 에 쓴다
    (config73 표와 같은 고정폭 CDS 형식). 쓴 뒤 KSPEC_FIBER_TABLE 을 이 경로로 두고
    패키지를 import 한다 (표는 import 때 읽는다).
    반환: (positioner 수, fiducial 수)"""
    src_table = src_table or cfg.DEFAULT_FIBER_TABLE_PATH
    pos = [str(p).strip() for p in positioners]
    tab = ascii.read(src_table)
    c = tab.colnames
    ids = [str(v).strip() for v in tab[c[0]]]
    flags = {i: int(f) for i, f in zip(ids, tab[c[3]])}
    unknown = [p for p in pos if p not in flags]
    if unknown:
        raise ValueError(f"holes not in {src_table}: {unknown}")
    fid = set(i for i, f in flags.items() if f == 1) if fiducials is None else set(map(str, fiducials))
    clash = sorted(fid & set(pos))
    if clash:
        raise ValueError(f"listed both as positioner and fiducial: {clash}")
    has_ij = len(c) >= 6
    name = os.path.basename(out_path)
    hdr = ["Title: K-SPEC Fiber Configuration (lab test)",
           f"Authors: made by kspec_metrology.lab.make_fiber_table from {os.path.basename(src_table)}",
           "Table: Fiber Configuration",
           "=" * 80,
           f"Byte-by-byte Description of file: {name}",
           "-" * 80,
           " Bytes Format Units  Label     Explanations",
           "-" * 80,
           " 1- 3  A3     ---    ID           Hole ID",
           " 5-13  F9.4   mm     X            X coordinate",
           "15-23  F9.4   mm     Y            Y coordinate",
           "25-26  I2     ---    FiducialFlag [-9/1] Fiducial flag (1)"]
    if has_ij:
        hdr += ["28-29  I2     ---    Row          Row number (i)",
                "31-32  I2     ---    Column       Column number (j)"]
    hdr += ["-" * 80,
            "Note (1) : Flag as follows :",
            "    0 = Fiber positioner",
            "    1 = Fiducial",
            "    -9 = Neither (positioner not installed)",
            "-" * 80]
    npos = nfid = 0
    rows = []
    for k, hole in enumerate(ids):
        new = 0 if hole in pos else (1 if hole in fid else -9)
        npos += new == 0; nfid += new == 1
        line = f"{hole:<3} {float(tab[c[1]][k]):9.4f} {float(tab[c[2]][k]):9.4f} {new:>2}"
        if has_ij:
            line += f" {int(tab[c[4]][k]):>2} {int(tab[c[5]][k]):>2}"
        rows.append(line)
    with open(out_path, 'w') as ff:
        ff.write('\n'.join(hdr + rows) + '\n')
    return npos, nfid


def ab2xy(xorigin, yorigin, alpha_deg, beta_deg, arm1, arm2):
    """positioner 출력 각도 (alpha, beta) [deg, json 과 같은 부호 규약] -> fiber 끝 (x, y) [mm].
    mtlcal 은 계산각 (theta, phi) 를 부호를 뒤집어 내보내므로 (출력 = -계산각) 여기서 되돌린다."""
    sa, sb = cfg.ANGLE_SIGN
    theta = sa*np.asarray(alpha_deg, float)/rtod          # 부호 x 부호 = 1 이므로 곱해서 되돌린다
    phi = sb*np.asarray(beta_deg, float)/rtod
    if cfg.CLOCKWISE:
        theta, phi = -theta, -phi
    x = xorigin + arm1*np.cos(theta) + arm2*np.cos(theta + phi)
    y = yorigin + arm1*np.sin(theta) + arm2*np.sin(theta + phi)
    return x, y


def xy2ab(xorigin, yorigin, x, y, arm1, arm2):
    """(x, y) [mm] -> 출력 각도 (alpha, beta) [deg]. ab2xy 의 역이고 mtlcal 과 같은 계산이다."""
    x, y = np.atleast_1d(x), np.atleast_1d(y)
    xo, yo = np.broadcast_to(xorigin, x.shape), np.broadcast_to(yorigin, x.shape)
    a1, a2 = np.broadcast_to(arm1, x.shape), np.broadcast_to(arm2, x.shape)
    th = np.empty(x.shape); ph = np.empty(x.shape)
    for i in range(x.size):
        th.flat[i], ph.flat[i] = find_angle_double_method2_select_elbow(
            xo.flat[i], yo.flat[i], x.flat[i], y.flat[i], a1.flat[i], a2.flat[i],
            elbow=cfg.ELBOW, clockwise=cfg.CLOCKWISE)
    sa, sb = cfg.ANGLE_SIGN
    return sa*th*rtod, sb*ph*rtod


def read_spec(path):
    """'ID  v1  v2' 세 칸짜리 텍스트를 {ID: (v1, v2)} 로 읽는다. '#' 뒤는 주석."""
    out = {}
    with open(path) as ff:
        for n, line in enumerate(ff, 1):
            line = line.split('#')[0].strip()
            if not line:
                continue
            p = line.replace(',', ' ').split()
            if len(p) != 3:
                raise ValueError(f"{path}:{n}: 'ID v1 v2' 세 칸이어야 한다: {line!r}")
            if p[0] in out:
                raise ValueError(f"{path}:{n}: {p[0]} 가 중복이다")
            out[p[0]] = (float(p[1]), float(p[2]))
    return out


def make_target_file(spec_path, out_path, kind='xy', tile='lab', use_measured=None,
                     zenith_angle=0.0):
    """목표 텍스트 파일 -> mtlcal 이 읽는 target json (object.info 형식).

    spec_path : 'ID x y' (kind='xy', mm) 또는 'ID alpha beta' (kind='ab', deg; json 과
                같은 부호 규약) 세 칸 텍스트. 표의 positioner 전부가 있어야 한다.
    각도는 positioner 회전 중심(실측값이 켜져 있으면 실측)과 arm 길이로 (x, y) 로 바꾼다.
    반환: (xp, yp) 표 순서."""
    from kspec_metrology.analysis.mtlcal import load_configuration
    spec = read_spec(spec_path)
    ids = list(cfg.fiber_ids())
    missing = [i for i in ids if i not in spec]
    extra = [i for i in spec if i not in ids]
    if missing:
        raise ValueError(f"{spec_path}: positioner {missing} 의 목표가 없다 "
                         f"(표 {cfg.FIBER_TABLE_PATH} 의 positioner 전부가 있어야 한다)")
    if extra:
        raise ValueError(f"{spec_path}: 표에 positioner 로 없는 ID: {extra}")
    v1 = np.array([spec[i][0] for i in ids]); v2 = np.array([spec[i][1] for i in ids])
    if kind == 'xy':
        xp, yp = v1, v2
    elif kind == 'ab':
        # 회전 중심: load_configuration 이 실측/설계를 가려서 준다 (target 은 아직 없으니 더미)
        tmp = out_path + '.tmp'
        json.dump(dict(tile_id=tile, xp=[0.]*len(ids), yp=[0.]*len(ids)), open(tmp, 'w'))
        try:
            xo, yo, _, _, _, nfib = load_configuration(tmp, apply_zenith_offset=False,
                                                       use_measured=use_measured)
        finally:
            os.remove(tmp)
        a1, a2 = cfg.arm_lengths(use_measured)
        xp, yp = ab2xy(xo[:nfib], yo[:nfib], v1, v2, a1, a2)
    else:
        raise ValueError("kind must be 'xy' or 'ab'")
    data = dict(tile_id=tile, inst='', func='lab', ra=[], dec=[],
                xp=[float(v) for v in xp], yp=[float(v) for v in yp],
                zenith_angle=float(zenith_angle))
    with open(out_path, 'w') as ff:
        json.dump(data, ff, indent=1)
    return xp, yp


# ============================================================================ 그림
def _binned(im, n):
    ny, nx = im.shape
    im = im[:ny - ny % n, :nx - nx % n]
    return im.reshape(ny // n, n, nx // n, n).mean(axis=(1, 3))


def load_frames(data_dir, head, nexposure=1):
    """findpeak 과 같은 방향([::-1,:]) 으로 읽어 평균한 이미지."""
    im = None
    for i in range(nexposure):
        f = fits.getdata(image_path(data_dir, head, i)).astype(float)[::-1, :] / nexposure
        im = f if im is None else im + f
    return im


def chip2pix(xchip, ychip, shape):
    """findpeak 의 칩 좌표 [mm] -> 픽셀 (u, v)."""
    ny, nx = shape
    return xchip / PIX_MM + (nx - 1) / 2., ychip / PIX_MM + (ny - 1) / 2.


def show_image(im, n=8, ax=None, title=None, vmax_pct=99.5):
    """n x n 으로 줄인 전체 영상."""
    import matplotlib.pyplot as plt
    small = _binned(im, n)
    if ax is None:
        _, ax = plt.subplots(figsize=(13, 10))
    lo, hi = np.percentile(small, [1, vmax_pct])
    # test_260917.ipynb 와 같은 방향: origin='lower' (v 가 위로 커진다). 이미지는 findpeak 처럼
    # [::-1, :] 로 뒤집어 읽은 것이라 이렇게 그리면 배치표(초점면 x, y)와 바로 견줄 수 있다.
    ax.imshow(small, cmap='gray', vmin=lo, vmax=hi, origin='lower',
              extent=(-.5, small.shape[1]*n - .5, -.5, small.shape[0]*n - .5))
    ax.set_xlabel('u [px]'); ax.set_ylabel('v [px]')
    if title:
        ax.set_title(title)
    return ax


def show_detections(im, xobs, yobs, labels=None, flag=None, n=8, ax=None, title=None, r=60):
    """검출된 spot (findpeak 의 칩 좌표) 을 영상 위에 표시. flag 가 True 인 것은 주황."""
    import matplotlib.pyplot as plt
    ax = show_image(im, n, ax, title)
    u, v = chip2pix(np.asarray(xobs), np.asarray(yobs), im.shape)
    flag = np.zeros(u.size, bool) if flag is None else np.asarray(flag, bool)
    for k in range(u.size):
        c = plt.Circle((u[k], v[k]), r, fc='none', ec='tab:orange' if flag[k] else 'c', lw=0.8)
        ax.add_artist(c)
        if labels is not None:
            ax.text(u[k], v[k] - 1.6*r, str(labels[k]), color='y', fontsize=7, ha='center')
    return ax


def show_matching(x, y, xfocal, yfocal, fid_flag, ids=None, ax=None, ref_um=200.):
    """초점면에서 목표(설계) 와 측정 위치: 화살표 = 측정 - 목표 (과장), fiducial 은 주황."""
    import matplotlib.pyplot as plt
    if ax is None:
        _, ax = plt.subplots(figsize=(9, 8.5))
    dx, dy = xfocal - x, yfocal - y
    k = 12. / (ref_um*1e-3)
    q = None
    for f, c, lab in ((~fid_flag, 'k', 'fiber'), (fid_flag, 'tab:orange', 'fiducial')):
        if f.any():
            q = ax.quiver(x[f], y[f], dx[f]*k, dy[f]*k, angles='xy', scale_units='xy', scale=1, color=c, width=0.004)
        ax.plot(x[f], y[f], 'o', mfc='none', color=c, ms=5, label=lab)
    if q is not None:
        ax.quiverkey(q, 0.85, 1.03, 12., f"{ref_um:.0f} um", labelpos='E')
    if ids is not None:
        for xi, yi, i in zip(x, y, ids):
            ax.text(xi, yi - 3, str(i), fontsize=6, ha='center', va='top')
    ax.set_aspect('equal'); ax.set_xlabel('x [mm]'); ax.set_ylabel('y [mm]'); ax.legend(loc='lower left')
    ax.set_title('measured - target (arrows exaggerated)')
    return ax


def show_offsets(offset_file, ax=None):
    """mtlcal 이 저장한 _offset.txt 를 막대로."""
    import matplotlib.pyplot as plt
    ids = np.loadtxt(offset_file, usecols=0, dtype=str)
    d = np.loadtxt(offset_file, usecols=(1, 2, 3, 4), ndmin=2)
    if ax is None:
        _, ax = plt.subplots(2, 1, figsize=(max(8, 0.25*len(ids)), 7), sharex=True)
    k = np.arange(len(ids))
    ax[0].bar(k - 0.2, d[:, 0], 0.4, label='dx'); ax[0].bar(k + 0.2, d[:, 1], 0.4, label='dy')
    ax[0].set_ylabel('position error [um]'); ax[0].legend(); ax[0].axhline(0, c='gray', lw=.5)
    ax[1].bar(k - 0.2, d[:, 2], 0.4, label='dalpha'); ax[1].bar(k + 0.2, d[:, 3], 0.4, label='dbeta')
    ax[1].set_ylabel('rotation to apply [deg]'); ax[1].legend(); ax[1].axhline(0, c='gray', lw=.5)
    ax[1].set_xticks(k); ax[1].set_xticklabels(ids, rotation=90, fontsize=7)
    return ax


# ============================================================================ 단계별 확인
def _all_ids():
    """load_configuration 과 같은 순서의 홀 ID (fiber 표 순서 + fiducial)."""
    return list(cfg.fiber_ids()) + [i for i, f in zip(_table_ids(), _table_flags())
                                   if f == 1 and i not in cfg.FIDUCIAL_EXCLUDE]


def _inspect(data_dir, head, fid_heads, target_file, nexposure=1, fid_nexposure=None, mode='Raw',
             threshold=3e3, nwindow=40, niter_recenter=0, finder='sep', finder_opts=None,
             background='crop', background_opts=None, magnification=None, model='full',
             sat_level=65000., fid_min_peak=0., n_extra=0, use_measured=None,
             apply_pinhole_offset=False, cross_exclude=True, min_dist=40, fid_fallback_fiber=True, n=8,
             leftover=None):
    """mtlcal 과 같은 설정으로 단계별로 다시 분석하며 그림을 그린다. json 은 건드리지 않는다.
    leftover: dict 를 주면 fiber 목표에 할당되지 않은 검출을 채워 준다 (measure_fibers 참고; 노출 분리 때만)."""
    from kspec_metrology.analysis.mtlcal import (load_configuration, measure_fiducials,
                                                 measure_fibers)
    xo, yo, x, y, fid_flag, nfib = load_configuration(
        target_file, apply_pinhole_offset=apply_pinhole_offset, use_measured=use_measured)
    ids = _all_ids()
    # 끊어진 fiber 는 빼고 본다 (mtlcal 과 같다)
    dead = np.r_[cfg.dead_mask(), np.zeros(x.size-nfib, dtype=bool)]
    x, y, fid_flag = x[~dead], y[~dead], fid_flag[~dead]
    ids = [i for i, d in zip(ids, dead) if not d]
    nfib = int((~dead[:nfib]).sum())
    n_extra = n_extra + len(cfg.FIBER_FIXED) + len(cfg.SKY_FIBERS)   # 켜져 있지만 무시하는 점 (mtlcal 과 같다)
    pk = dict(threshold=threshold, nwindow=nwindow, niter_recenter=niter_recenter, finder=finder,
              finder_opts=finder_opts, background=background, background_opts=background_opts,
              min_dist=min_dist)
    fid_nexposure = nexposure if fid_nexposure is None else fid_nexposure
    im = load_frames(data_dir, head, nexposure)
    if fid_heads:
        heads_all = list(fid_heads) + ([head] if fid_fallback_fiber else [])
        nexp_all = [fid_nexposure]*len(fid_heads) + ([nexposure] if fid_fallback_fiber else [])
        fb_all = [False]*len(fid_heads) + ([True] if fid_fallback_fiber else [])
        xo_f, yo_f, choice, th, (ox, oy) = measure_fiducials(
            heads_all, x, y, fid_flag, data_dir, fid_nexposure, set_nexposure=nexp_all, fallback=fb_all,
            m_init=magnification, sat_level=sat_level, fid_min_peak=fid_min_peak, n_extra=n_extra, **pk)
        fid_ids = [i for i, f in zip(ids, fid_flag) if f]
        for k, h in enumerate(heads_all):
            imf = load_frames(data_dir, h, nexp_all[k])
            show_detections(imf, xo_f, yo_f, labels=fid_ids, flag=(choice != k), n=n,
                            title=f'fiducial set {k} ({h}): cyan = used from this set, orange = taken from another set')
        xf, yf, _, _, coeff = fitdistortion(
            x[fid_flag], y[fid_flag], np.ones(int(fid_flag.sum()), bool), xo_f, yo_f,
            np.arange(int(fid_flag.sum())), th, ox, oy, model=model, m_init=magnification)
        xfocal, yfocal, dist, (xobs, yobs) = measure_fibers(
            head, x, y, nfib, coeff, data_dir, nexposure, n_extra=n_extra,
            exclude=(xo_f, yo_f) if cross_exclude else None, leftover=leftover, **pk)
        if cross_exclude:                       # fiber 자리를 지우고 fiducial 을 다시 (mtlcal 과 같다)
            xo_f, yo_f, choice, th, (ox, oy) = measure_fiducials(
                heads_all, x, y, fid_flag, data_dir, fid_nexposure, set_nexposure=nexp_all, fallback=fb_all,
                m_init=magnification, sat_level=sat_level, fid_min_peak=fid_min_peak, n_extra=n_extra,
                exclude=(xobs[:nfib], yobs[:nfib]), **pk)
            xf, yf, _, _, coeff = fitdistortion(
                x[fid_flag], y[fid_flag], np.ones(int(fid_flag.sum()), bool), xo_f, yo_f,
                np.arange(int(fid_flag.sum())), th, ox, oy, model=model, m_init=magnification)
            xfocal, yfocal, dist, (xobs, yobs) = measure_fibers(
                head, x, y, nfib, coeff, data_dir, nexposure, n_extra=n_extra,
                exclude=(xo_f, yo_f), leftover=leftover, **pk)
        xfocal[fid_flag], yfocal[fid_flag] = xf, yf
        # fiber 는 fiber 노출의 매칭 결과, fiducial 은 fiducial 노출에서 잰 자리(주황; 이 이미지에서는 쓰지 않음)
        show_detections(im, np.r_[xobs[:nfib], xo_f], np.r_[yobs[:nfib], yo_f], labels=ids, flag=fid_flag, n=n,
                        title=f'fiber image ({head}): cyan = matched fibers, orange = fiducial positions from the fiducial exposure')
    else:
        npk = x.size if (mode != 'Raw' or n_extra == 0) else (x.size, x.size + n_extra)
        _, xobs, yobs, peak, nsat = findpeak(npk, data_dir=data_dir, head=head, nexposure=nexposure,
                                             mode=mode, x=x, y=y, sat_level=sat_level,
                                             ReturnNsat=True, **pk)
        imatch, th, (ox, oy) = matchfiber(x, y, xobs, yobs, m_init=magnification)
        xfocal, yfocal, _, _, coeff = fitdistortion(x, y, fid_flag, xobs, yobs, imatch, th, ox, oy,
                                                    model=model, m_init=magnification)
        show_detections(im, xobs[imatch], yobs[imatch], labels=ids, flag=fid_flag, n=n,
                        title=f'{head}: matched peaks (orange = fiducial); saturated: {int((nsat[imatch] > 0).sum())}')
    show_matching(x, y, xfocal, yfocal, fid_flag, ids)
    r_fid = np.hypot(xfocal - x, yfocal - y)[fid_flag]*1e3
    r_fib = np.hypot(xfocal - x, yfocal - y)[~fid_flag]*1e3
    print(f"fiducial fit residual: rms {np.sqrt((r_fid**2).mean()):.1f} um, max {r_fid.max():.1f} um   |   "
          f"fiber - target: median {np.median(r_fib):.1f} um, max {r_fib.max():.1f} um")
    return dict(x=x, y=y, fid_flag=fid_flag, xfocal=xfocal, yfocal=yfocal, coeff=coeff, ids=ids)


def inspect_trial(run, itrial, n=8):
    """MetrologyRun 이 분석한 trial 을 같은 설정으로 단계별로 다시 돌려 그림으로 보여 준다."""
    return _inspect(run.data_dir, run.image_head(itrial), run.fid_image_heads(itrial), run.target_file,
                    nexposure=run.nexposure, fid_nexposure=run.fid_nexposure, mode=run.mode,
                    threshold=run.threshold, nwindow=run.nwindow, niter_recenter=run.niter_recenter,
                    finder=run.finder, finder_opts=run.finder_opts, background=run.background,
                    background_opts=run.background_opts, magnification=run.magnification,
                    model=run.model, sat_level=run.sat_level, fid_min_peak=run.fid_min_peak,
                    n_extra=run.n_extra, use_measured=run.use_measured,
                    apply_pinhole_offset=run.apply_pinhole_offset, n=n)


# ============================================================================ 목표 파일 만들기
def make_target(out_path, angles=None, offset=None, xy=None, tile='lab', use_measured=None):
    """target 파일(object.info 형식) 을 만든다. 셋 중 하나를 준다.
        angles=(alpha, beta)  모든 positioner 를 같은 각도로 [deg, json 부호 규약]
        offset=(dx, dy)       모든 fiber 끝을 각자의 회전 중심에서 같은 (dx, dy) 만큼 [mm]
        xy=(xp, yp)           positioner 마다 다른 목표 [mm] (표 순서)
    각도 파일은 'alpha'/'beta' 키로 저장되어 read_targets 가 그대로 읽는다.
    반환: 저장한 dict."""
    ids = list(cfg.fiber_ids()); n = len(ids)
    if angles is not None:
        data = dict(tile_id=tile, alpha=[float(angles[0])]*n, beta=[float(angles[1])]*n)
    elif offset is not None:
        from kspec_metrology.analysis.mtlcal import load_configuration
        tmp = out_path + '.tmp'
        json.dump(dict(tile_id=tile, xp=[0.]*n, yp=[0.]*n), open(tmp, 'w'))
        try:
            xo, yo, _, _, _, nfib = load_configuration(tmp, apply_zenith_offset=False, use_measured=use_measured)
        finally:
            os.remove(tmp)
        data = dict(tile_id=tile, xp=[float(v) for v in xo[:nfib] + offset[0]],
                    yp=[float(v) for v in yo[:nfib] + offset[1]])
    elif xy is not None:
        xp, yp = np.asarray(xy[0], float), np.asarray(xy[1], float)
        if xp.size != n or yp.size != n:
            raise ValueError(f"xy must have {n} entries (table order {ids})")
        data = dict(tile_id=tile, xp=[float(v) for v in xp], yp=[float(v) for v in yp])
    else:
        raise ValueError("give angles=(alpha, beta), offset=(dx, dy) or xy=(xp, yp)")
    with open(out_path, 'w') as ff:
        json.dump(data, ff, indent=1)
    return data


# ============================================================================ 검출 점검
def check_peaks(fits_path, threshold=3e3, min_dist=40, finder='sep', finder_opts=None, background='crop',
                nwindow=40, exclude=None, exclude_r=60, n=8, crop=60, show_crops=24):
    """이미지 한 장에서 peak 검출만 해 보고 (findpeak 과 같은 길), 개수·밝기·서로 가까운 쌍을
    표와 그림으로 보여 준다. 한 spot 이 여러 peak 으로 쪼개지는지, threshold 가 맞는지,
    min_dist / finder_opts 를 어떻게 잡을지 정할 때 쓴다.

    문턱값 탐색 없이 threshold 그대로 한 번 돌린다.
    반환: pandas DataFrame(u, v, peak, nearest_px) -- nearest_px 는 가장 가까운 다른 검출까지 거리."""
    import matplotlib.pyplot as plt
    import pandas as pd
    from scipy.spatial import cKDTree
    d = os.path.dirname(os.path.abspath(fits_path))
    base = os.path.basename(fits_path)
    if not base.endswith('0.fits'):
        raise ValueError("파일 이름이 ...0.fits 로 끝나야 한다 (findpeak 의 이름 규칙)")
    head = base[:-len('0.fits')]
    im, xo, yo, pk = findpeak((1, 100000), data_dir=d, head=head, nexposure=1, threshold=threshold,
                              niter_max=1, min_dist=min_dist, finder=finder, finder_opts=finder_opts,
                              background=background, nwindow=nwindow, exclude=exclude, exclude_r=exclude_r)
    u, v = chip2pix(xo, yo, im.shape)
    dd = cKDTree(np.c_[u, v]).query(np.c_[u, v], k=2)[0][:, 1] if u.size > 1 else np.full(u.size, np.nan)
    T = pd.DataFrame(dict(u=u, v=v, peak=pk, nearest_px=dd)).sort_values('peak', ascending=False).reset_index(drop=True)
    close = T[T.nearest_px < 3*min_dist]
    print(f"{base}: {len(T)} peaks at threshold {threshold:.0f} (min_dist {min_dist} px); "
          f"peak {T.peak.min():.0f}..{T.peak.max():.0f}; {len(close)} within {3*min_dist} px of another peak "
          f"({'split spots?' if len(close) else 'ok'})")
    show_detections(im, xo, yo, flag=(dd < 3*min_dist), n=n, r=max(60, min_dist),
                    title=f'{base}: {len(T)} peaks (orange = closer than {3*min_dist} px to another)')
    k = min(show_crops, len(T))
    if k:
        ncol = 8; nrow = int(np.ceil(k/ncol))
        fig, axs = plt.subplots(nrow, ncol, figsize=(2.2*ncol, 2.3*nrow), squeeze=False)
        order = np.argsort(T.nearest_px.values)[:k]            # 가까운 쌍부터
        for a, i in zip(axs.ravel(), order):
            uu, vv = int(round(T.u[i])), int(round(T.v[i]))
            sub = im[max(vv-crop, 0):vv+crop+1, max(uu-crop, 0):uu+crop+1]
            a.imshow(np.log10(np.clip(sub - np.median(sub), 3, None)), cmap='inferno', origin='lower')
            a.set_title(f'peak {T.peak[i]:.0f}  near {T.nearest_px[i]:.0f}px', fontsize=7); a.set_xticks([]); a.set_yticks([])
        for a in axs.ravel()[k:]:
            a.axis('off')
        fig.tight_layout()
    return T



# ============================================================================ fiducial 밝기 점검
def fiducial_positions(use_measured=None):
    """표의 fiducial ID 와 초점면 위치 [mm] (측정 때와 같은 load_configuration 경로)."""
    import tempfile
    from kspec_metrology.analysis.mtlcal import load_configuration
    n = len(cfg.fiber_ids())
    with tempfile.NamedTemporaryFile('w', suffix='.info', delete=False) as f:
        json.dump(dict(tile_id='lab', xp=[0.]*n, yp=[0.]*n), f)
    try:
        _, _, x, y, fid_flag, nfib = load_configuration(f.name, apply_zenith_offset=False, use_measured=use_measured)
    finally:
        os.remove(f.name)
    ids = _all_ids()
    return [i for i, fl in zip(ids, fid_flag) if fl], x[fid_flag], y[fid_flag]


def _affine_fit(xo, yo, x, y):
    """칩 (xo, yo) -> 초점면 (x, y) 1차 변환 (최소제곱). 반환: (x, y) 를 내는 함수."""
    A = np.column_stack((xo, yo, np.ones(xo.size)))
    cx, _, _, _ = np.linalg.lstsq(A, x, rcond=None)
    cy, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
    return lambda u, v: (cx[0]*u + cx[1]*v + cx[2], cy[0]*u + cy[1]*v + cy[2])


def match_fiducials(xo, yo, magnification=None, tol=1.5, use_measured=None, target_file=None):
    """검출(칩 좌표) 에서 fiducial 을 찾아 ID 를 붙인다. 검출에 fiber 등 다른 점이 섞여 있어도,
    fiducial 일부가 안 보여도 된다 (measure_fiducials 의 세트별 매칭과 같은 방법).

    matchfiber 의 배율·회전·offset 으로 옮긴 검출이 설계 위치에서 tol [mm] 안이면 "찾았다" 고 보고,
    찾은 쌍으로 1차(affine) 변환을 최소제곱으로 다시 맞춰 예측 위치 근처의 검출을 다시 붙인다
    (찾은 수가 늘지 않을 때까지). 한 검출은 한 fiducial 에만.
    target_file : fiber 가 같이 찍힌 이미지면 object.info 를 준다. fiber 목표까지 넣은 전체 패턴으로
                  매칭한다 -- fiber 와 fiducial 이 같은 격자에 있어 fiducial 30개만으로는 회전이
                  정해지지 않는다 (measure_fiducials 와 같다).
    반환: ids(fiducial ID 목록), idx(검출 번호, 못 찾으면 -1), resid [mm] (못 찾으면 NaN)."""
    from scipy.spatial import cKDTree
    from kspec_metrology.analysis.utils import transform
    from kspec_metrology.analysis.mtlcal import camera2focal_coeff
    ids, xf, yf = fiducial_positions(use_measured)
    xo, yo = np.asarray(xo, float), np.asarray(yo, float)
    nfid = len(ids)
    idx = np.full(nfid, -1); resid = np.full(nfid, np.nan)
    if xo.size < 4:
        return ids, idx, resid
    if target_file is not None and xo.size > nfid:
        from kspec_metrology.analysis.mtlcal import load_configuration
        _, _, xa, ya, fa, _ = load_configuration(target_file, apply_zenith_offset=False, use_measured=use_measured)
        xa, ya = xa[~np.r_[cfg.dead_mask(), np.zeros(xa.size - len(cfg.fiber_ids()), bool)]], \
                 ya[~np.r_[cfg.dead_mask(), np.zeros(ya.size - len(cfg.fiber_ids()), bool)]]
        _, theta, (xoff, yoff) = matchfiber(xa, ya, xo, yo, m_init=magnification)
    else:
        if xo.size > 1.5*nfid:
            get_logger().warning("match_fiducials: %d detections for %d fiducials -- fiber 가 같이 찍혔으면 "
                                 "target_file 을 주어야 회전이 바로 잡힌다", xo.size, nfid)
        _, theta, (xoff, yoff) = matchfiber(xf, yf, xo, yo, m_init=magnification)
    coeff_s = np.copy(camera2focal_coeff); coeff_s[0] = magnification or coeff_s[0]
    coeff_s[1], coeff_s[2], coeff_s[3] = theta, xoff, yoff        # 왜곡 항은 기본 계수 그대로 (matchfiber 와 같은 변환)
    xs, ys = transform(xo, yo, coeff_s)

    def assign(px, py):
        """예측 초점면 위치 (px, py) 의 검출을 fiducial 마다 tol 안 가장 가까운 것으로, 중복 없이."""
        d, j = cKDTree(np.column_stack((px, py))).query(np.column_stack((xf, yf)))
        found = d < tol
        for jj in np.unique(j[found]):
            same = np.where(found & (j == jj))[0]
            if same.size > 1:
                found[same] = False; found[same[np.argmin(d[same])]] = True
        return j, d, found

    j, d, found = assign(xs, ys)
    for _ in range(8):
        if found.sum() < 3:
            break
        z = xo[j[found]] + 1j*yo[j[found]]; w = xf[found] + 1j*yf[found]
        A = np.column_stack((z, np.conj(z), np.ones(z.size)))
        M = np.vstack([np.column_stack([A.real, -A.imag]), np.column_stack([A.imag, A.real])])
        c, *_ = np.linalg.lstsq(M, np.r_[w.real, w.imag], rcond=None)
        cc = c[:3] + 1j*c[3:]
        p = np.column_stack((xo + 1j*yo, xo - 1j*yo, np.ones(xo.size))) @ cc
        j2, d2, found2 = assign(p.real, p.imag)
        if found2.sum() < found.sum():
            break
        improved = found2.sum() > found.sum()
        j, d, found = j2, d2, found2
        if not improved:
            break
    idx[found] = j[found]; resid[found] = d[found]
    return ids, idx, resid


def fiducial_brightness(fits_path, threshold=1e3, min_dist=80, finder='sep', finder_opts=None,
                        nwindow=40, magnification=None, groups=None, sat_level=65000.,
                        use_measured=None, target_file=None, n=8, crop=60, show=True):
    """fiducial 밝기 조정용: 이미지 한 장에서 peak 을 찾아 fiducial ID 를 붙이고, 그림 위에
    ID 와 peak 값을 적고, 표로 돌려준다.

    groups : {'그룹이름': ['A7', 'B1', ...]} 처럼 fiducial 밝기 그룹. 주면 그룹별 색과 요약표.
    target_file : fiber 도 같이 찍힌 이미지면 object.info (전체 패턴으로 매칭). fiducial 만 찍혔으면 None.
    표 열: id (fiducial ID, fiducial 이 아니면 '?'), group, peak (창 안 최대 화소 [ADU, 배경 포함]),
           flux (배경을 뺀 창 안 합 [ADU]), nsat (포화 화소 수), resid_mm (매칭 잔차), u, v [px].
    peak 이 sat_level 에 닿은 fiducial 은 포화라 위치가 틀어진다; flux 는 포화돼도 대략 비교가 된다.
    반환: (DataFrame, 그룹 요약 DataFrame 또는 None)."""
    import matplotlib.pyplot as plt
    import pandas as pd
    d = os.path.dirname(os.path.abspath(fits_path)); base = os.path.basename(fits_path)
    if not base.endswith('0.fits'):
        raise ValueError("파일 이름이 ...0.fits 로 끝나야 한다 (findpeak 의 이름 규칙)")
    head = base[:-len('0.fits')]
    im, xo, yo, _ = findpeak((1, 100000), data_dir=d, head=head, nexposure=1, threshold=threshold,
                             niter_max=1, min_dist=min_dist, finder=finder, finder_opts=finder_opts,
                             background='crop', nwindow=nwindow)
    u, v = chip2pix(xo, yo, im.shape)
    ny, nx = im.shape
    peak = np.zeros(u.size); flux = np.zeros(u.size); nsat = np.zeros(u.size, int)
    for k in range(u.size):
        i0, j0 = int(round(u[k])), int(round(v[k]))
        sub = im[max(j0-nwindow, 0):j0+nwindow+1, max(i0-nwindow, 0):i0+nwindow+1]
        ring = im[max(j0-2*nwindow, 0):j0+2*nwindow+1, max(i0-2*nwindow, 0):i0+2*nwindow+1]
        bg = np.median(ring)
        peak[k] = sub.max(); flux[k] = (sub - bg).sum(); nsat[k] = int((sub >= sat_level).sum())
    ids, idx, resid = match_fiducials(xo, yo, magnification=magnification, use_measured=use_measured,
                                      target_file=target_file)
    label = np.array(['?']*u.size, dtype=object); res_col = np.full(u.size, np.nan)
    for i, j in enumerate(idx):
        if j >= 0:
            label[j] = ids[i]; res_col[j] = resid[i]
    gname = {}
    if groups:
        for g, members in groups.items():
            for m in members:
                gname[str(m)] = str(g)
    grp = np.array([gname.get(l, '' if l == '?' else '-') for l in label], dtype=object)
    T = pd.DataFrame(dict(id=label, group=grp, peak=peak, flux=flux, nsat=nsat, resid_mm=res_col*1e0, u=u, v=v))
    T = pd.concat([T[T.id != '?'].sort_values(['group', 'id']), T[T.id == '?'].sort_values('peak', ascending=False)]).reset_index(drop=True)
    nfound = int((idx >= 0).sum()); missing = [i for i, j in zip(ids, idx) if j < 0]
    print(f"{base}: {u.size} peaks (threshold {threshold:.0f}); fiducials matched {nfound}/{len(ids)}"
          + (f", not found: {', '.join(missing)}" if missing else '')
          + f"; saturated (>= {sat_level:.0f}): {int(((T.id != '?') & (T.nsat > 0)).sum())}")
    summary = None
    if groups:
        F = T[T.id != '?']
        summary = F.groupby('group').agg(n=('id', 'size'), peak_min=('peak', 'min'), peak_median=('peak', 'median'),
                                         peak_max=('peak', 'max'), flux_median=('flux', 'median'),
                                         n_sat=('nsat', lambda s: int((s > 0).sum())))
    if show:
        colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
        gkeys = list(groups.keys()) if groups else []
        ax = show_image(im, n, title=f'{base}: fiducial peaks (label = ID: peak ADU; red ring = saturated)')
        for _, r in T.iterrows():
            is_fid = r.id != '?'
            c = 'red' if (is_fid and r.nsat > 0) else (colors[gkeys.index(r.group) % len(colors)] if r.group in gkeys else ('c' if is_fid else 'gray'))
            ax.add_artist(plt.Circle((r.u, r.v), max(60, min_dist), fc='none', ec=c, lw=1.0 if is_fid else 0.5))
            if is_fid:
                ax.text(r.u, r.v + 1.6*max(60, min_dist), f'{r.id}: {r.peak:.0f}', color=c, fontsize=8, ha='center', va='bottom',
                        bbox=dict(fc='k', ec='none', alpha=0.5, pad=1))
        if gkeys:
            for g, c in zip(gkeys, colors):
                ax.plot([], [], 'o', mfc='none', color=c, label=g)
            ax.legend(loc='upper right', fontsize=8)
        F = T[T.id != '?']
        k = len(F)
        if k:
            ncol = 10; nrow = int(np.ceil(k/ncol))
            fig, axs = plt.subplots(nrow, ncol, figsize=(1.9*ncol, 2.1*nrow), squeeze=False)
            for a, (_, r) in zip(axs.ravel(), F.iterrows()):
                uu, vv = int(round(r.u)), int(round(r.v))
                sub = im[max(vv-crop, 0):vv+crop+1, max(uu-crop, 0):uu+crop+1]
                a.imshow(sub, cmap='inferno', origin='lower', vmin=np.median(sub), vmax=sat_level)
                a.set_title(f'{r.id} {r.group if r.group not in ("-", "") else ""}\n{r.peak:.0f}' + (' SAT' if r.nsat else ''),
                            fontsize=7, color='red' if r.nsat else 'k')
                a.set_xticks([]); a.set_yticks([])
            for a in axs.ravel()[k:]:
                a.axis('off')
            fig.suptitle(f'{base}: fiducial crops (same colour scale, white = {sat_level:.0f})', fontsize=9)
            fig.tight_layout()
    return T, summary


def _match_pattern(xt, yt, xo, yo, magnification=None, tol=1.5):
    """설계 패턴 (xt, yt) 와 검출 (xo, yo; 칩 좌표) 을 짝짓는다 (match_fiducials 의 본체).
    tol 은 스칼라 또는 목표별 배열 [mm]. 반환: idx (목표별 검출 번호, 못 찾으면 -1), resid [mm]."""
    from scipy.spatial import cKDTree
    from kspec_metrology.analysis.utils import transform
    from kspec_metrology.analysis.mtlcal import camera2focal_coeff
    xt, yt = np.asarray(xt, float), np.asarray(yt, float)
    xo, yo = np.asarray(xo, float), np.asarray(yo, float)
    tol = np.broadcast_to(np.asarray(tol, float), xt.shape)
    idx = np.full(xt.size, -1); resid = np.full(xt.size, np.nan)
    if xo.size < 4 or xt.size < 4:
        return idx, resid
    _, theta, (xoff, yoff) = matchfiber(xt, yt, xo, yo, m_init=magnification)
    coeff_s = np.copy(camera2focal_coeff); coeff_s[0] = magnification or coeff_s[0]
    coeff_s[1], coeff_s[2], coeff_s[3] = theta, xoff, yoff        # 왜곡 항은 기본 계수 그대로 (matchfiber 와 같은 변환)
    xs, ys = transform(xo, yo, coeff_s)

    def assign(px, py):
        d, j = cKDTree(np.column_stack((px, py))).query(np.column_stack((xt, yt)))
        found = d < tol
        for jj in np.unique(j[found]):
            same = np.where(found & (j == jj))[0]
            if same.size > 1:
                found[same] = False; found[same[np.argmin(d[same])]] = True
        return j, d, found

    j, d, found = assign(xs, ys)
    for _ in range(8):
        if found.sum() < 3:
            break
        z = xo[j[found]] + 1j*yo[j[found]]; w = xt[found] + 1j*yt[found]
        A = np.column_stack((z, np.conj(z), np.ones(z.size)))
        M = np.vstack([np.column_stack([A.real, -A.imag]), np.column_stack([A.imag, A.real])])
        c, *_ = np.linalg.lstsq(M, np.r_[w.real, w.imag], rcond=None)
        cc = c[:3] + 1j*c[3:]
        pz = np.column_stack((xo + 1j*yo, xo - 1j*yo, np.ones(xo.size))) @ cc
        j2, d2, found2 = assign(pz.real, pz.imag)
        if found2.sum() < found.sum():
            break
        improved = found2.sum() > found.sum()
        j, d, found = j2, d2, found2
        if not improved:
            break
    idx[found] = j[found]; resid[found] = d[found]
    return idx, resid


def _measure_spots(im, u, v, nwindow, sat_level):
    """검출마다 창 안 최대 화소(peak, 배경 포함), 배경 뺀 합(flux), 포화 화소 수."""
    peak = np.zeros(u.size); flux = np.zeros(u.size); nsat = np.zeros(u.size, int)
    for k in range(u.size):
        i0, j0 = int(round(u[k])), int(round(v[k]))
        sub = im[max(j0-nwindow, 0):j0+nwindow+1, max(i0-nwindow, 0):i0+nwindow+1]
        ring = im[max(j0-2*nwindow, 0):j0+2*nwindow+1, max(i0-2*nwindow, 0):i0+2*nwindow+1]
        bg = np.median(ring)
        peak[k] = sub.max(); flux[k] = (sub - bg).sum(); nsat[k] = int((sub >= sat_level).sum())
    return peak, flux, nsat


def spot_brightness(fits_path, target_file, threshold=1e3, min_dist=80, finder='sep', finder_opts=None,
                    nwindow=40, magnification=None, sat_level=65000., groups=None, fid_tol=1.5, fib_tol=3.0,
                    use_measured=None, n=8, show=True):
    """fiber 와 fiducial 을 모두 켜고 찍은 한 장에서 peak 을 찾아 종류별(fiducial / fiber / sky·고정 / 기타)로
    밝기를 나눠 본다. 노출시간을 정할 때 쓴다.

    target_file : object.info (xp/yp 또는 각도). 살아 있는 fiber 목표 + fiducial 전체 패턴으로 매칭한다.
                  끊어진 fiber(FIBER_EXCLUDE) 는 기대하지 않고, 고정된 positioner(FIBER_FIXED) 와
                  sky fiber(SKY_FIBERS) 는 그 홀의 arm 범위 안에서 목표에 안 붙은 검출을 그것으로 본다.
    fid_tol, fib_tol : 매칭 허용 거리 [mm] (fiber 는 positioner 오차만큼 크게).
    반환: (T, summary, missing)
      T       : 검출별 표 — id, kind, group(fiducial 그룹), peak(창 안 최대, 배경 포함), flux(배경 뺀 합),
                nsat(포화 화소 수), resid_mm, u, v
      summary : kind 별 기대 수·찾은 수·peak 최소/중앙/최대·포화 수
      missing : {'fiducial': [...], 'fiber': [...]} 기대했는데 못 찾은 ID"""
    import matplotlib.pyplot as plt
    import pandas as pd
    from scipy.spatial import cKDTree
    from kspec_metrology.analysis.mtlcal import load_configuration
    from kspec_metrology.analysis.utils import transform
    groups = groups if groups is not None else cfg.FIDUCIAL_GROUPS
    d = os.path.dirname(os.path.abspath(fits_path)); base = os.path.basename(fits_path)
    if not base.endswith('0.fits'):
        raise ValueError("파일 이름이 ...0.fits 로 끝나야 한다 (findpeak 의 이름 규칙)")
    head = base[:-len('0.fits')]
    im, xo, yo, _ = findpeak((1, 100000), data_dir=d, head=head, nexposure=1, threshold=threshold,
                             niter_max=1, min_dist=min_dist, finder=finder, finder_opts=finder_opts,
                             background='crop', nwindow=nwindow)
    u, v = chip2pix(xo, yo, im.shape)
    peak, flux, nsat = _measure_spots(im, u, v, nwindow, sat_level)

    # 목표 패턴: 살아 있는 fiber + fiducial
    xp, yp, kind_t = read_targets(target_file)
    tf = target_file
    if kind_t == 'ab':
        import tempfile
        a1, a2 = cfg.arm_lengths(use_measured)
        with tempfile.NamedTemporaryFile('w', suffix='.info', delete=False) as f:
            json.dump(dict(tile_id='lab', xp=[0.]*xp.size, yp=[0.]*yp.size), f)
        try:
            xo0, yo0, _, _, _, nfib0 = load_configuration(f.name, apply_zenith_offset=False, use_measured=use_measured)
        finally:
            os.remove(f.name)
        xq, yq = ab2xy(xo0[:nfib0], yo0[:nfib0], xp, yp, a1, a2)
        with tempfile.NamedTemporaryFile('w', suffix='.info', delete=False) as f:
            json.dump(dict(tile_id='lab', xp=[float(q) for q in xq], yp=[float(q) for q in yq]), f); tf = f.name
    _, _, x, y, fid_flag, nfib = load_configuration(tf, apply_zenith_offset=False, use_measured=use_measured)
    if tf != target_file:
        os.remove(tf)
    ids = _all_ids()
    dead = np.r_[cfg.dead_mask(), np.zeros(x.size - nfib, bool)]
    xt, yt, ft = x[~dead], y[~dead], fid_flag[~dead]; ids_t = [i for i, dd in zip(ids, dead) if not dd]
    idx, resid = _match_pattern(xt, yt, xo, yo, magnification=magnification, tol=np.where(ft, fid_tol, fib_tol))

    label = np.array(['?']*u.size, dtype=object); kind = np.array(['other']*u.size, dtype=object)
    res_col = np.full(u.size, np.nan)
    for i, j in enumerate(idx):
        if j >= 0:
            label[j] = ids_t[i]; kind[j] = 'fiducial' if ft[i] else 'fiber'; res_col[j] = resid[i]
    # 목표에 안 붙은 검출 가운데 고정/sky 홀의 arm 범위 안이면 그것으로
    holes = cfg.lit_unmatched_holes()
    if len(holes) and (kind == 'other').any():
        f = idx >= 0
        if f.sum() >= 3:
            z = xo[idx[f]] + 1j*yo[idx[f]]; w = xt[f] + 1j*yt[f]
            A = np.column_stack((z, np.conj(z), np.ones(z.size)))
            M = np.vstack([np.column_stack([A.real, -A.imag]), np.column_stack([A.imag, A.real])])
            c, *_ = np.linalg.lstsq(M, np.r_[w.real, w.imag], rcond=None); cc = c[:3] + 1j*c[3:]
            pz = np.column_stack((xo + 1j*yo, xo - 1j*yo, np.ones(xo.size))) @ cc
            a1, a2 = cfg.arm_lengths(); reach = float((a1 + a2).max()) + 1.0
            hx = np.array([h[0] for h in holes]) if not isinstance(holes, np.ndarray) else holes[:, 0]
            hy = np.array([h[1] for h in holes]) if not isinstance(holes, np.ndarray) else holes[:, 1]
            dh, _ = cKDTree(np.column_stack((hx, hy))).query(np.column_stack((pz.real, pz.imag)))
            kind[(kind == 'other') & (dh < reach)] = 'sky/fixed'
    gname = {m: g for g, members in groups.items() for m in members} if groups else {}
    grp = np.array([gname.get(l, '') for l in label], dtype=object)
    near = np.array(['']*u.size, dtype=object)
    f = idx >= 0
    if f.sum() >= 3:                                   # 안 붙은 검출: 가장 가까운 살아 있는 fiber 목표와 거리
        z = xo[idx[f]] + 1j*yo[idx[f]]; w = xt[f] + 1j*yt[f]
        A = np.column_stack((z, np.conj(z), np.ones(z.size)))
        M = np.vstack([np.column_stack([A.real, -A.imag]), np.column_stack([A.imag, A.real])])
        c, *_ = np.linalg.lstsq(M, np.r_[w.real, w.imag], rcond=None); cc = c[:3] + 1j*c[3:]
        pz = np.column_stack((xo + 1j*yo, xo - 1j*yo, np.ones(xo.size))) @ cc
        dn, jn = cKDTree(np.column_stack((xt[~ft], yt[~ft]))).query(np.column_stack((pz.real, pz.imag)))
        fib_ids = [i for i, flag in zip(ids_t, ft) if not flag]
        for k in np.where(kind == 'other')[0]:
            near[k] = f'{fib_ids[jn[k]]} {dn[k]:.1f} mm'
    T = pd.DataFrame(dict(id=label, kind=kind, group=grp, peak=peak, flux=flux, nsat=nsat, resid_mm=res_col, u=u, v=v,
                          nearest_fiber=near))
    order = {'fiducial': 0, 'fiber': 1, 'sky/fixed': 2, 'other': 3}
    T['_o'] = T.kind.map(order); T = T.sort_values(['_o', 'group', 'id']).drop(columns='_o').reset_index(drop=True)

    n_exp = {'fiducial': int(ft.sum()), 'fiber': int((~ft).sum()),
             'sky/fixed': len(cfg.FIBER_FIXED) + len(cfg.SKY_FIBERS), 'other': 0}
    rows = []
    for k in order:
        F = T[T.kind == k]
        rows.append(dict(kind=k, expected=n_exp[k], found=len(F),
                         peak_min=F.peak.min() if len(F) else np.nan, peak_median=F.peak.median() if len(F) else np.nan,
                         peak_max=F.peak.max() if len(F) else np.nan, flux_median=F.flux.median() if len(F) else np.nan,
                         n_sat=int((F.nsat > 0).sum())))
    summary = pd.DataFrame(rows).set_index('kind')
    missing = {'fiducial': [ids_t[i] for i in range(len(ids_t)) if ft[i] and idx[i] < 0],
               'fiber': [ids_t[i] for i in range(len(ids_t)) if not ft[i] and idx[i] < 0]}
    print(f"{base}: {u.size} peaks (threshold {threshold:.0f}); broken (not expected): {list(cfg.FIBER_EXCLUDE) or '-'}; "
          f"fixed: {list(cfg.FIBER_FIXED) or '-'}; sky: {len(cfg.SKY_FIBERS)}")
    for k in ('fiducial', 'fiber'):
        r = summary.loc[k]
        print(f"  {k:9s}: {int(r.found)}/{int(r.expected)} found, {int(r.n_sat)} saturated, peak {r.peak_min:.0f}..{r.peak_max:.0f} (median {r.peak_median:.0f})"
              + (f"; missing: {', '.join(missing[k])}" if missing[k] else ''))
    print(f"  sky/fixed: {int(summary.loc['sky/fixed'].found)}/{n_exp['sky/fixed']}; other: {int(summary.loc['other'].found)}"
          + (" (" + "; ".join(f"peak {r.peak:.0f} near {r.nearest_fiber}" for _, r in T[T.kind == 'other'].iterrows()) + ")"
             if (T.kind == 'other').any() else ''))
    # 노출 제안: 가장 밝은 것이 포화 수준의 절반쯤 오도록 (포화된 것은 실제 peak 을 모르므로 상한만)
    for k in ('fiducial', 'fiber'):
        F = T[T.kind == k]
        if not len(F):
            continue
        if (F.nsat > 0).any():
            print(f"  {k}: {int((F.nsat > 0).sum())} saturated -> exposure must drop by more than x{0.5*sat_level/F.peak.max():.2f} "
                  f"(true peak unknown); for a split exposure measure the fiducial frame separately")
        else:
            print(f"  {k}: brightest {F.peak.max():.0f} -> x{0.5*sat_level/F.peak.max():.2f} brings it to 50 % of saturation; "
                  f"dimmest {F.peak.min():.0f} = {F.peak.min()/threshold:.1f} x threshold")
    if show:
        colors = {'fiducial': 'tab:orange', 'fiber': 'c', 'sky/fixed': 'm', 'other': 'gray'}
        ax = show_image(im, n, title=f'{base}: orange = fiducial, cyan = fiber, magenta = sky/fixed, gray = other; red ring = saturated')
        r0 = max(60, min_dist)
        for _, r in T.iterrows():
            c = 'red' if r.nsat > 0 else colors[r.kind]
            ax.add_artist(plt.Circle((r.u, r.v), r0, fc='none', ec=c, lw=1.0 if r.kind != 'other' else 0.6))
            if r.kind in ('fiducial', 'fiber'):
                ax.text(r.u, r.v + 1.6*r0, f'{r.id}:{r.peak:.0f}', color=colors[r.kind], fontsize=6, ha='center', va='bottom',
                        bbox=dict(fc='k', ec='none', alpha=0.4, pad=0.5))
        fig, axs = plt.subplots(2, 1, figsize=(14, 7))
        for a, k in zip(axs, ('fiducial', 'fiber')):
            F = T[T.kind == k].sort_values('peak')
            a.bar(range(len(F)), F.peak, color=colors[k], edgecolor=['red' if s_ > 0 else 'none' for s_ in F.nsat], linewidth=1.2)
            a.axhline(sat_level, color='red', ls='--', lw=0.8); a.axhline(threshold, color='gray', ls=':', lw=0.8)
            a.set_yscale('log'); a.set_ylim(max(50., threshold/5.), sat_level*1.6)
            a.set_xticks(range(len(F))); a.set_xticklabels(F.id, rotation=90, fontsize=7); a.set_ylabel('peak [ADU]')
            a.set_title(f"{k}: {len(F)}/{n_exp[k]} found, {int((F.nsat > 0).sum())} saturated (red edge); missing: {', '.join(missing[k]) or 'none'}", fontsize=9)
        fig.tight_layout()
    return T, summary, missing


def plot_group_brightness(T, groups=None, sat_level=65000., threshold=None, ax=None, title=None):
    """fiducial_brightness 의 표 T 로 그룹별 peak 막대 그림. 포화 수준·검출 문턱 선 포함.
    못 찾은 fiducial(그룹에는 있는데 표에 없음) 은 빈 자리로 표시한다."""
    import matplotlib.pyplot as plt
    groups = groups if groups is not None else cfg.FIDUCIAL_GROUPS
    F = T[T.id != '?'].set_index('id')
    if ax is None:
        _, ax = plt.subplots(figsize=(14, 4))
    colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    pos = 0; ticks = []; labels = []
    for gi, (g, members) in enumerate(groups.items()):
        c = colors[gi % len(colors)]
        vals = [F.peak.get(m, np.nan) for m in members]
        for m, v in zip(members, vals):
            if np.isfinite(v):
                ax.bar(pos, v, color=c, edgecolor='red' if F.nsat.get(m, 0) > 0 else 'none', linewidth=1.5)
            else:
                ax.text(pos, 1.2*(threshold or 100), 'x', ha='center', color='gray', fontsize=8)
            ticks.append(pos); labels.append(m); pos += 1
        found = int(np.isfinite(vals).sum())
        ax.text(pos - len(members)/2. - 0.5, sat_level*1.15, f'{g} ({found}/{len(members)})', ha='center', color=c, fontsize=9)
        pos += 1
    ax.axhline(sat_level, color='red', ls='--', lw=0.8); ax.text(pos, sat_level, ' saturation', color='red', fontsize=7, va='center')
    if threshold:
        ax.axhline(threshold, color='gray', ls=':', lw=0.8); ax.text(pos, threshold, ' threshold', color='gray', fontsize=7, va='center')
    ax.set_yscale('log'); ax.set_ylim(max(50., (threshold or 100)/5.), sat_level*1.6)
    ax.set_xticks(ticks); ax.set_xticklabels(labels, rotation=90, fontsize=8); ax.set_ylabel('peak [ADU]')
    ax.set_title(title or 'fiducial peak by group (red edge = saturated, x = not detected)')
    return ax


def compare_brightness(results, groups=None, sat_level=65000., threshold=None, show=True):
    """여러 이미지(조정 전후, 노출별) 의 fiducial peak 을 한 표로: 행 = fiducial, 열 = 이미지 이름.
    results : {'이름': T} (fiducial_brightness 의 표). show 면 fiducial 마다 peak 의 변화를 그룹 색으로 그린다."""
    import matplotlib.pyplot as plt
    import pandas as pd
    groups = groups if groups is not None else cfg.FIDUCIAL_GROUPS
    cmp = pd.DataFrame({k: T[T.id != '?'].set_index('id').peak for k, T in results.items()})
    order = [m for members in groups.values() for m in members]
    cmp = cmp.reindex([m for m in order if m in cmp.index] + [i for i in cmp.index if i not in order])
    cmp.insert(0, 'group', [next((g for g, m in groups.items() if i in m), '') for i in cmp.index])
    if show and len(results) > 1:
        colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
        _, ax = plt.subplots(figsize=(max(6, 1.6*len(results) + 4), 4.5))
        names = list(results)
        for gi, (g, members) in enumerate(groups.items()):
            for k, m in enumerate(members):
                if m in cmp.index:
                    ax.plot(range(len(names)), cmp.loc[m, names].values, '-o', color=colors[gi % len(colors)], ms=3, lw=0.8,
                            label=g if k == 0 else None)
        ax.axhline(sat_level, color='red', ls='--', lw=0.8)
        if threshold:
            ax.axhline(threshold, color='gray', ls=':', lw=0.8)
        ax.set_yscale('log'); ax.set_xticks(range(len(names))); ax.set_xticklabels(names, rotation=20, fontsize=8, ha='right')
        ax.set_ylabel('peak [ADU]'); ax.legend(fontsize=8); ax.set_title('fiducial peak per image (one line per fiducial)')
    return cmp


# ============================================================================ 한 번 측정
def read_targets(path):
    """목표 파일 -> (xp, yp, kind). object.info 와 같은 json 이고 셋 중 하나를 담는다.
        {"xp": [...], "yp": [...]}            초점면 목표 [mm]            (kind 'xy')
        {"alpha": [...], "beta": [...]}       positioner 각도 [deg]      (kind 'ab')
        {"C4_a": .., "C4_b": .., ...}         각도 json (mtlcal 출력 형식) (kind 'ab')
    배열은 fiber 표의 positioner 순서여야 한다. 각도는 json 과 같은 부호 규약."""
    data = json.load(open(path))
    low = {str(k).lower(): v for k, v in data.items()}
    ids = list(cfg.fiber_ids())
    if 'xp' in low and 'yp' in low:
        xp, yp, kind = np.asarray(low['xp'], float), np.asarray(low['yp'], float), 'xy'
    elif 'alpha' in low and 'beta' in low:
        xp, yp, kind = np.asarray(low['alpha'], float), np.asarray(low['beta'], float), 'ab'
    elif all(f"{i}_a" in data and f"{i}_b" in data for i in ids):
        xp = np.array([data[f"{i}_a"] for i in ids], float)
        yp = np.array([data[f"{i}_b"] for i in ids], float)
        kind = 'ab'
    else:
        raise ValueError(f"{path}: 'xp'/'yp', 'alpha'/'beta', 또는 '{{ID}}_a'/'{{ID}}_b' 키가 필요하다")
    if xp.size != len(ids) or yp.size != len(ids):
        raise ValueError(f"{path}: 값이 {xp.size}/{yp.size} 개인데 표의 positioner 는 {len(ids)} 개다 "
                         f"({cfg.FIBER_TABLE_PATH})")
    return xp, yp, kind


def next_trial(out_dir, tile):
    """out_dir 에 있는 {tile}_MetrologyTrial_{k}.json 중 가장 큰 k + 1 (없으면 1)."""
    k = 0
    for f in os.listdir(out_dir) if os.path.isdir(out_dir) else []:
        m = re.fullmatch(re.escape(tile) + r'_MetrologyTrial_(\d+)\.json', f)
        if m:
            k = max(k, int(m.group(1)))
    return k + 1


def measure(target_file, fiber_image, fid_images=(), out_dir='./lab_out', tile='lab', itrial=None,
            magnification=None, model='full', nwindow=40, threshold=3e3, niter_recenter=0,
            finder='sep', finder_opts=None, background='crop', background_opts=None,
            sat_level=65000., fid_min_peak=0., n_extra=0, use_measured=None, mode='Raw',
            cross_exclude=True, min_dist=40, fid_fallback_fiber=True):
    """한 배치를 한 번 잰다: 목표 파일과 이미지 1-3장 -> fiber 위치 오차와 positioner 회전량.

    target_file : object.info 형식 (read_targets 참고; xp/yp 또는 각도)
    fiber_image : fiber 가 찍힌 FITS 경로 (fiducial 도 같이 찍혔으면 이것 한 장으로 충분)
    fid_images  : fiducial 전용 노출 FITS 경로 0-2 개. 비면 fiber_image 에서 fiducial 도 찾고,
                  하나면 그것으로, 둘이면 fiducial 마다 포화되지 않은 밝은 쪽을 쓴다.
    itrial      : 몇 번째 측정인지. None 이면 out_dir 에 있는 json 다음 번호 (처음이면 1).
                  누적 각도 = 직전 trial json + 이번 회전량 이므로, positioner 를 옮기고 다시
                  찍은 이미지로 같은 out_dir/tile 로 부르면 각도가 누적된다. trial 0 json
                  (목표 각도) 은 처음 부를 때 함께 만든다.
    나머지 인자는 mtlcal 과 같다. 이미지는 out_dir/data 에 패키지 이름 규칙으로 링크(복사)되고
    결과는 out_dir 에 {tile}_MetrologyTrial_{itrial}.json (누적 각도) 과 _offset.txt 로 남는다.

    반환 dict: itrial, ids, dx, dy [mm] (fiber + fiducial, 측정 - 목표), angle_rot (deg, fiber
    순서로 alpha, beta 번갈아), angle_cum, json, offsets, 그리고 show_steps 에 넘길 설정."""
    import shutil
    out_dir = os.path.abspath(out_dir)
    data_dir = os.path.join(out_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    if itrial is None:
        itrial = next_trial(out_dir, tile)

    # 목표: 각도면 (x, y) 로 바꿔 표준 target json 으로 저장
    xp, yp, kind = read_targets(target_file)
    if kind == 'ab':
        from kspec_metrology.analysis.mtlcal import load_configuration
        tmp = os.path.join(out_dir, '_tmp_target.json')
        json.dump(dict(tile_id=tile, xp=[0.]*xp.size, yp=[0.]*yp.size), open(tmp, 'w'))
        try:
            xo, yo, _, _, _, nfib = load_configuration(tmp, apply_zenith_offset=False,
                                                       use_measured=use_measured)
        finally:
            os.remove(tmp)
        a1, a2 = cfg.arm_lengths(use_measured)
        xp, yp = ab2xy(xo[:nfib], yo[:nfib], xp, yp, a1, a2)
    tfile = os.path.join(out_dir, f'{tile}_target.info')
    json.dump(dict(tile_id=tile, func='lab', xp=[float(v) for v in xp], yp=[float(v) for v in yp],
                   zenith_angle=0.0), open(tfile, 'w'), indent=1)

    def place(src, dst):
        if os.path.lexists(dst):
            os.remove(dst)
        try:
            os.symlink(os.path.abspath(src), dst)
        except OSError:
            shutil.copy2(src, dst)

    if itrial == 1:
        from kspec_metrology.analysis.mtlcal import save_initial_angles, save_angles
        if kind == 'ab':
            # 각도로 준 목표는 그 값 그대로 trial 0 으로 (xy 로 갔다 오면 -330 처럼 360 도 돌아간 값이 된다)
            a = np.empty(2*xp.size); a[0::2], a[1::2] = read_targets(target_file)[:2]
            save_angles(out_dir, tile, 0, a)
        else:
            save_initial_angles(out_dir, tile, tfile, use_measured=use_measured)   # trial 0 = 목표 각도
    head = naming.image_head(tile, itrial)
    place(fiber_image, image_path(data_dir, head, 0))
    fid_heads = []
    for k, f in enumerate(fid_images or ()):
        h = naming.fid_image_head(tile, itrial, k)
        place(f, image_path(data_dir, h, 0))
        fid_heads.append(h)

    from kspec_metrology.analysis.mtlcal import mtlcal
    params = dict(mode=mode, threshold=threshold, nwindow=nwindow, niter_recenter=niter_recenter,
                  finder=finder, finder_opts=finder_opts, background=background,
                  background_opts=background_opts, magnification=magnification, model=model,
                  sat_level=sat_level, fid_min_peak=fid_min_peak, n_extra=n_extra,
                  use_measured=use_measured, cross_exclude=cross_exclude, min_dist=min_dist,
                  fid_fallback_fiber=fid_fallback_fiber)
    dx, dy, angle_rot, angle_cum = mtlcal(data_dir=data_dir, head=head, nexposure=1,
                                          fid_head=fid_heads or None, target_file=tfile,
                                          json_dir=out_dir, target_name=tile, itrial=itrial, **params)
    return dict(itrial=itrial, ids=_all_ids(), nfib=xp.size, dx=dx, dy=dy, angle_rot=angle_rot, angle_cum=angle_cum,
                json=naming.json_path(out_dir, tile, itrial), offsets=naming.offset_path(out_dir, tile, itrial),
                data_dir=data_dir, head=head, fid_heads=fid_heads, target_file=tfile, params=params)


def show_steps(res, n=8):
    """measure 의 결과를 단계별 그림으로: fiducial 검출(세트별), fiber 매칭, 초점면 잔차."""
    return _inspect(res['data_dir'], res['head'], res['fid_heads'], res['target_file'], n=n, **res['params'])


def find_fixed_spots(res, out_path=None, show=False):
    """고정 positioner(FIBER_FIXED) 와 sky fiber(SKY_FIBERS) 의 실제 자리를 재서 Fixed_Spots.txt 형식으로 적는다.

    measure 의 결과 res 와 같은 설정으로 다시 분석해, 살아 있는 fiber 목표에 할당되지 않은 검출을
    고정/sky 홀에 (홀 중심에서 arm 길이 안, 거리 합 최소로) 배정한다. 고정 positioner 와 sky fiber 는
    움직이지 않으므로 한 번 적어 두면 이후 매칭에서 그 자리(반지름 FIXED_SPOT_TOL = 1.5 mm)의 검출은
    바로 빠지고, 살아 있는 fiber 가 목표에서 몇 mm 벗어나 있어도 고정 점과 헷갈리지 않는다.

    out_path : 적을 파일. 패키지 기본 경로는 cfg.FIXED_SPOTS_PATH (analysis/Fixed_Spots.txt);
               다른 곳에 두면 KSPEC_FIXED_SPOTS 환경변수로 가리킨다. None 이면 적지 않는다.
    반환 DataFrame: hole, x_mm, y_mm (초점면), hole_dist_mm (홀 중심에서 거리), u, v (픽셀), status
      status = 'found' (파일에 적음) / 'not found' (범위 안에 남은 검출이 없음) / 'extra' (어느 홀에도 못 붙은 검출)"""
    import pandas as pd
    import matplotlib.pyplot as plt
    from scipy.optimize import linear_sum_assignment
    if not res.get('fid_heads'):
        raise ValueError("find_fixed_spots 는 fiducial 노출을 따로 준 측정(fid_images)에서만 쓸 수 있다")
    lo = {}
    _inspect(res['data_dir'], res['head'], res['fid_heads'], res['target_file'], n=8, leftover=lo, **res['params'])
    if not show:
        plt.close('all')
    names = list(cfg.FIBER_FIXED) + list(cfg.SKY_FIBERS)
    rows = []
    if names and lo.get('xf') is not None and lo['xf'].size:
        hx = cfg.hole_xy(names)
        a1, a2 = cfg.arm_lengths(); reach = float((a1 + a2).max()) + 1.0
        D = np.hypot(hx[:, 0][:, None] - lo['xf'][None, :], hx[:, 1][:, None] - lo['yf'][None, :])
        C = np.where(D > reach, 1e6 + D, D)
        ri, ci = linear_sum_assignment(C)
        got = {}
        for i, k in zip(ri, ci):
            if D[i, k] <= reach:
                got[i] = k
        for i, h in enumerate(names):
            if i in got:
                k = got[i]
                u, v = chip2pix(np.array([lo['xobs'][k]]), np.array([lo['yobs'][k]]), load_frames(res['data_dir'], res['head'], 1).shape)
                rows.append(dict(hole=h, x_mm=float(lo['xf'][k]), y_mm=float(lo['yf'][k]), hole_dist_mm=float(D[i, k]),
                                 u=float(u[0]), v=float(v[0]), status='found'))
            else:
                rows.append(dict(hole=h, x_mm=np.nan, y_mm=np.nan, hole_dist_mm=np.nan, u=np.nan, v=np.nan, status='not found'))
        for k in range(lo['xf'].size):
            if k not in got.values():
                rows.append(dict(hole='?', x_mm=float(lo['xf'][k]), y_mm=float(lo['yf'][k]), hole_dist_mm=float(D[:, k].min()),
                                 u=np.nan, v=np.nan, status='extra'))
    else:
        rows = [dict(hole=h, x_mm=np.nan, y_mm=np.nan, hole_dist_mm=np.nan, u=np.nan, v=np.nan, status='not found') for h in names]
    T = pd.DataFrame(rows, columns=['hole', 'x_mm', 'y_mm', 'hole_dist_mm', 'u', 'v', 'status'])
    nf = int((T.status == 'found').sum()); nn = int((T.status == 'not found').sum()); ne = int((T.status == 'extra').sum())
    print(f"fixed/sky spots: {nf}/{len(names)} found, {nn} not found" + (f": {', '.join(T.hole[T.status == 'not found'])}" if nn else '')
          + (f"; {ne} extra detection(s) not near any fixed/sky hole" if ne else ''))
    if out_path is not None:
        with open(out_path, 'w') as f:
            f.write("# 켜져 있지만 fiber 매칭에서 뺄 점들의 초점면 좌표 [mm] (plate 중심 기준).\n"
                    f"# lab.find_fixed_spots 가 적음: {os.path.basename(res['head'])} (trial {res['itrial']}), "
                    f"{len(cfg.FIBER_FIXED)} fixed positioner(s) + {len(cfg.SKY_FIBERS)} sky fiber(s)\n"
                    "# 'name X Y' 세 칸, '#' 뒤는 주석. 이 거리(FIXED_SPOT_TOL = 1.5 mm) 안의 검출은 fiber 후보에서 뺀다.\n"
                    "# positioner 를 갈거나 다시 움직이게 되면 그 줄을 지우고 FIBER_FIXED 에서도 뺀다.\n"
                    "#\n# name     X          Y\n")
            for _, r in T[T.status == 'found'].iterrows():
                f.write(f"{r.hole:<6} {r.x_mm:10.4f} {r.y_mm:10.4f}\n")
            for _, r in T[T.status == 'not found'].iterrows():
                f.write(f"# {r.hole:<6} not found in this image\n")
        print(f"written: {out_path}")
    return T


def history(out_dir, tile):
    """out_dir 의 trial 별 offset 표를 읽어 fiber 오차의 최대/중앙값 [um] 표로 (pandas DataFrame)."""
    import pandas as pd
    rows = []
    for k in range(1, next_trial(out_dir, tile)):
        f = naming.offset_path(out_dir, tile, k)
        if not os.path.exists(f):
            continue
        d = np.loadtxt(f, usecols=(1, 2), ndmin=2)
        r = np.hypot(d[:, 0], d[:, 1]); r = r[np.isfinite(r)]
        rows.append(dict(trial=k, err_max_um=r.max(), err_median_um=np.median(r),
                         json=os.path.basename(naming.json_path(out_dir, tile, k))))
    return pd.DataFrame(rows).set_index('trial')


def offsets_table(res):
    """measure 결과를 fiber 별 표(pandas 가 있으면 DataFrame, 없으면 리스트)로."""
    nfib = res['nfib']
    rows = [(i, res['dx'][k]*1e3, res['dy'][k]*1e3, res['angle_rot'][2*k], res['angle_rot'][2*k+1],
             res['angle_cum'][2*k], res['angle_cum'][2*k+1])
            for k, i in enumerate(res['ids'][:nfib])]
    cols = ('ID', 'dx_um', 'dy_um', 'dalpha_deg', 'dbeta_deg', 'alpha_deg', 'beta_deg')
    try:
        import pandas as pd
        return pd.DataFrame(rows, columns=cols).set_index('ID')
    except ImportError:
        return [dict(zip(cols, r)) for r in rows]


def _table_ids():
    tab = ascii.read(cfg.FIBER_TABLE_PATH)
    return [str(v).strip() for v in tab[tab.colnames[0]]]


def _table_flags():
    tab = ascii.read(cfg.FIBER_TABLE_PATH)
    return [int(v) for v in tab[tab.colnames[3]]]
