import math
from astropy.coordinates import SkyCoord, CartesianRepresentation
import astropy.units as u
import numpy as np

AS_PER_DEG = 3600.0

def wrap_deg360(x):
    return x % 360.0

def wrap_deg180(x):
    return (x + 180.0) % 360.0 - 180.0

def ra_deg_to_hms(ra_deg, precision=3):
    """
    RA [deg] → 'HH:MM:SS.sss'
    precision: 초 소수점 자리수
    """
    ra_deg = ra_deg % 360.0
    total_hours = ra_deg / 15.0

    h = int(total_hours)
    m = int((total_hours - h) * 60.0)
    s = (total_hours - h - m/60.0) * 3600.0

    s_fmt = f"{s:0{2 + (precision+1 if precision>0 else 0)}.{precision}f}"
    return f"{h:02d}:{m:02d}:{s_fmt}"

def dec_deg_to_dms(dec_deg, precision=2):
    """
    DEC [deg] → '±DD:MM:SS.ss'
    precision: 초 소수점 자리수
    """
    sign = '+' if dec_deg >= 0 else '-'
    d = abs(dec_deg)

    deg = int(d)
    arcmin = int((d - deg) * 60.0)
    arcsec = (d - deg - arcmin/60.0) * 3600.0

    arcsec_fmt = f"{arcsec:0{2 + (precision+1 if precision>0 else 0)}.{precision}f}"
    return f"{sign}{deg:02d}:{arcmin:02d}:{arcsec_fmt}"

def ra_hms_to_deg(h, m, s):
    """
    RA 'h, m, s' → degrees
    """
    return 15.0 * (float(h) + float(m)/60.0 + float(s)/3600.0)

def ra_hms_str_to_deg(hms_str):
    h, m, s = hms_str.strip().split(':')
    return ra_hms_to_deg(h, m, s)

#def dec_dms_to_deg(sign, d, m, s):
#    """
#    DEC 'sign, d, m, s' → degrees
#    sign: '+' or '-'
#    """
#    deg = abs(float(d)) + float(m)/60.0 + float(s)/3600.0
#    return deg if sign == '+' else -deg

#def dec_dms_str_to_deg(dms_str):
#    sgn = dms_str.strip()[0]
#    d, m, s = dms_str.strip()[1:].split(':')
#    return dec_dms_to_deg(sgn, d, m, s)

def radec_str_to_deg(ra_str: str, dec_str: str):
    """
    Convert RA/Dec strings to degrees.
    - ra_str: 'hh:mm:ss.s' (or with spaces/extra)
    - dec_str: '+dd:mm:ss.s' or '-dd:mm:ss.s' or 'dd:mm:ss.s' (assume + if no sign)
    Returns: (ra_deg, dec_deg) as floats
    """
    ra = ra_str.strip()
    dec = dec_str.strip()

    # Dec sign handling: if no explicit sign, assume '+'
    if dec and dec[0] not in ['+', '-']:
        dec = '+' + dec

    # SkyCoord can parse sexagesimal with explicit units
    c = SkyCoord(ra=ra, dec=dec, unit=(u.hourangle, u.deg), frame='icrs')

    return c.ra.deg, c.dec.deg


#def dec_sexagesimal_to_deg(dec_str):
#    """
#    DEC sexagesimal string → degree
#    Accepts:
#      '+DD:MM:SS.ss'
#      '-DD:MM:SS.ss'
#      'DD:MM:SS.ss'  (assumed '+')
#    """
#    s = dec_str.strip()
#    if not s:
#        raise ValueError("Empty DEC string")

#    if s[0] in '+-':
#        sign = -1 if s[0] == '-' else 1
#        body = s[1:]
#    else:
#        sign = 1
#        body = s

#    try:
#        d, m, sec = body.split(':')
#    except ValueError:
#        raise ValueError("DEC must be in format 'DD:MM:SS'")

#    deg = float(d)
#    arcmin = float(m)
#    arcsec = float(sec)

#    if not (0 <= arcmin < 60):
#        raise ValueError("Arcmin out of range [0,60)")
#    if not (0 <= arcsec < 60):
#        raise ValueError("Arcsec out of range [0,60)")

#    dec = sign * (deg + arcmin / 60.0 + arcsec / 3600.0)

#    if abs(dec) > 90:
#        raise ValueError("DEC out of physical range [-90,+90]")

#    return dec




#def get_separation(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
#    """두 점 사이 대원 separation [arcsec]"""
#    ra1 = math.radians(ra1_deg); dec1 = math.radians(dec1_deg)
#    ra2 = math.radians(ra2_deg); dec2 = math.radians(dec2_deg)
#    d_ra = ra2 - ra1
#    cos_d = math.sin(dec1)*math.sin(dec2) + math.cos(dec1)*math.cos(dec2)*math.cos(d_ra)
#    cos_d = max(-1.0, min(1.0, cos_d))
#    return math.degrees(math.acos(cos_d)) * AS_PER_DEG

