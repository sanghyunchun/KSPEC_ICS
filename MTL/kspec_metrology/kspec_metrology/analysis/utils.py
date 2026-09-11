import numpy as np
from astropy.table import Table
from scipy.spatial import cKDTree
from functools import lru_cache
from math import factorial

def com(im_crop, x_crop, y_crop):
    xsum = np.sum(im_crop, axis=0)
    ysum = np.sum(im_crop, axis=1)

    xcom = np.sum( x_crop*xsum ) / np.sum(xsum)
    ycom = np.sum( y_crop*ysum ) / np.sum(ysum)

    return xcom, ycom


def measure_fwhm(im_crop, x_crop, y_crop):
    """measure FWHM of the cropped image along x and y axes
    SW added on 2026-01-31"""

    xsum = np.sum(im_crop, axis=0)
    ysum = np.sum(im_crop, axis=1)
    
    x_max = np.max(xsum)
    x_half = x_max / 2
    x_above_half = np.where(xsum >= x_half)[0]
    fwhm_x = x_crop[x_above_half[-1]] - x_crop[x_above_half[0]]
    
    y_max = np.max(ysum)
    y_half = y_max / 2
    y_above_half = np.where(ysum >= y_half)[0]
    fwhm_y = y_crop[y_above_half[-1]] - y_crop[y_above_half[0]]
    
    return fwhm_x, fwhm_y

def measure_sigma(im_crop, x_crop, y_crop):
    """Measure width (sigma) of the cropped image along x and y axes
    SW added on 2026-06-10"""

    xcom, ycom = com(im_crop, x_crop, y_crop)

    xsum = np.sum(im_crop, axis=0)
    ysum = np.sum(im_crop, axis=1)

    sigma_x = np.sqrt(np.sum(xsum * (x_crop - xcom)**2) / np.sum(xsum))
    sigma_y = np.sqrt(np.sum(ysum * (y_crop - ycom)**2) / np.sum(ysum))

    return sigma_x, sigma_y


focal2camera_coeff = np.array([-1.18e-1, 0., 0., 0.
                            , -1e-4 , -1e-8 , -1e-10, -1e-13
                            ,  1e-7 ,  1e-11, -1e-1
                            , -1e-10, -1e-10,  1e-8 , -1e-8])

camera2focal_coeff = np.array([-8.9, 3.39, -17.6, 6.12
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
               ):
    """왜곡 다항식 본체. (x, y) 배열을 받아 (xnew-x0, ynew-y0)를 돌려준다.

    속도 우선으로 쓴 코드라 식이 원래 형태와 다르게 보인다. 하는 계산은 같다.
      - r = sqrt(x^2+y^2)를 아예 만들지 않는다. radial/tangential 항에 r은
        짝수 거듭제곱으로만 들어가므로 s = r^2 만 있으면 된다.
      - radial 항 r1x*r^2 + r2x*r^4 + r3x*r^6 + r4x*r^8 은 s에 대한 Horner 형태.
      - Zernike 항 Z20, Z10 은 (x+iy)^5, (x+iy)^3 의 실수부이고
        Z21, Z9 는 각각의 허수부다 (zernike() 참고). 복소 거듭제곱을
        곱셈 연쇄로 한 번만 만들어 네 항이 나눠 쓴다.
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
            )

    ynew = (y + y*rad_poly + (t2x*(s + 2.*y2) + (t1x*2.)*xy)*tan_scale
            + a2y*w5.imag
            + a3y*w3.imag
            )

    return xnew - x0, ynew - y0


def transform_polynomial(xin
               , m
               , theta
               , x0, y0
               , r1x, r2x, r3x, r4x
               , t1x, t2x, t3x
               , a1x, a2y, a4x, a3y
               ):
    """curve_fit용 wrapper. x, y가 두 번 반복된 배열을 받아 결과를 이어붙여 돌려준다.
    (curve_fit이 파라미터 개수를 signature에서 읽으므로 인자를 풀어서 적어 둔다.)"""

    xtemp, ytemp = xin
    xnew, ynew = _transform_core(xtemp[:xtemp.size//2], ytemp[:ytemp.size//2]
                        , m, theta, x0, y0
                        , r1x, r2x, r3x, r4x
                        , t1x, t2x, t3x
                        , a1x, a2y, a4x, a3y
                        )

    return np.concatenate((xnew, ynew))

def transform(x, y, coeff):
    return _transform_core(np.asarray(x), np.asarray(y), *coeff)

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

