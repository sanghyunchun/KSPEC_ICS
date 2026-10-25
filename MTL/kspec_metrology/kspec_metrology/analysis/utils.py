import numpy as np
from astropy.table import Table
from scipy.spatial import cKDTree
from functools import lru_cache
from math import factorial

@lru_cache(maxsize=16)
def _ones(n, dtype_str):
    """행렬-벡터 곱에 쓸 1 벡터. 크기/타입별로 한 번만 만든다."""
    return np.ones(n, dtype=np.dtype(dtype_str))


def _marginals(im_crop):
    """열 방향 합, 행 방향 합, 총합.

    np.sum(axis=...) 대신 1 벡터와의 행렬곱을 쓴다. BLAS로 내려가서 2배쯤
    빠르고 (80x80에서 5.8us -> 2.8us), 특히 axis=0은 메모리를 건너뛰며 더하므로
    차이가 크다. 총합은 두 marginal의 합이 같으므로 한 번만 구한다.
    """
    ny, nx = im_crop.shape
    dt = im_crop.dtype.str

    xsum = _ones(ny, dt) @ im_crop          # == im_crop.sum(axis=0)
    ysum = im_crop @ _ones(nx, dt)          # == im_crop.sum(axis=1)

    return xsum, ysum, xsum.sum()


def com(im_crop, x_crop, y_crop):
    """밝기 무게중심."""
    xsum, ysum, total = _marginals(im_crop)

    return (x_crop @ xsum)/total, (y_crop @ ysum)/total


def measure_fwhm(im_crop, x_crop, y_crop):
    """measure FWHM of the cropped image along x and y axes
    SW added on 2026-01-31

    각 축으로 합친 profile에서 최대값 절반을 넘는 첫/마지막 픽셀 간격이다.
    보간하지 않으므로 픽셀 단위로 양자화되어 있다.
    """
    xsum, ysum, _ = _marginals(im_crop)

    # profile이 수십 개짜리라 np.where가 argmax 두 번보다 싸다 (재봤다)
    ix = np.where(xsum >= xsum.max()/2)[0]
    iy = np.where(ysum >= ysum.max()/2)[0]

    return (x_crop[ix[-1]] - x_crop[ix[0]],
            y_crop[iy[-1]] - y_crop[iy[0]])


def measure_sigma(im_crop, x_crop, y_crop):
    """Measure width (sigma) of the cropped image along x and y axes
    SW added on 2026-06-10

    무게중심 기준 2차 모멘트다 (FWHM이 아니다). com()과 marginal을 공유하므로
    com을 따로 부르지 않는다.
    """
    xsum, ysum, total = _marginals(im_crop)

    xcom = (x_crop @ xsum)/total
    ycom = (y_crop @ ysum)/total

    dx = x_crop - xcom
    dy = y_crop - ycom

    return (np.sqrt((dx*dx) @ xsum / total),
            np.sqrt((dy*dy) @ ysum / total))


focal2camera_coeff = np.array([-1.18e-1, 0., 0., 0.
                            , -1e-4 , -1e-8 , -1e-10, -1e-13
                            ,  1e-7 ,  1e-11, -1e-1
                            , -1e-10, -1e-10,  1e-8 , -1e-8])

# camera -> focal 배율(magnification) 초기값.
#
# matchfiber는 회전과 offset만 grid search하고 배율은 맞추지 않으므로, 이 값이
# 실제와 몇 % 이상 어긋나면 시야 가장자리에서 fiber 매칭이 어긋난다.
#
# 지금 값은 image_simulation의 mock 이미지(Zemax 설계 광학계)에 맞춘 것이다.
#   focal2ccd 배율 -0.11809820162629767 의 역수
# 실카메라 배율이 확정되면 이 상수만 바꾸면 된다 (참고: 커미셔닝 카메라를 fit한
# camera2focal_coeff_comm[0]은 -8.86122935).
CAMERA2FOCAL_M = -8.467529447775467

