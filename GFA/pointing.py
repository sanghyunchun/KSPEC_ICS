import json
import math
import os
import re
from astropy.coordinates import SkyCoord, CartesianRepresentation, SkyOffsetFrame
from astropy.io import fits
from astropy.wcs import WCS
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



def get_separation(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
    c1 = SkyCoord(ra1_deg*u.deg, dec1_deg*u.deg, frame='icrs')
    c2 = SkyCoord(ra2_deg*u.deg, dec2_deg*u.deg, frame='icrs')
    return c1.separation(c2).arcsec


def get_boresight(ra_list_deg, dec_list_deg, frame="icrs", min_guides=5):
    """
    5개 이상 가이드 카메라 이미지 중심 좌표(RA, DEC)로부터
    초점면 중심(boresight)을 계산한다.

    Parameters
    ----------
    ra_list_deg : array-like
        RA values in degrees
    dec_list_deg : array-like
        DEC values in degrees
    frame : str
        Coordinate frame, default='icrs'
    min_guides : int
        최소 사용 가능한 가이드 수, default=4

    Returns
    -------
    ra_bs_deg : float
        Boresight RA in degrees
    dec_bs_deg : float
        Boresight DEC in degrees
    """

    ra_list_deg = np.asarray(ra_list_deg, dtype=float)
    dec_list_deg = np.asarray(dec_list_deg, dtype=float)

    if len(ra_list_deg) != len(dec_list_deg):
        raise ValueError("RA and DEC lists must have the same length.")

    if len(ra_list_deg) < min_guides:
        raise ValueError(f"At least {min_guides} guide coordinates are required.")

    # NaN 제거
    valid = np.isfinite(ra_list_deg) & np.isfinite(dec_list_deg)
    ra_list_deg = ra_list_deg[valid]
    dec_list_deg = dec_list_deg[valid]

    if len(ra_list_deg) < min_guides:
        raise ValueError(f"At least {min_guides} valid guide coordinates are required.")

    guides = SkyCoord(
        ra=ra_list_deg * u.deg,
        dec=dec_list_deg * u.deg,
        frame=frame
    )

    # Astropy CartesianRepresentation 평균
    v_mean = guides.cartesian.mean()

    # 정규화
    v_mean = v_mean / v_mean.norm()

    # CartesianRepresentation을 바로 SkyCoord로 변환
    boresight = SkyCoord(v_mean, frame=frame)

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

# ---------------- 카메라 기하 기반 boresight ----------------
# 각 GFA 카메라에서 boresight(초점면 중심)는 칩 밖의 고정된 위치에 있다.
# 카메라마다 (sep, theta)를 한 번 보정해 두면:
#   sep   : 칩 중심 -> boresight 각거리 [deg]
#   theta : 카메라 픽셀 좌표계에서 boresight 방향 [deg, +x에서 +y 쪽으로]
# 매 pointing에서 카메라 하나의 WCS만으로 boresight를 추정할 수 있다.
# 카메라 중심의 단순 평균(get_boresight)은 링 위 카메라가 모두 있을 때만
# 중심과 일치하고, 1대가 빠지면 반대쪽으로 R/5 (R=1.47 deg -> ~1060") 치우친다.

BORESIGHT_GEOMETRY_FILE = "boresight_geometry.json"
_GFA_SERIAL_RE = re.compile(r"D\d{8}_T\d{6}_(\d+)_")


def camera_serial(filename):
    """GFA 파일명(D20260124_T100007_40103667_exp1s...)에서 카메라 serial."""
    m = _GFA_SERIAL_RE.search(os.path.basename(str(filename)))
    if m is None:
        raise ValueError(f"Cannot parse camera serial from {filename}")
    return m.group(1)


def _camera_center(header):
    """(celestial WCS, 칩 중심 x, y [0-based], 칩 중심 SkyCoord)."""
    w = WCS(header).celestial
    nx = header.get("NAXIS1") or header.get("IMAGEW")
    ny = header.get("NAXIS2") or header.get("IMAGEH")
    if not nx or not ny:
        raise KeyError("Header has neither NAXIS1/2 nor IMAGEW/H")
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    ra, dec = w.pixel_to_world_values(cx, cy)
    return w, cx, cy, SkyCoord(ra * u.deg, dec * u.deg, frame="icrs")


def _vector_mean(coords):
    v = SkyCoord(coords).cartesian.mean()
    return SkyCoord(v / v.norm(), frame="icrs")


def ring_centre(coords, max_iter=20, tol_arcsec=1e-3):
    """
    카메라 중심들이 이루는 링(원)의 중심. 설계상 카메라가 boresight에서 같은
    반경에 있으므로, 3대 이상이면 빠진 카메라와 무관하게 boresight를 준다
    (커미셔닝 WCS에서 카메라별 반경 차이 ~5" -> 중심 정확도 ~5").

    현재 중심을 접점으로 한 gnomonic 접평면에서 원을 선형 최소제곱(Kasa)으로
    맞추고 접점을 새 중심으로 옮겨 반복한다. 접점이 링 중심이면 링은 접평면에서
    정확한 원이므로, 카메라가 비대칭으로 빠져도 치우침이 없다.

    Returns
    -------
    centre : SkyCoord
    radii_arcsec : np.ndarray
        각 카메라 중심의 링 중심 거리
    """
    coords = SkyCoord(coords)
    if len(coords) < 3:
        raise ValueError(f"Ring centre needs >= 3 cameras, got {len(coords)}")
    centre = _vector_mean(coords)
    for _ in range(max_iter):
        frame = SkyOffsetFrame(origin=centre)
        v = coords.transform_to(frame).cartesian  # +x towards the tangent point
        x, y = (v.y / v.x).value, (v.z / v.x).value  # gnomonic coordinates
        a = np.c_[2.0 * x, 2.0 * y, np.ones_like(x)]
        (xc, yc, _), *_ = np.linalg.lstsq(a, x**2 + y**2, rcond=None)
        c = SkyCoord(CartesianRepresentation(1.0, xc, yc), frame=frame).icrs
        new = SkyCoord(c.ra, c.dec, frame="icrs")
        step = new.separation(centre).arcsec
        centre = new
        if step < tol_arcsec:
            break
    return centre, coords.separation(centre).arcsec


def calibrate_boresight_geometry(headers, boresight=None):
    """
    카메라별 boresight 기하 (sep, theta) 보정.

    Parameters
    ----------
    headers : dict
        {serial: astrometry WCS header}
    boresight : SkyCoord, optional
        이 프레임 세트의 boresight (알려진 좌표, ring_centre(), 또는 다른
        카메라의 기존 기하로 구한 값). 없으면 카메라 중심의 벡터 평균을 쓴다
        (링 위 카메라가 모두 풀린 프레임에서만 의미가 있다).

    Returns
    -------
    dict : {serial: {"sep_deg": float, "theta_deg": float}}
    """
    centers = {s: _camera_center(h) for s, h in headers.items()}
    if boresight is None:
        boresight = _vector_mean([c for *_, c in centers.values()])

    geometry = {}
    for serial, (w, cx, cy, c) in centers.items():
        sep = c.separation(boresight)
        step = c.directional_offset_by(c.position_angle(boresight), 60 * u.arcsec)
        px, py = w.world_to_pixel_values(step.ra.deg, step.dec.deg)
        theta = math.degrees(math.atan2(py - cy, px - cx))
        geometry[serial] = {"sep_deg": float(sep.deg), "theta_deg": float(theta)}
    return geometry


def average_boresight_geometry(geometries):
    """여러 프레임 세트의 기하를 카메라별로 평균 (theta는 원형 평균)."""
    serials = sorted({s for g in geometries for s in g})
    out = {}
    for s in serials:
        vals = [g[s] for g in geometries if s in g]
        t = np.radians([v["theta_deg"] for v in vals])
        out[s] = {
            "sep_deg": float(np.mean([v["sep_deg"] for v in vals])),
            "theta_deg": float(
                np.degrees(np.arctan2(np.mean(np.sin(t)), np.mean(np.cos(t))))
            ),
            "n_sets": len(vals),
        }
    return out


def boresight_estimates(headers, geometry):
    """카메라별 boresight 추정 {serial: SkyCoord}; geometry에 없는 카메라는 제외."""
    est = {}
    for serial, h in headers.items():
        g = geometry.get(serial)
        if g is None:
            continue
        w, cx, cy, c = _camera_center(h)
        t = math.radians(g["theta_deg"])
        ra, dec = w.pixel_to_world_values(cx + 100.0 * math.cos(t), cy + 100.0 * math.sin(t))
        pa = c.position_angle(SkyCoord(ra * u.deg, dec * u.deg, frame="icrs"))
        est[serial] = c.directional_offset_by(pa, g["sep_deg"] * u.deg)
    return est


def boresight_from_wcs(headers, geometry, reject_arcsec=30.0, min_cameras=2):
    """
    카메라 WCS와 보정된 기하로 boresight 추정. 카메라 수와 무관하게 동작한다.

    카메라별 추정을 벡터 평균하고, 평균에서 reject_arcsec보다 먼 추정
    (잘못 풀린 WCS 등)은 버리고 다시 평균한다.

    Returns
    -------
    ra_deg, dec_deg : float
    info : dict
        used / rejected serial 목록, 사용 추정의 rms [arcsec],
        카메라별 평균과의 거리 [arcsec]
    """
    est = boresight_estimates(headers, geometry)
    if len(est) < min_cameras:
        raise ValueError(
            f"Boresight needs >= {min_cameras} cameras with geometry, got {len(est)}"
        )

    used = sorted(est)
    bs = _vector_mean([est[s] for s in used])
    dist = {s: float(bs.separation(est[s]).arcsec) for s in used}
    keep = [s for s in used if dist[s] <= reject_arcsec]
    if len(keep) >= min_cameras and len(keep) < len(used):
        used = keep
        bs = _vector_mean([est[s] for s in used])
        dist = {s: float(bs.separation(est[s]).arcsec) for s in est}

    rms = float(np.sqrt(np.mean([dist[s] ** 2 for s in used])))
    info = {
        "used": used,
        "rejected": sorted(set(est) - set(used)),
        "rms_arcsec": rms,
        "dist_arcsec": dist,
    }
    return float(bs.ra.deg), float(bs.dec.deg), info


def load_boresight_geometry(path):
    """boresight_geometry.json -> {serial: {"sep_deg", "theta_deg"}}."""
    with open(path, "r") as f:
        return json.load(f)["cameras"]


def boresight_from_astro_files(astro_paths, geometry, **kwargs):
    """astro_*.fits 경로 목록으로 boresight_from_wcs 실행."""
    headers = {}
    for p in astro_paths:
        with fits.open(p) as hdul:
            headers[camera_serial(p)] = hdul[0].header.copy()
    return boresight_from_wcs(headers, geometry, **kwargs)


#def refine_command_coordinate(
#    ra1, dec1, ra2, dec2,          # guide centers
#    ra_cmd_old, dec_cmd_old,        # 내가 이미 입력했던 좌표(보통 RA_target,DEC_target)
#    ra_target, dec_target           # 원하는 최종 목표
#):
#    """
#    이미 ra_cmd_old/dec_cmd_old로 보냈는데 실제 보어사이트가 빗나간 상황에서,
#    새로 입력할 보정 좌표를 계산.

#    반환:
#      - solved boresight
#      - target-boresight separation
#      - needed move (ΔRA,ΔDEC) arcsec (+East,+North)
#      - new command RA/DEC (deg)  (망원경에 직접 입력)
#    """
#    ra_bs, dec_bs = boresight_from_two_guides_spherical(ra1, dec1, ra2, dec2)

    # 타겟-보어사이트 separation
#    sep_arcsec = great_circle_sep_arcsec(ra_bs, dec_bs, ra_target, dec_target)

    # 실제 보어사이트 -> 목표로 가야 하는 오프셋
#    dRA_as, dDEC_as = offsets_arcsec_east_north(ra_bs, dec_bs, ra_target, dec_target)

    # 그 오프셋을 "이전 명령 좌표"에 더해 새 명령 좌표 생성
#    ra_cmd_new, dec_cmd_new = apply_offsets_to_radec(ra_cmd_old, dec_cmd_old, dRA_as, dDEC_as)

#    return {
#        "boresight_ra_deg": ra_bs,
#        "boresight_dec_deg": dec_bs,
#        "target_boresight_sep_arcsec": sep_arcsec,
#        "needed_dRA_arcsec_EastPlus": dRA_as,
#        "needed_dDEC_arcsec_NorthPlus": dDEC_as,
#        "new_command_ra_deg": ra_cmd_new,
#        "new_command_dec_deg": dec_cmd_new,
#    }


# ---------------- 사용 예시 ----------------
if __name__ == "__main__":
    # guide에서 얻은 두 중심 (astrometry)
    RA1, DEC1 = 66.90855384, -46.51216440
    RA2, DEC2 = 63.11557109, -46.54759615

    # 내가 망원경에 이미 입력한 좌표 (= 목표)
    RA_TARGET, DEC_TARGET = 65.00000000, -46.55000000

#    res = refine_command_coordinate(
#        RA1, DEC1, RA2, DEC2,
#        ra_cmd_old=RA_TARGET, dec_cmd_old=DEC_TARGET,
#        ra_target=RA_TARGET, dec_target=DEC_TARGET
#    )

#    print("Solved boresight (deg):", res["boresight_ra_deg"], res["boresight_dec_deg"])
#    print("Target-boresight separation:", res["target_boresight_sep_arcsec"], "arcsec")
#    print("Needed move:")
#    print("  ΔRA  =", res["needed_dRA_arcsec_EastPlus"],  "arcsec  (+East)")
#    print("  ΔDEC =", res["needed_dDEC_arcsec_NorthPlus"], "arcsec  (+North)")
#    print("Enter NEW command RA/DEC:")
#    print("  RA  =", res["new_command_ra_deg"], "deg")
#    print("  DEC =", res["new_command_dec_deg"], "deg")

