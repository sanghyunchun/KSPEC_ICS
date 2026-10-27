"""positioner 회전 중심과 arm 길이 측정: alpha(또는 beta) arm 을 돌리며 찍은 이미지들의 궤적.

    from kspec_metrology.analysis.armcal import arm_calibration, fit_arms

    res = arm_calibration(fiber_images, fid_images=None, ...)   # 이미지 여러 장 -> positioner 마다 원
    res.table                 # id, x0, y0 (회전 중심 [mm]), R (반지름), rms, n (쓴 점 수)

원리: beta 를 고정하고 alpha 를 한 바퀴 돌리면 fiber 끝은 positioner 회전 중심을 중심으로
반지름 R = |a1 + a2 e^{i phi}| 인 원을 그린다. 원의 중심이 곧 회전 중심이다.
    beta = 0 (phi = 0)   : R = a1 + a2
    beta = 180           : R = |a2 - a1|
두 beta 에서 잰 R 로 a1, a2 를 따로 구한다 (fit_arms). 반대로 alpha 를 고정하고 beta 를
돌리면 팔꿈치를 중심으로 반지름 a2 인 원이 나온다.

이미지마다 (1) peak 을 찾고 (2) fiducial 로 camera -> focal 변환을 맞춘 뒤 (3) 검출을
초점면으로 옮겨 (4) 각 positioner 중심에서 arm 길이 안에 있는 점을 그 positioner 의
궤적 점으로 모은다. fiducial 이 매 이미지에 같이 찍혀 있으면 이미지마다 변환을 새로
맞추고 (카메라가 흘러가도 됨), 없으면 fid_images (한 벌) 로 맞춘 변환을 모든 이미지에 쓴다.
"""
import os
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

from kspec_metrology.analysis import fiber_config as cfg
from kspec_metrology.analysis.findpeak import findpeak
from kspec_metrology.analysis.fitdistortion import fitdistortion
from kspec_metrology.analysis.mtlcal import (load_configuration, measure_fiducials, measure_fiducials_ref,
                                             fit_fiducials)
from kspec_metrology.analysis.utils import transform
from kspec_metrology.logging.log import get_logger