# 왜곡 다항식 계수 이름 (_transform_core 인자 순서). fitdistortion 이 어느 항을 풀지
# 고를 때 쓴다.
COEFF_NAMES = ('m', 'theta', 'x0', 'y0',
               'r1', 'r2', 'r3', 'r4',          # radial   r^2 .. r^8
               't1', 't2', 't3',                # tangential
               'a1', 'a2', 'a4', 'a3',          # PSF 비대칭(coma)으로 생기는 centroid 이동 항
               'b1', 'b2')                      # affine 비등방 항 (b1+i b2)*conj(w): 축별 배율 차, 전단

# 왜곡 모델. 광학계가 단순하거나 fiducial 이 적을 때 풀 항을 줄인다.
# 풀지 않는 항은 0 으로 고정되고, 쓰려면 fiducial 이 (항 수 / 2) 개 이상 있어야 한다.
#   full        본 장비. radial 4 + tangential 3 + PSF 4 항 (15 개, fiducial 8 개 이상)
#   optics      PSF 항 없이 광학 왜곡만 (11 개). PSF 가 대칭에 가까울 때
#   radial      배율 · 회전 · offset + r^2, r^4 (6 개). 렌즈가 적은 실험실 광학계
#   similarity  배율 · 회전 · offset 만 (4 개). 왜곡을 무시해도 될 때
#   +affine     위 모델에 b1, b2 를 더한 것. plate 가 카메라 축에 기울어 있거나(한쪽 축 축소)
#               전단이 있을 때 필요하다. 실험실 영상(2026-10-19)에서 잔차 108 -> 61 um.
DISTORTION_MODELS = {
    'full': COEFF_NAMES[:15],
    'optics': COEFF_NAMES[:11],
    'radial': ('m', 'theta', 'x0', 'y0', 'r1', 'r2'),
    'similarity': ('m', 'theta', 'x0', 'y0'),
    'full+affine': COEFF_NAMES,
    'optics+affine': COEFF_NAMES[:11] + ('b1', 'b2'),
    'radial+affine': ('m', 'theta', 'x0', 'y0', 'r1', 'r2', 'b1', 'b2'),
    'affine': ('m', 'theta', 'x0', 'y0', 'b1', 'b2'),
}


def model_mask(model):
    """모델 이름(또는 계수 이름 목록) -> 풀 계수를 True 로 한 길이 15 의 bool 배열."""
    if isinstance(model, str):
        if model not in DISTORTION_MODELS:
            raise ValueError(f"unknown distortion model {model!r}; "
                             f"choose from {list(DISTORTION_MODELS)} or give coefficient names")
        names = DISTORTION_MODELS[model]
    else:
        names = tuple(model)
    bad = [n for n in names if n not in COEFF_NAMES]
    if bad:
        raise ValueError(f"unknown coefficient name(s) {bad}; valid: {COEFF_NAMES}")
    for n in ('m', 'theta', 'x0', 'y0'):
        if n not in names:
            raise ValueError(f"'{n}' must always be free (it is a pose term, not distortion)")
    return np.array([n in names for n in COEFF_NAMES])


def full_coeff(coeff):
    """길이 15 (affine 항 없음) 또는 17 의 계수 배열 -> 길이 17 (b1, b2 는 0 으로 채움)."""
    coeff = np.asarray(coeff, float)
    if coeff.size == len(COEFF_NAMES):
        return coeff
    if coeff.size == len(COEFF_NAMES) - 2:
        return np.r_[coeff, 0., 0.]
    raise ValueError(f"coefficient array must have {len(COEFF_NAMES)-2} or {len(COEFF_NAMES)} entries")


camera2focal_coeff = np.array([CAMERA2FOCAL_M, 3.39, -17.6, 6.12
                            , 1e-7 , 1e-10,  -1e-14, 1e-19
                            , 1e-5 , -1e-5, -1e-5 
                            , -1e-12, 1e-12, -1e-8, -1e-8])

