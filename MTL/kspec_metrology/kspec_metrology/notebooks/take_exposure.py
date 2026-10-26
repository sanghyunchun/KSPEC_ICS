#!/usr/bin/env python
"""시험 촬영: 원하는 노출시간으로 찍어 원하는 이름으로 저장한다 (fiducial 밝기 조정 등).

    python take_exposure.py --exptime 10 --out /data/fid_10ms.fits
    python take_exposure.py --exptime 2 10 --out /data/{date}_fid_{ms}ms.fits
    python take_exposure.py --exptime 400 --n 3 --out /data/fib_400ms.fits        # 3장: ..._0 _1 _2
    python take_exposure.py --fiber 400 --fid 2 10 --out /data/calib_t1           # 한 세트: fiber 1장 + fiducial 2장
        -> /data/calib_t1_fib_400ms_0.fits, /data/calib_t1_fid1_2ms_0.fits, /data/calib_t1_fid2_10ms_0.fits

- exptime 단위는 ms (MetrologyRun 의 exptime 과 같다). 여러 개를 주면 차례로 찍는다.
- 저장 이름: --out 에 {ms} (노출시간 ms), {date} (YYMMDD), {time} (HHMMSS), {i} (장 번호) 를 쓸 수 있다.
  분석 함수(findpeak, lab.check_peaks, lab.fiducial_brightness)가 '...{i}.fits' 꼴을 기대하므로
  {i} 가 없으면 '.fits' 앞에 '_{i}' 를 붙인다 (fid_10ms.fits -> fid_10ms_0.fits).
- 찍은 뒤 최대 화소값과 포화 화소 수를 바로 찍어 준다 (--sat-level, 기본 65000).
- 카메라 설정은 MetrologyRun 기본값과 같다 (--gain 10 --offset 30 --readmode 1 --usb-traffic 40).
- --dry-run 은 카메라 없이 저장될 이름만 보여 준다.
- 세트 촬영 (--fiber, --fid): fiber 노출 1장과 fiducial 전용 노출 0-2장을 이어서 찍는다. 이때 --out 은
  이름의 앞부분(확장자 없이)이고, 끝에 노트북에 붙여 넣을 FIBER_IMAGE / FID_IMAGES 줄을 찍어 준다.
"""
import argparse
import datetime
import os
import sys

# 이 저장소 안의 패키지를 우선 쓴다 (다른 곳에 설치된 옛 버전이 잡히지 않게)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if os.path.exists(os.path.join(_ROOT, 'kspec_metrology', '__init__.py')) and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from kspec_metrology.naming import image_path


def output_paths(pattern, exptime, nexposure, now=None):
    """--out 패턴에서 실제 저장 경로(폴더, head, 각 장의 경로)를 만든다.

    mtlexp 가 저장하는 이름은 naming.image_path(data_dir, head, i) = {data_dir}/{head}{i}.fits 이므로
    head 는 '{i}.fits' 바로 앞까지의 이름이어야 한다 (확장자가 들어가면 ..._.fits0.fits 가 된다).
    """
    now = now or datetime.datetime.now()
    name = pattern.format(ms=f'{exptime:g}', date=now.strftime('%y%m%d'), time=now.strftime('%H%M%S'), i='{i}')
    if '{i}' not in name:
        root, _ext = os.path.splitext(name)
        name = f'{root}_{{i}}.fits'
    if not name.endswith('{i}.fits'):
        raise SystemExit(f"--out 의 {{i}} 는 '.fits' 바로 앞에 와야 한다 (예: fid_{{i}}.fits): {pattern}")
    head = os.path.abspath(name[:-len('{i}.fits')])
    data_dir, head = os.path.dirname(head), os.path.basename(head)
    paths = [image_path(data_dir, head, i) for i in range(nexposure)]
    return data_dir, head, paths


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split('\n', 1)[1])
    ap.add_argument('--exptime', type=float, nargs='+', help='노출시간 [ms]. 여러 개 가능')
    ap.add_argument('--fiber', type=float, help='세트 촬영: fiber 노출시간 [ms]')
    ap.add_argument('--fid', type=float, nargs='*', default=None, help='세트 촬영: fiducial 전용 노출시간 [ms] 0-2개')
    ap.add_argument('--out', required=True, help="저장 이름. {ms} {date} {time} {i} 사용 가능. 예: /data/{date}_fid_{ms}ms.fits. "
                                                "세트 촬영이면 앞부분만 (예: /data/calib_t1)")
    ap.add_argument('--n', type=int, default=1, help='노출시간마다 찍을 장 수 (기본 1)')
    ap.add_argument('--gain', type=float, default=10); ap.add_argument('--offset', type=float, default=30)
    ap.add_argument('--readmode', type=int, default=1); ap.add_argument('--usb-traffic', type=int, default=40)
    ap.add_argument('--sat-level', type=float, default=65000.)
    ap.add_argument('--note', default='', help='FITS header NOTE 에 남길 메모 (예: "G1 up")')
    ap.add_argument('--dry-run', action='store_true', help='찍지 않고 저장될 이름만')
    a = ap.parse_args(argv)

    if a.fiber is not None:                                    # 세트: fiber 1장 + fiducial 0-2장
        stem = a.out[:-5] if a.out.endswith('.fits') else a.out
        plan = [(a.fiber, *output_paths(f'{stem}_fib_{a.fiber:g}ms.fits', a.fiber, a.n))]
        for k, t in enumerate(a.fid or [], 1):
            plan.append((t, *output_paths(f'{stem}_fid{k}_{t:g}ms.fits', t, a.n)))
    elif a.exptime:
        plan = [(t, *output_paths(a.out, t, a.n)) for t in a.exptime]
    else:
        ap.error('--exptime 또는 --fiber (세트) 가 필요하다')
    for t, d, head, paths in plan:
        print(f'exptime {t:g} ms: ' + ', '.join(paths))
    if a.fiber is not None:
        print("\n노트북에 붙여 넣기:")
        print(f"FIBER_IMAGE = '{plan[0][3][0]}'")
        print(f"FID_IMAGES  = [{', '.join(repr(p[3][0]) for p in plan[1:])}]")
    if a.dry_run:
        return 0

    import numpy as np
    from astropy.io import fits
    from kspec_metrology.exposure.mtlexp import mtlexp        # 카메라 SDK 는 여기서야 로드된다
    for t, d, head, paths in plan:
        hdr = {'NOTE': a.note} if a.note else {}
        saved = mtlexp(t, readmode=a.readmode, usb_traffic=a.usb_traffic, gain=a.gain, offset=a.offset,
                       nexposure=a.n, data_dir=d, head=head, extra_header=hdr)
        for p in saved:
            im = fits.getdata(p)
            nsat = int((im >= a.sat_level).sum())
            print(f'{p}: max {im.max():.0f}, saturated pixels {nsat}' + ('  <-- SATURATED' if nsat else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
