"""관측 고도(천정거리)에 따른 focal plane 위치 보정.

ADC가 들어간 광학계는 천정거리(zenith angle, ZA)가 커질수록 sky -> focal plane
매핑이 조금씩 달라진다. 같은 천체가 ZA=0에서 맺히던 자리와 ZA에서 맺히는 자리의
차이 (dx, dy)를 ZA 함수로 미리 계산해 둔 것이 이 모듈이다.

계산 과정 (ADC_effect/src/ADC_sky2focal.ipynb):

  1. Zemax grid distortion 출력 (data/Zenith{ZA}_Orig_Distortion.TXT, ZA = 0..50,
     5도 간격, field < 1.4 deg)에서 real focal plane 좌표를 읽는다.
  2. 각 ZA에서 dx = rx(ZA) - rx(0), dy = ry(ZA) - ry(0)를 구하고, 이를 unit disk로
     normalize한 좌표 (rho = r/R_NORM) 위의 Zernike 다항식으로 전개한다.
     45개 mode를 모두 fit해 본 뒤 dominant한 것만 남긴 것이 SELECTED_JX/JY다.
  3. 각 mode의 계수를 ZA의 함수로 보면 매끄러운 곡선이라, 상수항 없는 2차식
     coeff(ZA) = b*ZA^2 + c*ZA 로 fit했다 (ZA=0에서 정의상 0).

여기 박아둔 (b, c)가 그 fit 결과다. 이 모델은 Zemax 원본 offset을 ZA=50도에서
RMS 0.25 um 수준으로 재현한다 (원본 offset 자체는 같은 곳에서 RMS 9.3 um).

주의:
  - 계수는 Zemax focal plane 좌표계 기준이다. metrology 좌표계의 축 방향/부호가
    다르면 여기서 나온 dx, dy도 같이 돌려줘야 한다.
  - fit 구간은 ZA 0~50도다. 그 밖에서는 외삽이므로 경고를 남긴다.
  - R_NORM은 field 1.4도에 해당하는 반경이라, 그보다 바깥(r > 128.5mm)의
    fiducial은 rho가 1을 조금 넘는다 (최대 1.03). 다항식이라 계산 자체는 되지만
    엄밀히는 외삽이다.
"""

import numpy as np

from kspec_metrology.analysis.utils import zernike
from kspec_metrology.logging.log import get_logger

# Zernike를 전개한 unit disk의 반경 (mm). field 1.4도에 해당한다.
R_NORM = 128.54952409795223

# 계수를 fit한 천정거리 구간 (deg)
ZA_FIT_RANGE = (0., 50.)

# (Noll index j, b, c) : coeff_j(ZA) = b*ZA^2 + c*ZA   [mm, ZA는 deg]
# 계수는 Noll normalize된 Zernike (sqrt(2(n+1)) 또는 sqrt(n+1) 상수 포함) 기준이다.
ZERNIKE_X = (
    ( 5,  4.158252721659e-08, -1.317014550975e-04),
    ( 3, -2.533350660361e-07,  2.858282474461e-05),
    ( 1,  2.232258057289e-07, -1.372932993515e-06),
    ( 4,  1.359945883683e-07, -9.463815207056e-07),
    ( 6,  1.065918767416e-07, -6.850979272714e-07),
    (13, -1.370932256606e-10,  2.639715380948e-06),
)

ZERNIKE_Y = (
    ( 6, -3.704183670905e-08,  1.315411606103e-04),
    ( 1,  3.153417083013e-09, -1.491306786638e-05),
    ( 2, -1.483865827989e-07,  1.681367644690e-05),
    ( 3, -1.368025823734e-07, -1.333035157813e-07),
    (11, -2.665711422383e-09,  4.871609701175e-06),
    ( 5,  1.068499498982e-07, -6.883521773694e-07),
    (12,  3.064285047927e-09, -2.729858538331e-06),
    ( 4, -1.783286851520e-09, -2.520349054347e-06),
)

def _noll_nm(j):
    """Noll index j (1-based) -> (n, m). utils._zernike_terms와 같은 규칙."""
    n, j1 = 0, j - 1
    while j1 > n:
        n += 1
        j1 -= n
    m = (-1)**j * ((n % 2) + 2*((j1 + ((n+1) % 2)) // 2))
    return n, m


def _noll_norm(j):
    """Noll normalization 상수. utils.zernike()에는 이 상수가 빠져 있다."""
    n, m = _noll_nm(j)
    return np.sqrt(2*(n+1)) if m != 0 else np.sqrt(n+1)


def _evaluate(table, xn, yn, za):
    """table의 mode들을 합쳐 offset 한 성분을 만든다."""
    out = np.zeros_like(xn)
    for j, b, c in table:
        out += (b*za**2 + c*za) * _noll_norm(j) * zernike(j, xn, yn)
    return out


def zenith_offset(x, y, zenith_angle):
    """천정거리 zenith_angle(deg)에서 생기는 focal plane 위치 offset.

    인자:
        x, y         : ZA=0 기준 focal plane 좌표 (mm)
        zenith_angle : 천정거리 (deg). scalar 또는 x와 broadcast되는 배열

    반환:
        dx, dy : 같은 천체가 이 ZA에서 실제로 맺히는 자리와의 차이 (mm).
                 즉 실제 상 위치 = (x + dx, y + dy)
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    za = np.asarray(zenith_angle, dtype=float)

    lo, hi = ZA_FIT_RANGE
    if np.any(za < lo) or np.any(za > hi):
        get_logger().warning(
            "Zenith angle %s deg is outside the fitted range %g-%g deg; "
            "the offset is extrapolated", np.atleast_1d(za), lo, hi)

    xn, yn = x/R_NORM, y/R_NORM

    return _evaluate(ZERNIKE_X, xn, yn, za), _evaluate(ZERNIKE_Y, xn, yn, za)