camera2focal_coeff_comm = np.array([-8.86122935e+00,  3.38690494e+00, -1.82528850e+01,  4.97957578e+00,
  1.66354341e-06, -6.79248222e-12, -3.24245319e-15,  1.21355101e-19,
  2.15555123e-05, -5.33596998e-06, -4.25871882e-06,
  5.61938788e-13,  3.45829439e-12,  1.43624651e-08, -5.47145640e-08,])

focal2camera_coeff_comm = np.array([-1.12893885e-01,  2.89629810e+00,  1.85740059e+00, -1.04152670e+00,
       -1.33678211e-04,  3.67028322e-07, -9.27834147e-10,  7.36408576e-13,
       -3.62509537e-05,  2.26389928e-05, -4.46138400e-03, -2.61271864e-09,
       -5.30498957e-09, -1.01272086e-07,  2.18848467e-06])


camera2focal_coeff_zenith = np.array([-8.88334560e+00,  3.38700174e+00, -1.76299812e+01,  6.11948903e+00,
        5.01277558e-08,  1.52527759e-10, -8.35238497e-15,  1.44455386e-19,
        3.32079508e-05, -7.45270979e-06, -2.48535912e-05, -2.39478923e-12,
        1.08525801e-12, -1.75640760e-08, -9.46657939e-09])

focal2camera_coeff_zenith = np.array([-1.14025638e-01,  2.89630479e+00,  1.76308248e+00, -1.15206862e+00,
       -4.99918536e-04,  5.47202289e-06, -2.77633572e-08,  4.81952720e-11,
       -9.64169873e-05,  3.62897445e-06, -3.64394798e-03, -3.24563147e-09,
        2.11100339e-08, -6.03280334e-07,  2.57246047e-08])