def get_separation(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
    c1 = SkyCoord(ra1_deg*u.deg, dec1_deg*u.deg, frame='icrs')
    c2 = SkyCoord(ra2_deg*u.deg, dec2_deg*u.deg, frame='icrs')
    return c1.separation(c2).arcsec


#def get_boresight(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
#    """두 점의 대원 중점(구면삼각법) = 보어사이트"""
#    ra1 = math.radians(ra1_deg); dec1 = math.radians(dec1_deg)
#    ra2 = math.radians(ra2_deg); dec2 = math.radians(dec2_deg)

#    d_ra = ra2 - ra1
#    cos_d = math.sin(dec1)*math.sin(dec2) + math.cos(dec1)*math.cos(dec2)*math.cos(d_ra)
#    cos_d = max(-1.0, min(1.0, cos_d))
#    d = math.acos(cos_d)

#    if d < 1e-15:
#        return wrap_deg360(ra1_deg), dec1_deg
#    if abs(math.pi - d) < 1e-12:
#        raise ValueError("두 점이 거의 antipodal이라 보어사이트가 유일하지 않습니다.")

#    w = math.sin(0.5*d) / math.sin(d)

#    def to_vec(ra, dec):
#        return (
#            math.cos(dec) * math.cos(ra),
#            math.cos(dec) * math.sin(ra),
#            math.sin(dec)
#        )

#    x1, y1, z1 = to_vec(ra1, dec1)
#    x2, y2, z2 = to_vec(ra2, dec2)

#    xm = w*x1 + w*x2
#    ym = w*y1 + w*y2
#    zm = w*z1 + w*z2

#    n = math.sqrt(xm*xm + ym*ym + zm*zm)
#    xm, ym, zm = xm/n, ym/n, zm/n

#    ra0 = wrap_deg360(math.degrees(math.atan2(ym, xm)))
#    dec0 = math.degrees(math.asin(zm))
#    return ra0, dec0

#def get_boresight(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
#    """두 점의 대원 중점 (boresight)"""

#    ra1 = math.radians(ra1_deg); dec1 = math.radians(dec1_deg)
#    ra2 = math.radians(ra2_deg); dec2 = math.radians(dec2_deg)

#    def to_vec(ra, dec):
#        return (
#            math.cos(dec) * math.cos(ra),
#            math.cos(dec) * math.sin(ra),
#            math.sin(dec)
#        )

#    x1, y1, z1 = to_vec(ra1, dec1)
#    x2, y2, z2 = to_vec(ra2, dec2)

#    xm = x1 + x2
#    ym = y1 + y2
#    zm = z1 + z2

#    n = math.sqrt(xm*xm + ym*ym + zm*zm)

#    if n < 1e-15:
#        raise ValueError("두 점이 거의 antipodal이라 보어사이트가 유일하지 않습니다.")

#    xm, ym, zm = xm/n, ym/n, zm/n

#    ra0  = wrap_deg360(math.degrees(math.atan2(ym, xm)))
#    dec0 = math.degrees(math.asin(zm))

#    return ra0, dec0


def get_boresight(ra_list_deg, dec_list_deg, frame="icrs"):
    """
    6개의 가이드 카메라 이미지 중심 좌표(RA, DEC)로부터
    초점면 중심(boresight)을 계산한다.

    Parameters
    ----------
    ra_list_deg : array-like
        RA values in degrees (length = 6)
    dec_list_deg : array-like
        DEC values in degrees (length = 6)
    frame : str
        Astropy coordinate frame (default: 'icrs')

    Returns
    -------
    ra_bs_deg : float
        Boresight RA in degrees
    dec_bs_deg : float
        Boresight DEC in degrees
    """

    if len(ra_list_deg) != 6 or len(dec_list_deg) != 6:
        raise ValueError("Guide camera coordinates must be exactly 6 points.")

    # SkyCoord 생성
    guides = SkyCoord(
        ra=ra_list_deg * u.deg,
        dec=dec_list_deg * u.deg,
        frame=frame
    )

    # 단위벡터(cartesian) 평균
    xyz = guides.cartesian.xyz.value  # shape (3, 6)
    v_mean = np.mean(xyz, axis=1)

    # 정규화
    v_mean /= np.linalg.norm(v_mean)

    # 다시 SkyCoord로 변환
    boresight = SkyCoord(
        CartesianRepresentation(v_mean[0], v_mean[1], v_mean[2]),
        frame=frame
    )

    return boresight.ra.deg, boresight.dec.deg


def offsets_arcsec(ra_from, dec_from, ra_to, dec_to):
    """
    from -> to 로 가기 위한 오프셋.
    ΔRA_arcsec: +East (하늘에서 동쪽 각거리)
    ΔDEC_arcsec:+North
    """
    dRA_deg  = wrap_deg180(ra_to - ra_from)
    dDEC_deg = (dec_to - dec_from)

    dec_ref = math.radians(0.5*(dec_from + dec_to))
    dRA_arcsec  = dRA_deg * math.cos(dec_ref) * AS_PER_DEG
    dDEC_arcsec = dDEC_deg * AS_PER_DEG
    return dRA_arcsec, dDEC_arcsec

def apply_offsets(ra_deg, dec_deg, dRA_arcsec_east, dDEC_arcsec_north):
    """
    (ra,dec)에 동/북 오프셋(arcsec)을 적용해 새 좌표를 만든다.
    ΔRA_arcsec는 하늘상 동서 각거리이므로 RA 변화로 바꿀 때 cos(dec)로 나눔.
    """
    dec2 = dec_deg + dDEC_arcsec_north / AS_PER_DEG
    dec_ref = math.radians(0.5*(dec_deg + dec2))
    if abs(math.cos(dec_ref)) < 1e-12:
        raise ValueError("DEC가 극에 너무 가까워 RA 변환이 불안정합니다.")
    dRA_deg = (dRA_arcsec_east / AS_PER_DEG) / math.cos(dec_ref)
    ra2 = wrap_deg360(ra_deg + dRA_deg)
    return ra2, dec2

def refine_command_coordinate(
    ra1, dec1, ra2, dec2,          # guide centers
    ra_cmd_old, dec_cmd_old,        # 내가 이미 입력했던 좌표(보통 RA_target,DEC_target)
    ra_target, dec_target           # 원하는 최종 목표
):
    """
    이미 ra_cmd_old/dec_cmd_old로 보냈는데 실제 보어사이트가 빗나간 상황에서,
    새로 입력할 보정 좌표를 계산.

    반환:
      - solved boresight
      - target-boresight separation
      - needed move (ΔRA,ΔDEC) arcsec (+East,+North)
      - new command RA/DEC (deg)  (망원경에 직접 입력)
    """
    ra_bs, dec_bs = boresight_from_two_guides_spherical(ra1, dec1, ra2, dec2)

    # 타겟-보어사이트 separation
    sep_arcsec = great_circle_sep_arcsec(ra_bs, dec_bs, ra_target, dec_target)

    # 실제 보어사이트 -> 목표로 가야 하는 오프셋
    dRA_as, dDEC_as = offsets_arcsec_east_north(ra_bs, dec_bs, ra_target, dec_target)

    # 그 오프셋을 "이전 명령 좌표"에 더해 새 명령 좌표 생성
    ra_cmd_new, dec_cmd_new = apply_offsets_to_radec(ra_cmd_old, dec_cmd_old, dRA_as, dDEC_as)

    return {
        "boresight_ra_deg": ra_bs,
        "boresight_dec_deg": dec_bs,
        "target_boresight_sep_arcsec": sep_arcsec,
        "needed_dRA_arcsec_EastPlus": dRA_as,
        "needed_dDEC_arcsec_NorthPlus": dDEC_as,
        "new_command_ra_deg": ra_cmd_new,
        "new_command_dec_deg": dec_cmd_new,
    }


# ---------------- 사용 예시 ----------------
if __name__ == "__main__":
    # guide에서 얻은 두 중심 (astrometry)
    RA1, DEC1 = 66.90855384, -46.51216440
    RA2, DEC2 = 63.11557109, -46.54759615

    # 내가 망원경에 이미 입력한 좌표 (= 목표)
    RA_TARGET, DEC_TARGET = 65.00000000, -46.55000000

    res = refine_command_coordinate(
        RA1, DEC1, RA2, DEC2,
        ra_cmd_old=RA_TARGET, dec_cmd_old=DEC_TARGET,
        ra_target=RA_TARGET, dec_target=DEC_TARGET
    )

    print("Solved boresight (deg):", res["boresight_ra_deg"], res["boresight_dec_deg"])
    print("Target-boresight separation:", res["target_boresight_sep_arcsec"], "arcsec")
    print("Needed move:")
    print("  ΔRA  =", res["needed_dRA_arcsec_EastPlus"],  "arcsec  (+East)")
    print("  ΔDEC =", res["needed_dDEC_arcsec_NorthPlus"], "arcsec  (+North)")
    print("Enter NEW command RA/DEC:")
    print("  RA  =", res["new_command_ra_deg"], "deg")
    print("  DEC =", res["new_command_dec_deg"], "deg")

