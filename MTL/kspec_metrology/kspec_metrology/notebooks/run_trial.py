#!/usr/bin/env python
"""metrology trial 을 명령 한 번에 하나씩 돌린다 (촬영 + 계산 + json 저장).

    python run_trial.py --start  --target object.info --out ~/mtl_run           # Trial 0 json (목표 각도)
    python run_trial.py          --target object.info --out ~/mtl_run           # trial 1: 촬영 + 계산
    (positioner 를 옮긴 뒤)
    python run_trial.py          --target object.info --out ~/mtl_run           # trial 2 ...
    python run_trial.py --no-expose --target object.info --out ~/mtl_run        # 마지막 trial 이미지로 계산만 다시

MetrologyRun 의 상태(trial 번호)는 메모리에 있지만 누적 각도는 직전 trial 의 json 파일에서 읽으므로,
매번 새 프로세스로 띄워도 --out 에 있는 json 번호를 보고 다음 trial 번호를 이어 간다.
같은 배치에서는 --out, --tile, --target 을 바꾸지 말 것. 새 배치는 다른 --out 을 쓴다.
노출시간 단위는 ms. 이미지는 {out}/data/, json 과 offset 표는 {out}/ 에 저장된다.
"""
import argparse
import os
import sys

# 이 저장소 안의 패키지를 우선 쓴다 (다른 곳에 설치된 옛 버전이 잡히지 않게)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if os.path.exists(os.path.join(_ROOT, 'kspec_metrology', '__init__.py')) and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from kspec_metrology.lab import next_trial
from kspec_metrology.mtlrun import MetrologyRun


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument('--target', required=True, help='target 파일 (object.info 형식, 또는 각도 파일)')
    ap.add_argument('--out', required=True, help='결과 폴더. json/offset 은 여기, 이미지는 {out}/data')
    ap.add_argument('--tile', default=None, help='파일 이름 앞부분. 기본은 target 파일의 tile_id')
    ap.add_argument('--start', action='store_true', help='Trial 0 json(목표 각도) 만 저장하고 끝')
    ap.add_argument('--no-expose', action='store_true', help='찍지 않고 마지막 trial 이미지로 계산만 다시')
    ap.add_argument('--exptime', type=float, default=400., help='fiber 노출시간 [ms] (기본 400)')
    ap.add_argument('--fid', type=float, nargs='*', default=[2., 10.],
                    help='fiducial 전용 노출시간 [ms], 0-2 개 (기본 2 10). 없으면 fiber 이미지에서 fiducial 도 찾는다')
    ap.add_argument('--n', type=int, default=1, help='노출 장수 (기본 1)')
    ap.add_argument('--mode', default='Raw', choices=['Raw', 'Predict'])
    ap.add_argument('--magnification', type=float, default=None, help='배율 초기값. 기본 None = 패키지 기본 (2026-01 commissioning -8.86)')
    ap.add_argument('--model', default='full+affine')
    ap.add_argument('--threshold', type=float, default=1e3)
    ap.add_argument('--min-dist', type=float, default=80)
    ap.add_argument('--nwindow', type=int, default=40)
    ap.add_argument('--niter-recenter', type=int, default=1)
    ap.add_argument('--n-extra', type=int, default=0)
    ap.add_argument('--tolerance', type=float, default=10., help='수렴 기준 [um]')
    ap.add_argument('--gain', type=float, default=10)
    ap.add_argument('--offset', type=float, default=30)
    ap.add_argument('--readmode', type=int, default=1)
    ap.add_argument('--usb-traffic', type=int, default=40)
    a = ap.parse_args(argv)

    out = os.path.abspath(os.path.expanduser(a.out))
    run = MetrologyRun(target_file=a.target, data_dir=os.path.join(out, 'data'), json_dir=out, tile=a.tile,
                       exptime=a.exptime, fid_exptime=a.fid or None, nexposure=a.n, mode=a.mode,
                       magnification=a.magnification, model=a.model, threshold=a.threshold, min_dist=a.min_dist,
                       nwindow=a.nwindow, niter_recenter=a.niter_recenter, n_extra=a.n_extra,
                       finder_opts={'minarea': 9, 'deblend_cont': 1.0}, tolerance=a.tolerance, max_trial=None,
                       gain=a.gain, offset=a.offset, readmode=a.readmode, usb_traffic=a.usb_traffic)

    if a.start:
        path = run.start()
        print(f'Trial 0 (목표 각도) -> {path}')
        return 0

    last = next_trial(out, run.tile) - 1                       # 지금까지 저장된 trial 번호 (0 = start 만)
    if last < 0 or not os.path.exists(run.json_path(0)):
        print(f'{out} 에 {run.tile} 의 Trial 0 json 이 없다. 먼저 --start 를 돌린다', file=sys.stderr)
        return 1
    if a.no_expose:                                             # 이미지는 있는데 계산이 안 된 trial 이 있으면 그것, 아니면 마지막 trial
        k = last + 1 if all(os.path.exists(f) for f in run.image_paths(last + 1)) else last
        if k < 1:
            print('다시 계산할 trial 이미지가 없다', file=sys.stderr)
            return 1
        run.itrial = k - 1
    else:
        run.itrial = last                                       # trial() 은 itrial+1 을 돈다

    res = run.trial(expose=not a.no_expose)
    print(f"Trial {res.itrial}: fiber error max {res.err_max:.1f} um, median {res.err_median:.1f} um"
          f" -> {'converged' if res.converged else 'not converged'} (tolerance {run.tolerance:g} um)")
    print(f'  images : {", ".join(res.images)}')
    print(f'  offsets: {res.offsets}')
    print(f'  json   : {res.json}      <- 이 각도로 positioner 를 옮긴 뒤 다시 실행')
    return 0


if __name__ == '__main__':
    sys.exit(main())