@lru_cache(maxsize=None)
def _zernike_terms(j):
    """
    Noll index j -> (|m|, sine 여부, radial 항 ((rho^2의 차수, 계수), ...))

    Z_j = R_n^|m|(rho) * cos(|m|*theta)  (m >= 0)
        = R_n^|m|(rho) * sin(|m|*theta)  (m <  0)
    인데 R_n^|m|(rho) / rho^|m| 는 rho^2에 대한 다항식이고,
    rho^|m| * cos(|m|*theta) = Re((x+iy)^|m|),
    rho^|m| * sin(|m|*theta) = Im((x+iy)^|m|) 이므로
    삼각함수 없이 x, y의 다항식으로 그대로 전개된다.
    """
    # Noll index -> (n, m)
    n, j1 = 0, j - 1
    while j1 > n:
        n += 1
        j1 -= n
    m = (-1)**j * ((n % 2) + 2*((j1 + ((n+1) % 2)) // 2))

    mm = abs(m)
    nk = (n - mm) // 2
    terms = tuple(
        (nk - k,
         (-1)**k * factorial(n-k)
         / (factorial(k) * factorial((n+mm)//2 - k) * factorial(nk - k)))
        for k in range(nk + 1)
    )
    return mm, m < 0, terms


def zernike(j, x, y):
    """
    Noll index j의 Zernike 다항식. 정규화 상수를 붙이지 않는 관례를 쓴다
    (zernike(2,x,y) = x, zernike(3,x,y) = y, zernike(4,x,y) = 2*(x^2+y^2)-1, ...).

    다항식 항등식으로 계산하므로 x, y를 unit disk로 normalize할 필요가 없다.
    """
    if j < 1:
        raise ValueError("Noll index j must be >= 1")

    mm, sine, terms = _zernike_terms(j)

    r2 = x*x + y*y
    radial = sum(c * r2**p for p, c in terms)
    if mm == 0:
        return radial

    ang = (x + 1j*y)**mm
    return radial * (ang.imag if sine else ang.real)


def _transform_core(xtemp, ytemp
               , m
               , theta
               , x0, y0
               , r1x, r2x, r3x, r4x
               , t1x, t2x, t3x
               , a1x, a2y, a4x, a3y
               , b1=0., b2=0.
               ):
    """왜곡 다항식 본체. (x, y) 배열을 받아 (xnew-x0, ynew-y0)를 돌려준다.

    속도 우선으로 쓴 코드라 식이 원래 형태와 다르게 보인다. 하는 계산은 같다.
      - r = sqrt(x^2+y^2)를 아예 만들지 않는다. radial/tangential 항에 r은
        짝수 거듭제곱으로만 들어가므로 s = r^2 만 있으면 된다.
      - radial 항 r1x*r^2 + r2x*r^4 + r3x*r^6 + r4x*r^8 은 s에 대한 Horner 형태.
      - Zernike 항 Z20, Z10 은 (x+iy)^5, (x+iy)^3 의 실수부이고
        Z21, Z9 는 각각의 허수부다 (zernike() 참고). 복소 거듭제곱을
        곱셈 연쇄로 한 번만 만들어 네 항이 나눠 쓴다.
      - affine 항 (b1 + i b2) * (x - iy) = (b1 x + b2 y) + i (b2 x - b1 y):
        회전·등방 배율(m, theta)이 못 담는 축별 배율 차와 전단. 기본 0 이라 예전
        15개 계수 배열을 그대로 넘겨도 결과가 같다.
    """

    cos_t, sin_t = np.cos(theta), np.sin(theta)
    x = m*(xtemp*cos_t - ytemp*sin_t)
    y = m*(xtemp*sin_t + ytemp*cos_t)

    x2, y2, xy = x*x, y*y, x*y
    s = x2 + y2

    rad_poly = s*(r1x + s*(r2x + s*(r3x + s*r4x)))
    tan_scale = 1. + t3x*s

    w = np.empty(x.shape, dtype=complex)
    w.real, w.imag = x, y
    w2 = w*w
    w3 = w2*w
    w5 = w3*w2

    xnew = (x + x*rad_poly + (t1x*(s + 2.*x2) + (t2x*2.)*xy)*tan_scale
            + a1x*w5.real
            + a4x*w3.real
            + b1*x + b2*y
            )

    ynew = (y + y*rad_poly + (t2x*(s + 2.*y2) + (t1x*2.)*xy)*tan_scale
            + a2y*w5.imag
            + a3y*w3.imag
            + b2*x - b1*y
            )

    return xnew - x0, ynew - y0


def transform_polynomial(xin
               , m
               , theta
               , x0, y0
               , r1x, r2x, r3x, r4x
               , t1x, t2x, t3x
               , a1x, a2y, a4x, a3y
               , b1=0., b2=0.
               ):
    """curve_fit용 wrapper. x, y가 두 번 반복된 배열을 받아 결과를 이어붙여 돌려준다.
    (curve_fit이 파라미터 개수를 signature 또는 p0 에서 읽으므로 인자를 풀어서 적어 둔다.)"""

    xtemp, ytemp = xin
    xnew, ynew = _transform_core(xtemp[:xtemp.size//2], ytemp[:ytemp.size//2]
                        , m, theta, x0, y0
                        , r1x, r2x, r3x, r4x
                        , t1x, t2x, t3x
                        , a1x, a2y, a4x, a3y
                        , b1, b2
                        )

    return np.concatenate((xnew, ynew))

def transform(x, y, coeff):
    return _transform_core(np.asarray(x), np.asarray(y), *coeff)


def invert_transform(xfocal, yfocal, coeff, n_iter=8):
    """camera->focal 변환의 역: 초점면 (xfocal, yfocal) 에 대응하는 칩 좌표 [mm].
    닫힌 역함수가 없으므로 1차 근사(최소제곱)로 출발해 Newton 반복(수치 Jacobian)으로 푼다."""
    xf, yf = np.asarray(xfocal, float), np.asarray(yfocal, float)
    g = np.linspace(-15., 15., 7)                              # 칩 전체를 덮는 격자 [mm]
    gx, gy = np.meshgrid(g, g); gx, gy = gx.ravel(), gy.ravel()
    fx, fy = transform(gx, gy, coeff)
    A = np.column_stack((fx, fy, np.ones(fx.size)))
    cx, *_ = np.linalg.lstsq(A, gx, rcond=None); cy, *_ = np.linalg.lstsq(A, gy, rcond=None)
    u = cx[0]*xf + cx[1]*yf + cx[2]; v = cy[0]*xf + cy[1]*yf + cy[2]
    h = 1e-3
    for _ in range(n_iter):
        px, py = transform(u, v, coeff)
        ex, ey = xf - px, yf - py
        pxu, pyu = transform(u + h, v, coeff); pxv, pyv = transform(u, v + h, coeff)
        j11, j21 = (pxu - px)/h, (pyu - py)/h                   # d(px,py)/du
        j12, j22 = (pxv - px)/h, (pyv - py)/h                   # d(px,py)/dv
        det = j11*j22 - j12*j21
        du = ( j22*ex - j12*ey)/det; dv = (-j21*ex + j11*ey)/det
        u, v = u + du, v + dv
        if np.nanmax(np.hypot(du, dv)) < 1e-7:
            break
    return u, v

def dedupe_peaks_kdtree(peak_table: Table, min_dist: float) -> Table:
    """
    peak_table: photutils.find_peaks 결과 (x_peak, y_peak, peak_value 컬럼 포함)
    min_dist  : 같은 소스군으로 간주할 최소 거리(픽셀)
    반환값    : 중복 제거된 Table (원본 메타 유지)
    """

    # 배열 추출
    x = np.asarray(peak_table['x_peak'], dtype=float)
    y = np.asarray(peak_table['y_peak'], dtype=float)
    v = np.asarray(peak_table['peak_value'], dtype=float)

    n = x.size
    if n == 0:
        return peak_table.copy()

    # 더 밝은 순서(내림차순)로 처리 → 이 순서로 선택하면 주변 약한 피크를 지움
    order = np.argsort(-v)

    pts = np.column_stack((x, y))
    tree = cKDTree(pts)

    keep = np.ones(n, dtype=bool)
    selected_idx = []

    for idx in order:
        if not keep[idx]:
            continue
        # 이 피크는 채택
        selected_idx.append(idx)
        # min_dist 이내 이웃(자기 자신 포함)
        neighbors = tree.query_ball_point(pts[idx], r=min_dist)
        # 자신보다 어두운 이웃들을 제거(우리는 내림차순으로 돌고 있으므로 이웃은 항상 같거나 더 어둠)
        for nb in neighbors:
            if nb == idx:
                continue
            keep[nb] = False

    selected_idx = np.array(selected_idx, dtype=int)
    selected_idx.sort()  # 원하면 원래 순서로 복원하려면 주석 해제/유지 선택
    return peak_table[selected_idx]

def _find_angle_double_method2_ccw(
    ori_x, ori_y,
    target_x_ori, target_y_ori,
    arm1, arm2,
    elbow="down",
):
    """
    (내부용) 반시계방향(CCW) 정의에서 elbow 선택 버전
    elbow="down": phi in [0, +pi]
    elbow="up"  : phi in [-pi, 0]
    반환: theta, phi (rad), theta는 [0,2pi)
    """
    Positioner_p = arm1 + arm2

    elbow = str(elbow).lower()
    if elbow not in ("down", "up"):
        raise ValueError("elbow must be 'down' or 'up'")
    sgn = +1.0 if elbow == "down" else -1.0

    # base 기준 상대좌표
    target_x = target_x_ori - ori_x
    target_y = target_y_ori - ori_y

    d = float(np.hypot(target_x, target_y))
    gamma = float(np.arctan2(target_y, target_x))  # [-pi, pi]

    # ---- 도달 불가능: 너무 멀면 완전 펼침(phi=0) ----
    if d >= Positioner_p:
        theta = gamma
        phi = 0.0

    # ---- 도달 불가능: 너무 가까우면 완전 접힘(phi=±pi) ----
    elif d <= abs(arm2 - arm1):
        theta = gamma + np.pi
        phi = (np.pi if sgn > 0 else -np.pi)

    # ---- 도달 가능: elbow 선택 ----
    else:
        arg = (d**2 - arm1**2 - arm2**2) / (-2.0 * arm1 * arm2)
        arg = float(np.clip(arg, -1.0, 1.0))

        theta_beta = float(np.arccos(arg))
        phi_mag = float(np.pi - theta_beta)  # (0~pi)
        phi = sgn * phi_mag                  # down:+, up:-

        theta_alpha = float(np.arctan2(
            arm2 * np.sin(phi),
            arm1 + arm2 * np.cos(phi)
        ))
        theta = float(gamma - theta_alpha)

    # ---- theta를 항상 [0, 2pi)로 정규화 ----
    theta = float(theta % (2.0 * np.pi))

    # ---- phi 범위 정리 ----
    if sgn > 0:
        phi = float(np.clip(phi, 0.0, np.pi))       # down
    else:
        phi = float(np.clip(phi, -np.pi, 0.0))      # up

    return theta, phi

def find_angle_double_method2_select_elbow(
    ori_x, ori_y,
    target_x_ori, target_y_ori,
    arm1, arm2,
    elbow="down",
    clockwise=False,
):
    """
    ✅ 최종 사용자용 함수

    elbow="down"/"up" 선택 가능
    clockwise=False : 반시계(CCW) 정의 (기존과 동일)
    clockwise=True  : 시계(CW) 정의 (각도 증가가 시계방향)

    반환: theta, phi (rad)
      - theta는 항상 [0, 2pi)
      - elbow-down이면 phi는 [0, pi], elbow-up이면 [-pi, 0]
        (clockwise=True에서도 동일하게 유지되도록 자동 변환)
    """
    elbow = str(elbow).lower()
    if elbow not in ("down", "up"):
        raise ValueError("elbow must be 'down' or 'up'")

    if not clockwise:
        # 기존(반시계) 그대로
        return _find_angle_double_method2_ccw(
            ori_x, ori_y, target_x_ori, target_y_ori, arm1, arm2, elbow=elbow
        )

    # --- 시계방향(CW) 각도 정의 ---
    # CW로 바꾸면 (theta, phi)를 단순히 부호반전하면 되는데,
    # elbow-down/up의 phi 부호 조건을 유지하려면 elbow를 swap해서 계산해야 함.
    elbow_ccw = ("up" if elbow == "down" else "down")

    theta_ccw, phi_ccw = _find_angle_double_method2_ccw(
        ori_x, ori_y, target_x_ori, target_y_ori, arm1, arm2, elbow=elbow_ccw
    )

    theta = float((-theta_ccw) % (2.0 * np.pi))
    phi   = float(-phi_ccw)

    # phi 범위 강제 (수치오차 방지)
    if elbow == "down":
        phi = float(np.clip(phi, 0.0, np.pi))
    else:
        phi = float(np.clip(phi, -np.pi, 0.0))

    return theta, phi



def nearest_index_sorted(grid, x):
    """
    grid: (N,) 오름차순 정렬된 1D array (예: xchip, ychip)
    x   : (M,) 혹은 scalar
    return: x와 가장 가까운 grid index (int)
    """
    grid = np.asarray(grid)
    x = np.asarray(x)

    # 들어갈 위치 찾기 (오른쪽 인덱스)
    idx = np.searchsorted(grid, x)

    # 비교를 위해 idx가 1~N-1 범위에 있도록 클립
    idx = np.clip(idx, 1, len(grid) - 1)

    left  = grid[idx - 1]
    right = grid[idx]

    # 왼쪽/오른쪽 중 더 가까운 쪽 선택
    choose_left = (x - left) <= (right - x)
    return np.where(choose_left, idx - 1, idx).astype(np.int32)