def circle_fit(x, y, robust=True):
    """점들에 원을 맞춘다. 반환: (x0, y0, R, rms, inlier mask).
    대수적 해를 초기값으로 기하학적 최소제곱(soft_l1)을 한 번 더 돈다."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    A = np.column_stack((2*x, 2*y, np.ones(x.size)))
    c = np.linalg.lstsq(A, x*x + y*y, rcond=None)[0]
    p0 = np.r_[c[0], c[1], np.sqrt(max(c[2] + c[0]**2 + c[1]**2, 1e-12))]
    f = lambda p: np.hypot(x - p[0], y - p[1]) - p[2]
    sol = least_squares(f, p0, loss='soft_l1' if robust else 'linear', f_scale=0.05)
    r = f(sol.x)
    inl = np.abs(r) < max(3*1.4826*np.median(np.abs(r)), 0.02)
    if robust and inl.sum() >= 3 and inl.sum() < x.size:
        sol = least_squares(lambda p: (np.hypot(x[inl] - p[0], y[inl] - p[1]) - p[2]), sol.x)
        r = f(sol.x)
    return sol.x[0], sol.x[1], sol.x[2], float(np.sqrt(np.mean(r[inl]**2))), inl


@dataclass
class ArmCalResult:
    ids: list
    centres: np.ndarray            # (n, 2) 설계(또는 실측) 회전 중심
    points: dict                   # id -> (N, 2) 궤적 점 [mm]
    frames: dict                   # id -> 점이 나온 이미지 번호
    table: object = None           # pandas DataFrame
    log: list = field(default_factory=list)


def scan_sets(pattern):
    """take_exposure.py 세트 촬영 (--fiber/--fid) 으로 찍은 scan 영상을 (fiber, [fiducial ...]) 목록으로.

    pattern 은 세트 이름의 앞부분 glob (예: '/data/scan_b0/alpha_*'). 각 세트는
    {stem}_fib_{ms}ms_0.fits 한 장과 {stem}_fid1_*_0.fits, {stem}_fid2_*_0.fits (0-2 장) 으로 이루어진다.
    이름 순으로 정렬한다 (이름에 각도를 넣으면 alpha 순).
    """
    import glob, re
    fibs = sorted(glob.glob(pattern + '_fib_*ms_0.fits'))
    if not fibs:
        raise FileNotFoundError(f"no scan fiber images match {pattern}_fib_*ms_0.fits")
    out = []
    for f in fibs:
        stem = re.sub(r'_fib_[^_]+ms_0\.fits$', '', f)
        fids = sorted(glob.glob(stem + '_fid[0-9]_*ms_0.fits'))
        out.append((f, fids))
    return out


def _detect_focal(fiber_image, fid_images, target_file, nfib_expect, n_extra, magnification, model,
                  ref=None, **pk):
    """이미지 한 장(+ fiducial 이미지들)에서 검출을 초점면 좌표로.

    fiducial 은 본 metrology (mtlcal) 와 같은 방법으로 찾는다: fiducial 전용 노출(들) + fiber 노출을 세트로
    보고 fiducial 마다 포화되지 않은 가장 밝은 세트를 쓴다. ref ((nfid, 2) 칩 좌표) 가 있으면 그 주변에서만
    찾고 (직전 프레임의 fiducial 자리; scan 중 카메라는 고정), 없으면 패턴 매칭.
    반환: (xf, yf, peak, xorigin, yorigin, fid_chip (nfid, 2))."""
    log = get_logger()
    xo, yo, x, y, fid_flag, nfib = load_configuration(target_file, apply_zenith_offset=False)
    dead = np.r_[cfg.dead_mask(), np.zeros(x.size - nfib, bool)]
    xa, ya, fa = x[~dead], y[~dead], fid_flag[~dead]
    d, b = os.path.dirname(os.path.abspath(fiber_image)), os.path.basename(fiber_image)
    head = b[:-len('0.fits')]
    fid_heads, fid_dirs = [], []
    for f in (fid_images or []):
        fid_heads.append(os.path.basename(f)[:-len('0.fits')])
    fid_dir = os.path.dirname(os.path.abspath(fid_images[0])) if fid_images else d
    if fid_dir != d and fid_images:
        raise ValueError("fiducial 이미지와 fiber 이미지는 같은 폴더에 있어야 한다 (findpeak 의 경로 규칙)")
    heads = fid_heads + [head]
    nfid = int(fa.sum())
    fb = [False]*len(fid_heads) + [True]
    xf_d, yf_d = xa[fa], ya[fa]
    got = None
    if ref is not None:
        got = measure_fiducials_ref(heads, xf_d, yf_d, ref, d, 1, nfib_expect, set_nexposure=[1]*len(heads),
                                    n_extra=n_extra, fallback=fb, **pk)
    if got is not None:
        xo_f, yo_f, _ = got
        ok = np.isfinite(xo_f)
        from kspec_metrology.analysis.matchfiber import matchfiber
        _, th, off = matchfiber(xf_d[ok], yf_d[ok], xo_f[ok], yo_f[ok], m_init=magnification)
    else:
        xo_f, yo_f, choice, th, off = measure_fiducials(
            heads, xa, ya, fa, d, 1, set_nexposure=[1]*len(heads), n_extra=n_extra + nfib_expect,
            m_init=magnification, fallback=fb, **pk)
    _, _, coeff, used = fit_fiducials(xf_d, yf_d, xo_f, yo_f, th, off[0], off[1], model, magnification)
    xo_f = np.where(used, xo_f, np.nan); yo_f = np.where(used, yo_f, np.nan)
    _, xobs, yobs, peak = findpeak((1, nfid + nfib_expect + n_extra + 50), data_dir=d, head=head,
                                   nexposure=1, exclude=(xo_f[used], yo_f[used]), **pk)
    xf, yf = transform(xobs, yobs, coeff)
    return xf, yf, peak, xo[:nfib], yo[:nfib], np.column_stack((xo_f, yo_f))


def arm_calibration(fiber_images, fid_images=None, target_file=None, reach=None, magnification=None,
                    model='radial+affine', n_extra=0, min_points=5, **pk):
    """alpha(또는 beta)를 돌리며 찍은 이미지들로 positioner 마다 궤적 원을 맞춘다.

    fiber_images : 궤적 이미지들 (각각 ...0.fits), 또는 scan_sets() 가 돌려주는 [(fiber, [fid, ...]), ...]
                   (alpha 단계마다 take_exposure.py --fiber 30 --fid 1 10 으로 찍은 세트; 본 metrology 와 같은
                   방식으로 fiducial 을 노출별로 고른다 -- 권장).
    fid_images   : fiber_images 가 경로 목록일 때, 모든 프레임에 같이 쓸 fiducial 전용 노출 (같은 폴더).
                   None 이면 각 fiber 이미지의 fiducial 만 쓴다 (포화되어 있으면 수십 um 틀어진다).
    target_file  : 더미 target (각도 아무 값). None 이면 모두 0 으로 만든다.
    reach        : positioner 중심에서 이 거리 [mm] 안의 검출을 그 positioner 의 점으로 본다.
                   None 이면 a1 + a2 + 1.
    pk           : findpeak 인자 (threshold, nwindow, min_dist, finder_opts, background ...)

    반환: ArmCalResult (table: id, x0, y0, R, rms, n, dx, dy = 설계 중심과의 차이 [mm])"""
    fiber_images = list(fiber_images)
    if not fiber_images:
        raise ValueError('arm_calibration: no scan images given (fiber_images is empty)')
    if isinstance(fiber_images[0], (tuple, list)):                 # scan_sets() 형식: 프레임마다 fiducial 세트
        sets = [(f, list(fd)) for f, fd in fiber_images]
    else:
        sets = [(f, list(fid_images or [])) for f in fiber_images]
    fiber_images = [f for f, _ in sets]

    import json, tempfile
    import pandas as pd
    log = get_logger()
    ids = list(cfg.fiber_ids())
    a1, a2 = cfg.arm_lengths()
    reach = (a1 + a2).max() + 1.0 if reach is None else reach
    if target_file is None:
        tmp = tempfile.NamedTemporaryFile('w', suffix='.info', delete=False)
        json.dump(dict(tile_id='armcal', alpha=[0.]*len(ids), beta=[0.]*len(ids)), tmp); tmp.close()
        target_file = tmp.name
    dead = cfg.dead_mask()
    pts = {i: [] for i in ids}; frm = {i: [] for i in ids}
    centres = None
    ref = None                                                     # 직전 프레임의 fiducial 칩 좌표
    for k, (img, fids) in enumerate(sets):
        xf, yf, peak, xo, yo, ref = _detect_focal(img, fids, target_file, int((~dead).sum()), n_extra,
                                                  magnification, model, ref=ref, **pk)
        centres = np.column_stack((xo, yo))
        tree = cKDTree(np.column_stack((xf, yf)))
        for i, (cx, cy), dd in zip(ids, centres, dead):
            if dd:
                continue                                  # 끊어진 fiber: 궤적이 없다
            near = tree.query_ball_point((cx, cy), reach)
            if not near:
                continue
            # 중심에 가장 가까운 것 하나 (이웃 positioner 의 fiber 는 보통 더 멀다)
            j = min(near, key=lambda q: np.hypot(xf[q] - cx, yf[q] - cy))
            pts[i].append((xf[j], yf[j])); frm[i].append(k)
        log.info("frame %d (%s): %d detections, points assigned to %d positioners", k, os.path.basename(img),
                 xf.size, sum(1 for i in ids if frm[i] and frm[i][-1] == k))
    rows = []
    for i, (cx, cy) in zip(ids, centres):
        P = np.array(pts[i])
        if P.shape[0] < min_points:
            rows.append(dict(id=i, x0=np.nan, y0=np.nan, R=np.nan, rms=np.nan, n=P.shape[0], dx=np.nan, dy=np.nan))
            continue
        x0, y0, R, rms, inl = circle_fit(P[:, 0], P[:, 1])
        rows.append(dict(id=i, x0=x0, y0=y0, R=R, rms=rms, n=int(inl.sum()), dx=x0 - cx, dy=y0 - cy))
    T = pd.DataFrame(rows).set_index('id')
    ok = np.isfinite(T.R)
    log.info("arm calibration: %d/%d positioners fitted; R median %.3f mm, circle rms median %.1f um, "
             "centre offset from design median %.1f um", int(ok.sum()), len(T), T.R[ok].median(),
             T.rms[ok].median()*1e3, np.hypot(T.dx[ok], T.dy[ok]).median()*1e3)
    return ArmCalResult(ids=ids, centres=centres, points={i: np.array(p) for i, p in pts.items()},
                        frames=frm, table=T)


def fit_arms(R_beta0, R_beta180):
    """두 beta 에서 잰 반지름 -> (a1, a2). beta=0: R = a1 + a2, beta=180: R = |a2 - a1| (a2 > a1)."""
    R0, R180 = np.asarray(R_beta0, float), np.asarray(R_beta180, float)
    a2 = 0.5*(R0 + R180); a1 = 0.5*(R0 - R180)
    return a1, a2


def plot_arm_calibration(res, ids=None, ncol=6, half=None):
    """positioner 마다 궤적 점과 맞춘 원, 설계 중심(+)과 맞춘 중심(x)."""
    import matplotlib.pyplot as plt
    ids = ids or [i for i in res.ids if np.isfinite(res.table.R.get(i, np.nan))]
    n = len(ids); nrow = int(np.ceil(n/ncol))
    fig, axs = plt.subplots(nrow, ncol, figsize=(2.6*ncol, 2.6*nrow), squeeze=False)
    th = np.linspace(0, 2*np.pi, 200)
    for ax, i in zip(axs.ravel(), ids):
        P = res.points[i]; r = res.table.loc[i]; k = res.ids.index(i); cx, cy = res.centres[k]
        ax.plot(P[:, 0], P[:, 1], 'c.', ms=4)
        ax.plot(r.x0 + r.R*np.cos(th), r.y0 + r.R*np.sin(th), 'y-', lw=0.8)
        ax.plot(cx, cy, 'k+', ms=10); ax.plot(r.x0, r.y0, 'rx', ms=8)
        h = half or 1.3*r.R
        ax.set_xlim(cx - h, cx + h); ax.set_ylim(cy - h, cy + h); ax.set_aspect('equal')
        ax.set_title(f"{i}  R {r.R:.3f}  rms {r.rms*1e3:.0f} um  d({r.dx*1e3:+.0f},{r.dy*1e3:+.0f})", fontsize=7)
        ax.set_xticks([]); ax.set_yticks([])
    for ax in axs.ravel()[n:]:
        ax.axis('off')
    fig.tight_layout()
    return fig


def write_measured_geometry(res, path, template=None, arms=None, min_n=5):
    """arm_calibration 결과(회전 중심, 선택적으로 arm 길이)를 Measured_Geometry 형식으로 쓴다.
    template: 바탕이 될 기존 파일 (없는 줄은 설계값 주석 없이 새로 쓴다). arms: {id: (a1, a2)}."""
    T = res.table
    lines = []
    if template and os.path.exists(template):
        src = open(template).read().splitlines()
    else:
        src = ["# ID            X          Y    arm1    arm2"]
    done = set()
    for line in src:
        body, _, comment = line.partition('#')
        p = body.split()
        if len(p) == 5 and p[0] in T.index and T.n[p[0]] >= min_n and np.isfinite(T.x0[p[0]]):
            r = T.loc[p[0]]; a = arms.get(p[0], (None, None)) if arms else (None, None)
            s1 = f"{a[0]:.4f}" if a[0] is not None else p[3]; s2 = f"{a[1]:.4f}" if a[1] is not None else p[4]
            line = f"  {p[0]:<5} {r.x0:12.4f} {r.y0:10.4f} {s1:>7} {s2:>7}   # positioner centre from arm scan (rms {r.rms*1e3:.0f} um, n {int(r.n)})"
            done.add(p[0])
        lines.append(line)
    for i, r in T.iterrows():
        if i in done or not (r.n >= min_n and np.isfinite(r.x0)):
            continue
        a = arms.get(i, (None, None)) if arms else (None, None)
        s1 = f"{a[0]:.4f}" if a[0] is not None else '-'; s2 = f"{a[1]:.4f}" if a[1] is not None else '-'
        lines.append(f"  {i:<5} {r.x0:12.4f} {r.y0:10.4f} {s1:>7} {s2:>7}   # positioner centre from arm scan (rms {r.rms*1e3:.0f} um, n {int(r.n)})")
    with open(path, 'w') as ff:
        ff.write('\n'.join(lines) + '\n')
    return path
