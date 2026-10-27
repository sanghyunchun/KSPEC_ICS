"""
GFA 카메라별 boresight 기하 (sep, theta) 보정 -> GFA/etc/boresight_geometry.json

입력: 모든 GFA 카메라가 풀린 astrometry 결과 (astro_*.fits 또는 solve-field .wcs).
파일명 타임스탬프(D..._T...)가 --group-seconds 이내인 파일을 한 프레임 세트로 묶고,
세트마다 카메라 중심의 벡터 평균을 boresight로 삼아 기하를 구한 뒤 세트들을 평균한다.
카메라가 하나라도 빠진 세트는 쓰지 않는다 (평균이 중심에서 벗어남).

보정에 쓴 세트 각각에 대해, 나머지 세트로 만든 기하로 1대를 뺀 boresight를 다시
계산해 6대 평균과의 차이(leave-one-out)를 출력한다.

사용:
    python -m GFA.calib_boresight FILES... [-o GFA/etc/boresight_geometry.json]
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from astropy.io import fits

from GFA.pointing import (
    _camera_center,
    _vector_mean,
    average_boresight_geometry,
    boresight_estimates,
    calibrate_boresight_geometry,
    camera_serial,
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+", help="astro_*.fits or solve-field .wcs files")
    ap.add_argument("-o", "--output", default="GFA/etc/boresight_geometry.json")
    ap.add_argument("--group-seconds", type=float, default=10.0)
    args = ap.parse_args(argv)

    path_sets = group_frame_sets(args.files, args.group_seconds)
    groups = [read_headers(g) for g in path_sets]
    n_cam = max(len(h) for h in groups)
    full = [h for h in groups if len(h) == n_cam]
    names = [
        sorted(Path(p).name for p in g)[0]
        for g, h in zip(path_sets, groups)
        if len(h) == n_cam
    ]
    print(f"{len(groups)} frame sets, {len(full)} with all {n_cam} cameras")
    if not full:
        raise SystemExit("No complete frame set to calibrate from.")

    per_set = [calibrate_boresight_geometry(h) for h in full]
    geometry = average_boresight_geometry(per_set)
    for s, g in geometry.items():
        seps = [p[s]["sep_deg"] for p in per_set]
        print(
            f"  {s}: sep={g['sep_deg']:.4f} deg (spread {3600 * (max(seps) - min(seps)):.1f}\")"
            f"  theta={g['theta_deg']:.2f} deg"
        )

    if len(full) > 1:
        print("leave-one-set-out, 1 camera dropped: |boresight - all-camera mean| [arcsec]")
        for i, h in enumerate(full):
            geo = average_boresight_geometry(per_set[:i] + per_set[i + 1 :])
            bore = _vector_mean([_camera_center(hh)[3] for hh in h.values()])
            est = boresight_estimates(h, geo)
            worst = max(
                bore.separation(_vector_mean([est[s] for s in est if s != drop])).arcsec
                for drop in est
            )
            print(f"  set {names[i]}: worst {worst:.1f}\"")

    out = {
        "description": (
            "GFA boresight geometry per camera serial: sep_deg = chip centre to boresight, "
            "theta_deg = boresight direction in the camera pixel frame (+x towards +y). "
            "Boresight of each calibration set = vector mean of all camera centres."
        ),
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "calibration_sets": names,
        "cameras": geometry,
    }
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
