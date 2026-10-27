"""
GFA 카메라별 boresight 기하 (sep, theta) 보정 -> GFA/etc/boresight_geometry.json

입력: astrometry 결과 (astro_*.fits 또는 solve-field .wcs). 파일명 타임스탬프
(D..._T...)가 --group-seconds 이내인 파일을 한 프레임 세트로 묶는다.
세트마다 boresight를 정하고 각 카메라의 (sep, theta)를 구해 세트들을 평균한다.

세트의 boresight를 정하는 방법 (--center):
  ring  카메라 중심이 이루는 링의 중심 (기본값). 3대 이상이면 되므로 카메라가
        빠져 있어도 된다. 설계상 같은 반경이라는 가정 (커미셔닝 WCS에서 반경 차이
        ~5" -> ~5").
  mean  카메라 중심의 벡터 평균. 모든 카메라가 풀린 세트에서만 쓸 수 있다.
  radec --boresight RA DEC로 준 좌표 (세트 하나). 별을 알려진 fiber에 올리는
        dither 등으로 boresight를 따로 잰 경우.

--update GEOMETRY --cameras SERIAL...: 지정한 카메라만 다시 보정한다. 세트의
boresight는 나머지 카메라의 기존 기하로 구하고(boresight_from_wcs), 나머지
카메라의 값은 그대로 둔다. 카메라를 다시 달았거나 수리해 추가할 때.

사용:
    python -m GFA.calib_boresight FILES...                          # 새 설치, 5대도 가능
    python -m GFA.calib_boresight FILES... --center radec --boresight 05:49:45.1 -46:00:03
    python -m GFA.calib_boresight FILES... --update GFA/etc/boresight_geometry.json \\
        --cameras 40103833
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits

from GFA.pointing import (
    _camera_center,
    _vector_mean,
    average_boresight_geometry,
    boresight_estimates,
    boresight_from_wcs,
    calibrate_boresight_geometry,
    camera_serial,
    load_boresight_geometry,
    ring_centre,
)

_TS_RE = re.compile(r"D(\d{8})_T(\d{6})_")


def _timestamp(path):
    m = _TS_RE.search(Path(path).name)
    if m is None:
        raise ValueError(f"No D..._T... timestamp in {path}")
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")


def group_frame_sets(paths, group_seconds=10.0):
    """타임스탬프가 group_seconds 이내로 이어지는 파일들을 한 세트로."""
    paths = sorted(paths, key=_timestamp)
    sets, cur, last = [], [], None
    for p in paths:
        t = _timestamp(p)
        if last is not None and (t - last).total_seconds() > group_seconds:
            sets.append(cur)
            cur = []
        cur.append(p)
        last = t
    if cur:
        sets.append(cur)
    return sets


def read_headers(paths):
    headers = {}
    for p in paths:
        with fits.open(p) as hdul:
            headers[camera_serial(p)] = hdul[0].header.copy()
    return headers


def set_boresight(headers, center, boresight=None, n_cam_all=None):
    """프레임 세트 하나의 boresight (SkyCoord)."""
    if center == "radec":
        return boresight
    centres = [_camera_center(h)[3] for h in headers.values()]
    if center == "mean":
        if n_cam_all is not None and len(headers) < n_cam_all:
            raise ValueError("--center mean needs every camera in the set")
        return _vector_mean(centres)
    return ring_centre(centres)[0]


def calibrate(path_sets, center="ring", boresight=None, update=None, cameras=None):
    """
    Returns (geometry, report): geometry {serial: {...}}, report = list of per-set
    dicts (name, cameras, boresight) for logging.
    """
    groups = [read_headers(g) for g in path_sets]
    names = [sorted(Path(p).name for p in g)[0] for g in path_sets]
    n_cam_all = max(len(h) for h in groups)

    if center == "radec" and len(groups) != 1:
        raise ValueError("--center radec takes exactly one frame set")

    per_set, report = [], []
    for name, headers in zip(names, groups):
        if update is not None:
            fixed = {s: g for s, g in update.items() if s not in cameras}
            others = {s: h for s, h in headers.items() if s in fixed}
            ra, dec, _ = boresight_from_wcs(others, fixed)
            bore = SkyCoord(ra * u.deg, dec * u.deg)
            targets = {s: h for s, h in headers.items() if s in cameras}
        else:
            if center == "ring" and len(headers) < 3:
                print(f"  skip {name}: {len(headers)} cameras (ring needs >= 3)")
                continue
            if center == "mean" and len(headers) < n_cam_all:
                print(f"  skip {name}: {len(headers)}/{n_cam_all} cameras (mean needs all)")
                continue
            bore = set_boresight(headers, center, boresight, n_cam_all)
            targets = headers
        if not targets:
            print(f"  skip {name}: none of the cameras to calibrate")
            continue
        per_set.append(calibrate_boresight_geometry(targets, boresight=bore))
        report.append({"name": name, "cameras": sorted(headers), "boresight": bore})

    if not per_set:
        raise SystemExit("No usable frame set.")

    geometry = average_boresight_geometry(per_set)
    if update is not None:
        merged = {s: g for s, g in update.items() if s not in cameras}
        merged.update(geometry)
        geometry = dict(sorted(merged.items()))
    return geometry, per_set, report


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1],
    )
    ap.add_argument("files", nargs="+", help="astro_*.fits or solve-field .wcs files")
    ap.add_argument("-o", "--output", default="GFA/etc/boresight_geometry.json")
    ap.add_argument("--center", choices=("ring", "mean", "radec"), default="ring")
    ap.add_argument("--boresight", nargs=2, metavar=("RA", "DEC"),
                    help="boresight of the frame set, sexagesimal or degrees")
    ap.add_argument("--update", metavar="GEOMETRY",
                    help="existing geometry; recalibrate only --cameras")
    ap.add_argument("--cameras", nargs="+", metavar="SERIAL")
    ap.add_argument("--group-seconds", type=float, default=10.0)
    args = ap.parse_args(argv)

    boresight = None
    if args.center == "radec":
        if not args.boresight:
            ap.error("--center radec needs --boresight RA DEC")
        ra, dec = args.boresight
        unit = (u.deg, u.deg) if ":" not in ra else (u.hourangle, u.deg)
        boresight = SkyCoord(ra, dec, unit=unit, frame="icrs")
    update = None
    if args.update:
        if not args.cameras:
            ap.error("--update needs --cameras")
        update = load_boresight_geometry(args.update)

    path_sets = group_frame_sets(args.files, args.group_seconds)
    print(f"{len(path_sets)} frame sets")
    geometry, per_set, report = calibrate(
        path_sets, args.center, boresight, update, args.cameras
    )
    for r in report:
        print(f"  {r['name']}: cameras {r['cameras']}")
    for s, g in geometry.items():
        seps = [p[s]["sep_deg"] for p in per_set if s in p]
        spread = f"{3600 * (max(seps) - min(seps)):.1f}\"" if seps else "kept"
        print(f"  {s}: sep={g['sep_deg']:.4f} deg (spread {spread})  theta={g['theta_deg']:.2f} deg")

    # Leave-one-set-out: geometry from the other sets, drop one camera at a time
    if len(per_set) > 1 and update is None:
        print("leave-one-set-out, 1 camera dropped: |boresight - set boresight| [arcsec]")
        headers_by_name = {sorted(Path(p).name for p in g)[0]: read_headers(g) for g in path_sets}
        for i, r in enumerate(report):
            geo = average_boresight_geometry(per_set[:i] + per_set[i + 1:])
            est = boresight_estimates(headers_by_name[r["name"]], geo)
            worst = max(
                r["boresight"].separation(
                    _vector_mean([est[s] for s in est if s != drop])
                ).arcsec
                for drop in est
            )
            print(f"  set {r['name']}: worst {worst:.1f}\"")

    out = {
        "description": (
            "GFA boresight geometry per camera serial: sep_deg = chip centre to boresight, "
            "theta_deg = boresight direction in the camera pixel frame (+x towards +y)."
        ),
        "method": (
            f"update of {args.update} for cameras {args.cameras}" if update is not None
            else {"ring": "boresight of each set = centre of the camera ring",
                  "mean": "boresight of each set = vector mean of all camera centres",
                  "radec": f"boresight given: {args.boresight}"}[args.center]
        ),
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "calibration_sets": [r["name"] for r in report],
        "cameras": geometry,
    }
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
